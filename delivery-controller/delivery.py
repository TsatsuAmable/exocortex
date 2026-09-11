#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parent
if sys.platform == "darwin":
    DEFAULT_STATE_DIR = Path.home() / "Library" / "Application Support" / "Aineko" / "delivery-controller"
else:
    DEFAULT_STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "aineko" / "delivery-controller"
DB_PATH = Path(os.environ.get("AINEKO_DELIVERY_DB", DEFAULT_STATE_DIR / "delivery.sqlite3"))
GOMS_ROOT = ROOT.parent / "goms-v2"
LOCAL_DISPATCH = ROOT.parent / "local-ai" / "dispatch.py"

STATES = {
    "CREATED", "PLANNING", "IMPLEMENTING", "LOCAL_VERIFY", "PR_OPEN",
    "WAIT_CI", "WAIT_APPROVAL", "WAIT_REVIEW", "MERGE_GATE", "MERGED", "DEPLOY_STAGING",
    "VERIFY_STAGING", "PRODUCTION_GATE", "DEPLOY_PRODUCTION",
    "VERIFY_PRODUCTION", "COMPLETE", "BLOCKED", "FAILED", "ABORTED",
}
TERMINAL_STATES = {"COMPLETE", "FAILED", "ABORTED"}
ACTIVE_STATES = STATES - TERMINAL_STATES
FAIL_CHECKS = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STALE"}
PENDING_CHECKS = {"PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "WAITING", "REQUESTED"}
HUMAN_GATE_CHECKS = {"approval-gate"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_id() -> str:
    return "job_" + uuid.uuid4().hex[:12]


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY,
  repo TEXT NOT NULL,
  goal TEXT NOT NULL,
  state TEXT NOT NULL,
  authority TEXT NOT NULL DEFAULT 'observe',
  provider TEXT NOT NULL DEFAULT 'none',
  pr_number INTEGER,
  goms_branch_id TEXT,
  last_result TEXT NOT NULL DEFAULT '',
  next_action TEXT NOT NULL DEFAULT '',
  blocker TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT,
  detail TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, seq);
"""


class Provider(Protocol):
    def advise(self, task_type: str, prompt: str) -> str: ...


class NullProvider:
    def advise(self, task_type: str, prompt: str) -> str:
        return ""


class LocalDispatchProvider:
    """Adapter to the existing local-ai dispatcher. Model choice remains outside this controller."""
    def advise(self, task_type: str, prompt: str) -> str:
        if not LOCAL_DISPATCH.exists():
            raise RuntimeError(f"local dispatcher missing: {LOCAL_DISPATCH}")
        cp = subprocess.run(
            [sys.executable, str(LOCAL_DISPATCH), "--task", task_type, "--prompt", prompt],
            text=True, capture_output=True, timeout=300,
        )
        if cp.returncode:
            raise RuntimeError(cp.stderr.strip() or f"dispatcher exited {cp.returncode}")
        return cp.stdout.strip()


def provider_for(name: str) -> Provider:
    if name == "local-dispatch":
        return LocalDispatchProvider()
    return NullProvider()


class GomsBridge:
    def __init__(self):
        self.store = None
        if GOMS_ROOT.exists():
            sys.path.insert(0, str(GOMS_ROOT))
            try:
                from goms_store import GomsStore
                self.store = GomsStore()
            except Exception:
                self.store = None

    @staticmethod
    def branch_status(state: str) -> str:
        if state in TERMINAL_STATES:
            return "CONCLUDED"
        if state == "BLOCKED":
            return "BLOCKED"
        if state in {"WAIT_CI", "WAIT_APPROVAL", "WAIT_REVIEW"}:
            return "DELEGATED"
        return "ACTIVE"

    def create(self, job_id: str, repo: str, goal: str) -> str | None:
        if not self.store:
            return None
        return self.store.create_branch(
            title=f"Delivery {job_id}: {repo}", project=repo,
            objective=goal, next_action="Observe/plan delivery job",
            actor="delivery-controller",
        )

    def checkpoint(self, branch_id: str | None, state: str, summary: str,
                   next_action: str = "", blocker: str = "") -> None:
        if not self.store or not branch_id:
            return
        self.store.checkpoint(
            branch_id, self.branch_status(state), summary or state,
            next_action=next_action, blocker=blocker, actor="delivery-controller",
        )


class Store:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def submit(self, repo: str, goal: str, authority: str, provider: str,
               pr_number: int | None, goms: GomsBridge) -> str:
        jid, ts = make_id(), now()
        branch = goms.create(jid, repo, goal)
        state = "PR_OPEN" if pr_number else "CREATED"
        next_action = "Observe PR checks/reviews" if pr_number else "Plan or attach a PR when work begins"
        with self.connect() as con:
            con.execute(
                """INSERT INTO jobs(id,repo,goal,state,authority,provider,pr_number,goms_branch_id,
                   next_action,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (jid, repo, goal, state, authority, provider, pr_number, branch,
                 next_action, ts, ts),
            )
            con.execute(
                "INSERT INTO events(job_id,at,kind,to_state,detail) VALUES(?,?,?,?,?)",
                (jid, ts, "submit", state, json.dumps({"goal": goal, "pr": pr_number})),
            )
        goms.checkpoint(branch, state, f"Delivery job submitted: {goal}", next_action)
        return jid

    def get(self, jid: str) -> dict:
        with self.connect() as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise KeyError(jid)
        return dict(row)

    def list(self, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM jobs"
        vals: list[str] = []
        if active_only:
            marks = ",".join("?" for _ in ACTIVE_STATES)
            sql += f" WHERE state IN ({marks})"
            vals = sorted(ACTIVE_STATES)
        sql += " ORDER BY updated_at DESC"
        with self.connect() as con:
            return [dict(r) for r in con.execute(sql, vals).fetchall()]

    def transition(self, jid: str, to_state: str, reason: str,
                   next_action: str = "", blocker: str = "", kind: str = "transition") -> dict:
        if to_state not in STATES:
            raise ValueError(f"unknown state: {to_state}")
        job = self.get(jid)
        ts = now()
        with self.connect() as con:
            con.execute(
                """UPDATE jobs SET state=?,last_result=?,next_action=?,blocker=?,updated_at=?
                   WHERE id=?""",
                (to_state, reason, next_action, blocker, ts, jid),
            )
            con.execute(
                "INSERT INTO events(job_id,at,kind,from_state,to_state,detail) VALUES(?,?,?,?,?,?)",
                (jid, ts, kind, job["state"], to_state,
                 json.dumps({"reason": reason, "next_action": next_action, "blocker": blocker})),
            )
        return self.get(jid)

    def record_event(self, jid: str, kind: str, detail: dict) -> None:
        job = self.get(jid)
        with self.connect() as con:
            con.execute(
                "INSERT INTO events(job_id,at,kind,from_state,to_state,detail) VALUES(?,?,?,?,?,?)",
                (jid, now(), kind, job["state"], job["state"], json.dumps(detail)),
            )

    def attach_pr(self, jid: str, pr: int) -> dict:
        ts = now()
        job = self.get(jid)
        with self.connect() as con:
            con.execute("UPDATE jobs SET pr_number=?,state='PR_OPEN',updated_at=? WHERE id=?", (pr, ts, jid))
            con.execute(
                "INSERT INTO events(job_id,at,kind,from_state,to_state,detail) VALUES(?,?,?,?,?,?)",
                (jid, ts, "attach_pr", job["state"], "PR_OPEN", json.dumps({"pr": pr})),
            )
        return self.get(jid)


@dataclass
class PrObservation:
    merged: bool
    closed: bool
    checks: str
    failed_checks: list[str]
    pending_checks: list[str]
    review_decision: str
    merge_state: str
    url: str


class GitHub:
    def observe_pr(self, repo: str, number: int) -> PrObservation:
        fields = "state,mergedAt,mergeStateStatus,reviewDecision,statusCheckRollup,url"
        cp = subprocess.run(
            ["gh", "pr", "view", str(number), "-R", repo, "--json", fields],
            text=True, capture_output=True, timeout=45,
        )
        if cp.returncode:
            raise RuntimeError(cp.stderr.strip() or f"gh exited {cp.returncode}")
        data = json.loads(cp.stdout)
        failed, pending = [], []
        rollup = data.get("statusCheckRollup") or []
        latest_by_name = {}
        for index, check in enumerate(rollup):
            name = check.get("name") or check.get("context") or "unnamed-check"
            stamp = check.get("startedAt") or check.get("completedAt") or ""
            previous = latest_by_name.get(name)
            if previous is None or (stamp, index) >= previous[0]:
                latest_by_name[name] = ((stamp, index), check)
        for name, (_, check) in latest_by_name.items():
            state = (check.get("conclusion") or check.get("state") or check.get("status") or "").upper()
            if state in FAIL_CHECKS:
                failed.append(name)
            elif state in PENDING_CHECKS or not state:
                pending.append(name)
        checks = "failed" if failed else "pending" if pending else "green" if rollup else "none"
        state = (data.get("state") or "").upper()
        return PrObservation(
            merged=bool(data.get("mergedAt")),
            closed=state == "CLOSED" and not data.get("mergedAt"),
            checks=checks,
            failed_checks=failed,
            pending_checks=pending,
            review_decision=(data.get("reviewDecision") or "").upper(),
            merge_state=(data.get("mergeStateStatus") or "").upper(),
            url=data.get("url") or "",
        )


class Controller:
    def __init__(self, store: Store, goms: GomsBridge, github: GitHub | None = None):
        self.store, self.goms, self.github = store, goms, github or GitHub()

    def tick_job(self, job: dict) -> dict:
        jid, state = job["id"], job["state"]
        if state in TERMINAL_STATES:
            return job
        if not job.get("pr_number"):
            # v0.1 is intentionally non-destructive: persist and wait for explicit work/PR attachment.
            return job

        try:
            obs = self.github.observe_pr(job["repo"], int(job["pr_number"]))
        except Exception as exc:
            out = self.store.transition(jid, "BLOCKED", f"GitHub observation failed: {exc}",
                                        next_action="Restore GitHub access and retry", blocker=str(exc),
                                        kind="observation_error")
            self.goms.checkpoint(job.get("goms_branch_id"), out["state"], out["last_result"],
                                 out["next_action"], out["blocker"])
            return out

        if obs.merged:
            target, reason, nxt = "MERGED", f"PR merged: {obs.url}", "Observe deployment or mark complete"
        elif obs.closed:
            target, reason, nxt = "ABORTED", f"PR closed without merge: {obs.url}", ""
        elif obs.checks == "failed" and obs.failed_checks and all(
            name.lower() in HUMAN_GATE_CHECKS for name in obs.failed_checks
        ):
            target = "WAIT_APPROVAL"
            reason = "Human/policy gate pending: " + ", ".join(obs.failed_checks)
            nxt = "Provide exact-head approval/promotion evidence; controller remains observe-only"
        elif obs.checks == "failed":
            target = "WAIT_CI"
            reason = "CI failures: " + ", ".join(obs.failed_checks)
            nxt = "Diagnose and remediate failed checks"
        elif obs.checks == "pending":
            target, reason, nxt = "WAIT_CI", "CI is still running", "Wait for GitHub checks"
        elif obs.checks in {"green", "none"} and obs.review_decision == "CHANGES_REQUESTED":
            target, reason, nxt = "WAIT_REVIEW", "Review changes requested", "Address review feedback"
        elif obs.checks in {"green", "none"} and obs.review_decision in {"APPROVED", ""}:
            target = "MERGE_GATE"
            reason = f"Checks {obs.checks}; review={obs.review_decision or 'not-required/unknown'}; merge={obs.merge_state or 'unknown'}"
            nxt = "Evaluate merge policy; v0.1 never auto-merges"
        else:
            target, reason, nxt = "WAIT_REVIEW", f"Awaiting review: {obs.review_decision or 'pending'}", "Wait for review"

        out = self.store.transition(jid, target, reason, nxt, kind="github_observation")
        self.goms.checkpoint(job.get("goms_branch_id"), out["state"], reason, nxt)
        return out

    def tick(self, only: str | None = None) -> list[dict]:
        jobs = [self.store.get(only)] if only else self.store.list(active_only=True)
        return [self.tick_job(j) for j in jobs]


def print_jobs(rows: list[dict]) -> None:
    if not rows:
        print("No delivery jobs.")
        return
    for j in rows:
        pr = f"PR#{j['pr_number']}" if j.get("pr_number") else "no-pr"
        print(f"{j['id']}  {j['state']:<16} {j['repo']:<32} {pr:<8} {j['goal']}")
        if j.get("last_result"):
            print(f"  result: {j['last_result']}")
        if j.get("next_action"):
            print(f"  next:   {j['next_action']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aineko local durable delivery controller")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    s = sub.add_parser("submit")
    s.add_argument("--repo", required=True, help="GitHub OWNER/REPO")
    s.add_argument("--goal", required=True)
    s.add_argument("--pr", type=int)
    s.add_argument("--authority", choices=["observe", "pr", "staging", "production"], default="observe")
    s.add_argument("--provider", choices=["none", "local-dispatch"], default="none")
    st = sub.add_parser("status")
    st.add_argument("--active", action="store_true")
    st.add_argument("--json", action="store_true")
    t = sub.add_parser("tick")
    t.add_argument("--job")
    a = sub.add_parser("attach-pr")
    a.add_argument("job"); a.add_argument("pr", type=int)
    tr = sub.add_parser("advance")
    tr.add_argument("job"); tr.add_argument("state", choices=sorted(STATES)); tr.add_argument("--reason", required=True)
    sub.add_parser("doctor")
    return p


def main() -> None:
    args = build_parser().parse_args()
    store, goms = Store(), GomsBridge()
    if args.command == "init":
        print(f"delivery controller ready: {store.path}")
    elif args.command == "submit":
        jid = store.submit(args.repo, args.goal, args.authority, args.provider, args.pr, goms)
        print(jid)
    elif args.command == "status":
        rows = store.list(active_only=args.active)
        print(json.dumps(rows, indent=2) if args.json else "", end="" if args.json else "")
        if not args.json: print_jobs(rows)
    elif args.command == "tick":
        print_jobs(Controller(store, goms).tick(args.job))
    elif args.command == "attach-pr":
        out = store.attach_pr(args.job, args.pr)
        goms.checkpoint(out.get("goms_branch_id"), out["state"], f"Attached PR #{args.pr}", "Observe PR")
        print_jobs([out])
    elif args.command == "advance":
        out = store.transition(args.job, args.state, args.reason, kind="manual_transition")
        goms.checkpoint(out.get("goms_branch_id"), out["state"], args.reason)
        print_jobs([out])
    elif args.command == "doctor":
        checks = {
            "db": str(store.path),
            "gh": subprocess.run(["sh", "-lc", "command -v gh"], capture_output=True, text=True).stdout.strip() or None,
            "git": subprocess.run(["sh", "-lc", "command -v git"], capture_output=True, text=True).stdout.strip() or None,
            "goms": bool(goms.store),
            "local_dispatch": LOCAL_DISPATCH.exists(),
        }
        print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
