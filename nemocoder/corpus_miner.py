#!/usr/bin/env python3
"""Build a deterministic provenance-only historical task manifest from Git merges."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

SCHEMA_VERSION = 1
PR_RE = re.compile(r"Merge pull request #(\d+)")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*[\"']?[A-Za-z0-9._~+/-]{16,}", re.I),
    re.compile(r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{12,}", re.I),
)

class GitError(RuntimeError):
    pass

def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout or "git command failed").strip())
    return proc.stdout

def _remote_identity(repo: Path) -> str:
    try:
        value = _git(repo, "remote", "get-url", "origin").strip()
    except GitError:
        value = ""
    return value or str(repo.resolve())

def _normalize_task_text(body: str) -> tuple[str | None, str]:
    body = body.strip()
    if not body:
        return None, "missing_task_text"
    if any(pattern.search(body) for pattern in SECRET_PATTERNS):
        return None, "quarantined_secret_pattern"
    return body, "metadata_admitted"

def _changed_paths(repo: Path, base_sha: str, solution_sha: str) -> list[dict[str, object]]:
    raw = _git(repo, "diff", "--name-status", "--find-renames", base_sha, solution_sha)
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            rows.append({"status": status, "path": parts[2], "previous_path": parts[1]})
        elif len(parts) >= 2:
            rows.append({"status": status, "path": parts[1]})
    return rows

def collect(repo: Path, *, max_records: int = 100) -> list[dict[str, object]]:
    repo = repo.resolve()
    _git(repo, "rev-parse", "--git-dir")
    raw = _git(
        repo, "log", "--first-parent", "--merges",
        f"--max-count={max(1, int(max_records))}",
        "--format=%H%x00%P%x00%B%x1e",
    )
    records = []
    for chunk in raw.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        parts = chunk.split("\x00", 2)
        if len(parts) != 3:
            continue
        solution_sha, parents, body = parts
        parent_list = [p for p in parents.split() if p]
        if not parent_list:
            continue
        base_sha = parent_list[0]
        task_text, admission = _normalize_task_text(body)
        pr_match = PR_RE.search(body)
        changed = _changed_paths(repo, base_sha, solution_sha)
        records.append({
            "schema_version": SCHEMA_VERSION,
            "source_type": "git_first_parent_merge",
            "source_repository": _remote_identity(repo),
            "source_ref": f"commit:{solution_sha}",
            "base_sha": base_sha,
            "solution_sha": solution_sha,
            "pr_number": int(pr_match.group(1)) if pr_match else None,
            "task_text": task_text,
            "admission": admission,
            "changed_paths": changed,
            "changed_paths_sha256": hashlib.sha256(
                json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        })
    records.reverse()
    return records

def write_manifest(records: list[dict[str, object]], output: Path, *, repository: str, head: str) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in records)
    output.write_text(payload)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "head": head,
        "record_count": len(records),
        "records_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "records_file": output.name,
        "content_scope": "provenance_only_no_patches",
    }
    output.with_suffix(output.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--max-records", type=int, default=100)
    args = ap.parse_args()
    repo = args.repo.expanduser().resolve()
    records = collect(repo, max_records=args.max_records)
    manifest = write_manifest(
        records,
        args.output.expanduser().resolve(),
        repository=_remote_identity(repo),
        head=_git(repo, "rev-parse", "HEAD").strip(),
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
