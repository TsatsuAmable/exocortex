#!/usr/bin/env python3
"""Submit a declarative scheduled task to the durable Aineko intent queue."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def _load_service(exocortex_home: Path):
    sys.path.insert(0, str(exocortex_home / "goms-v2"))
    from control_intents import ControlIntentService
    return ControlIntentService


def submit(spec_path: Path, *, exocortex_home: Path, goms_home: Path) -> dict:
    spec = json.loads(spec_path.read_text())
    required = {"id", "title", "summary", "instructions"}
    missing = sorted(required - set(spec))
    if missing:
        raise ValueError("missing scheduled-intent fields: " + ",".join(missing))

    service_type = _load_service(exocortex_home)
    service = service_type(goms_home)
    day_key = datetime.now().astimezone().date().isoformat()
    job_id = str(spec["id"])
    return service.submit_intent(
        title=str(spec["title"]),
        summary=str(spec["summary"]),
        kind="aineko_task",
        source="system",
        source_ref=f"schedule:{job_id}",
        project=spec.get("project"),
        priority=str(spec.get("priority", "P2")),
        risk_tier=str(spec.get("risk_tier", "normal")),
        execution_policy="AUTO_AFTER_APPROVAL",
        recommended_action={
            "type": "aineko_task",
            "target_id": job_id,
            "instructions": str(spec["instructions"]),
        },
        verification_policy=spec.get("verification_policy") or {
            "require_real_outcome_check": True,
        },
        provenance={
            "scheduled_job_id": job_id,
            "schedule_instance": day_key,
            "bounded_worker": True,
        },
        decision_required=True,
        idempotency_key=f"schedule:{job_id}:{day_key}",
        actor="system:schedule",
        human_attested=True,
        resolved_by="human:T",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec")
    parser.add_argument("--exocortex-home", default=os.environ.get(
        "EXOCORTEX_CURRENT", "~/.local/share/exocortex/current"))
    parser.add_argument("--goms-home", default=os.environ.get(
        "GOMS_HOME", "~/Library/Application Support/Aineko/GOMS"))
    parser.add_argument("--print-result", action="store_true")
    args = parser.parse_args()
    result = submit(
        Path(args.spec).expanduser(),
        exocortex_home=Path(args.exocortex_home).expanduser(),
        goms_home=Path(args.goms_home).expanduser(),
    )
    if args.print_result:
        print(json.dumps({
            "intent_id": result["intent_id"],
            "replayed": result.get("replayed", False),
            "status": result["intent"]["status"],
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
