#!/usr/bin/env python3
"""Offline authority-audit reconciliation — verify local audit integrity with no GOMS dependency.

Reads a Hermes authority audit journal (audit.jsonl) plus its state file and
verifies, entirely offline:

  1. every line is valid JSON with the required audit fields;
  2. timestamps are present, parseable and non-decreasing (append-only order);
  3. every recorded mode is a legal authority mode;
  4. mode transitions are legal: escalations never skip levels, and
     de-escalation events (exit/expire/deescalate) may drop any distance;
  5. the live state file agrees with the last authoritative journal entry
     (same mode, or an expiry/exit event explains the difference).

The reconciler reads only. It never mutates state and never contacts GOMS —
that independence is the point: after a GOMS outage or on a reconstructed
host, the local authority substrate must still be verifiable.

Usage:
  python3 reconcile_authority_audit.py --root ~/.hermes/authority [--json]

Exit code 0 = reconciled cleanly; 1 = findings require attention.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

MODES = ("OBSERVE", "OPERATE", "ADMIN", "RECOVERY", "EMERGENCY")
LEVEL = {mode: i for i, mode in enumerate(MODES)}

REQUIRED_FIELDS = ("action", "at", "principal", "mode")
DEESCALATION_ACTIONS = {"exit_mode", "lease_expired", "mode_change"}

#: Events whose "mode" field describes the PRE-transition mode rather than the
#: effective one. Their target mode lives in detail.to (mode_change) or is
#: OBSERVE by definition (lease_expired).
PRE_TRANSITION_ACTIONS = {"lease_expired"}


def _parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _entry_target_mode(entry, fallback):
    """Best-effort effective mode for an audit entry."""
    if entry.get("action") in PRE_TRANSITION_ACTIONS:
        return "OBSERVE"
    detail = entry.get("detail") or {}
    if isinstance(detail, dict) and isinstance(detail.get("to"), str):
        return detail["to"]
    mode = entry.get("mode")
    return mode if mode in LEVEL else fallback


def reconcile(root: Path) -> dict:
    """Reconcile the audit journal under *root* and return a findings dict."""
    audit_path = root / "audit.jsonl"
    state_path = root / "state.json"
    findings = {"root": str(root), "journal": str(audit_path),
                "entries": 0, "corrupt_lines": [], "order_violations": [],
                "illegal_transitions": [], "unknown_modes": [],
                "state_consistent": None, "issues": []}

    def issue(msg):
        findings["issues"].append(msg)

    if not audit_path.exists():
        issue("audit journal missing")
        findings["state_consistent"] = None
        return findings

    entries = []
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            findings["corrupt_lines"].append({"line": lineno, "error": str(exc)})
            issue(f"line {lineno}: corrupt JSON ({exc})")
            continue
        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            issue(f"line {lineno}: missing fields {missing}")
            findings["corrupt_lines"].append({"line": lineno, "missing": missing})
            continue
        entries.append((lineno, entry))

    findings["entries"] = len(entries)

    last_ts = None
    last_mode = "OBSERVE"
    for lineno, entry in entries:
        ts_raw = entry.get("at")
        ts = _parse_ts(ts_raw)
        if ts is None:
            issue(f"line {lineno}: unparseable timestamp {ts_raw!r}")
            findings["order_violations"].append({"line": lineno, "at": ts_raw})
            continue
        if last_ts is not None and ts < last_ts:
            issue(f"line {lineno}: timestamp goes backwards ({ts} < {last_ts})")
            findings["order_violations"].append(
                {"line": lineno, "at": ts_raw, "prev": last_ts.isoformat()})
        last_ts = ts

        mode = entry.get("mode")
        if mode not in LEVEL:
            issue(f"line {lineno}: unknown mode {mode!r}")
            findings["unknown_modes"].append({"line": lineno, "mode": mode})
            continue

        target = _entry_target_mode(entry, mode)
        if target not in LEVEL:
            issue(f"line {lineno}: unknown target mode {target!r}")
            findings["unknown_modes"].append({"line": lineno, "target": target})
            continue

        action = entry.get("action")
        if action in DEESCALATION_ACTIONS and LEVEL[target] < LEVEL[last_mode]:
            # De-escalation: any drop is legal.
            last_mode = target
            continue
        if LEVEL[target] >= LEVEL[last_mode]:
            if LEVEL[target] - LEVEL[last_mode] > 1:
                issue(f"line {lineno}: skipped levels "
                      f"{last_mode} -> {target}")
                findings["illegal_transitions"].append(
                    {"line": lineno, "from": last_mode, "to": target})
            last_mode = target
        else:
            issue(f"line {lineno}: silent de-escalation {last_mode} -> {target} "
                  f"without a recognized exit/expire event")
            findings["illegal_transitions"].append(
                {"line": lineno, "from": last_mode, "to": target,
                 "reason": "silent_drop"})
            last_mode = target

    # State-file consistency: the live state must be explained by the journal.
    if not state_path.exists():
        if entries:
            issue("state file missing while journal has entries")
            findings["state_consistent"] = False
        else:
            findings["state_consistent"] = True
    else:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issue(f"state file corrupt: {exc}")
            findings["state_consistent"] = False
        else:
            state_mode = state.get("mode")
            if state_mode not in LEVEL:
                issue(f"state file has unknown mode {state_mode!r}")
                findings["state_consistent"] = False
            elif entries and state_mode != last_mode:
                issue(f"state file mode {state_mode!r} disagrees with "
                      f"journal-implied mode {last_mode!r}")
                findings["state_consistent"] = False
            else:
                findings["state_consistent"] = True

    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline Hermes authority audit reconciliation.")
    parser.add_argument("--root", required=True,
                        help="authority root containing audit.jsonl and state.json")
    parser.add_argument("--json", action="store_true",
                        help="emit the findings dict as JSON")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser()
    findings = reconcile(root)

    clean = (not findings["corrupt_lines"]
             and not findings["order_violations"]
             and not findings["illegal_transitions"]
             and not findings["unknown_modes"]
             and findings["state_consistent"] is not False)

    if args.json:
        print(json.dumps(findings, indent=2, default=str))
    else:
        print(f"audit reconciliation: {root}")
        print(f"  entries={findings['entries']} "
              f"corrupt={len(findings['corrupt_lines'])} "
              f"order_violations={len(findings['order_violations'])} "
              f"illegal_transitions={len(findings['illegal_transitions'])} "
              f"unknown_modes={len(findings['unknown_modes'])} "
              f"state_consistent={findings['state_consistent']}")
        for msg in findings["issues"]:
            print(f"  ISSUE: {msg}")
        print(f"  verdict: {'OK' if clean else 'FINDINGS REQUIRE ATTENTION'}")

    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())