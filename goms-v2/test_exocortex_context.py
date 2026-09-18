#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

import mcp_server
from exocortex_context import ExocortexContext
from goms_store import GomsStore


class ExocortexContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="exocortex-context-")
        self.store = GomsStore(Path(self.tmp.name))
        self.person_id = self.store.add_entity(
            "person", "User", "Human principal", entity_id="person_user", actor="test"
        )
        self.goal_id = self.store.add_entity(
            "idea", "Ship the exocortex", "Make GOMS useful to Hermes.",
            project="alpha", entity_id="goal_ship", actor="test"
        )
        self.constraint_id = self.store.add_entity(
            "scarcity", "Human attention", "Keep interruptions bounded.",
            project="alpha", entity_id="constraint_attention", actor="test"
        )
        self.source_id = self.store.add_entity(
            "source", "Planning conversation", project="alpha",
            entity_id="source_plan", actor="test"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def add_assertion(self, assertion_id, subject_id, predicate, *, object_id=None,
                      literal=None, valid_from="2026-09-01T00:00:00+00:00",
                      valid_to=None, source_ref="conversation://plan"):
        with self.store.connect() as con:
            con.execute("""INSERT INTO semantic_assertions(
              id,subject_id,predicate,object_id,literal_value,confidence,
              epistemic_status,valid_from,valid_to,source_entity_id,source_ref,
              supersedes,metadata,created_at,updated_at)
              VALUES(?,?,?,?,?,0.91,'validated_extracted',?,?,?,?,NULL,?,?,?)""",
              (assertion_id, subject_id, predicate, object_id, literal, valid_from,
               valid_to, self.source_id, source_ref,
               json.dumps({"extractor": "test-model"}), valid_from, valid_from))

    def add_intent(self, intent_id, status):
        ts = "2026-09-16T00:00:00+00:00"
        with self.store.connect() as con:
            con.execute("""INSERT INTO control_intents(
              id,kind,title,summary,status,priority,risk_tier,execution_policy,
              source,source_ref,provenance,evidence_refs,recommended_action,
              alternatives,decision_required,verification_policy,outcome,
              created_at,updated_at)
              VALUES(?,?,?,?,?,'P1','normal','HUMAN_ONLY','test','test://intent',
                     '{}','[]','{}','[]',1,'{}','{}',?,?)""",
              (intent_id, "clarification", "Choose a boundary", "Needs input",
               status, ts, ts))

    def test_brief_extracts_current_context_with_auditable_assertion_fields(self):
        self.add_assertion("assert_goal", self.person_id, "has objective",
                           object_id=self.goal_id)
        self.add_assertion("assert_constraint", self.goal_id, "constrained by",
                           object_id=self.constraint_id)
        self.add_assertion("assert_preference", self.person_id, "prefers",
                           literal="Concise updates")
        self.add_assertion(
            "assert_expired", self.person_id, "has_objective", literal="Old goal",
            valid_from="1999-01-01T00:00:00+00:00",
            valid_to="2000-01-01T00:00:00+00:00",
        )
        active_branch = self.store.create_branch(
            "Implementation", "alpha", objective="Build it", status="ACTIVE", actor="test"
        )
        self.store.create_branch(
            "Finished", "alpha", objective="Old work", status="CONCLUDED", actor="test"
        )
        self.add_intent("intent_open", "NEEDS_DECISION")
        self.add_intent("intent_done", "RESOLVED")

        brief = ExocortexContext(self.store).brief(
            person_title="User", project="alpha", limit=12
        )

        self.assertEqual(brief["person"]["id"], self.person_id)
        self.assertEqual([item["id"] for item in brief["goals"]], ["assert_goal"])
        goal = brief["goals"][0]
        self.assertEqual(goal["predicate"], "has_objective")
        self.assertEqual(goal["raw_predicate"], "has objective")
        self.assertEqual(goal["object"]["title"], "Ship the exocortex")
        self.assertEqual(goal["epistemic_status"], "validated_extracted")
        self.assertEqual(goal["validity"], {
            "valid_from": "2026-09-01T00:00:00+00:00", "valid_to": None,
        })
        self.assertEqual(goal["provenance"]["source_entity_id"], self.source_id)
        self.assertEqual(goal["provenance"]["source_ref"], "conversation://plan")
        self.assertEqual(goal["provenance"]["metadata"]["extractor"], "test-model")
        self.assertEqual(
            [item["object"]["title"] for item in brief["constraints"]],
            ["Human attention"],
        )
        self.assertEqual(brief["preferences"][0]["literal_value"], "Concise updates")
        self.assertEqual([branch["id"] for branch in brief["active_branches"]],
                         [active_branch])
        self.assertEqual([intent["id"] for intent in brief["unresolved_intents"]],
                         ["intent_open"])
        self.assertEqual(brief["unresolved_intents"][0]["execution_policy"],
                         "HUMAN_ONLY")

    def test_governed_writes_are_durable_and_cannot_mutate_human_only_intent(self):
        self.add_intent("intent_guarded", "NEEDS_DECISION")
        context = ExocortexContext(self.store)

        clarification_id = context.record_clarification(
            "Boundary detail", "User clarified the recovery boundary.",
            project="alpha", intent_id="intent_guarded",
            source="conversation://clarification", actor="hermes",
        )
        proposal_id = context.propose_policy(
            "Recovery policy", "Permit explicitly invoked local recovery mode.",
            project="alpha", intent_id="intent_guarded",
            source="conversation://proposal", actor="hermes",
        )

        clarification = self.store.get_entity(clarification_id)
        proposal = self.store.get_entity(proposal_id)
        self.assertEqual(clarification["type"], "evidence")
        self.assertEqual(clarification["metadata"]["epistemic_role"], "clarification")
        self.assertEqual(clarification["metadata"]["intent_id"], "intent_guarded")
        self.assertEqual(clarification["metadata"]["authority_effect"], "none")
        self.assertEqual(proposal["type"], "idea")
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertTrue(proposal["metadata"]["requires_human_ratification"])
        self.assertEqual(proposal["metadata"]["authority_effect"], "none")

        with self.store.connect() as con:
            intent = dict(con.execute(
                "SELECT status,execution_policy,decision_required FROM control_intents "
                "WHERE id='intent_guarded'"
            ).fetchone())
            events = con.execute(
                "SELECT count(*) n FROM control_intent_events "
                "WHERE intent_id='intent_guarded'"
            ).fetchone()["n"]
        self.assertEqual(intent["status"], "NEEDS_DECISION")
        self.assertEqual(intent["execution_policy"], "HUMAN_ONLY")
        self.assertEqual(intent["decision_required"], 1)
        self.assertEqual(events, 0)

    def test_governed_write_rejects_unknown_intent_without_creating_entity(self):
        before = self.store.stats()
        with self.assertRaises(KeyError):
            ExocortexContext(self.store).record_clarification(
                "No target", "Must not orphan intent-bound evidence.",
                intent_id="intent_missing", actor="hermes",
            )
        self.assertEqual(self.store.stats(), before)

    def test_mcp_governed_write_tools_preserve_human_only_intent(self):
        self.add_intent("intent_guarded", "NEEDS_DECISION")
        old_store = mcp_server.store
        mcp_server.store = self.store
        try:
            clarification = mcp_server.record_clarification(
                "Detail", "Clarified", "alpha", "intent_guarded",
                "conversation://detail", "hermes"
            )
            proposal = mcp_server.propose_policy(
                "Proposal", "Change later", "alpha", "intent_guarded",
                "conversation://proposal", "hermes"
            )
        finally:
            mcp_server.store = old_store
        self.assertTrue(clarification["ok"])
        self.assertTrue(proposal["ok"])
        with self.store.connect() as con:
            row = con.execute(
                "SELECT status,execution_policy FROM control_intents "
                "WHERE id='intent_guarded'"
            ).fetchone()
        self.assertEqual(row["status"], "NEEDS_DECISION")
        self.assertEqual(row["execution_policy"], "HUMAN_ONLY")

    def test_mcp_tool_delegates_to_focused_context_module(self):
        self.add_assertion("assert_goal", self.person_id, "has_objective",
                           object_id=self.goal_id)
        old_store = mcp_server.store
        mcp_server.store = self.store
        try:
            result = mcp_server.exocortex_brief("User", "alpha", 12)
        finally:
            mcp_server.store = old_store

        self.assertTrue(result["ok"])
        self.assertEqual(result["context"]["goals"][0]["id"], "assert_goal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
