#!/usr/bin/env python3
"""Provider lifecycle manager for the evidence-driven model router.

Issue #1 obligation: "provider lifecycle / requalification handled".

Fleet candidates carry `qualification` (qualified / provisional /
unqualified) and an optional `retire_at` date. The router honours these at
route time (router.py::lifecycle_state) but nothing maintained the fleet:
no digest tracking, no drift detection, no requalification workflow. This
tool adds the maintenance half, offline and auditable:

  digest     Record every provider-side model digest for local ollama
             candidates. A digest change (provider pulled/retagged/removed
             a model) is provider-side drift that may invalidate prior
             benchmark evidence; qualified candidates are auto-demoted to
             provisional so routing prefers better-evidenced routes.
  verify     Deterministic health checks no benchmark run is needed for:
             local models exist, digests unchanged, cloud candidates have
             adapter/provider configured, lifecycle fields well-formed.
  requalify  Explicit qualification transitions and retire dates. Writes
             fleet.json atomically and appends a JSONL audit trail so
             routing decisions stay explainable after the fact.

Offline by design: local ollama is queried when reachable but fleet hygiene
never requires network access; cloud reachability is checked as
configuration presence only, never as a network claim.

Usage:
  python3 provider_lifecycle.py digest   [--fleet PATH] [--audit PATH]
  python3 provider_lifecycle.py verify   [--fleet PATH] [--audit PATH] [--json]
  python3 provider_lifecycle.py requalify --id ID --to provisional|unqualified|qualified
         [--reason TEXT] [--retire-at ISO_DATE|none] [--fleet PATH] [--audit PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FLEET_DEFAULT = ROOT / "fleet.json"
DIGESTS_DEFAULT = ROOT / "model-digests.json"
AUDIT_DEFAULT = ROOT / "lifecycle-audit.jsonl"

OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
QUALIFICATIONS = ("qualified", "provisional", "unqualified")
#: Upgrades to `qualified` must cite evidence; downgrades are always allowed.
EVIDENCE_REQUIRED = "qualified"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, payload: dict) -> None:
    """Write JSON atomically: temp file in the same dir, then rename."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-fleet-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


def _append_audit(audit_path: Path, entry: dict) -> None:
    entry = {"at": _now(), **entry}
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def load_fleet(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "candidates" not in data:
        raise ValueError(f"fleet file {path} has no 'candidates'")
    return data


def load_digests(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_ollama_tags(timeout: float = 5.0):
    """Return {model_name: digest} from local ollama, or None if unreachable."""
    try:
        req = urllib.request.Request(OLLAMA_TAGS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except (OSError, ValueError):
        return None
    return {m.get("name"): m.get("digest") for m in data.get("models", [])}


def _local_ollama_candidates(fleet: dict):
    for cand in fleet["candidates"]:
        if cand.get("provider") == "local-ollama" and cand.get("enabled", True):
            yield cand


def cmd_digest(args) -> int:
    fleet = load_fleet(Path(args.fleet))
    digests_path = Path(args.digests)
    stored = load_digests(digests_path)
    audit_path = Path(args.audit)

    tags = fetch_ollama_tags()
    if tags is None:
        print(json.dumps({"ok": False, "error": "local ollama unreachable",
                          "endpoint": OLLAMA_TAGS}))
        return 2

    recorded = {}
    changes = []
    demotions = []
    for cand in _local_ollama_candidates(fleet):
        cid = cand["id"]
        model = cand.get("model")
        digest = tags.get(model)
        recorded[cid] = {"model": model, "digest": digest,
                         "recorded_at": _now()}
        old = stored.get(cid)
        old_digest = old.get("digest") if isinstance(old, dict) else None
        if old is None:
            _append_audit(audit_path, {
                "actor": args.actor, "action": "digest_recorded",
                "id": cid, "model": model, "digest": digest})
        elif old_digest != digest:
            changes.append(cid)
            _append_audit(audit_path, {
                "actor": args.actor, "action": "digest_changed",
                "id": cid, "model": model,
                "old_digest": old_digest, "new_digest": digest})
            # Drift invalidates prior evidence: demote qualified candidates
            # so routing prefers better-evidenced routes until requalification.
            if cand.get("qualification") == "qualified":
                cand["qualification"] = "provisional"
                reason = (f"provider digest changed "
                          f"{str(old_digest)[:12]}..->{str(digest)[:12]}..")
                cand["requalify_reason"] = reason
                demotions.append(cid)
                _append_audit(audit_path, {
                    "actor": args.actor, "action": "requalified",
                    "id": cid, "from": "qualified", "to": "provisional",
                    "reason": reason})

    if recorded != stored:
        _atomic_write(digests_path, recorded)
    if demotions:
        _atomic_write(Path(args.fleet), fleet)
    print(json.dumps({"ok": True, "tracked": len(recorded),
                      "changed": changes, "demoted": demotions,
                      "fleet_path": str(Path(args.fleet)),
                      "digests_path": str(digests_path)}))
    return 0


def cmd_verify(args) -> int:
    fleet = load_fleet(Path(args.fleet))
    stored = load_digests(Path(args.digests))
    tags = fetch_ollama_tags()
    findings = []
    for cand in fleet["candidates"]:
        cid = cand["id"]
        qual = str(cand.get("qualification") or "qualified").lower()
        if qual not in QUALIFICATIONS:
            findings.append({"id": cid, "check": "qualification",
                             "status": "invalid",
                             "detail": f"unknown qualification {qual!r}"})
        retire_at = cand.get("retire_at")
        if retire_at:
            try:
                datetime.fromisoformat(str(retire_at).replace("Z", "+00:00"))
            except ValueError:
                findings.append({"id": cid, "check": "retire_at",
                                 "status": "invalid",
                                 "detail": f"unparseable retire_at {retire_at!r}"})
        if not cand.get("adapter") or not cand.get("provider"):
            findings.append({"id": cid, "check": "config",
                             "status": "missing",
                             "detail": "cloud candidate lacks adapter/provider"})
        if cand.get("provider") == "local-ollama" and cand.get("enabled", True):
            model = cand.get("model")
            if tags is None:
                findings.append({"id": cid, "check": "ollama",
                                 "status": "unreachable",
                                 "detail": OLLAMA_TAGS})
            elif model not in tags:
                findings.append({"id": cid, "check": "model_present",
                                 "status": "missing",
                                 "detail": f"model {model!r} not in local ollama"})
            else:
                rec = stored.get(cid)
                if isinstance(rec, dict) and rec.get("digest") and \
                        rec["digest"] != tags[model]:
                    findings.append({"id": cid, "check": "digest",
                                     "status": "changed",
                                     "detail": "run `digest` to reconcile"})
    verdict = "OK" if not findings else "ATTENTION"
    print(json.dumps({"verdict": verdict, "candidates": len(fleet["candidates"]),
                      "findings": findings}))
    return 0 if verdict == "OK" else 1


def cmd_requalify(args) -> int:
    fleet_path = Path(args.fleet)
    audit_path = Path(args.audit)
    target = args.to
    if target not in QUALIFICATIONS:
        print(json.dumps({"ok": False,
                          "error": f"invalid target {target!r}"}))
        return 2
    fleet = load_fleet(fleet_path)
    by_id = {c["id"]: c for c in fleet["candidates"]}
    cand = by_id.get(args.id)
    if cand is None:
        print(json.dumps({"ok": False, "error": f"unknown candidate {args.id!r}"}))
        return 2
    old = str(cand.get("qualification") or "qualified").lower()
    if target == EVIDENCE_REQUIRED and old != EVIDENCE_REQUIRED and not args.reason:
        print(json.dumps({"ok": False,
                          "error": "upgrading to qualified requires --reason "
                                   "citing benchmark or runtime evidence"}))
        return 2
    cand["qualification"] = target
    changed = {"qualification": {"from": old, "to": target}}
    if args.retire_at:
        if args.retire_at.lower() == "none":
            cand.pop("retire_at", None)
            changed["retire_at"] = {"from": cand.get("retire_at"), "to": None}
        else:
            datetime.fromisoformat(args.retire_at.replace("Z", "+00:00"))
            cand["retire_at"] = args.retire_at
            changed["retire_at"] = {"to": args.retire_at}
    if args.reason:
        cand["requalify_reason"] = args.reason
    _atomic_write(fleet_path, fleet)
    _append_audit(audit_path, {
        "actor": args.actor, "action": "requalified", "id": args.id,
        "from": old, "to": target, "reason": args.reason,
        "changed": changed})
    print(json.dumps({"ok": True, "id": args.id, "from": old, "to": target,
                      "fleet": str(fleet_path)}))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Provider lifecycle manager")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--fleet", default=str(FLEET_DEFAULT))
        p.add_argument("--digests", default=str(DIGESTS_DEFAULT))
        p.add_argument("--audit", default=str(AUDIT_DEFAULT))
        p.add_argument("--actor", default="gsv-aineko")

    p = sub.add_parser("digest", help="record/diff local model digests")
    common(p)
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("verify", help="deterministic fleet health checks")
    common(p)
    p.add_argument("--timeout", type=float, default=5.0)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("requalify", help="explicit qualification transition")
    common(p)
    p.add_argument("--id", required=True)
    p.add_argument("--to", required=True, choices=list(QUALIFICATIONS))
    p.add_argument("--reason", default=None)
    p.add_argument("--retire-at", default=None)
    p.set_defaults(func=cmd_requalify)

    args = ap.parse_args(argv)
    if args.cmd == "verify":
        args.timeout = getattr(args, "timeout", 5.0)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())