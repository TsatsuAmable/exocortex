import unittest
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import json
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import submit_scheduled_intent as mod


class ScheduleInstanceTests(unittest.TestCase):
    def test_default_day_shape(self):
        now = datetime(2026, 10, 3, 21, 45, tzinfo=timezone.utc)
        self.assertEqual(mod._schedule_instance("day", now=now), "2026-10-03")

    def test_hour_shape(self):
        now = datetime(2026, 10, 3, 21, 45, tzinfo=timezone.utc)
        self.assertEqual(mod._schedule_instance("hour", now=now), "2026-10-03T21")

    def test_unknown_period_fails_closed(self):
        with self.assertRaises(ValueError):
            mod._schedule_instance("minute", now=datetime.now(timezone.utc))


class SubmitIdempotencyTests(unittest.TestCase):
    def test_hourly_spec_uses_hourly_key(self):
        calls = {}

        class FakeService:
            def __init__(self, _goms_home):
                pass

            def submit_intent(self, **kwargs):
                calls.update(kwargs)
                return {"intent_id": "x", "intent": {"status": "pending"}}

        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "spec.json"
            spec.write_text(json.dumps({
                "id": "nemocoder-apprenticeship",
                "title": "NemoCoder",
                "summary": "test",
                "instructions": "test",
                "idempotency_period": "hour",
            }))
            fixed = datetime(2026, 10, 3, 21, 45, tzinfo=timezone.utc)
            with patch.object(mod, "_load_service", return_value=FakeService),                  patch.object(mod, "_schedule_instance", return_value=mod._schedule_instance("hour", now=fixed)):
                mod.submit(spec, exocortex_home=Path(td), goms_home=Path(td))

        self.assertEqual(
            calls["idempotency_key"],
            "schedule:nemocoder-apprenticeship:2026-10-03T21",
        )
        self.assertEqual(calls["provenance"]["idempotency_period"], "hour")


if __name__ == "__main__":
    unittest.main()
