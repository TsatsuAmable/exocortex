#!/usr/bin/env python3
"""Data-driven rescue executor for the documented recovery order.

Turns docs/operations/DISASTER_RECOVERY.md recovery-order prose into an
executable, auditable, resumable procedure.

Concepts:
  plan     JSON file: {"failure_class": ..., "description": ...,
           "steps": [{"id", "description", "command" (argv list), "check"
           (argv list, optional), "optional" (bool)}]}
  run      Executes steps in order under RECOVERY authority. Completed steps
           recorded in the journal are skipped on re-run (resume semantics).
           A failing step aborts unless "optional": true. --dry-run executes
           nothing and mutates nothing.
  journal  Append-only JSONL next to the authority state
           (~/.hermes/authority/rescue-journal/<failure_class>.jsonl by
           default). Every step attempt is recorded with outcome, output
           digest, and timestamps.

Authority: requires RECOVERY (or EMERGENCY) per local hermes_authority unless
--dry-run, which is safe to run under OBSERVE to preview a plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "goms-v2"))
from hermes_authority import HermesAuthority  # noqa: E402

DEFAULT_PLAN_ROOT = Path.home() / ".hermes" / "rescue-plans"
DEFAULT_JOURNAL_ROOT = Path.home() / ".hermes" / "authority" / "rescue-journal"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    required = {"failure_class", "steps"}
    missing = required - plan.keys()
    if missing:
        sys.exit(f"error: plan missing required keys: {sorted(missing)}")
    for i, step in enumerate(plan["steps"]):
        for key in ("id", "description", "command"):
            if key not in step:
                sys.exit(f"error: step {i} missing key: {key}")
        if not isinstance(step["command"], list):
            sys.exit(f"error: step {i} command must be an argv list")
    return plan


def journal_path(journal_root: Path, failure_class: str) -> Path:
    d = journal_root / failure_class
    d.mkdir(parents=True, exist_ok=True)
    return d / "journal.jsonl"


def completed_step_ids(path: Path) -> set:
    done = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") == "step_completed":
            done.add(rec.get("step_id"))
    return done


def run_argv(argv, timeout=120):
    # Remote Commander environments may lack HOME; plans legitimately use $HOME.
    # Inject it from Path.home() rather than trusting the ambient environment.
    env = dict(os.environ)
    env.setdefault("HOME", str(Path.home()))
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          env=env)
    return proc.returncode, proc.stdout, proc.stderr


def append_journal(path: Path, record: dict):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def cmd_validate(args):
    plan = load_plan(args.plan)
    print(json.dumps({"plan": str(args.plan),
                      "failure_class": plan["failure_class"],
                      "steps": len(plan["steps"]),
                      "valid": True}, indent=2))


def cmd_run(args):
    plan = load_plan(args.plan)
    failure_class = plan["failure_class"]

    if args.dry_run:
        print(json.dumps({"dry_run": True, "failure_class": failure_class,
                          "steps": [{"id": s["id"],
                                     "command": s["command"]}
                                    for s in plan["steps"]]}, indent=2))
        return

    authority = HermesAuthority(args.authority_root or
                                Path.home() / ".hermes" / "authority")
    state = authority.current()
    if not authority.allows("RECOVERY"):
        sys.exit(f"error: rescue run requires RECOVERY authority; current mode "
                 f"{state.mode} (enter with human_authorized=True)")

    jpath = journal_path(args.journal_root, failure_class)
    done = completed_step_ids(jpath)
    results = []
    for step in plan["steps"]:
        sid = step["id"]
        if sid in done and not args.rerun_completed:
            results.append({"id": sid, "outcome": "skipped_completed"})
            append_journal(jpath, {"event": "step_skipped", "step_id": sid,
                                   "at": utc_now()})
            continue
        append_journal(jpath, {"event": "step_started", "step_id": sid,
                               "at": utc_now(), "command": step["command"]})
        try:
            rc, out, err = run_argv(step["command"])
        except subprocess.TimeoutExpired:
            rc, out, err = 124, "", "timeout"
        except OSError as exc:
            rc, out, err = 127, "", str(exc)
        ok = rc == 0
        append_journal(jpath, {
            "event": "step_completed" if ok else "step_failed",
            "step_id": sid, "at": utc_now(), "returncode": rc,
            "stdout_sha256": hashlib.sha256(out.encode()).hexdigest(),
            "stderr_tail": err[-400:],
        })
        results.append({"id": sid, "outcome": "completed" if ok else "failed",
                        "returncode": rc})
        if not ok and not step.get("optional"):
            print(json.dumps({"failure_class": failure_class,
                              "aborted_at": sid, "results": results}, indent=2))
            sys.exit(1)

    print(json.dumps({"failure_class": failure_class,
                      "results": results}, indent=2))


def cmd_status(args):
    jpath = journal_path(args.journal_root, args.failure_class)
    done = sorted(completed_step_ids(jpath))
    print(json.dumps({"failure_class": args.failure_class,
                      "journal": str(jpath),
                      "completed_steps": done}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate")
    v.add_argument("--plan", required=True, type=Path)
    v.set_defaults(func=cmd_validate)

    r = sub.add_parser("run")
    r.add_argument("--plan", required=True, type=Path)
    r.add_argument("--journal-root", type=Path, default=DEFAULT_JOURNAL_ROOT)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--rerun-completed", action="store_true")
    r.add_argument("--authority-root", type=Path, default=None)
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("status")
    s.add_argument("--failure-class", required=True)
    s.add_argument("--journal-root", type=Path, default=DEFAULT_JOURNAL_ROOT)
    s.set_defaults(func=cmd_status)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()