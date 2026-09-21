#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from control_intents import ControlIntentService
from goms_store import GomsStore
from manfred_control import ManfredControl
try:
    import mcp_server  # type: ignore
    HAS_MCP = True
except Exception:
    HAS_MCP = False
    mcp_server = None  # type: ignore


class AinekoDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aineko-dispatch-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.svc = ControlIntentService(self.root)
        self.ctl = ManfredControl(self.root / "goms.sqlite3")
        self.old_store = None
        if HAS_MCP:
            self.old_store = mcp_server.store
            mcp_server.store = self.store

    def tearDown(self):
        if HAS_MCP:
            mcp_server.store = self.old_store
        self.tmp.cleanup()

    def test_submit_creates_durable_intent_with_acknowledgement(self):
        result = self.svc.submit_intent(
            title="Aineko task 1", summary="Do the thing",
            kind="aineko_task", source="ChatGPT", actor="chatgpt",
            idempotency_key="submit-ack-1", priority="P1")
        self.assertTrue(result["acknowledged"])
        self.assertFalse(result["replayed"])
        intent_id = result["intent_id"]
        intent = self.svc.get(intent_id)
        self.assertEqual(intent["status"], "NEEDS_DECISION")
        self.assertEqual(intent["title"], "Aineko task 1")
        self.assertIsNotNone(intent["acknowledged_at"])
        self.assertEqual(intent["execution_policy"], "HUMAN_ONLY")
        # ledger auditable
        events = self.store.recent_events(10)
        self.assertTrue(any(e.get("op") == "control_intent_submit" and e.get("intent_id") == intent_id for e in events))
        # status queryable via get
        self.assertEqual(self.svc.get(intent_id)["id"], intent_id)

    def test_submit_duplicate_same_key_same_payload_replays(self):
        r1 = self.svc.submit_intent(title="Dup", summary="same", actor="chatgpt", idempotency_key="dup-1")
        r2 = self.svc.submit_intent(title="Dup", summary="same", actor="chatgpt", idempotency_key="dup-1")
        self.assertEqual(r1["intent_id"], r2["intent_id"])
        self.assertTrue(r2["replayed"])
        # no duplicate row
        with self.store.connect() as con:
            count = con.execute("SELECT count(*) FROM control_intents WHERE id=?", (r1["intent_id"],)).fetchone()[0]
            self.assertEqual(count, 1)
            sub = con.execute("SELECT count(*) FROM control_intent_submissions WHERE idempotency_key='dup-1'").fetchone()[0]
            self.assertEqual(sub, 1)

    def test_submit_duplicate_same_key_different_payload_rejected(self):
        self.svc.submit_intent(title="First", summary="a", actor="chatgpt", idempotency_key="dup-diff-1")
        with self.assertRaises(ValueError) as ctx:
            self.svc.submit_intent(title="Second", summary="b", actor="chatgpt", idempotency_key="dup-diff-1")
        self.assertEqual(str(ctx.exception), "idempotency_key_reused")

    def test_submit_status_queryable(self):
        r = self.svc.submit_intent(title="Query", summary="status", actor="chatgpt", idempotency_key="q-1")
        intent_id = r["intent_id"]
        # via service get
        self.assertEqual(self.svc.get(intent_id)["status"], "NEEDS_DECISION")
        # via MCP tool if available
        if HAS_MCP:
            mcp = mcp_server.control_intent(intent_id)
            self.assertTrue(mcp["ok"])
            self.assertEqual(mcp["intent"]["id"], intent_id)
        # via list_open excludes terminal but includes needs_decision
        open_ids = [x["id"] for x in self.svc.list_open(limit=50)]
        self.assertIn(intent_id, open_ids)

    def test_cancel_before_execution_succeeds(self):
        r = self.svc.submit_intent(title="CancelMe", summary="x", actor="chatgpt", idempotency_key="cancel-1")
        intent_id = r["intent_id"]
        cancelled = self.svc.cancel_intent(intent_id, actor="chatgpt", reason="no longer needed")
        self.assertEqual(cancelled["status"], "CANCELLED")
        # cancelling again fails
        with self.assertRaises(ValueError):
            self.svc.cancel_intent(intent_id, actor="chatgpt")
        # not in open list
        self.assertNotIn(intent_id, [x["id"] for x in self.svc.list_open(limit=50)])

    def test_cancel_after_execution_fails(self):
        r = self.svc.submit_intent(
            title="ExecCancel", summary="x", actor="human:alice",
            human_attested=True, resolved_by="human:alice",
            execution_policy="AUTO_AFTER_APPROVAL", idempotency_key="exec-cancel-1",
            recommended_action={"type": "aineko_task", "target_id": "x"})
        intent_id = r["intent_id"]
        self.assertEqual(self.svc.get(intent_id)["status"], "APPROVED")
        attempt = self.svc.claim_for_aineko(intent_id, worker_id="aineko-1")
        with self.assertRaises(ValueError):
            self.svc.cancel_intent(intent_id, actor="human:alice")

    def test_cancel_from_approved_succeeds(self):
        r = self.svc.submit_intent(
            title="CancelApproved", summary="x", actor="human:alice",
            human_attested=True, resolved_by="human:alice",
            idempotency_key="cancel-approved-1")
        intent_id = r["intent_id"]
        self.assertEqual(self.svc.get(intent_id)["status"], "APPROVED")
        cancelled = self.svc.cancel_intent(intent_id, actor="human:alice")
        self.assertEqual(cancelled["status"], "CANCELLED")

    def test_claim_boundary_single_worker(self):
        r = self.svc.submit_intent(
            title="Claimable", summary="do", actor="human:alice",
            human_attested=True, resolved_by="human:alice",
            execution_policy="AUTO_AFTER_APPROVAL", idempotency_key="claim-1",
            recommended_action={"type": "aineko_task", "target_id": "x"})
        intent_id = r["intent_id"]
        pending = self.svc.list_pending_for_worker(limit=10)
        self.assertTrue(any(x["id"] == intent_id for x in pending))
        a1 = self.svc.claim_for_aineko(intent_id, worker_id="worker-a")
        self.assertIsNotNone(a1)
        self.assertEqual(self.svc.get(intent_id)["status"], "EXECUTING")
        # second claim fails
        with self.assertRaises(ValueError):
            self.svc.claim_for_aineko(intent_id, worker_id="worker-b")
        # execution attempts durable
        with self.store.connect() as con:
            row = con.execute("SELECT status FROM control_intent_execution_attempts WHERE intent_id=?", (intent_id,)).fetchone()
            self.assertEqual(row["status"], "EXECUTING")

    def test_claim_human_only_not_allowed(self):
        r = self.svc.submit_intent(title="HO", summary="x", actor="chatgpt", idempotency_key="ho-1", execution_policy="HUMAN_ONLY")
        # approve via human
        self.svc.decide(r["intent_id"], "APPROVE", "human:bob", {"human_attested": True})
        self.assertEqual(self.svc.get(r["intent_id"])["status"], "APPROVED")
        with self.assertRaises(ValueError) as ctx:
            self.svc.claim_for_aineko(r["intent_id"], worker_id="worker-1")
        self.assertIn("human_only", str(ctx.exception))

    def test_execution_evidence_and_result(self):
        r = self.svc.submit_intent(
            title="Evidence", summary="produce", actor="human:alice",
            human_attested=True, resolved_by="human:alice",
            execution_policy="AUTO_AFTER_APPROVAL", idempotency_key="ev-1")
        intent_id = r["intent_id"]
        attempt = self.svc.claim_for_aineko(intent_id, worker_id="aineko-worker")
        result = self.svc.record_aineko_result(
            intent_id, attempt, worker_id="aineko-worker", status="SUCCESS",
            result={"output": "done"}, evidence_title="Aineko result", evidence_summary="completed successfully")
        self.assertEqual(result["status"], "RESOLVED")
        self.assertIn("worker_id", result["outcome"])
        # evidence durable
        with self.store.connect() as con:
            ev = con.execute("SELECT id FROM entities WHERE type='evidence' AND title='Aineko result'").fetchone()
            self.assertIsNotNone(ev)
            intent = self.svc.get(intent_id)
            self.assertIn(ev["id"], intent["evidence_refs"])

    def test_restart_resumable(self):
        r = self.svc.submit_intent(title="Restart", summary="x", actor="chatgpt", idempotency_key="restart-1")
        intent_id = r["intent_id"]
        # simulate restart by creating new service instance same root
        svc2 = ControlIntentService(self.root)
        intent = svc2.get(intent_id)
        self.assertEqual(intent["title"], "Restart")
        self.assertEqual(intent["status"], "NEEDS_DECISION")
        # also claim persists across restart
        r2 = self.svc.submit_intent(
            title="RestartClaim", summary="x", actor="human:alice", human_attested=True,
            resolved_by="human:alice", execution_policy="AUTO_AFTER_APPROVAL", idempotency_key="restart-claim-1")
        cid = r2["intent_id"]
        attempt = self.svc.claim_for_aineko(cid, worker_id="w1")
        svc3 = ControlIntentService(self.root)
        self.assertEqual(svc3.get(cid)["status"], "EXECUTING")
        with svc3.store.connect() as con:
            row = con.execute("SELECT id FROM control_intent_execution_attempts WHERE intent_id=?", (cid,)).fetchone()
            self.assertEqual(row["id"], attempt)

    def test_authority_submission_not_authorization_without_human_attested(self):
        # without human_attested, stays NEEDS_DECISION
        r = self.svc.submit_intent(title="NoAuth", summary="x", actor="chatgpt", idempotency_key="noauth-1", execution_policy="AUTO_AFTER_APPROVAL")
        self.assertEqual(self.svc.get(r["intent_id"])["status"], "NEEDS_DECISION")
        # with human_attested True but not human actor -> stays NEEDS_DECISION
        r2 = self.svc.submit_intent(title="NoAuth2", summary="x", actor="chatgpt", human_attested=True, resolved_by="chatgpt", idempotency_key="noauth-2", execution_policy="AUTO_AFTER_APPROVAL")
        self.assertEqual(self.svc.get(r2["intent_id"])["status"], "NEEDS_DECISION")
        # with human_attested True and human resolved_by -> auto-approved
        r3 = self.svc.submit_intent(title="Auth", summary="x", actor="human:alice", human_attested=True, resolved_by="human:alice", idempotency_key="auth-1", execution_policy="AUTO_AFTER_APPROVAL")
        self.assertEqual(self.svc.get(r3["intent_id"])["status"], "APPROVED")
        # HUMAN_ONLY even with human_attested does not auto-execute, stays APPROVED and not claimable
        r4 = self.svc.submit_intent(title="HOAuth", summary="x", actor="human:alice", human_attested=True, resolved_by="human:alice", idempotency_key="ho-auth-1", execution_policy="HUMAN_ONLY")
        self.assertEqual(self.svc.get(r4["intent_id"])["status"], "APPROVED")
        with self.assertRaises(ValueError):
            self.svc.claim_for_aineko(r4["intent_id"], worker_id="w")

    @unittest.skipUnless(HAS_MCP, "mcp not available")
    def test_mcp_submit_intent_idempotent_and_status(self):
        first = mcp_server.submit_intent(title="MCP Task", summary="via mcp", actor="chatgpt", idempotency_key="mcp-1", source="ChatGPT")
        self.assertTrue(first["ok"])
        self.assertTrue(first["acknowledged"])
        intent_id = first["intent_id"]
        second = mcp_server.submit_intent(title="MCP Task", summary="via mcp", actor="chatgpt", idempotency_key="mcp-1", source="ChatGPT")
        self.assertTrue(second["ok"])
        self.assertEqual(second["intent_id"], intent_id)
        self.assertTrue(second["replayed"])
        # status queryable
        queried = mcp_server.control_intent(intent_id)
        self.assertEqual(queried["intent"]["status"], "NEEDS_DECISION")
        # cancel via MCP
        cancelled = mcp_server.cancel_intent(intent_id, actor="chatgpt")
        self.assertTrue(cancelled["ok"])
        self.assertEqual(cancelled["status"], "CANCELLED")

    @unittest.skipUnless(HAS_MCP, "mcp not available")
    def test_mcp_worker_queue(self):
        r = mcp_server.submit_intent(title="QueueTask", summary="q", actor="human:alice", human_attested=True, resolved_by="human:alice", idempotency_key="queue-1", execution_policy="AUTO_AFTER_APPROVAL", source="Hermes")
        self.assertTrue(r["ok"])
        pending = mcp_server.aineko_pending_intents(limit=10)
        self.assertTrue(pending["ok"])
        self.assertTrue(any(x["id"] == r["intent_id"] for x in pending["intents"]))
        claimed = mcp_server.aineko_claim_intent(r["intent_id"], worker_id="aineko-test-worker")
        self.assertTrue(claimed["ok"])
        completed = mcp_server.aineko_complete_intent(r["intent_id"], claimed["execution_attempt_id"], worker_id="aineko-test-worker", status="SUCCESS", result={"done": True}, evidence_title="MCP evidence", evidence_summary="ok")
        self.assertTrue(completed["ok"])
        self.assertEqual(completed["status"], "RESOLVED")

    def test_manfred_submit_intent_via_command_ledger(self):
        cmd = {"idempotency_key": "manfred-submit-1", "type": "submit_intent", "target_id": "", "payload": {"title": "Manfred Task", "summary": "via manfred", "actor": "Manfred", "source": "Manfred"}}
        first = self.ctl.execute_command(cmd)
        self.assertTrue(first["ok"])
        second = self.ctl.execute_command(cmd)
        self.assertEqual(first, second)
        # duplicate with different payload rejected
        bad = {"idempotency_key": "manfred-submit-1", "type": "submit_intent", "target_id": "", "payload": {"title": "Different", "actor": "Manfred"}}
        bad_res = self.ctl.execute_command(bad)
        self.assertEqual(bad_res["error"], "idempotency_key_reused")

    def test_manfred_cancel_and_claim_flow(self):
        sub = self.ctl.execute_command({"idempotency_key": "manfred-sub-2", "type": "submit_intent", "target_id": "", "payload": {"title": "Flow", "actor": "human:alice", "human_attested": True, "resolved_by": "human:alice", "execution_policy": "AUTO_AFTER_APPROVAL"}})
        intent_id = sub["intent_id"]
        # pending
        pending = self.svc.list_pending_for_worker()
        self.assertTrue(any(x["id"] == intent_id for x in pending))
        claim = self.ctl.execute_command({"idempotency_key": "manfred-claim-1", "type": "aineko_claim_intent", "target_id": intent_id, "payload": {"worker_id": "aineko-1"}})
        self.assertTrue(claim["ok"])
        complete = self.ctl.execute_command({"idempotency_key": "manfred-complete-1", "type": "aineko_complete_intent", "target_id": intent_id, "payload": {"worker_id": "aineko-1", "execution_attempt_id": claim["execution_attempt_id"], "status": "SUCCESS", "result": {"x": 1}, "evidence_title": "Manfred evidence"}})
        self.assertTrue(complete["ok"])
        self.assertEqual(self.svc.get(intent_id)["status"], "RESOLVED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
