#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path
import survivability_audit as s

class SurvivabilityAuditTests(unittest.TestCase):
    def test_declared_components_and_state_are_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            release=root/"current"; release.mkdir()
            (release/"a").mkdir(); (release/"a"/"main.py").write_text("x")
            (release/"manifest.json").write_text(json.dumps({
                "components":{"a":{"install":"a","entrypoint":"main.py"}}
            }))
            state=root/"goms"; state.mkdir()
            (state/"goms.sqlite3").write_bytes(b"db")
            (state/"events.jsonl").write_text("")
            result=s.audit(release,state)
            self.assertTrue(result["ok"])
            self.assertEqual(result["failures"],[])
            self.assertTrue(result["components"]["a"]["sha256"])

    def test_missing_declared_component_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); release=root/"current"; release.mkdir()
            (release/"manifest.json").write_text(json.dumps({
                "components":{"a":{"install":"a","entrypoint":"main.py"}}
            }))
            result=s.audit(release)
            self.assertFalse(result["ok"])
            self.assertIn("component_entrypoint_missing:a",result["failures"])

if __name__=="__main__":
    unittest.main()
