#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from delivery import Store

ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = Path(os.environ.get(
    "AINEKO_WORKTREE_ROOT",
    Path.home() / "Library/Application Support/Aineko/worktrees",
)).expanduser()
POLICY_ROOT = ROOT / "policies"
AUTHORITY = {"observe": 0, "pr": 1, "staging": 2, "production": 3}


class WorkspaceError(RuntimeError):
    pass


def run(args: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    cp = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if cp.returncode:
        raise WorkspaceError(cp.stderr.strip() or cp.stdout.strip() or f"command failed: {args[0]}")
    return cp.stdout.strip()


def require_pr_authority(job: dict) -> None:
    if AUTHORITY.get(job.get("authority", "observe"), 0) < AUTHORITY["pr"]:
        raise WorkspaceError(f"job {job['id']} lacks PR write authority")
    if not job.get("pr_number"):
        raise WorkspaceError(f"job {job['id']} has no attached PR")


def repo_slug_from_remote(remote: str) -> str | None:
    remote = remote.strip()
    if remote.startswith("git@github.com:"):
        slug = remote.split(":", 1)[1]
    elif "github.com/" in remote:
        slug = remote.split("github.com/", 1)[1]
    else:
        return None
    return slug.removesuffix(".git").strip("/")


def load_policy(repo: str, policy_root: Path = POLICY_ROOT) -> dict:
    path = policy_root / f"{repo.replace('/', '__')}.json"
    if not path.is_file():
        raise WorkspaceError(f"no delivery policy for {repo}: {path}")
    policy = json.loads(path.read_text())
    if policy.get("repository") != repo:
        raise WorkspaceError(f"policy repository mismatch in {path}")
    return policy


def normalize_repo_path(raw: str) -> str:
    path = raw.replace("\\", "/").strip()
    while path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    if path.startswith("/") or path == ".." or path.startswith("../") or "/../" in path:
        raise WorkspaceError(f"unsafe repository path: {raw}")
    return path


def ensure_allowed(paths: list[str] | set[str], policy: dict) -> list[str]:
    blocked = [p.rstrip("/") for p in policy.get("blocked_paths", [])]
    clean = sorted({normalize_repo_path(p) for p in paths if p and p != "/dev/null"})
    for path in clean:
        for prefix in blocked:
            if path == prefix or path.startswith(prefix + "/"):
                raise WorkspaceError(f"policy blocks change to {path}")
    return clean


def patch_paths(text: str) -> list[str]:
    paths = set()
    for line in text.splitlines():
        if not (line.startswith("+++ ") or line.startswith("--- ")):
            continue
        raw = line[4:].split("\t", 1)[0].strip()
        if raw != "/dev/null":
            paths.add(normalize_repo_path(raw))
    if not paths:
        raise WorkspaceError("patch contains no repository paths")
    return sorted(paths)


def pr_metadata(job: dict) -> dict:
    fields = "headRefName,headRefOid,isCrossRepository,state,url"
    raw = run(["gh", "pr", "view", str(job["pr_number"]), "-R", job["repo"], "--json", fields])
    data = json.loads(raw)
    if data.get("isCrossRepository"):
        raise WorkspaceError("cross-repository PR writes are not supported in this tranche")
    if data.get("state") != "OPEN":
        raise WorkspaceError(f"PR is not open: {data.get('state')}")
    return {
        "head_ref": data["headRefName"],
        "expected_remote_head": data["headRefOid"],
        "url": data.get("url", ""),
    }


def meta_path(job_id: str, worktree_root: Path = WORKTREE_ROOT) -> Path:
    return worktree_root / ".meta" / f"{job_id}.json"


def read_meta(job_id: str, worktree_root: Path = WORKTREE_ROOT) -> dict:
    path = meta_path(job_id, worktree_root)
    if not path.is_file():
        raise WorkspaceError(f"workspace not prepared for {job_id}")
    return json.loads(path.read_text())


def write_meta(job_id: str, meta: dict, worktree_root: Path = WORKTREE_ROOT) -> None:
    path = meta_path(job_id, worktree_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")


def prepare(store: Store, job_id: str, source: Path, worktree_root: Path = WORKTREE_ROOT,
            policy_root: Path = POLICY_ROOT) -> dict:
    job = store.get(job_id)
    require_pr_authority(job)
    policy = load_policy(job["repo"], policy_root)
    source = source.expanduser().resolve()
    slug = repo_slug_from_remote(run(["git", "-C", str(source), "remote", "get-url", "origin"]))
    if not slug or slug.lower() != job["repo"].lower():
        raise WorkspaceError(f"source origin does not match {job['repo']}")
    pr = pr_metadata(job)
    run(["git", "-C", str(source), "fetch", "origin", pr["head_ref"]], timeout=180)
    worktree = worktree_root / job_id
    if worktree.exists():
        raise WorkspaceError(f"workspace already exists: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    branch = f"aineko/{job_id}"
    run(["git", "-C", str(source), "worktree", "add", "-b", branch, str(worktree), pr["expected_remote_head"]])
    meta = {**pr, "job_id": job_id, "repo": job["repo"], "source": str(source),
            "worktree": str(worktree), "branch": branch, "policy": policy.get("name", job["repo"])}
    write_meta(job_id, meta, worktree_root)
    store.record_event(job_id, "workspace_prepare", {"worktree": str(worktree), "head": pr["expected_remote_head"]})
    return meta


def apply_patch(store: Store, job_id: str, patch: Path,
                worktree_root: Path = WORKTREE_ROOT, policy_root: Path = POLICY_ROOT) -> list[str]:
    job = store.get(job_id)
    require_pr_authority(job)
    meta = read_meta(job_id, worktree_root)
    policy = load_policy(job["repo"], policy_root)
    text = patch.expanduser().read_text()
    paths = ensure_allowed(patch_paths(text), policy)
    worktree = Path(meta["worktree"])
    run(["git", "apply", "--check", str(patch)], cwd=worktree)
    run(["git", "apply", str(patch)], cwd=worktree)
    store.record_event(job_id, "patch_apply", {"paths": paths})
    return paths


def run_check(store: Store, job_id: str, profile: str,
              worktree_root: Path = WORKTREE_ROOT, policy_root: Path = POLICY_ROOT) -> str:
    job = store.get(job_id)
    meta = read_meta(job_id, worktree_root)
    policy = load_policy(job["repo"], policy_root)
    command = policy.get("checks", {}).get(profile)
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise WorkspaceError(f"unknown verification profile: {profile}")
    try:
        output = run(command, cwd=Path(meta["worktree"]), timeout=int(policy.get("check_timeout_seconds", 900)))
    except Exception as exc:
        store.record_event(job_id, "check_failed", {"profile": profile, "error": str(exc)[-2000:]})
        raise
    store.record_event(job_id, "check_passed", {"profile": profile})
    return output


def changed_paths(worktree: Path) -> list[str]:
    tracked = run(["git", "diff", "--name-only", "HEAD"], cwd=worktree).splitlines()
    untracked = run(["git", "ls-files", "--others", "--exclude-standard"], cwd=worktree).splitlines()
    return sorted(set(tracked + untracked))


def commit_push(store: Store, job_id: str, message: str,
                worktree_root: Path = WORKTREE_ROOT, policy_root: Path = POLICY_ROOT) -> str:
    job = store.get(job_id)
    require_pr_authority(job)
    meta = read_meta(job_id, worktree_root)
    policy = load_policy(job["repo"], policy_root)
    worktree = Path(meta["worktree"])
    paths = ensure_allowed(changed_paths(worktree), policy)
    if not paths:
        raise WorkspaceError("no changes to commit")
    current = pr_metadata(job)
    if current["head_ref"] != meta["head_ref"]:
        raise WorkspaceError("PR head branch changed since workspace preparation")
    if current["expected_remote_head"] != meta["expected_remote_head"]:
        raise WorkspaceError("PR head moved; reprepare/reconcile before push")
    run(["git", "add", "--", *paths], cwd=worktree)
    run(["git", "commit", "-m", message], cwd=worktree)
    new_head = run(["git", "rev-parse", "HEAD"], cwd=worktree)
    run(["git", "push", "origin", f"HEAD:refs/heads/{meta['head_ref']}"], cwd=worktree, timeout=180)
    meta["expected_remote_head"] = new_head
    write_meta(job_id, meta, worktree_root)
    store.record_event(job_id, "commit_push", {"head": new_head, "paths": paths, "message": message})
    return new_head


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aineko bounded PR workspace tools")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("prepare"); a.add_argument("job"); a.add_argument("--source", required=True)
    a = sub.add_parser("apply"); a.add_argument("job"); a.add_argument("--patch", required=True)
    a = sub.add_parser("check"); a.add_argument("job"); a.add_argument("profile")
    a = sub.add_parser("commit-push"); a.add_argument("job"); a.add_argument("--message", required=True)
    return p


def main() -> None:
    args = build_parser().parse_args()
    store = Store()
    if args.command == "prepare":
        print(json.dumps(prepare(store, args.job, Path(args.source)), indent=2))
    elif args.command == "apply":
        print(json.dumps({"paths": apply_patch(store, args.job, Path(args.patch))}, indent=2))
    elif args.command == "check":
        output = run_check(store, args.job, args.profile)
        print(output)
    elif args.command == "commit-push":
        print(commit_push(store, args.job, args.message))


if __name__ == "__main__":
    main()
