#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from goms_store import GomsStore, make_id, now

ATTENTION_CLASSES = ("A0", "A1", "A2", "A3")
BEHAVIORS = {
    "A0": "execute_autonomously",
    "A1": "next_digest",
    "A2": "bundle_next_interaction",
    "A3": "interrupt_now",
}
MODES = {"shadow", "suppress_a0", "suppress_a0_a1"}
DEFAULT_EXPERIMENT = "attention-market-shadow-v1"

SEVERITY_EXPECTED_VALUE = {"info": 0.25, "warning": 0.55, "critical": 0.85}
SEVERITY_URGENCY = {"info": 0.15, "warning": 0.50, "critical": 0.90}
SEVERITY_DELAY_COST = {"info": 0.10, "warning": 0.35, "critical": 0.80}
PRIORITY_EXPECTED_VALUE = {"P0": 0.95, "P1": 0.70, "P2": 0.45}
PRIORITY_URGENCY = {"P0": 0.90, "P1": 0.55, "P2": 0.25}

PROTECTED_END_FLAGS = (
    "objective_change",
    "acceptable_risk_change",
    "personal_commitment",
    "irreversible",
    "values_required",
    "protected_end_question",
)


def _loads(value, fallback):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return fallback
    return fallback if parsed is None else parsed


def _clamp(value, low=0.0, high=1.0):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _positive_minutes(value, default=5.0):
    try:
        return max(0.5, float(value))
    except (TypeError, ValueError):
        return float(default)


def source_family(source: str | None, category: str | None = None,
                  title: str | None = None) -> str:
    text = " ".join(str(x or "") for x in (source, category, title)).lower()
    if "nemosyne" in text or "moneta" in text:
        return "nemosyne"
    if any(token in text for token in (
        "infrastructure", "topology", "cognition", "replication", "healthcontroller",
        "delivery-controller", "remote commander",
    )):
        return "infrastructure"
    if any(token in text for token in (
        "guardian", "research", "paper", "academic", "agalmic", "experiment",
    )):
        return "research"
    if "hermes" in text or "aineko" in text or "exocortex" in text:
        return "hermes"
    return "other"


@dataclass(frozen=True)
class AttentionBid:
    attention_id: str
    intent_id: str | None
    attention_class: str
    behavior: str
    bid: float
    expected_value: float
    urgency: float
    human_irreplaceability: float
    attention_cost_minutes: float
    delay_cost: float
    human_decision: str
    delay_cost_reason: str
    protected_end_question: bool
    machine_resolution_expected: bool
    source_family: str
    rationale: str
    surface_now: bool
    mode: str

    def asdict(self):
        return asdict(self)


def classify_bid(*, attention_id: str, intent_id: str | None = None,
                 expected_value: float, urgency: float,
                 human_irreplaceability: float, attention_cost_minutes: float,
                 delay_cost: float = 0.0, human_decision: str = "",
                 delay_cost_reason: str = "", protected_end_question: bool = False,
                 machine_resolution_expected: bool = False,
                 family: str = "other", mode: str = "shadow") -> AttentionBid:
    if mode not in MODES:
        raise ValueError("invalid_attention_market_mode")
    expected_value = _clamp(expected_value)
    urgency = _clamp(urgency)
    human_irreplaceability = _clamp(human_irreplaceability)
    delay_cost = _clamp(delay_cost)
    attention_cost_minutes = _positive_minutes(attention_cost_minutes)
    cost_units = max(0.25, attention_cost_minutes / 10.0)
    bid = (expected_value * urgency * human_irreplaceability) / cost_units

    decision_text = str(human_decision or "").strip()
    delay_text = str(delay_cost_reason or "").strip()
    genuinely_human = protected_end_question or human_irreplaceability >= 0.80

    # Importance alone cannot create A3. The machine must identify both the
    # concrete human decision and the cost of waiting.
    if (genuinely_human and decision_text and delay_text
            and delay_cost >= 0.65 and bid >= 0.20):
        attention_class = "A3"
        rationale = "human-irreducible decision with explicit material delay cost"
    elif protected_end_question or human_irreplaceability >= 0.80:
        attention_class = "A2"
        rationale = "privileged human judgment, but immediate interruption is not justified"
    elif machine_resolution_expected and human_irreplaceability < 0.50:
        attention_class = "A0"
        rationale = "authorized machinery is expected to resolve this without human judgment"
    elif human_irreplaceability >= 0.45:
        attention_class = "A2"
        rationale = "human decision is useful but delay has not justified interruption"
    elif bid >= 0.08 or expected_value >= 0.40 or urgency >= 0.35:
        attention_class = "A1"
        rationale = "worth preserving for digest, not worth immediate human attention"
    else:
        attention_class = "A0"
        rationale = "low marginal value at the human boundary"

    behavior = BEHAVIORS[attention_class]
    surface_now = True
    if mode == "suppress_a0" and attention_class == "A0":
        surface_now = False
    elif mode == "suppress_a0_a1" and attention_class in {"A0", "A1"}:
        surface_now = False

    return AttentionBid(
        attention_id=attention_id,
        intent_id=intent_id,
        attention_class=attention_class,
        behavior=behavior,
        bid=round(bid, 6),
        expected_value=expected_value,
        urgency=urgency,
        human_irreplaceability=human_irreplaceability,
        attention_cost_minutes=attention_cost_minutes,
        delay_cost=delay_cost,
        human_decision=decision_text,
        delay_cost_reason=delay_text,
        protected_end_question=bool(protected_end_question),
        machine_resolution_expected=bool(machine_resolution_expected),
        source_family=family,
        rationale=rationale,
        surface_now=surface_now,
        mode=mode,
    )


class AttentionMarket:
    def __init__(self, root: str | Path, clock=None):
        self.root = Path(root)
        self.store = GomsStore(self.root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _mode(self, mode: str | None = None) -> str:
        resolved = str(mode or os.environ.get("GOMS_ATTENTION_MARKET_MODE") or "shadow").lower()
        if resolved not in MODES:
            raise ValueError("invalid_attention_market_mode")
        return resolved

    def ensure_experiment(self, experiment_id: str = DEFAULT_EXPERIMENT,
                          mode: str = "shadow", target_count: int = 50) -> dict[str, Any]:
        mode = self._mode(mode)
        target_count = max(1, int(target_count))
        ts = now()
        with self.store.connect() as con:
            con.execute(
                """INSERT INTO attention_market_experiments(
                       id,mode,status,target_count,config,started_at,updated_at)
                   VALUES(?,?, 'ACTIVE', ?, '{}', ?, ?)
                   ON CONFLICT(id) DO UPDATE SET mode=excluded.mode,
                     target_count=excluded.target_count,updated_at=excluded.updated_at""",
                (experiment_id, mode, target_count, ts, ts),
            )
            row = con.execute(
                "SELECT * FROM attention_market_experiments WHERE id=?", (experiment_id,)
            ).fetchone()
        return dict(row)

    def _candidate(self, attention_id: str) -> dict[str, Any]:
        with self.store.connect() as con:
            row = con.execute(
                """SELECT a.*,m.intent_id,
                          i.status AS intent_status,i.priority,i.risk_tier,
                          i.execution_policy,i.provenance,i.recommended_action,
                          i.alternatives,i.decision_required
                   FROM attention_items a
                   LEFT JOIN attention_control_intents m ON m.attention_id=a.id
                   LEFT JOIN control_intents i ON i.id=m.intent_id
                   WHERE a.id=?""",
                (attention_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown attention item: {attention_id}")
        item = dict(row)
        item["suggested_actions"] = _loads(item.get("suggested_actions"), [])
        item["provenance"] = _loads(item.get("provenance"), {})
        item["recommended_action"] = _loads(item.get("recommended_action"), {})
        item["alternatives"] = _loads(item.get("alternatives"), [])
        return item

    def _features(self, item: dict[str, Any]) -> dict[str, Any]:
        severity = str(item.get("severity") or "info").lower()
        priority = str(item.get("priority") or "P2").upper()
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        override = provenance.get("attention_market")
        override = override if isinstance(override, dict) else {}

        expected_value = _clamp(override.get(
            "expected_value",
            max(SEVERITY_EXPECTED_VALUE.get(severity, 0.30),
                PRIORITY_EXPECTED_VALUE.get(priority, 0.45)),
        ))
        urgency = _clamp(override.get(
            "urgency",
            max(SEVERITY_URGENCY.get(severity, 0.20),
                PRIORITY_URGENCY.get(priority, 0.25)),
        ))
        delay_cost = _clamp(override.get(
            "delay_cost", SEVERITY_DELAY_COST.get(severity, 0.15)
        ))
        attention_cost = _positive_minutes(override.get(
            "attention_cost_minutes",
            10.0 if severity == "critical" else 7.0 if severity == "warning" else 5.0,
        ))

        protected = bool(override.get("protected_end_question"))
        for flag in PROTECTED_END_FLAGS:
            protected = protected or bool(provenance.get(flag))

        has_intent = bool(item.get("intent_id"))
        execution_policy = str(
            item.get("execution_policy") or ("HUMAN_ONLY" if has_intent else "UNKNOWN")
        ).upper()
        decision_required = bool(item.get("decision_required")) if has_intent else False
        if protected:
            irrepl = 1.0
        elif execution_policy == "HUMAN_ONLY":
            irrepl = 0.85
        elif decision_required:
            irrepl = 0.55
        elif not has_intent:
            irrepl = 0.25
        else:
            irrepl = 0.10
        irrepl = _clamp(override.get("human_irreplaceability", irrepl))

        recommended = item.get("recommended_action")
        machine_resolution_expected = bool(override.get(
            "machine_resolution_expected",
            execution_policy != "HUMAN_ONLY" and bool(recommended),
        ))
        if not decision_required and execution_policy != "HUMAN_ONLY":
            machine_resolution_expected = True

        human_decision = str(override.get("human_decision") or "").strip()
        if not human_decision and (protected or execution_policy == "HUMAN_ONLY"):
            human_decision = f"Decide whether and how to proceed with: {item.get('title') or item['id']}"

        # Deliberately no severity-derived prose here. A3 requires the producer or
        # a classifier to state the actual consequence of delay, not merely label it urgent.
        delay_reason = str(override.get("delay_cost_reason") or "").strip()

        return {
            "expected_value": expected_value,
            "urgency": urgency,
            "human_irreplaceability": irrepl,
            "attention_cost_minutes": attention_cost,
            "delay_cost": delay_cost,
            "human_decision": human_decision,
            "delay_cost_reason": delay_reason,
            "protected_end_question": protected,
            "machine_resolution_expected": machine_resolution_expected,
            "family": source_family(item.get("source"), item.get("category"), item.get("title")),
        }

    def classify_attention(self, attention_id: str, *,
                           experiment_id: str = DEFAULT_EXPERIMENT,
                           mode: str | None = None,
                           persist: bool = True) -> dict[str, Any]:
        resolved_mode = self._mode(mode)
        self.ensure_experiment(experiment_id, resolved_mode)
        item = self._candidate(attention_id)
        bid = classify_bid(
            attention_id=attention_id,
            intent_id=item.get("intent_id"),
            mode=resolved_mode,
            **self._features(item),
        )
        result = bid.asdict()
        result["experiment_id"] = experiment_id
        if persist:
            ts = now()
            classification_id = "attnbid_" + make_id("x").split("_", 1)[1]
            with self.store.connect() as con:
                existing = con.execute(
                    """SELECT id FROM attention_market_classifications
                       WHERE experiment_id=? AND attention_id=?""",
                    (experiment_id, attention_id),
                ).fetchone()
                if existing:
                    classification_id = existing["id"]
                con.execute(
                    """INSERT INTO attention_market_classifications(
                         id,experiment_id,attention_id,intent_id,attention_class,behavior,bid,
                         expected_value,urgency,human_irreplaceability,attention_cost_minutes,
                         delay_cost,human_decision,delay_cost_reason,protected_end_question,
                         machine_resolution_expected,source_family,rationale,mode,surface_now,
                         classified_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(experiment_id,attention_id) DO UPDATE SET
                         intent_id=excluded.intent_id,attention_class=excluded.attention_class,
                         behavior=excluded.behavior,bid=excluded.bid,
                         expected_value=excluded.expected_value,urgency=excluded.urgency,
                         human_irreplaceability=excluded.human_irreplaceability,
                         attention_cost_minutes=excluded.attention_cost_minutes,
                         delay_cost=excluded.delay_cost,human_decision=excluded.human_decision,
                         delay_cost_reason=excluded.delay_cost_reason,
                         protected_end_question=excluded.protected_end_question,
                         machine_resolution_expected=excluded.machine_resolution_expected,
                         source_family=excluded.source_family,rationale=excluded.rationale,
                         mode=excluded.mode,surface_now=excluded.surface_now,
                         classified_at=excluded.classified_at""",
                    (
                        classification_id, experiment_id, attention_id, item.get("intent_id"),
                        bid.attention_class, bid.behavior, bid.bid, bid.expected_value,
                        bid.urgency, bid.human_irreplaceability, bid.attention_cost_minutes,
                        bid.delay_cost, bid.human_decision, bid.delay_cost_reason,
                        int(bid.protected_end_question), int(bid.machine_resolution_expected),
                        bid.source_family, bid.rationale, bid.mode, int(bid.surface_now), ts,
                    ),
                )
                count = con.execute(
                    "SELECT count(*) n FROM attention_market_classifications WHERE experiment_id=?",
                    (experiment_id,),
                ).fetchone()["n"]
                target = con.execute(
                    "SELECT target_count FROM attention_market_experiments WHERE id=?",
                    (experiment_id,),
                ).fetchone()["target_count"]
                if count >= target:
                    con.execute(
                        """UPDATE attention_market_experiments
                           SET status='READY_FOR_REVIEW',updated_at=? WHERE id=?""",
                        (ts, experiment_id),
                    )
            result["classification_id"] = classification_id
        return result

    def classify_intent(self, intent_id: str, **kwargs) -> dict[str, Any] | None:
        with self.store.connect() as con:
            row = con.execute(
                "SELECT attention_id FROM attention_control_intents WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
        if not row:
            return None
        return self.classify_attention(row["attention_id"], **kwargs)

    def _recent_candidates(self, pool_limit: int = 500) -> list[dict[str, Any]]:
        with self.store.connect() as con:
            rows = con.execute(
                """SELECT id,source,category,title,updated_at
                   FROM attention_items
                   ORDER BY updated_at DESC,id DESC LIMIT ?""",
                (max(50, int(pool_limit)),),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["source_family"] = source_family(
                item.get("source"), item.get("category"), item.get("title")
            )
            out.append(item)
        return out

    def shadow_sample(self, *, limit: int = 50,
                      experiment_id: str = DEFAULT_EXPERIMENT) -> dict[str, Any]:
        limit = max(1, int(limit))
        self.ensure_experiment(experiment_id, "shadow", limit)
        pool = self._recent_candidates(max(500, limit * 10))
        families = ("hermes", "nemosyne", "research", "infrastructure")
        quota = max(1, limit // len(families))
        selected = []
        used = set()
        for family in families:
            for item in pool:
                if item["source_family"] != family or item["id"] in used:
                    continue
                selected.append(item)
                used.add(item["id"])
                if sum(1 for x in selected if x["source_family"] == family) >= quota:
                    break
        for item in pool:
            if len(selected) >= limit:
                break
            if item["id"] not in used:
                selected.append(item)
                used.add(item["id"])
        results = [
            self.classify_attention(
                item["id"], experiment_id=experiment_id, mode="shadow", persist=True
            )
            for item in selected[:limit]
        ]
        return {
            "experiment_id": experiment_id,
            "requested": limit,
            "classified": len(results),
            "coverage": {
                family: sum(1 for x in results if x["source_family"] == family)
                for family in (*families, "other")
            },
            "classes": {
                klass: sum(1 for x in results if x["attention_class"] == klass)
                for klass in ATTENTION_CLASSES
            },
        }

    def record_outcome(self, classification_id: str, *,
                       useful: bool | None = None,
                       materially_changed_outcome: bool | None = None,
                       minutes_to_decision: float | None = None,
                       resolved_by_machine_later: bool | None = None,
                       bundled: bool | None = None,
                       note: str = "", actor: str = "human") -> dict[str, Any]:
        ts = now()
        with self.store.connect() as con:
            exists = con.execute(
                "SELECT id FROM attention_market_classifications WHERE id=?",
                (classification_id,),
            ).fetchone()
            if not exists:
                raise KeyError(f"Unknown attention classification: {classification_id}")
            con.execute(
                """INSERT INTO attention_market_outcomes(
                     classification_id,useful,materially_changed_outcome,minutes_to_decision,
                     resolved_by_machine_later,bundled,note,actor,recorded_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(classification_id) DO UPDATE SET
                     useful=excluded.useful,
                     materially_changed_outcome=excluded.materially_changed_outcome,
                     minutes_to_decision=excluded.minutes_to_decision,
                     resolved_by_machine_later=excluded.resolved_by_machine_later,
                     bundled=excluded.bundled,note=excluded.note,actor=excluded.actor,
                     recorded_at=excluded.recorded_at""",
                (
                    classification_id,
                    None if useful is None else int(bool(useful)),
                    None if materially_changed_outcome is None else int(bool(materially_changed_outcome)),
                    None if minutes_to_decision is None else max(0.0, float(minutes_to_decision)),
                    None if resolved_by_machine_later is None else int(bool(resolved_by_machine_later)),
                    None if bundled is None else int(bool(bundled)),
                    str(note or ""), str(actor or "human"), ts,
                ),
            )
            row = con.execute(
                "SELECT * FROM attention_market_outcomes WHERE classification_id=?",
                (classification_id,),
            ).fetchone()
        return dict(row)

    def metrics(self, experiment_id: str = DEFAULT_EXPERIMENT) -> dict[str, Any]:
        with self.store.connect() as con:
            exp = con.execute(
                "SELECT * FROM attention_market_experiments WHERE id=?", (experiment_id,)
            ).fetchone()
            if not exp:
                return {"experiment_id": experiment_id, "classified": 0, "reviewed": 0}
            classes = {
                row["attention_class"]: row["n"]
                for row in con.execute(
                    """SELECT attention_class,count(*) n
                       FROM attention_market_classifications
                       WHERE experiment_id=? GROUP BY attention_class""",
                    (experiment_id,),
                ).fetchall()
            }
            coverage = {
                row["source_family"]: row["n"]
                for row in con.execute(
                    """SELECT source_family,count(*) n
                       FROM attention_market_classifications
                       WHERE experiment_id=? GROUP BY source_family""",
                    (experiment_id,),
                ).fetchall()
            }
            agg = con.execute(
                """SELECT count(*) reviewed,
                          sum(CASE WHEN o.useful=1 OR o.materially_changed_outcome=1 THEN 1 ELSE 0 END) actionable,
                          avg(o.minutes_to_decision) avg_minutes,
                          sum(CASE WHEN o.resolved_by_machine_later=1 THEN 1 ELSE 0 END) machine_later,
                          avg(CASE WHEN o.bundled IS NULL THEN NULL ELSE o.bundled END) bundling_ratio,
                          sum(CASE WHEN o.materially_changed_outcome=1 THEN 1 ELSE 0 END) material_changes
                   FROM attention_market_classifications c
                   JOIN attention_market_outcomes o ON o.classification_id=c.id
                   WHERE c.experiment_id=?""",
                (experiment_id,),
            ).fetchone()
            total = con.execute(
                "SELECT count(*) n FROM attention_market_classifications WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()["n"]
        return {
            "experiment_id": experiment_id,
            "mode": exp["mode"],
            "status": exp["status"],
            "target_count": exp["target_count"],
            "classified": total,
            "interruptions": total if exp["mode"] == "shadow" else None,
            "classes": {klass: int(classes.get(klass, 0)) for klass in ATTENTION_CLASSES},
            "coverage": coverage,
            "reviewed": int(agg["reviewed"] or 0),
            "actionable_interruptions": int(agg["actionable"] or 0),
            "minutes_to_decision": agg["avg_minutes"],
            "interruptions_resolved_by_machine_later": int(agg["machine_later"] or 0),
            "bundling_ratio": agg["bundling_ratio"],
            "human_interventions_materially_changed_outcomes": int(agg["material_changes"] or 0),
        }

    def disagreements(self, experiment_id: str = DEFAULT_EXPERIMENT,
                      limit: int = 50) -> list[dict[str, Any]]:
        with self.store.connect() as con:
            rows = con.execute(
                """SELECT c.*,o.useful,o.materially_changed_outcome,o.minutes_to_decision,
                          o.resolved_by_machine_later,o.bundled,o.note,o.actor,o.recorded_at
                   FROM attention_market_classifications c
                   JOIN attention_market_outcomes o ON o.classification_id=c.id
                   WHERE c.experiment_id=? AND (
                     (c.attention_class IN ('A0','A1')
                      AND (o.useful=1 OR o.materially_changed_outcome=1))
                     OR
                     (c.attention_class IN ('A2','A3')
                      AND o.useful=0
                      AND COALESCE(o.materially_changed_outcome,0)=0)
                     OR
                     (c.attention_class IN ('A2','A3')
                      AND o.resolved_by_machine_later=1)
                   )
                   ORDER BY o.recorded_at DESC LIMIT ?""",
                (experiment_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return [dict(row) for row in rows]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GOMS Attention Budget Market")
    parser.add_argument("command", choices=("shadow", "metrics", "disagreements"))
    parser.add_argument("--root", default=os.environ.get("GOMS_HOME"))
    parser.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if not args.root:
        raise SystemExit("GOMS_HOME or --root is required")
    market = AttentionMarket(args.root)
    if args.command == "shadow":
        result = market.shadow_sample(limit=args.limit, experiment_id=args.experiment)
    elif args.command == "metrics":
        result = market.metrics(args.experiment)
    else:
        result = market.disagreements(args.experiment, args.limit)
    print(json.dumps(result, indent=2, sort_keys=True))
