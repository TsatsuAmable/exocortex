#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from goms_store import GomsStore


@dataclass(frozen=True)
class RepositoryReconciliationPolicy:
    task_id: str
    repository: Path
    canonical_branch: str = "main"
    upstream_ref: str = "origin/main"
    required_preservation_refs: tuple[str, ...] = ()
    required_preservation_commits: tuple[tuple[str, str], ...] = ()


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
    )


def _inspect(policy: RepositoryReconciliationPolicy) -> dict:
    repo = Path(policy.repository).expanduser().resolve()
    state = {"repository": str(repo), "reasons": [], "preservation_refs": {}}
    if not repo.is_dir():
        state["reasons"].append("repository_missing")
        return state

    probe = _git(repo, "rev-parse", "--is-inside-work-tree", check=False)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        state["reasons"].append("not_git_repository")
        return state
    remote = policy.upstream_ref.split("/", 1)[0]
    fetched = _git(repo, "fetch", "--quiet", remote, check=False)
    if fetched.returncode != 0:
        state["reasons"].append("fetch_failed")
        state["fetch_error"] = fetched.stderr.strip()
        return state

    branch = _git(repo, "branch", "--show-current").stdout.strip()
    state["branch"] = branch
    if branch != policy.canonical_branch:
        state["reasons"].append("wrong_branch")

    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout
    state["dirty"] = bool(status.strip())
    if state["dirty"]:
        state["reasons"].append("dirty_worktree")

    divergence = _git(
        repo, "rev-list", "--left-right", "--count",
        f"HEAD...{policy.upstream_ref}", check=False,
    )
    if divergence.returncode != 0:
        state["reasons"].append("upstream_unavailable")
        return state
    ahead, behind = (int(value) for value in divergence.stdout.split())
    state.update({"ahead": ahead, "behind": behind})
    if ahead or behind:
        state["reasons"].append("not_aligned")

    state["head"] = _git(repo, "rev-parse", "HEAD").stdout.strip()
    resolved_refs = {}
    for ref in policy.required_preservation_refs:
        check_ref = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        exists = check_ref.returncode == 0
        resolved = check_ref.stdout.strip() if exists else None
        resolved_refs[ref] = resolved
        state["preservation_refs"][ref] = resolved
        if not exists and "missing_preservation_ref" not in state["reasons"]:
            state["reasons"].append("missing_preservation_ref")

    for ref, expected in policy.required_preservation_commits:
        resolved = resolved_refs.get(ref)
        if resolved is None:
            check_ref = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
            resolved = check_ref.stdout.strip() if check_ref.returncode == 0 else None
            state["preservation_refs"][ref] = resolved
        if resolved != expected and "preservation_ref_mismatch" not in state["reasons"]:
            state["reasons"].append("preservation_ref_mismatch")

    state["eligible"] = not state["reasons"]
    return state


def default_repository_policies() -> list[RepositoryReconciliationPolicy]:
    return [
        RepositoryReconciliationPolicy(
            task_id="nemosyne-local",
            repository=Path.home() / "Documents" / "nemosyne",
            canonical_branch="main",
            upstream_ref="origin/main",
            required_preservation_refs=(
                "refs/heads/archive/local-pt4b-snapshot-2026-09-10",
            ),
            required_preservation_commits=((
                "refs/heads/archive/local-pt4b-snapshot-2026-09-10",
                "e695d894830e66a8f27e8a4e1eb6a4e6c821f6b2",
            ),),
        )
    ]


def reconcile_repository_tasks(root: str | Path, policies=None) -> list[dict]:
    store = GomsStore(root)
    policies = list(default_repository_policies() if policies is None else policies)
    results = []
    for policy in policies:
        with store.connect() as con:
            row = con.execute("SELECT status FROM branches WHERE id=?", (policy.task_id,)).fetchone()
        if not row or str(row["status"]).upper() != "BLOCKED":
            results.append({"task_id": policy.task_id, "disposition": "SKIPPED", "reasons": ["not_blocked"]})
            continue
        state = _inspect(policy)
        result = {"task_id": policy.task_id, **state}
        if not state.get("eligible"):
            result["disposition"] = "BLOCKED"
            results.append(result)
            continue

        refs = ", ".join(policy.required_preservation_refs) or "none required"
        summary = (
            f"Repository reconciliation verified: {policy.canonical_branch} is clean and exactly aligned "
            f"with {policy.upstream_ref} at {state['head'][:12]}; preservation refs verified: {refs}."
        )
        store.checkpoint(
            policy.task_id,
            "CONCLUDED",
            summary,
            unresolved=[],
            next_action=(
                "Treat future upstream drift as routine synchronization; preserve unique work in "
                "dedicated branches or isolated worktrees before canonical-main reconciliation."
            ),
            blocker="",
            source="repository-reconciliation",
            actor="system:repository-reconciliation",
        )
        result["disposition"] = "CONCLUDED"
        results.append(result)
    return results
