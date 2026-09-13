#!/usr/bin/env python3
import unittest

from distillation_policy import (
    ALLOWED_KINDS,
    build_extraction_prompt,
    build_validation_prompt,
    canonicalize_kind,
    score_gold_case,
)


class DistillationPolicyTests(unittest.TestCase):
    def test_validator_kind_alias_is_canonicalized(self):
        self.assertEqual(canonicalize_kind("requirement", "question"), "constraint")
        self.assertEqual(canonicalize_kind("objective", "question"), "objective")
        self.assertEqual(canonicalize_kind("invented-kind", "question"), "question")

    def test_prompts_constrain_output_to_canonical_taxonomy(self):
        extraction = build_extraction_prompt()
        validation = build_validation_prompt()
        for kind in ALLOWED_KINDS:
            self.assertIn(kind, extraction)
            self.assertIn(kind, validation)
        self.assertIn("every distinct durable item", extraction)
        self.assertIn("short unresolved question", extraction)

    def test_negative_gold_case_needs_no_keywords(self):
        gold = {"should_extract": False, "note": "transient request"}
        result = score_gold_case(gold, survives=False, validated_kind=None, text="")
        self.assertTrue(result["kind_ok"])
        self.assertEqual(result["keyword_fraction"], 1.0)

    def test_positive_case_uses_canonicalized_validator_kind(self):
        gold = {
            "should_extract": True,
            "acceptable_kinds": ["constraint"],
            "object_keywords": ["meaning", "ontology"],
        }
        result = score_gold_case(
            gold,
            survives=True,
            validated_kind="requirement",
            fallback_kind="question",
            text="ontology must evolve and embed meaning",
        )
        self.assertTrue(result["kind_ok"])
        self.assertEqual(result["keyword_fraction"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

# lifecycle regression tests
from datetime import datetime, timedelta, timezone
from distillation_policy import run_is_stale


class DistillationLifecycleTests(unittest.TestCase):
    def test_old_running_run_is_stale(self):
        now = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
        started = (now - timedelta(hours=2)).isoformat()
        self.assertTrue(run_is_stale("RUNNING", started, now=now, max_age_seconds=900))

    def test_recent_or_completed_run_is_not_stale(self):
        now = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
        recent = (now - timedelta(minutes=2)).isoformat()
        old = (now - timedelta(hours=2)).isoformat()
        self.assertFalse(run_is_stale("RUNNING", recent, now=now, max_age_seconds=900))
        self.assertFalse(run_is_stale("SUCCESS", old, now=now, max_age_seconds=900))


class DistillationReaperTests(unittest.TestCase):
    def test_reaper_marks_only_stale_running_rows_abandoned(self):
        import sqlite3
        from distillation_policy import reap_stale_runs
        now = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
        old = (now - timedelta(hours=2)).isoformat()
        recent = (now - timedelta(minutes=2)).isoformat()
        c = sqlite3.connect(":memory:")
        c.execute("create table distillation_runs(id text,status text,started_at text,completed_at text,metadata text)")
        c.executemany("insert into distillation_runs values(?,?,?,?,?)", [
            ("old", "RUNNING", old, None, "{}"),
            ("recent", "RUNNING", recent, None, "{}"),
            ("done", "SUCCESS", old, old, "{}"),
        ])
        changed = reap_stale_runs(c, now=now, max_age_seconds=900)
        self.assertEqual(changed, ["old"])
        self.assertEqual(c.execute("select status from distillation_runs where id='old'").fetchone()[0], "ABANDONED")
        self.assertEqual(c.execute("select status from distillation_runs where id='recent'").fetchone()[0], "RUNNING")
