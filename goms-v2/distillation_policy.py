#!/usr/bin/env python3

ALLOWED_KINDS = (
    "objective", "decision", "task", "scarcity", "capability", "constraint",
    "preference", "outcome", "adjacent_possible", "proposal", "principle", "question",
)

_KIND_ALIASES = {
    "requirement": "constraint",
}


def canonicalize_kind(kind, fallback=None):
    value = str(kind or "").strip().lower()
    value = _KIND_ALIASES.get(value, value)
    if value in ALLOWED_KINDS:
        return value
    fallback_value = str(fallback or "").strip().lower()
    fallback_value = _KIND_ALIASES.get(fallback_value, fallback_value)
    return fallback_value if fallback_value in ALLOWED_KINDS else None


def build_extraction_prompt():
    taxonomy = ", ".join(ALLOWED_KINDS)
    return f'''Extract durable semantic state from these USER messages.
Ignore acknowledgements and transient chatter.
Return strict JSON: {{"items":[...]}}.
Each item must contain kind, subject, predicate, object, literal, confidence, evidence_ids.
kind must be exactly one of: {taxonomy}.

Definitions:
- objective: enduring desired state/outcome.
- decision: committed choice or accepted change.
- task: concrete action that should be executed.
- scarcity: limiting resource or bottleneck.
- capability: reusable ability, tool, resource, or mechanism.
- constraint: requirement or boundary on acceptable action.
- preference: stable user preference, priority, or style.
- outcome: observed result or completed state change.
- adjacent_possible: newly reachable future state enabled by capability/state change.
- proposal: candidate change not yet accepted.
- principle: durable architectural/governance rule or framing.
- question: unresolved question whose answer materially affects work.

Extract every distinct durable item supported by each message, not merely one item per message.
A short unresolved question is durable when its answer materially affects ongoing architecture,
dependencies, execution, governance, or project direction.
Do not turn speculative questions into decisions.
Do not extract one-off content-generation requests unless they belong to an ongoing project.
Only include claims directly supported by cited evidence IDs.
Do not invent completion. confidence <= 0.98.
Prefer durable, reusable state over conversational detail.'''

def build_validation_prompt():
    taxonomy = ", ".join(ALLOWED_KINDS)
    return f'''Independently validate semantic candidates against their cited USER evidence.
Return strict JSON {{"items":[...]}} with one item per candidate:
candidate_id, verdict, kind, durability, confidence, rationale.
verdict must be accept, reject, or reclassify.
kind must be exactly one of: {taxonomy}.
durability must be ephemeral, session, project, or enduring.
Reject acknowledgements, unsupported claims, transient chatter, and one-off creative/writing/image/persona requests.
A proposal/question is not a decision unless evidence explicitly commits to it.
If a candidate contains interrogative and normative content, preserve the durable proposition without inventing facts;
use constraint for explicit requirements or boundaries.
Do not invent facts.'''


def score_gold_case(gold, survives, validated_kind, text, fallback_kind=None):
    positive = bool(gold.get("should_extract", True))
    if not positive:
        return {
            "kind_ok": not survives,
            "keyword_fraction": 1.0 if not survives else 0.0,
        }

    kind = canonicalize_kind(validated_kind, fallback_kind)
    acceptable = gold.get("acceptable_kinds") or [gold.get("kind")]
    keywords = [str(x).lower() for x in gold.get("object_keywords", [])]
    lowered = str(text or "").lower()
    fraction = 1.0 if not keywords else sum(k in lowered for k in keywords) / len(keywords)
    return {
        "kind_ok": bool(survives and kind in acceptable),
        "keyword_fraction": fraction if survives else 0.0,
    }


def run_is_stale(status, started_at, *, now=None, max_age_seconds=900):
    if str(status).upper() != "RUNNING" or not started_at:
        return False
    from datetime import datetime, timezone
    current = now or datetime.now(timezone.utc)
    try:
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (current - started).total_seconds() > max_age_seconds


def reap_stale_runs(connection, *, now=None, max_age_seconds=900):
    import json
    from datetime import datetime, timezone
    current = now or datetime.now(timezone.utc)
    rows = connection.execute(
        "select id,status,started_at,metadata from distillation_runs where status='RUNNING'"
    ).fetchall()
    changed = []
    for row in rows:
        run_id, status, started_at, metadata = row
        if not run_is_stale(status, started_at, now=current, max_age_seconds=max_age_seconds):
            continue
        try:
            meta = json.loads(metadata or "{}")
        except json.JSONDecodeError:
            meta = {}
        meta["abandoned_reason"] = "stale_running_run"
        meta["abandoned_at"] = current.isoformat()
        connection.execute(
            "update distillation_runs set status='ABANDONED',completed_at=?,metadata=? where id=? and status='RUNNING'",
            (current.isoformat(), json.dumps(meta, sort_keys=True), run_id),
        )
        changed.append(run_id)
    return changed
