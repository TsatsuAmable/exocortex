#!/usr/bin/env python3
"""Govern GOMS storage growth without treating old bytes as disposable knowledge.

The controller is deliberately conservative:
- dry-run planning is the default;
- exact SHA-256 equality is required before raw duplicate removal;
- deployment retention is explicit and deterministic;
- destructive apply requires a fresh verified continuity proof;
- ledger rotation uses a stable lock and preserves hash-chain continuity.

The scheduled mode plans every run and applies only when policy enables it and a
fresh continuity proof is present. Otherwise it exits successfully in dry-run.
"""
from __future__ import annotations

import argparse
import fcntl
import fnmatch
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_POLICY = {
    "schema_version": 1,
    "deployment_keep_latest": 2,
    "protected_deployment_patterns": [
        "*authority-review-consensus*",
    ],
    "raw_dedupe": True,
    "ledger_rotate_bytes": 268435456,
    "continuity_proof_max_age_hours": 720,
    "plan_max_age_hours": 48,
    "auto_apply": True,
    "ledger_auto_rotate": True,
}
HOT_NAMES = {
    "goms.sqlite3",
    "events.jsonl",
    "chatgpt_live_ingest.sqlite3",
    "manfred_sync.sqlite3",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_policy(path: Path | None) -> dict[str, Any]:
    policy = dict(DEFAULT_POLICY)
    if path:
        supplied = json.loads(path.read_text(encoding="utf-8"))
        if int(supplied.get("schema_version", 1)) != 1:
            raise ValueError("unsupported_storage_policy_schema")
        policy.update(supplied)
    return policy


def policy_hash(policy: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(policy))


def tree_stats(path: Path) -> dict[str, Any]:
    total = 0
    files = 0
    rows: list[str] = []
    if not path.exists():
        return {"bytes": 0, "files": 0, "fingerprint": sha256_bytes(b"")}
    if path.is_file():
        stat = path.stat()
        return {
            "bytes": stat.st_size,
            "files": 1,
            "fingerprint": sha256_bytes(
                f"{path.name}\0{stat.st_size}\0{stat.st_mtime_ns}".encode()
            ),
        }
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        stat = item.stat()
        rel = item.relative_to(path).as_posix()
        total += stat.st_size
        files += 1
        rows.append(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}")
    return {
        "bytes": total,
        "files": files,
        "fingerprint": sha256_bytes("\n".join(rows).encode("utf-8")),
    }


def directory_bytes(path: Path) -> int:
    return tree_stats(path)["bytes"] if path.exists() else 0


def inventory(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    hot = 0
    for name in HOT_NAMES:
        target = root / name
        if target.is_file():
            hot += target.stat().st_size
    warm = directory_bytes(root / "raw")
    deployments = directory_bytes(root / "deployments")
    cold_existing = directory_bytes(root / "cold")
    quarantine = directory_bytes(root / "quarantine")
    total = directory_bytes(root)
    classified = hot + warm + deployments + cold_existing + quarantine
    return {
        "root": str(root),
        "total_bytes": total,
        "hot_bytes": hot,
        "warm_raw_bytes": warm,
        "historical_deployment_bytes": deployments,
        "cold_bytes": cold_existing,
        "quarantine_bytes": quarantine,
        "other_bytes": max(0, total - classified),
        "live_db_bytes": (root / "goms.sqlite3").stat().st_size
        if (root / "goms.sqlite3").is_file()
        else 0,
        "live_ledger_bytes": (root / "events.jsonl").stat().st_size
        if (root / "events.jsonl").is_file()
        else 0,
    }


def deployment_actions(root: Path, policy: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    deployments = root / "deployments"
    if not deployments.is_dir():
        return [], []
    dirs = sorted(p for p in deployments.iterdir() if p.is_dir())
    keep_latest = max(0, int(policy.get("deployment_keep_latest", 0)))
    protected = set(dirs[-keep_latest:] if keep_latest else [])
    patterns = [str(x) for x in policy.get("protected_deployment_patterns", [])]
    for item in dirs:
        if (item / ".protected").exists() or any(
            fnmatch.fnmatch(item.name, pattern) for pattern in patterns
        ):
            protected.add(item)
    protected_rows = []
    actions = []
    for item in dirs:
        stats = tree_stats(item)
        row = {
            "path": str(item),
            "name": item.name,
            **stats,
        }
        if item in protected:
            row["reason"] = (
                "latest_retention"
                if item in set(dirs[-keep_latest:] if keep_latest else [])
                else "protected_anchor"
            )
            protected_rows.append(row)
            continue
        actions.append(
            {
                "kind": "remove_deployment",
                "path": str(item),
                "bytes": stats["bytes"],
                "files": stats["files"],
                "fingerprint": stats["fingerprint"],
                "reason": "outside_retention_set",
            }
        )
    return actions, protected_rows


def iter_raw_files(raw_root: Path):
    if not raw_root.is_dir():
        return
    for path in sorted(p for p in raw_root.rglob("*") if p.is_file()):
        if path.name.startswith("."):
            continue
        yield path


def raw_duplicate_actions(root: Path, policy: dict[str, Any]) -> tuple[list[dict], dict]:
    if not policy.get("raw_dedupe", True):
        return [], {"files_scanned": 0, "hash_candidates": 0, "duplicate_groups": 0}
    raw_root = root / "raw"
    by_size: dict[int, list[Path]] = defaultdict(list)
    files_scanned = 0
    for path in iter_raw_files(raw_root) or []:
        files_scanned += 1
        by_size[path.stat().st_size].append(path)
    hash_candidates = [p for group in by_size.values() if len(group) > 1 for p in group]
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in hash_candidates:
        by_hash[sha256_file(path)].append(path)
    groups = [sorted(group, key=lambda p: (len(p.relative_to(raw_root).parts), str(p)))
              for group in by_hash.values() if len(group) > 1]
    actions: list[dict] = []
    for group in sorted(groups, key=lambda g: str(g[0])):
        canonical = group[0]
        digest = sha256_file(canonical)
        for duplicate in group[1:]:
            actions.append(
                {
                    "kind": "remove_raw_duplicate",
                    "path": str(duplicate),
                    "canonical_path": str(canonical),
                    "sha256": digest,
                    "bytes": duplicate.stat().st_size,
                    "reason": "exact_sha256_duplicate",
                }
            )
    return actions, {
        "files_scanned": files_scanned,
        "hash_candidates": len(hash_candidates),
        "duplicate_groups": len(groups),
        "duplicate_extra_files": len(actions),
        "duplicate_reclaimable_bytes": sum(a["bytes"] for a in actions),
    }


def ledger_event_sha(event: dict[str, Any]) -> str:
    payload = dict(event)
    payload.pop("event_sha256", None)
    return sha256_bytes(canonical_bytes(payload))


def verify_ledger(path: Path, expected_first_prev: str | None | object = ...) -> dict[str, Any]:
    """Verify the hash chain, tolerating a legacy provenance head.

    Early GOMS ledgers begin with records that predate the hash chain: they
    carry neither prev_line_sha256 nor event_sha256. They remain provenance
    and still anchor the chain, because the first chained record's
    prev_line_sha256 is the raw-line hash of the last legacy record. Legacy
    records are valid only as a leading run; a legacy-shaped record after the
    chain has started is a chain break (its missing prev cannot match the
    running raw-line hash).
    """
    previous_line_hash = None
    first_prev = None
    chain_started = False
    legacy_lines = 0
    line_count = 0
    last_line_hash = None
    failures = []
    if not path.exists():
        return {
            "ok": True, "lines": 0, "first_prev_line_sha256": None,
            "last_line_sha256": None, "failures": [],
        }
    with path.open("rb") as handle:
        for lineno, raw in enumerate(handle, start=1):
            raw = raw.rstrip(b"\r\n")
            if not raw:
                continue
            line_count += 1
            try:
                event = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                failures.append({"line": lineno, "problem": "invalid_json", "detail": str(exc)})
                continue
            prev = event.get("prev_line_sha256")
            if not chain_started and prev is None and event.get("event_sha256") is None:
                legacy_lines += 1
                previous_line_hash = sha256_bytes(raw)
                last_line_hash = previous_line_hash
                continue
            if not chain_started:
                chain_started = True
                first_prev = prev
                if expected_first_prev is not ... and first_prev != expected_first_prev:
                    failures.append({
                        "line": lineno, "problem": "first_prev_mismatch",
                        "expected": expected_first_prev, "actual": first_prev,
                    })
            elif prev != previous_line_hash:
                failures.append({
                    "line": lineno, "problem": "prev_line_mismatch",
                    "expected": previous_line_hash,
                    "actual": prev,
                })
            expected_event = ledger_event_sha(event)
            if event.get("event_sha256") != expected_event:
                failures.append({
                    "line": lineno, "problem": "event_sha_mismatch",
                    "expected": expected_event,
                    "actual": event.get("event_sha256"),
                })
            previous_line_hash = sha256_bytes(raw)
            last_line_hash = previous_line_hash
    return {
        "ok": not failures,
        "lines": line_count,
        "legacy_lines": legacy_lines,
        "first_prev_line_sha256": first_prev,
        "last_line_sha256": last_line_hash,
        "failures": failures[:20],
    }


def ledger_action(root: Path, policy: dict[str, Any]) -> list[dict]:
    path = root / "events.jsonl"
    if not path.is_file():
        return []
    size = path.stat().st_size
    threshold = max(1, int(policy.get("ledger_rotate_bytes", 0)))
    if size < threshold:
        return []
    return [{
        "kind": "rotate_ledger",
        "path": str(path),
        "bytes": size,
        "sha256": sha256_file(path),
        "hot_reclaimable_bytes": max(0, size - 4096),
        "reason": "ledger_above_hot_threshold",
    }]


def build_plan(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    root = root.expanduser().resolve()
    deployment, protected = deployment_actions(root, policy)
    raw, raw_stats = raw_duplicate_actions(root, policy)
    ledger = ledger_action(root, policy)
    actions = sorted(deployment + raw + ledger, key=lambda a: (a["kind"], a["path"]))
    plan_core = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "policy_sha256": policy_hash(policy),
        "inventory": inventory(root),
        "protected_deployments": protected,
        "raw_scan": raw_stats,
        "actions": actions,
    }
    plan_id = sha256_bytes(canonical_bytes(plan_core))
    return {
        **plan_core,
        "plan_id": plan_id,
        "created_at": utc_now(),
        "reclaimable_bytes": sum(
            int(a.get("bytes", 0))
            for a in actions
            if a["kind"] in {"remove_deployment", "remove_raw_duplicate"}
        ),
        "hot_reclaimable_bytes": sum(
            int(a.get("hot_reclaimable_bytes", 0)) for a in actions
        ),
    }


def validate_plan(plan: dict[str, Any], root: Path, policy: dict[str, Any]) -> None:
    if int(plan.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError("plan_schema_mismatch")
    if Path(plan["root"]).resolve() != root.resolve():
        raise ValueError("plan_root_mismatch")
    if plan.get("policy_sha256") != policy_hash(policy):
        raise ValueError("plan_policy_mismatch")
    created = parse_time(plan["created_at"])
    age = datetime.now(timezone.utc) - created
    if age.total_seconds() > float(policy.get("plan_max_age_hours", 48)) * 3600:
        raise ValueError("plan_expired")


def create_continuity_proof(summary_path: Path, verification_path: Path) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    bundle = Path(summary["bundle"]).expanduser().resolve()
    verified_bundle = Path(verification["bundle"]).expanduser().resolve()
    if bundle != verified_bundle:
        raise ValueError("bundle_path_mismatch")
    if verification.get("ok") is not True:
        raise ValueError("bundle_verification_failed")
    if not bundle.is_file():
        raise ValueError("bundle_missing")
    actual = sha256_file(bundle)
    if actual != summary.get("bundle_sha256"):
        raise ValueError("bundle_sha256_mismatch")
    return {
        "schema_version": 1,
        "kind": "goms_storage_continuity_proof",
        "bundle": str(bundle),
        "bundle_sha256": actual,
        "bundle_created_at": summary.get("created_at"),
        "files_checked": verification.get("files_checked"),
        "verified": True,
        "verified_at": utc_now(),
    }


def validate_continuity_proof(path: Path, policy: dict[str, Any]) -> dict[str, Any]:
    proof = json.loads(path.read_text(encoding="utf-8"))
    if proof.get("kind") != "goms_storage_continuity_proof" or proof.get("verified") is not True:
        raise ValueError("invalid_continuity_proof")
    verified_at = parse_time(proof["verified_at"])
    age = datetime.now(timezone.utc) - verified_at
    if age.total_seconds() > float(policy.get("continuity_proof_max_age_hours", 720)) * 3600:
        raise ValueError("continuity_proof_expired")
    bundle = Path(proof["bundle"]).expanduser().resolve()
    if not bundle.is_file() or sha256_file(bundle) != proof.get("bundle_sha256"):
        raise ValueError("continuity_bundle_changed")
    return proof


def deployment_preflight(action: dict[str, Any]) -> None:
    path = Path(action["path"])
    if not path.is_dir():
        raise ValueError(f"deployment_missing:{path}")
    stats = tree_stats(path)
    if stats["bytes"] != action["bytes"] or stats["files"] != action["files"]:
        raise ValueError(f"deployment_changed:{path}")
    if stats["fingerprint"] != action["fingerprint"]:
        raise ValueError(f"deployment_fingerprint_changed:{path}")


def raw_duplicate_preflight(action: dict[str, Any]) -> None:
    duplicate = Path(action["path"])
    canonical = Path(action["canonical_path"])
    if not duplicate.is_file() or not canonical.is_file():
        raise ValueError("raw_duplicate_missing")
    expected = action["sha256"]
    if sha256_file(duplicate) != expected or sha256_file(canonical) != expected:
        raise ValueError("raw_duplicate_hash_changed")


def ledger_preflight(action: dict[str, Any]) -> None:
    path = Path(action["path"])
    if not path.is_file() or sha256_file(path) != action["sha256"]:
        raise ValueError("ledger_changed_since_plan")
    result = verify_ledger(path)
    if not result["ok"]:
        raise ValueError("ledger_chain_invalid")


def preflight(plan: dict[str, Any], enable_ledger_rotation: bool) -> None:
    for action in plan.get("actions", []):
        kind = action["kind"]
        if kind == "remove_deployment":
            deployment_preflight(action)
        elif kind == "remove_raw_duplicate":
            raw_duplicate_preflight(action)
        elif kind == "rotate_ledger":
            if enable_ledger_rotation:
                ledger_preflight(action)


def rotation_event(previous_hash: str, archive_rel: str, archive_sha: str,
                   archived_ledger_sha: str, lines: int) -> dict[str, Any]:
    event = {
        "op": "ledger_rotation",
        "actor": "storage-governor",
        "event_id": "event_storage_" + archived_ledger_sha[:12],
        "at": utc_now(),
        "archive": archive_rel,
        "archive_sha256": archive_sha,
        "archived_ledger_sha256": archived_ledger_sha,
        "archived_lines": lines,
        "prev_line_sha256": previous_hash,
    }
    event["event_sha256"] = ledger_event_sha(event)
    return event


def rotate_ledger(root: Path, action: dict[str, Any]) -> dict[str, Any]:
    ledger = root / "events.jsonl"
    lock_path = root / "events.lock"
    cold = root / "cold" / "ledger"
    cold.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if sha256_file(ledger) != action["sha256"]:
            raise ValueError("ledger_changed_before_rotation")
        verification = verify_ledger(ledger)
        if not verification["ok"]:
            raise ValueError("ledger_chain_invalid")
        source_sha = sha256_file(ledger)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = cold / f"events-{stamp}-{source_sha[:12]}.jsonl.gz"
        with ledger.open("rb") as src, archive.open("wb") as raw_out:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0) as gz:
                shutil.copyfileobj(src, gz, length=1024 * 1024)
        archive_sha = sha256_file(archive)
        with gzip.open(archive, "rb") as gz:
            archived_bytes = gz.read()
        if sha256_bytes(archived_bytes) != source_sha:
            raise ValueError("ledger_archive_roundtrip_mismatch")
        event = rotation_event(
            verification["last_line_sha256"],
            archive.relative_to(root).as_posix(),
            archive_sha,
            source_sha,
            verification["lines"],
        )
        manifest = {
            "schema_version": 1,
            "archive": archive.relative_to(root).as_posix(),
            "archive_sha256": archive_sha,
            "archived_ledger_sha256": source_sha,
            "archived_lines": verification["lines"],
            "first_prev_line_sha256": verification["first_prev_line_sha256"],
            "last_line_sha256": verification["last_line_sha256"],
            "rotated_at": event["at"],
            "next_ledger_anchor_event_id": event["event_id"],
        }
        manifest_path = archive.with_suffix(archive.suffix + ".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        tmp = ledger.with_suffix(".jsonl.next")
        tmp.write_text(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        os.replace(tmp, ledger)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    current = verify_ledger(ledger, expected_first_prev=verification["last_line_sha256"])
    if not current["ok"]:
        raise ValueError("rotated_ledger_verification_failed")
    return {
        "archive": str(archive),
        "manifest": str(manifest_path),
        "archive_bytes": archive.stat().st_size,
        "archived_bytes": action["bytes"],
        "new_hot_ledger_bytes": ledger.stat().st_size,
    }


def verify_archive_manifest(root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive = root / manifest["archive"]
    failures = []
    if not archive.is_file():
        failures.append("archive_missing")
    elif sha256_file(archive) != manifest["archive_sha256"]:
        failures.append("archive_sha256_mismatch")
    if archive.is_file():
        with gzip.open(archive, "rb") as gz:
            data = gz.read()
        if sha256_bytes(data) != manifest["archived_ledger_sha256"]:
            failures.append("archived_ledger_sha256_mismatch")
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(data)
            tmp_path = Path(handle.name)
        try:
            result = verify_ledger(tmp_path)
            if not result["ok"]:
                failures.append("archived_ledger_chain_invalid")
            if result["last_line_sha256"] != manifest["last_line_sha256"]:
                failures.append("archive_last_line_mismatch")
        finally:
            tmp_path.unlink(missing_ok=True)
    return {"ok": not failures, "failures": failures}


def apply_plan(root: Path, policy: dict[str, Any], plan: dict[str, Any],
               continuity_proof: Path, enable_ledger_rotation: bool = False) -> dict[str, Any]:
    validate_plan(plan, root, policy)
    proof = validate_continuity_proof(continuity_proof, policy)
    preflight(plan, enable_ledger_rotation)
    applied = []
    skipped = []
    reclaimed = 0
    hot_reclaimed = 0
    for action in plan.get("actions", []):
        kind = action["kind"]
        if kind == "remove_deployment":
            shutil.rmtree(Path(action["path"]))
            reclaimed += int(action["bytes"])
            applied.append(action)
        elif kind == "remove_raw_duplicate":
            Path(action["path"]).unlink()
            reclaimed += int(action["bytes"])
            applied.append(action)
        elif kind == "rotate_ledger":
            if not enable_ledger_rotation:
                skipped.append({**action, "skip_reason": "ledger_rotation_not_enabled"})
                continue
            result = rotate_ledger(root, action)
            hot_reclaimed += max(
                0, int(action["bytes"]) - int(result["new_hot_ledger_bytes"])
            )
            applied.append({**action, "result": result})
    state_dir = root / "storage-governance" / "history"
    state_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "plan_id": plan["plan_id"],
        "applied_at": utc_now(),
        "continuity_proof": {
            "bundle": proof["bundle"],
            "bundle_sha256": proof["bundle_sha256"],
            "verified_at": proof["verified_at"],
        },
        "applied": applied,
        "skipped": skipped,
        "reclaimed_bytes": reclaimed,
        "hot_reclaimed_bytes": hot_reclaimed,
        "inventory_after": inventory(root),
    }
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-apply.json"
    (state_dir / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def verify_root(root: Path) -> dict[str, Any]:
    failures = []
    ledger = root / "events.jsonl"
    if ledger.is_file():
        result = verify_ledger(ledger)
        if not result["ok"]:
            failures.append({"kind": "ledger", "detail": result})
    archive_results = []
    cold = root / "cold" / "ledger"
    if cold.is_dir():
        for manifest in sorted(cold.glob("*.manifest.json")):
            result = verify_archive_manifest(root, manifest)
            archive_results.append({"manifest": str(manifest), **result})
            if not result["ok"]:
                failures.append({"kind": "ledger_archive", "manifest": str(manifest),
                                 "detail": result})
    return {
        "ok": not failures,
        "inventory": inventory(root),
        "ledger_archives": archive_results,
        "failures": failures,
    }


def scheduled(root: Path, policy: dict[str, Any], policy_path: Path | None,
              state_dir: Path, enable_ledger_rotation: bool) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    plan = build_plan(root, policy)
    plan_path = state_dir / "latest-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    report: dict[str, Any] = {
        "mode": "dry-run",
        "plan": str(plan_path),
        "plan_id": plan["plan_id"],
        "actions": len(plan["actions"]),
        "reclaimable_bytes": plan["reclaimable_bytes"],
        "hot_reclaimable_bytes": plan["hot_reclaimable_bytes"],
        "inventory": plan["inventory"],
        "raw_scan": plan["raw_scan"],
    }
    proof_path = state_dir / "continuity-proof.json"
    if policy.get("auto_apply") and proof_path.is_file():
        try:
            validate_continuity_proof(proof_path, policy)
            applied = apply_plan(
                root, policy, plan, proof_path,
                enable_ledger_rotation=enable_ledger_rotation,
            )
            report["mode"] = "apply"
            report["apply"] = applied
        except Exception as exc:
            report["apply_blocked"] = str(exc)
    elif policy.get("auto_apply"):
        report["apply_blocked"] = "continuity_proof_missing"
    latest = state_dir / "latest-report.json"
    latest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path(os.environ.get("GOMS_HOME", ".")))
    parser.add_argument("--policy", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inventory")
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--output", type=Path)

    p_proof = sub.add_parser("proof")
    p_proof.add_argument("--summary", type=Path, required=True)
    p_proof.add_argument("--verification", type=Path, required=True)
    p_proof.add_argument("--output", type=Path, required=True)

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--plan", type=Path, required=True)
    p_apply.add_argument("--continuity-proof", type=Path, required=True)
    p_apply.add_argument("--enable-ledger-rotation", action="store_true")

    sub.add_parser("verify")

    p_scheduled = sub.add_parser("scheduled")
    p_scheduled.add_argument("--state-dir", type=Path)
    p_scheduled.add_argument("--enable-ledger-rotation", action="store_true")

    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    policy = load_policy(args.policy)

    if args.command == "inventory":
        result = inventory(root)
    elif args.command == "plan":
        result = build_plan(root, policy)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    elif args.command == "proof":
        result = create_continuity_proof(args.summary, args.verification)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    elif args.command == "apply":
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        result = apply_plan(
            root, policy, plan, args.continuity_proof,
            enable_ledger_rotation=args.enable_ledger_rotation,
        )
    elif args.command == "verify":
        result = verify_root(root)
    else:
        state_dir = args.state_dir or (root / "storage-governance")
        result = scheduled(
            root, policy, args.policy, state_dir,
            enable_ledger_rotation=args.enable_ledger_rotation,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
