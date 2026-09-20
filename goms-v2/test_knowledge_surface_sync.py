#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

import knowledge_surface_sync as ks
from goms_store import GomsStore


class KnowledgeSurfaceSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="knowledge-surface-")
        self.root = Path(self.tmp.name) / "goms"
        self.vault = Path(self.tmp.name) / "vault"
        self.root.mkdir(); self.vault.mkdir()
        self.store = GomsStore(self.root)
        self.store.create_branch(
            "Knowledge surfaces", project="Exocortex", status="ACTIVE",
            objective="Keep projections coherent", next_action="Project state",
            unresolved=["Connect Notion"], actor="test",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_projection_has_stable_goms_identity(self):
        result = ks.project(self.root, self.vault, self.store)
        text = (self.vault / ks.PROJECTION_REL).read_text()
        self.assertIn("id: goms-projection-exocortex", text)
        self.assertIn("goms://project/Exocortex", text)
        self.assertIn("Knowledge surfaces", text)
        self.assertTrue(result["sha256"])
        self.assertTrue((self.root / ks.STATE_REL).is_file())

    def test_human_edit_is_captured_before_projection_refresh(self):
        ks.project(self.root, self.vault, self.store)
        target = self.vault / ks.PROJECTION_REL
        target.write_text(target.read_text() + "\nHuman note: Notion needs OAuth.\n")
        result = ks.sync(self.root, self.vault)
        self.assertTrue(result["inbound"]["projection_edit"]["captured"])
        entity = self.store.get_entity(result["inbound"]["projection_edit"]["entity_id"])
        self.assertEqual(entity["type"], "evidence")
        self.assertEqual(entity["status"], "CANDIDATE")
        self.assertEqual(entity["metadata"]["surface"], "obsidian")
        self.assertTrue(entity["metadata"]["requires_reconciliation"])
        self.assertNotIn("Human note: Notion needs OAuth.", target.read_text())

    def test_sync_is_idempotent_without_human_delta(self):
        first = ks.sync(self.root, self.vault)
        second = ks.sync(self.root, self.vault)
        self.assertFalse(first["inbound"]["projection_edit"]["captured"])
        self.assertFalse(second["inbound"]["projection_edit"]["captured"])
        with self.store.connect() as con:
            n = con.execute("select count(*) from entities where source like 'obsidian://%'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_new_human_note_becomes_candidate(self):
        ks.project(self.root, self.vault, self.store)
        note = self.vault / "Manfred" / "phone-sync-test.md"
        note.parent.mkdir(parents=True)
        note.write_text("Still testing\n")
        result = ks.sync(self.root, self.vault)
        notes = result["inbound"]["human_notes"]
        self.assertEqual(notes["captured"], 1)
        candidate = notes["candidates"][0]
        self.assertEqual(candidate["vault_path"], "Manfred/phone-sync-test.md")
        entity = self.store.get_entity(candidate["entity_id"])
        self.assertEqual(entity["status"], "CANDIDATE")
        self.assertEqual(entity["summary"], "Still testing\n")
        self.assertTrue(entity["metadata"]["requires_reconciliation"])

    def test_unchanged_human_note_is_not_recaptured(self):
        ks.project(self.root, self.vault, self.store)
        note = self.vault / "Human.md"
        note.write_text("One\n")
        first = ks.sync(self.root, self.vault)
        second = ks.sync(self.root, self.vault)
        self.assertEqual(first["inbound"]["human_notes"]["captured"], 1)
        self.assertEqual(second["inbound"]["human_notes"]["captured"], 0)

    def test_sync_status_page_is_generated_and_not_ingested(self):
        ks.project(self.root, self.vault, self.store)
        note = self.vault / "Phone.md"
        note.write_text("hello\n")
        result = ks.sync(self.root, self.vault)
        status = self.vault / ks.STATUS_REL
        self.assertTrue(status.is_file())
        text = status.read_text()
        self.assertIn("Exocortex knowledge-surface sync status", text)
        self.assertIn("Phone Obsidian", text)
        self.assertIn("Phone.md", text)
        self.assertIn("Unresolved Obsidian candidates in GOMS", text)
        second = ks.sync(self.root, self.vault)
        paths = [x["vault_path"] for x in second["inbound"]["human_notes"]["candidates"]]
        self.assertNotIn(ks.STATUS_REL.as_posix(), paths)

    def test_same_edit_is_not_duplicated(self):
        ks.project(self.root, self.vault, self.store)
        target = self.vault / ks.PROJECTION_REL
        target.write_text(target.read_text() + "\nHuman edit\n")
        first = ks.capture_inbound_edit(self.root, self.vault, self.store)
        second = ks.capture_inbound_edit(self.root, self.vault, self.store)
        self.assertTrue(first["captured"])
        self.assertTrue(second["captured"])
        self.assertEqual(first["entity_id"], second["entity_id"])
        with self.store.connect() as con:
            n = con.execute("select count(*) from entities where id=?", (first["entity_id"],)).fetchone()[0]
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
