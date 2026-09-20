#!/usr/bin/env python3
"""Encrypted Exocortex continuity state-bundle tool.

Commands:
  create   Select continuity state, emit manifest.json, tar it, encrypt with
           AES-256-CBC (PBKDF2, 200k iterations) into a single .statebundle.
  verify   Re-derive every SHA-256 over the decrypted tar and compare against
           the manifest.
  restore  Decrypt, verify hashes, then copy items to their destination roots,
           refusing to overwrite unless --force is given. Restore order follows
           docs/reconstruction/STATE_AND_SECRETS.md.

The bundle is the encrypted Tier-B continuity tier; it is never stored in the
Exocortex Git repository. Secrets are never read into memory beyond streaming
into the archive; the manifest itself is non-secret.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()

DEFAULT_ITEMS = [
    ("goms_root", HOME / "Library/Application Support/Aineko/GOMS"),
    ("hermes_profile", HOME / ".hermes/profiles/gsvaineko"),
    ("hermes_authority", HOME / ".hermes/authority"),
]

SCHEMA_VERSION = 2


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_exclusions():
    names = []
    for path in (HOME / ".exocortex-state-bundle-ignore",
                 Path(__file__).resolve().parent.parent / ".statebundle-ignore"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    names.append(line)
    return tuple(names)


def is_sqlite_sidecar(name: str) -> bool:
    return name.endswith(("-wal", "-shm", "-journal"))


def item_files(root: Path, excludes):
    for base, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in excludes)
        for name in sorted(filenames):
            if name not in excludes and not is_sqlite_sidecar(name):
                yield Path(base) / name


def collect(items):
    excludes = load_exclusions()
    out = []
    skipped_specials = []
    for name, root in items:
        root = Path(root).expanduser()
        if not root.exists():
            sys.stderr.write(f"warning: {name} root missing: {root}\n")
            continue
        for path in item_files(root, excludes):
            if not path.is_file():
                # Sockets/FIFOs/devices cannot be streamed into an archive;
                # record them so nothing is silently dropped.
                skipped_specials.append(
                    {"item": name, "path": path.relative_to(root).as_posix()})
                continue
            rel = path.relative_to(root).as_posix()
            out.append((name, rel, path))
    return out, skipped_specials


def git_commit(repo: Path | None) -> str | None:
    if not repo:
        return None
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
            text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def openssl_encrypt(tar_path: Path, out_path: Path, env_file: Path) -> None:
    cmd = [
        "openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
        "-in", str(tar_path), "-out", str(out_path), "-pass", f"file:{env_file}",
    ]
    subprocess.run(cmd, check=True)


def openssl_decrypt(bundle: Path, tar_path: Path, env_file: Path) -> None:
    cmd = [
        "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
        "-in", str(bundle), "-out", str(tar_path), "-pass", f"file:{env_file}",
    ]
    subprocess.run(cmd, check=True)


def _stage_ignore(directory, names):
    ignored = list(shutil.ignore_patterns(*load_exclusions())(directory, names))
    for entry in names:
        if entry in ignored:
            continue
        entry_path = Path(directory) / entry
        if entry_path.is_dir():
            continue
        if not entry_path.is_file() or is_sqlite_sidecar(entry):
            ignored.append(entry)
    return ignored


def cmd_create(args):
    items = [(name, path) for name, path in (a.split("=", 1) for a in args.item)] \
        if args.item else DEFAULT_ITEMS
    if args.git_commit:
        commit = args.git_commit
    else:
        commit = git_commit(Path(__file__).resolve().parent.parent)

    entries, skipped_specials = collect(items)
    roots = {name: str(Path(root).expanduser()) for name, root in items}
    if not entries:
        sys.exit("error: no state files found; nothing to bundle")

    workdir = Path(tempfile.mkdtemp(prefix="statebundle-"))
    try:
        staged = workdir / "payload"
        for name, root in items:
            src = Path(root).expanduser()
            if not src.exists():
                continue
            dest = staged / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest, symlinks=False,
                                ignore=_stage_ignore)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        # Hash the staged copies, not the live sources: the manifest must
        # describe exactly the bytes that are archived and verified later.
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_now(),
            "git_commit": commit,
            "host": args.host or os.uname().nodename,
            "restore_order": [name for name, _root in items],
            "skipped_specials": skipped_specials,
            "items": [
                {"name": name, "root": roots[name], "path": rel,
                 "sha256": sha256_file(staged / name / rel),
                 "bytes": (staged / name / rel).stat().st_size}
                for name, rel, path in entries
            ],
        }
        (staged / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        tar_path = workdir / "payload.tar"
        with tarfile.open(tar_path, "w") as tar:
            tar.add(staged, arcname=".")
        openssl_encrypt(tar_path, Path(args.output).expanduser(), args.passfile)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    bundle = Path(args.output).expanduser()
    summary = {
        "bundle": str(bundle),
        "bundle_sha256": sha256_file(bundle),
        "bundle_bytes": bundle.stat().st_size,
        "git_commit": commit,
        "host": manifest["host"],
        "items": len(manifest["items"]),
        "files": len(entries),
        "skipped_specials": len(skipped_specials),
        "created_at": manifest["created_at"],
    }
    print(json.dumps(summary, indent=2))
    if args.summary_output:
        Path(args.summary_output).write_text(json.dumps(summary, indent=2) + "\n",
                                             encoding="utf-8")


def _open_bundle(bundle: Path, passfile: Path, workdir: Path) -> tuple[Path, dict]:
    tar_path = workdir / "payload.tar"
    openssl_decrypt(bundle, tar_path, passfile)
    with tarfile.open(tar_path, "r") as tar:
        tar.extractall(workdir / "extracted")
    extracted = workdir / "extracted"
    manifest_path = extracted / "manifest.json"
    if not manifest_path.exists():
        sys.exit("error: bundle has no manifest.json")
    return extracted, json.loads(manifest_path.read_text(encoding="utf-8"))


def _recompute_sha256(extracted: Path, entry: dict) -> str:
    return sha256_file(extracted / entry["name"] / entry["path"])


def cmd_verify(args):
    workdir = Path(tempfile.mkdtemp(prefix="statebundle-verify-"))
    try:
        extracted, manifest = _open_bundle(Path(args.bundle).expanduser(),
                                           args.passfile, workdir)
        bad = []
        for entry in manifest["items"]:
            target = extracted / entry["name"] / entry["path"]
            if not target.exists():
                bad.append({**entry, "problem": "missing"})
                continue
            actual = sha256_file(target)
            if actual != entry["sha256"]:
                bad.append({**entry, "problem": "hash_mismatch",
                            "actual": actual})
        print(json.dumps({
            "bundle": str(args.bundle),
            "manifest_schema_version": manifest.get("schema_version"),
            "files_checked": len(manifest["items"]),
            "ok": not bad,
            "failures": bad[:20],
        }, indent=2))
        if bad:
            sys.exit(1)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def cmd_restore(args):
    workdir = Path(tempfile.mkdtemp(prefix="statebundle-restore-"))
    try:
        extracted, manifest = _open_bundle(Path(args.bundle).expanduser(),
                                           args.passfile, workdir)
        bad = []
        for entry in manifest["items"]:
            target = extracted / entry["name"] / entry["path"]
            if not target.exists() or sha256_file(target) != entry["sha256"]:
                bad.append(entry["path"])
        if bad:
            sys.exit(f"error: {len(bad)} files failed verification; refusing restore")

        # Restore order: GOMS, authority, profile continuity (STATE_AND_SECRETS.md).
        for name in manifest.get("restore_order", []):
            src = extracted / name
            if not src.exists() or name == "manifest.json":
                continue
            dest = Path(args.dest_root).expanduser() / name
            if dest.exists() and not args.force:
                sys.exit(f"error: destination {dest} exists; use --force to overwrite")
            if src.is_dir():
                if dest.exists() and args.force:
                    shutil.rmtree(dest)
                shutil.copytree(src, dest, symlinks=False)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            print(f"restored {name} -> {dest}", file=sys.stderr)
        print(json.dumps({"restored": manifest.get("restore_order", []),
                          "files": len(manifest["items"]), "ok": True}, indent=2))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--output", required=True)
    c.add_argument("--passfile", required=True, type=Path)
    c.add_argument("--item", action="append", default=[],
                   help="name=path; defaults to goms_root, hermes_profile, hermes_authority")
    c.add_argument("--host")
    c.add_argument("--git-commit")
    c.add_argument("--summary-output", type=Path)
    c.set_defaults(func=cmd_create)

    v = sub.add_parser("verify")
    v.add_argument("--bundle", required=True, type=Path)
    v.add_argument("--passfile", required=True, type=Path)
    v.set_defaults(func=cmd_verify)

    r = sub.add_parser("restore")
    r.add_argument("--bundle", required=True, type=Path)
    r.add_argument("--passfile", required=True, type=Path)
    r.add_argument("--dest-root", required=True, type=Path)
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_restore)

    args = ap.parse_args()
    if not args.passfile.exists():
        sys.exit(f"error: passfile not found: {args.passfile}")
    args.func(args)


if __name__ == "__main__":
    main()