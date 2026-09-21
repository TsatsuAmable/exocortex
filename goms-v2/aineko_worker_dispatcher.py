#!/usr/bin/env python3
"""Drain approved Aineko intents into fresh, bounded Hermes workers."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from control_intents import ControlIntentService
from exocortex_context import ExocortexContext

DEFAULT_CONTEXT_CHARS = 28000
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_TOOL_CALLS = 12
INTENT_FIELDS = (
    "id", "kind", "title", "summary", "priority", "risk_tier",
    "execution_policy", "source", "source_ref", "recommended_action",
    "verification_policy", "evidence_refs", "provenance",
)


def _clip(value: Any, max_string: int = 1200, max_items: int = 5) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_string else value[: max_string - 1] + "…"
    if isinstance(value, list):
        return [_clip(v, max_string, max_items) for v in value[:max_items]]
    if isinstance(value, dict):
        return {str(k): _clip(v, max_string, max_items)
                for k, v in list(value.items())[: max_items * 3]}
    return value


def _size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def build_context_packet(service: ControlIntentService, intent: dict,
                         max_chars: int = DEFAULT_CONTEXT_CHARS) -> dict:
    max_chars = max(8000, int(max_chars))
    essential = {k: intent.get(k) for k in INTENT_FIELDS if k in intent}
    packet = {
        "contract": {
            "role": "bounded Aineko worker",
            "authority": "execute only this already-approved intent",
            "history_policy": "do not load broad conversation/session history",
            "state_policy": "fetch extra state only when directly required",
        },
        "intent": essential,
    }
    base_chars = _size(packet)
    if base_chars > int(max_chars * 0.75):
        raise ValueError(f"context_budget_exceeded_by_intent:{base_chars}")

    provenance = intent.get("provenance") if isinstance(intent.get("provenance"), dict) else {}
    project = provenance.get("project")
    ctx = ExocortexContext(service.store)
    brief = ctx.brief(person_title="T", project=project, limit=4)
    if not brief.get("person"):
        brief = ctx.brief(person_title="User", project=project, limit=4)
    packet["brief"] = _clip(brief)

    for key in (None, "unresolved_intents", "active_branches",
                "preferences", "constraints", "goals"):
        if _size(packet) <= max_chars:
            packet["context_chars"] = _size(packet)
            return packet
        if key and isinstance(packet.get("brief"), dict):
            packet["brief"].pop(key, None)
    packet.pop("brief", None)
    packet["context_chars"] = _size(packet)
    return packet


def build_worker_prompt(packet: dict, max_tool_calls: int = DEFAULT_TOOL_CALLS) -> str:
    return (
        "You are a fresh bounded worker for GSV Aineko, not the long-lived governor.\n"
        "The dispatcher has ALREADY claimed this intent for you. Use TASK_PACKET.execution "
        "as your held execution lease. Do NOT call any intent claim/approve/dispatch tool and "
        "do not interpret the intent's EXECUTING status as a competing worker.\n"
        f"Hard budget: at most {int(max_tool_calls)} model/tool rounds (enforced by Hermes). "
        "Do not search broad history, resume another session, or delegate recursively. "
        "Use only task-relevant state.\n"
        "Execute the approved intent end-to-end where authorized. Preserve rollback paths. "
        "Never report SUCCESS from command exit alone: verify the real outcome by test, "
        "read-back, live check, or equivalent evidence.\n"
        "Return ONLY JSON with keys status (SUCCESS|FAILED|UNKNOWN), result (object), "
        "verification ({performed:boolean,evidence:string}), evidence_title, evidence_summary. "
        "If side effects may have happened but verification is incomplete, return UNKNOWN.\n\n"
        "TASK_PACKET=" + json.dumps(packet, ensure_ascii=False, sort_keys=True)
    )


def _parse_output(text: str) -> dict:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("worker_output_not_json")
        value = json.loads(raw[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("worker_output_not_object")
    return value


def run_worker(packet: dict, *, profile: str, timeout_seconds: int,
               max_tool_calls: int, hermes_agent_home: Path) -> tuple[dict, dict]:
    python = hermes_agent_home / "venv" / "bin" / "python"
    if not python.exists():
        raise FileNotFoundError(f"Hermes Python not found: {python}")
    fd, usage_name = tempfile.mkstemp(prefix="aineko-worker-", suffix=".usage.json")
    os.close(fd)
    try:
        proc = subprocess.run(
            [str(python), "-m", "hermes_cli.main", "--profile", profile,
             "--ignore-rules", "--max-turns", str(int(max_tool_calls)),
             "--usage-file", usage_name, "--oneshot",
             build_worker_prompt(packet, max_tool_calls)],
            cwd=str(hermes_agent_home), text=True, capture_output=True,
            timeout=max(30, int(timeout_seconds)), env=os.environ.copy(),
        )
        try:
            usage = json.loads(Path(usage_name).read_text())
        except (OSError, json.JSONDecodeError):
            usage = {}
        if proc.returncode != 0:
            return {
                "status": "UNKNOWN",
                "result": {"reason": "worker_process_nonzero",
                           "returncode": proc.returncode, "stderr": proc.stderr[-2000:]},
                "verification": {"performed": False, "evidence": ""},
                "evidence_title": "Aineko bounded worker outcome unknown",
                "evidence_summary": "Worker exited non-zero after execution began; reconcile side effects.",
            }, usage
        try:
            return _parse_output(proc.stdout), usage
        except (ValueError, json.JSONDecodeError) as exc:
            return {
                "status": "UNKNOWN",
                "result": {"reason": str(exc), "raw_output": proc.stdout[-4000:]},
                "verification": {"performed": False, "evidence": ""},
                "evidence_title": "Aineko bounded worker output unverified",
                "evidence_summary": "Worker final output was not parseable; reconcile before retrying.",
            }, usage
    finally:
        Path(usage_name).unlink(missing_ok=True)


def dispatch_once(root: Path, *, profile: str = "gsvaineko",
                  context_chars: int = DEFAULT_CONTEXT_CHARS,
                  timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
                  max_tool_calls: int = DEFAULT_TOOL_CALLS,
                  hermes_agent_home: Path | None = None) -> dict:
    service = ControlIntentService(root)
    candidates = [i for i in service.list_pending_for_worker(limit=20)
                  if str(i.get("execution_policy") or "").upper() != "HUMAN_ONLY"]
    if not candidates:
        return {"status": "idle"}

    intent = candidates[0]
    packet = build_context_packet(service, intent, max_chars=context_chars)
    worker_id = f"aineko-bounded:{socket.gethostname()}:{os.getpid()}"
    # Reserve the exact-sized execution envelope BEFORE the durable claim so a
    # packet-budget failure can never strand the intent in EXECUTING.
    packet["execution"] = {
        "attempt_id": "intent_attempt_000000000000",
        "worker_id": worker_id,
        "claim_status": "HELD_BY_DISPATCHER",
        "do_not_claim": True,
    }
    packet["context_chars"] = _size(packet)
    if packet["context_chars"] > context_chars:
        raise ValueError("context_budget_exceeded_by_execution_envelope")
    attempt_id = service.claim_for_aineko(intent["id"], worker_id=worker_id)
    packet["execution"]["attempt_id"] = attempt_id
    home = hermes_agent_home or Path(
        os.environ.get("HERMES_AGENT_HOME", "~/.hermes/hermes-agent")
    ).expanduser()

    try:
        result, usage = run_worker(
            packet, profile=profile, timeout_seconds=timeout_seconds,
            max_tool_calls=max_tool_calls, hermes_agent_home=home)
    except subprocess.TimeoutExpired:
        result, usage = ({
            "status": "UNKNOWN", "result": {"reason": "worker_timeout"},
            "verification": {"performed": False, "evidence": ""},
            "evidence_title": "Aineko bounded worker timed out",
            "evidence_summary": "Timeout occurred after execution began; reconcile side effects.",
        }, {})
    except Exception as exc:
        result, usage = ({
            "status": "UNKNOWN",
            "result": {"reason": f"worker_exception:{type(exc).__name__}:{exc}"},
            "verification": {"performed": False, "evidence": ""},
            "evidence_title": "Aineko bounded worker exception",
            "evidence_summary": "Worker failed after claim; execution outcome requires reconciliation.",
        }, {})

    requested = str(result.get("status") or "UNKNOWN").upper()
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    evidence_summary = str(result.get("evidence_summary") or "").strip()
    payload = result.get("result") if isinstance(result.get("result"), dict) else {"value": result.get("result")}
    if requested == "SUCCESS" and not (verification.get("performed") and evidence_summary):
        requested = "UNKNOWN"
        payload["success_downgraded"] = "missing_verification"
    status = requested if requested in {"SUCCESS", "FAILED", "UNKNOWN"} else "UNKNOWN"
    payload.update({
        "context_chars": packet.get("context_chars"),
        "usage": usage,
        "verification": verification,
    })
    final = service.record_aineko_result(
        intent["id"], attempt_id, worker_id=worker_id, status=status, result=payload,
        evidence_title=str(result.get("evidence_title") or f"Bounded worker: {intent['title']}"),
        evidence_summary=evidence_summary or str(verification.get("evidence") or ""),
    )
    return {"status": status, "intent_id": intent["id"], "attempt_id": attempt_id,
            "context_chars": packet.get("context_chars"), "usage": usage,
            "intent_status": final["status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get(
        "GOMS_HOME", "~/Library/Application Support/Aineko/GOMS"))
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE", "gsvaineko"))
    parser.add_argument("--context-chars", type=int, default=int(os.environ.get(
        "AINEKO_WORKER_CONTEXT_CHARS", DEFAULT_CONTEXT_CHARS)))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get(
        "AINEKO_WORKER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)))
    parser.add_argument("--max-tool-calls", type=int, default=int(os.environ.get(
        "AINEKO_WORKER_MAX_TOOL_CALLS", DEFAULT_TOOL_CALLS)))
    args = parser.parse_args()
    root = Path(args.root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "aineko-bounded-worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "busy"}))
            return 0
        outcome = dispatch_once(root, profile=args.profile,
                                context_chars=args.context_chars,
                                timeout_seconds=args.timeout_seconds,
                                max_tool_calls=args.max_tool_calls)
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
