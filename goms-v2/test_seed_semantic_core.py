#!/usr/bin/env python3
from contextlib import closing
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class SeedSemanticCoreTests(unittest.TestCase):
    def test_seed_creates_entities_for_all_assertion_endpoints(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "Library/Application Support/Aineko/GOMS"
            runtime.mkdir(parents=True)
            db = runtime / "goms.sqlite3"
            with closing(sqlite3.connect(db)) as c, c:
                c.executescript((ROOT / "schema.sql").read_text())
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [os.sys.executable, str(ROOT / "seed_semantic_core.py")],
                cwd=ROOT, env=env, text=True, capture_output=True,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr)
            with closing(sqlite3.connect(db)) as c:
                dangling = c.execute("""
                  select a.id,a.subject_id,a.object_id
                  from semantic_assertions a
                  left join entities s on s.id=a.subject_id
                  left join entities o on o.id=a.object_id
                  where s.id is null or (a.object_id is not null and o.id is null)
                """).fetchall()
            self.assertEqual(dangling, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
