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
        self.assertTrue(result["inbound"]["captured"])
        entity = self.store.get_entity(result["inbound"]["entity_id"])
        self.assertEqual(entity["type"], "evidence")
        self.assertEqual(entity["status"], "CANDIDATE")
        self.assertEqual(entity["metadata"]["surface"], "obsidian")
        self.assertTrue(entity["metadata"]["requires_reconciliation"])
        self.assertNotIn("Human note: Notion needs OAuth.", target.read_text())

    def test_sync_is_idempotent_without_human_delta(self):
        first = ks.sync(self.root, self.vault)
        second = ks.sync(self.root, self.vault)
        self.assertFalse(first["inbound"]["captured"])
        self.assertFalse(second["inbound"]["captured"])
        with self.store.connect() as con:
            n = con.execute("select count(*) from entities where source like 'obsidian://%'").fetchone()[0]
        self.assertEqual(n, 0)

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
