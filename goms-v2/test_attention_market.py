#!/usr/bin/env python3
import json
import os
import tempfile
import unittest
from pathlib import Path

from attention_market import AttentionMarket, classify_bid
from alerts import AlertService
from control_intents import ControlIntentService
from goms_store import GomsStore


class PureAttentionMarketTests(unittest.TestCase):
    def test_machine_resolvable_low_irreplaceability_is_a0(self):
        bid = classify_bid(
            attention_id="a0",
            expected_value=.8,
            urgency=.7,
            human_irreplaceability=.1,
            attention_cost_minutes=5,
            machine_resolution_expected=True,
        )
        self.assertEqual(bid.attention_class, "A0")
        self.assertEqual(bid.behavior, "execute_autonomously")

    def test_moderate_machine_observation_is_a1(self):
        bid = classify_bid(
            attention_id="a1",
            expected_value=.5,
            urgency=.4,
            human_irreplaceability=.2,
            attention_cost_minutes=5,
        )
        self.assertEqual(bid.attention_class, "A1")
        self.assertEqual(bid.behavior, "next_digest")

    def test_human_judgment_without_delay_case_is_a2(self):
        bid = classify_bid(
            attention_id="a2",
            expected_value=.9,
            urgency=.9,
            human_irreplaceability=.9,
            attention_cost_minutes=5,
            delay_cost=.9,
            human_decision="Choose the acceptable risk boundary",
            delay_cost_reason="",
        )
        self.assertEqual(bid.attention_class, "A2")
        self.assertEqual(bid.behavior, "bundle_next_interaction")

    def test_a3_requires_specific_human_decision_and_delay_cost_reason(self):
        bid = classify_bid(
            attention_id="a3",
            expected_value=.9,
            urgency=.95,
            human_irreplaceability=.95,
            attention_cost_minutes=5,
            delay_cost=.9,
            human_decision="Approve or reject the irreversible public action",
            delay_cost_reason="Waiting past the filing window loses the opportunity",
        )
        self.assertEqual(bid.attention_class, "A3")
        self.assertEqual(bid.behavior, "interrupt_now")

    def test_protected_end_question_never_falls_below_a2(self):
        bid = classify_bid(
            attention_id="ends",
            expected_value=.1,
            urgency=.1,
            human_irreplaceability=.1,
            attention_cost_minutes=30,
            protected_end_question=True,
        )
        self.assertEqual(bid.attention_class, "A2")

    def test_suppression_modes_expand_only_from_low_value_classes(self):
        a0 = dict(
            attention_id="a0", expected_value=.2, urgency=.1,
            human_irreplaceability=.1, attention_cost_minutes=5,
            machine_resolution_expected=True,
        )
        self.assertTrue(classify_bid(mode="shadow", **a0).surface_now)
        self.assertFalse(classify_bid(mode="suppress_a0", **a0).surface_now)
        a1 = dict(
            attention_id="a1", expected_value=.5, urgency=.4,
            human_irreplaceability=.2, attention_cost_minutes=5,
        )
        self.assertTrue(classify_bid(mode="suppress_a0", **a1).surface_now)
        self.assertFalse(classify_bid(mode="suppress_a0_a1", **a1).surface_now)


class AttentionMarketPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="attention-market-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.intents = ControlIntentService(self.root)
        self.market = AttentionMarket(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def make_attention(self, attention_id, *, source="Hermes", category="test",
                       severity="warning", bounded=False):
        ts = "2026-09-20T18:00:00+00:00"
        actions = []
        if bounded:
            branch = self.store.create_branch("market branch", "test", status="ACTIVE")
            actions = [{
                "type": "checkpoint_branch",
                "target_id": branch,
                "payload": {"status": "PARKED", "summary": "done"},
            }]
        with self.store.connect() as con:
            con.execute(
                """INSERT INTO attention_items(
                     id,category,severity,title,summary,status,suggested_actions,
                     source,created_at,updated_at)
                   VALUES(?,?,?,?,?,'open',?,?,?,?)""",
                (
                    attention_id, category, severity, f"Decision {attention_id}",
                    "Candidate interruption", json.dumps(actions), source, ts, ts,
                ),
            )
        return self.intents.ensure_for_attention(attention_id)

    def set_attention_market_override(self, intent_id, **override):
        with self.store.connect() as con:
            row = con.execute(
                "SELECT provenance FROM control_intents WHERE id=?", (intent_id,)
            ).fetchone()
            provenance = json.loads(row["provenance"] or "{}")
            provenance["attention_market"] = override
            con.execute(
                "UPDATE control_intents SET provenance=? WHERE id=?",
                (json.dumps(provenance), intent_id),
            )

    def test_critical_importance_does_not_create_a3_without_delay_reason(self):
        intent = self.make_attention("critical", severity="critical")
        result = self.market.classify_intent(intent)
        self.assertEqual(result["attention_class"], "A2")
        self.assertEqual(result["delay_cost_reason"], "")

    def test_explicit_end_question_and_delay_case_can_create_a3(self):
        intent = self.make_attention("risk", severity="critical")
        self.set_attention_market_override(
            intent,
            expected_value=.95,
            urgency=.95,
            human_irreplaceability=1.0,
            delay_cost=.9,
            human_decision="Choose whether this irreversible risk is acceptable",
            delay_cost_reason="The irreversible action executes in 20 minutes",
            protected_end_question=True,
        )
        result = self.market.classify_intent(intent)
        self.assertEqual(result["attention_class"], "A3")
        self.assertTrue(result["protected_end_question"])

    def test_unreconciled_historical_attention_is_not_assumed_human_only(self):
        ts = "2026-09-20T18:00:00+00:00"
        with self.store.connect() as con:
            con.execute(
                """INSERT INTO attention_items(
                     id,category,severity,title,summary,status,suggested_actions,
                     source,created_at,updated_at)
                   VALUES('historic','research','info','Paper appeared','Read later',
                          'open','[]','ResearchWorker',?,?)""",
                (ts, ts),
            )
        result = self.market.classify_attention("historic")
        self.assertIn(result["attention_class"], {"A0", "A1"})
        self.assertLess(result["human_irreplaceability"], .5)

    def test_machine_resolvable_intent_can_be_a0(self):
        intent = self.make_attention("machine", severity="info", bounded=True)
        with self.store.connect() as con:
            con.execute(
                """UPDATE control_intents
                   SET decision_required=0,execution_policy='AUTO_AFTER_APPROVAL'
                   WHERE id=?""",
                (intent,),
            )
        result = self.market.classify_intent(intent)
        self.assertEqual(result["attention_class"], "A0")
        self.assertTrue(result["machine_resolution_expected"])

    def test_shadow_sample_records_50_and_reports_source_coverage(self):
        sources = [
            ("HermesExecutor", "hermes"),
            ("NemosyneWorker", "nemosyne"),
            ("ResearchGuardian", "research"),
            ("InfrastructureHealthController", "infrastructure"),
        ]
        ts_base = 100
        for index in range(60):
            source, _ = sources[index % len(sources)]
            ts = f"2026-09-20T18:{index // 60:02d}:{index % 60:02d}+00:00"
            with self.store.connect() as con:
                con.execute(
                    """INSERT INTO attention_items(
                         id,category,severity,title,summary,status,suggested_actions,
                         source,created_at,updated_at)
                       VALUES(?,?,?,?,?,'open','[]',?,?,?)""",
                    (
                        f"sample-{index}", "test", "info", f"Sample {index}",
                        "candidate", source, ts, ts,
                    ),
                )
        result = self.market.shadow_sample(limit=50, experiment_id="exp50")
        self.assertEqual(result["classified"], 50)
        self.assertGreater(result["coverage"]["hermes"], 0)
        self.assertGreater(result["coverage"]["nemosyne"], 0)
        self.assertGreater(result["coverage"]["research"], 0)
        self.assertGreater(result["coverage"]["infrastructure"], 0)
        metrics = self.market.metrics("exp50")
        self.assertEqual(metrics["classified"], 50)
        self.assertEqual(metrics["status"], "READY_FOR_REVIEW")
        self.assertEqual(metrics["interruptions"], 50)

    def test_alert_reconciliation_shadow_records_bid_but_still_surfaces(self):
        intent = self.make_attention("shadow-alert", severity="info", bounded=True)
        with self.store.connect() as con:
            con.execute(
                """UPDATE control_intents
                   SET decision_required=0,execution_policy='AUTO_AFTER_APPROVAL'
                   WHERE id=?""",
                (intent,),
            )
        old = os.environ.get("GOMS_ATTENTION_MARKET_MODE")
        os.environ["GOMS_ATTENTION_MARKET_MODE"] = "shadow"
        try:
            alert = AlertService(self.root).reconcile_intent(intent)
        finally:
            if old is None:
                os.environ.pop("GOMS_ATTENTION_MARKET_MODE", None)
            else:
                os.environ["GOMS_ATTENTION_MARKET_MODE"] = old
        self.assertIsNotNone(alert)
        with self.store.connect() as con:
            row = con.execute(
                """SELECT attention_class,surface_now,mode
                   FROM attention_market_classifications
                   WHERE attention_id='shadow-alert'"""
            ).fetchone()
        self.assertEqual((row["attention_class"], row["surface_now"], row["mode"]),
                         ("A0", 1, "shadow"))

    def test_suppress_a0_mode_suppresses_same_bid(self):
        intent = self.make_attention("suppress-alert", severity="info", bounded=True)
        with self.store.connect() as con:
            con.execute(
                """UPDATE control_intents
                   SET decision_required=0,execution_policy='AUTO_AFTER_APPROVAL'
                   WHERE id=?""",
                (intent,),
            )
        old = os.environ.get("GOMS_ATTENTION_MARKET_MODE")
        os.environ["GOMS_ATTENTION_MARKET_MODE"] = "suppress_a0"
        try:
            alert = AlertService(self.root).reconcile_intent(intent)
        finally:
            if old is None:
                os.environ.pop("GOMS_ATTENTION_MARKET_MODE", None)
            else:
                os.environ["GOMS_ATTENTION_MARKET_MODE"] = old
        self.assertIsNone(alert)
        with self.store.connect() as con:
            self.assertEqual(con.execute(
                "SELECT count(*) FROM alerts WHERE intent_id=?", (intent,)
            ).fetchone()[0], 0)
            row = con.execute(
                """SELECT attention_class,surface_now,mode
                   FROM attention_market_classifications
                   WHERE attention_id='suppress-alert'"""
            ).fetchone()
        self.assertEqual((row["attention_class"], row["surface_now"], row["mode"]),
                         ("A0", 0, "suppress_a0"))

    def test_outcomes_drive_metrics_and_disagreement_review(self):
        intent = self.make_attention("outcome", severity="info", bounded=True)
        with self.store.connect() as con:
            con.execute(
                """UPDATE control_intents
                   SET decision_required=0,execution_policy='AUTO_AFTER_APPROVAL'
                   WHERE id=?""",
                (intent,),
            )
        result = self.market.classify_intent(intent, experiment_id="outcomes")
        self.assertEqual(result["attention_class"], "A0")
        self.market.record_outcome(
            result["classification_id"],
            useful=True,
            materially_changed_outcome=True,
            minutes_to_decision=2.5,
            resolved_by_machine_later=False,
            bundled=False,
            note="Human noticed a constraint the machinery missed",
        )
        metrics = self.market.metrics("outcomes")
        self.assertEqual(metrics["reviewed"], 1)
        self.assertEqual(metrics["actionable_interruptions"], 1)
        self.assertEqual(metrics["human_interventions_materially_changed_outcomes"], 1)
        disagreements = self.market.disagreements("outcomes")
        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0]["attention_class"], "A0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
