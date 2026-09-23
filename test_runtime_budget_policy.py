#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent

class RuntimeBudgetPolicyTest(unittest.TestCase):
    def test_gsvaineko_fragment_has_execution_brakes(self):
        text = (ROOT / "config/hermes.gsvaineko.fragment.yaml").read_text()
        self.assertIn("max_turns: 60", text)
        self.assertIn("max_iterations: 30", text)
        self.assertIn("max_tool_calls: 20", text)
        self.assertIn("hard_stop_enabled: true", text)
        self.assertIn("idempotent_no_progress: 3", text)

    def test_interactive_session_routes_sustained_work(self):
        skill = (ROOT / "hermes/skills/exocortex-executive/SKILL.md").read_text()
        soul = (ROOT / "hermes/SOUL.md").read_text()
        self.assertIn("normally finish within six", skill)
        self.assertIn("approved-intent bounded worker path", skill)
        self.assertIn("persistent human-facing session thin", soul)
        self.assertIn("repeated no-progress tool calls as a fault condition", soul)

    def test_profile_installer_enforces_same_budget(self):
        installer = (ROOT / "hermes/install_profile.py").read_text()
        self.assertIn('agent["max_turns"] = 60', installer)
        self.assertIn('data.setdefault("delegation", {})["max_iterations"] = 30', installer)
        self.assertIn('guard["hard_stop_enabled"] = True', installer)

    def test_context_capacity_is_model_aware(self):
        fragment = (ROOT / "config/hermes.gsvaineko.fragment.yaml").read_text()
        installer = (ROOT / "hermes/install_profile.py").read_text()
        fallback = (ROOT / "models/gsvaineko-core.Modelfile").read_text()
        model_block = fragment.split("fallback_model:", 1)[0]
        self.assertNotIn("context_length:", model_block)
        self.assertIn('.pop("context_length", None)', installer)
        self.assertIn("PARAMETER num_ctx 65536", fallback)

if __name__ == "__main__":
    unittest.main()
