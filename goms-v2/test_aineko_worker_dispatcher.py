#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aineko_worker_dispatcher import (
    _create_bounded_profile, build_context_packet, dispatch_once, run_worker,
)
from control_intents import ControlIntentService
from goms_store import GomsStore


class BoundedWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aineko-worker-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.svc = ControlIntentService(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def approved(self, **overrides):
        values = dict(
            title="Bounded task",
            summary="Execute one focused task",
            source="system",
            actor="system:schedule",
            project="Exocortex",
            execution_policy="AUTO_AFTER_APPROVAL",
            recommended_action={"type": "aineko_task", "instructions": "verify one thing"},
            human_attested=True,
            resolved_by="human:T",
        )
        values.update(overrides)
        return self.svc.submit_intent(**values)["intent_id"]

    def test_context_packet_is_bounded_and_keeps_intent_semantics(self):
        intent_id = self.approved()
        intent = self.svc.get(intent_id)
        packet = build_context_packet(self.svc, intent, max_chars=8000)
        self.assertLessEqual(packet["context_chars"], 8000)
        self.assertEqual(packet["intent"]["id"], intent_id)
        self.assertEqual(
            packet["intent"]["recommended_action"]["instructions"],
            "verify one thing",
        )
        self.assertIn("history_policy", packet["contract"])

    def test_oversized_intent_is_rejected_not_silently_truncated(self):
        intent_id = self.approved(
            recommended_action={"type": "aineko_task", "instructions": "x" * 7000})
        with self.assertRaisesRegex(ValueError, "context_budget_exceeded_by_intent"):
            build_context_packet(self.svc, self.svc.get(intent_id), max_chars=8000)

    def test_success_without_verification_is_downgraded_unknown(self):
        intent_id = self.approved()
        fake = ({
            "status": "SUCCESS",
            "result": {"claimed": "done"},
            "verification": {"performed": False, "evidence": ""},
            "evidence_title": "unverified",
            "evidence_summary": "",
        }, {"prompt_tokens": 1000})
        with patch("aineko_worker_dispatcher.run_worker", return_value=fake):
            outcome = dispatch_once(self.root, hermes_agent_home=Path("/unused"))
        self.assertEqual(outcome["status"], "UNKNOWN")
        intent = self.svc.get(intent_id)
        self.assertEqual(intent["status"], "OUTCOME_UNKNOWN")
        self.assertEqual(intent["outcome"]["result"]["success_downgraded"],
                         "missing_verification")

    def test_bounded_profile_sets_authoritative_turn_cap(self):
        home = self.root / "hermes-agent"
        python = home / "venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("")
        completed = __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr="")
        with patch("aineko_worker_dispatcher._run_hermes_cli", return_value=completed) as cli, \
             patch("aineko_worker_dispatcher.secrets.token_hex", return_value="abc123"), \
             patch("aineko_worker_dispatcher.os.getpid", return_value=42):
            profile = _create_bounded_profile(
                python, home, "gsvaineko", max_tool_calls=7)
        self.assertEqual(profile, "ainekoworker42abc123")
        calls = [call.args[2] for call in cli.call_args_list]
        self.assertEqual(calls[0], [
            "profile", "create", profile, "--clone-from", "gsvaineko", "--no-alias"])
        self.assertEqual(calls[1], [
            "--profile", profile, "config", "set", "agent.max_turns", "7"])

    def test_worker_uses_isolated_profile_without_retired_max_turns_flag(self):
        home = self.root / "hermes-agent"
        python = home / "venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("")
        packet = {"intent": {"id": "intent_test"}, "execution": {"do_not_claim": True}}
        completed = __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({
                "status": "SUCCESS", "result": {},
                "verification": {"performed": True, "evidence": "ok"},
                "evidence_title": "ok", "evidence_summary": "ok"}), stderr="")
        with patch("aineko_worker_dispatcher._create_bounded_profile", return_value="ainekoworkertest"), \
             patch("aineko_worker_dispatcher._delete_bounded_profile") as cleanup, \
             patch("aineko_worker_dispatcher.subprocess.run", return_value=completed) as proc:
            run_worker(packet, profile="gsvaineko", timeout_seconds=30,
                       max_tool_calls=7, hermes_agent_home=home)
        argv = proc.call_args.args[0]
        self.assertIn("--profile", argv)
        self.assertEqual(argv[argv.index("--profile") + 1], "ainekoworkertest")
        self.assertNotIn("--max-turns", argv)
        cleanup.assert_called_once_with(python, home, "ainekoworkertest")

    def test_worker_receives_existing_claim_and_must_not_reclaim(self):
        intent_id = self.approved()
        seen = {}

        def fake_worker(packet, **kwargs):
            seen.update(packet)
            return ({
                "status": "SUCCESS",
                "result": {"done": True},
                "verification": {"performed": True, "evidence": "verified"},
                "evidence_title": "claim handoff",
                "evidence_summary": "verified",
            }, {})

        with patch("aineko_worker_dispatcher.run_worker", side_effect=fake_worker):
            dispatch_once(self.root, hermes_agent_home=Path("/unused"))
        self.assertTrue(seen["execution"]["do_not_claim"])
        self.assertEqual(seen["execution"]["claim_status"], "HELD_BY_DISPATCHER")
        self.assertTrue(seen["execution"]["attempt_id"].startswith("intent_attempt_"))
        self.assertEqual(self.svc.get(intent_id)["status"], "RESOLVED")

    def test_verified_success_resolves(self):
        intent_id = self.approved()
        fake = ({
            "status": "SUCCESS",
            "result": {"done": True},
            "verification": {"performed": True, "evidence": "read-back matched"},
            "evidence_title": "bounded result",
            "evidence_summary": "read-back matched",
        }, {"prompt_tokens": 1200})
        with patch("aineko_worker_dispatcher.run_worker", return_value=fake):
            outcome = dispatch_once(self.root, hermes_agent_home=Path("/unused"))
        self.assertEqual(outcome["status"], "SUCCESS")
        self.assertEqual(self.svc.get(intent_id)["status"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
