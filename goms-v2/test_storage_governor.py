#!/usr/bin/env python3
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import storage_governor as sg
from goms_store import GomsStore


def write_event(path: Path, event: dict, previous_line_hash=None):
    payload = dict(event)
    payload["prev_line_sha256"] = previous_line_hash
    payload["event_sha256"] = sg.ledger_event_sha(payload)
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    with path.open("ab") as handle:
        handle.write(raw + b"\n")
    return sg.sha256_bytes(raw)


class StorageGovernorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="goms-storage-")
        self.root = Path(self.tmp.name)
        (self.root / "deployments").mkdir()
        (self.root / "raw").mkdir()
        (self.root / "events.jsonl").touch()
        (self.root / "goms.sqlite3").write_bytes(b"db")
        self.policy = dict(sg.DEFAULT_POLICY)
        self.policy["deployment_keep_latest"] = 2
        self.policy["protected_deployment_patterns"] = ["*anchor*"]
        self.policy["ledger_rotate_bytes"] = 1

    def tearDown(self):
        self.tmp.cleanup()

    def deployment(self, name, payload=b"x"):
        path = self.root / "deployments" / name
        path.mkdir()
        (path / "goms.sqlite3").write_bytes(payload)
        return path

    def test_retention_keeps_latest_and_explicit_anchor(self):
        for name in ["001-old", "002-anchor", "003-mid", "004-new", "005-latest"]:
            self.deployment(name, name.encode())
        actions, protected = sg.deployment_actions(self.root, self.policy)
        removed = {Path(x["path"]).name for x in actions}
        kept = {x["name"] for x in protected}
        self.assertEqual(removed, {"001-old", "003-mid"})
        self.assertEqual(kept, {"002-anchor", "004-new", "005-latest"})

    def test_raw_duplicate_requires_exact_sha256(self):
        a = self.root / "raw" / "a.json"
        b = self.root / "raw" / "nested" / "b.json"
        c = self.root / "raw" / "c.json"
        b.parent.mkdir()
        a.write_bytes(b"same")
        b.write_bytes(b"same")
        c.write_bytes(b"diff")
        actions, stats = sg.raw_duplicate_actions(self.root, self.policy)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["sha256"], sg.sha256_file(a))
        self.assertEqual(stats["duplicate_groups"], 1)
        self.assertEqual(stats["duplicate_extra_files"], 1)
        self.assertTrue(Path(actions[0]["canonical_path"]).exists())

    def test_plan_is_dry_run_and_deterministic_in_actions(self):
        self.deployment("001-old", b"old")
        self.deployment("002-new", b"new")
        self.deployment("003-latest", b"latest")
        write_event(
            self.root / "events.jsonl",
            {"op": "plan-fixture", "event_id": "plan", "at": sg.utc_now()},
        )
        plan = sg.build_plan(self.root, self.policy)
        self.assertTrue((self.root / "deployments" / "001-old").exists())
        kinds = [x["kind"] for x in plan["actions"]]
        self.assertIn("remove_deployment", kinds)
        self.assertIn("rotate_ledger", kinds)

    def test_apply_requires_fresh_verified_continuity_proof(self):
        self.deployment("001-old", b"old")
        self.deployment("002-new", b"new")
        self.deployment("003-latest", b"latest")
        plan = sg.build_plan(self.root, self.policy)
        proof = self.root / "missing-proof.json"
        with self.assertRaises(FileNotFoundError):
            sg.apply_plan(self.root, self.policy, plan, proof)

    def make_proof(self):
        bundle = self.root / "bundle.enc"
        bundle.write_bytes(b"verified-bundle")
        proof = {
            "schema_version": 1,
            "kind": "goms_storage_continuity_proof",
            "bundle": str(bundle),
            "bundle_sha256": sg.sha256_file(bundle),
            "bundle_created_at": sg.utc_now(),
            "files_checked": 1,
            "verified": True,
            "verified_at": sg.utc_now(),
        }
        path = self.root / "proof.json"
        path.write_text(json.dumps(proof))
        return path

    def test_apply_removes_only_planned_redundancy_and_is_idempotent(self):
        self.deployment("001-old", b"old")
        self.deployment("002-new", b"new")
        self.deployment("003-latest", b"latest")
        dup_a = self.root / "raw" / "a"
        dup_b = self.root / "raw" / "b"
        dup_a.write_bytes(b"dupe")
        dup_b.write_bytes(b"dupe")
        plan = sg.build_plan(self.root, self.policy)
        proof = self.make_proof()
        report = sg.apply_plan(self.root, self.policy, plan, proof, False)
        self.assertFalse((self.root / "deployments" / "001-old").exists())
        self.assertEqual(sum(p.exists() for p in [dup_a, dup_b]), 1)
        self.assertGreater(report["reclaimed_bytes"], 0)
        next_plan = sg.build_plan(self.root, self.policy)
        self.assertFalse(any(a["kind"] in {"remove_deployment", "remove_raw_duplicate"}
                             for a in next_plan["actions"]))

    def test_ledger_verify_and_rotation_preserve_cross_archive_anchor(self):
        ledger = self.root / "events.jsonl"
        prev = write_event(ledger, {"op": "one", "event_id": "e1", "at": sg.utc_now()})
        prev = write_event(ledger, {"op": "two", "event_id": "e2", "at": sg.utc_now()}, prev)
        action = {
            "kind": "rotate_ledger",
            "path": str(ledger),
            "bytes": ledger.stat().st_size,
            "sha256": sg.sha256_file(ledger),
        }
        result = sg.rotate_ledger(self.root, action)
        archive_manifest = Path(result["manifest"])
        self.assertTrue(archive_manifest.exists())
        self.assertTrue(sg.verify_archive_manifest(self.root, archive_manifest)["ok"])
        current = sg.verify_ledger(ledger, expected_first_prev=prev)
        self.assertTrue(current["ok"])
        self.assertEqual(current["lines"], 1)

    def test_goms_store_append_survives_storage_governor_rotation(self):
        store_root = self.root / "real-store"
        store = GomsStore(store_root)
        store.append_event({"op": "before", "actor": "test"})
        self.assertTrue((store_root / "events.lock").exists())
        ledger = store_root / "events.jsonl"
        before = sg.verify_ledger(ledger)
        self.assertTrue(before["ok"])
        action = {
            "kind": "rotate_ledger",
            "path": str(ledger),
            "bytes": ledger.stat().st_size,
            "sha256": sg.sha256_file(ledger),
        }
        sg.rotate_ledger(store_root, action)
        store.append_event({"op": "after", "actor": "test"})
        current = sg.verify_ledger(
            ledger, expected_first_prev=before["last_line_sha256"]
        )
        self.assertTrue(current["ok"])
        self.assertEqual(current["lines"], 2)

    def test_verify_ledger_accepts_legacy_head_and_chain_anchors_to_it(self):
        ledger = self.root / "events.jsonl"
        legacy_lines = []
        with ledger.open("ab") as handle:
            for op in ("seed-branch", "seed-checkpoint"):
                raw = json.dumps(
                    {"op": op, "event_id": f"legacy-{op}", "at": sg.utc_now()},
                    sort_keys=True, ensure_ascii=False,
                ).encode()
                handle.write(raw + b"\n")
                legacy_lines.append(raw)
        anchor = sg.sha256_bytes(legacy_lines[-1])
        prev = write_event(ledger, {"op": "one", "event_id": "e1", "at": sg.utc_now()}, anchor)
        prev = write_event(ledger, {"op": "two", "event_id": "e2", "at": sg.utc_now()}, prev)
        result = sg.verify_ledger(ledger)
        self.assertTrue(result["ok"])
        self.assertEqual(result["lines"], 4)
        self.assertEqual(result["legacy_lines"], 2)
        self.assertEqual(result["first_prev_line_sha256"], anchor)
        self.assertEqual(result["last_line_sha256"], prev)
        self.assertTrue(sg.verify_ledger(ledger, expected_first_prev=anchor)["ok"])

    def test_verify_ledger_rejects_legacy_record_after_chain_starts(self):
        ledger = self.root / "events.jsonl"
        write_event(ledger, {"op": "one", "event_id": "e1", "at": sg.utc_now()})
        with ledger.open("ab") as handle:
            handle.write(json.dumps(
                {"op": "legacy-mid", "event_id": "legacy-mid", "at": sg.utc_now()},
                sort_keys=True, ensure_ascii=False,
            ).encode() + b"\n")
        result = sg.verify_ledger(ledger)
        self.assertFalse(result["ok"])
        self.assertIn("prev_line_mismatch", {f["problem"] for f in result["failures"]})

    def test_verify_ledger_rejects_partial_chain_metadata_in_legacy_head(self):
        ledger = self.root / "events.jsonl"
        with ledger.open("ab") as handle:
            payload = {
                "op": "broken-head", "event_id": "broken-head", "at": sg.utc_now(),
                "prev_line_sha256": sg.sha256_bytes(b"anchor"),
            }
            handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode() + b"\n")
        result = sg.verify_ledger(ledger)
        # A head record carrying chain metadata is not a legacy record: it is a
        # malformed chained record and must fail closed, never be absorbed into
        # the legacy provenance head.
        self.assertFalse(result["ok"])
        self.assertEqual(result["legacy_lines"], 0)
        self.assertIn("event_sha_mismatch", {f["problem"] for f in result["failures"]})

    def test_rotation_of_legacy_headed_ledger_preserves_cross_archive_anchor(self):
        ledger = self.root / "events.jsonl"
        with ledger.open("ab") as handle:
            raw = json.dumps(
                {"op": "legacy-seed", "event_id": "legacy-seed", "at": sg.utc_now()},
                sort_keys=True, ensure_ascii=False,
            ).encode()
            handle.write(raw + b"\n")
        prev = write_event(ledger, {"op": "one", "event_id": "e1", "at": sg.utc_now()},
                           sg.sha256_bytes(raw))
        action = {
            "kind": "rotate_ledger",
            "path": str(ledger),
            "bytes": ledger.stat().st_size,
            "sha256": sg.sha256_file(ledger),
        }
        result = sg.rotate_ledger(self.root, action)
        manifest = Path(result["manifest"])
        self.assertTrue(sg.verify_archive_manifest(self.root, manifest)["ok"])
        current = sg.verify_ledger(ledger, expected_first_prev=prev)
        self.assertTrue(current["ok"])
        self.assertEqual(current["lines"], 1)
        self.assertEqual(current["legacy_lines"], 0)

    def test_preflight_detects_changed_deployment_before_any_apply(self):
        old = self.deployment("001-old", b"old")
        self.deployment("002-new", b"new")
        self.deployment("003-latest", b"latest")
        plan = sg.build_plan(self.root, self.policy)
        (old / "extra").write_bytes(b"changed")
        proof = self.make_proof()
        with self.assertRaisesRegex(ValueError, "deployment_changed"):
            sg.apply_plan(self.root, self.policy, plan, proof, False)
        self.assertTrue(old.exists())

    def test_create_continuity_proof_binds_verified_bundle(self):
        bundle = self.root / "state.enc"
        bundle.write_bytes(b"state")
        summary = self.root / "summary.json"
        summary.write_text(json.dumps({
            "bundle": str(bundle),
            "bundle_sha256": sg.sha256_file(bundle),
            "created_at": sg.utc_now(),
        }))
        verify = self.root / "verify.json"
        verify.write_text(json.dumps({
            "bundle": str(bundle),
            "ok": True,
            "files_checked": 3,
        }))
        proof = sg.create_continuity_proof(summary, verify)
        self.assertTrue(proof["verified"])
        self.assertEqual(proof["bundle_sha256"], sg.sha256_file(bundle))


if __name__ == "__main__":
    unittest.main(verbosity=2)
