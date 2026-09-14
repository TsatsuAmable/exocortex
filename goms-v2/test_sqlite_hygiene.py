#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class SQLiteHygieneTests(unittest.TestCase):
    def test_no_raw_sqlite_connection_context_managers(self):
        offenders = []
        for path in ROOT.glob("*.py"):
            if path.name == Path(__file__).name:
                continue
            text = path.read_text()
            if "with sqlite3.connect(" in text:
                offenders.append(path.name)
        self.assertEqual(offenders, [], f"raw sqlite context managers leak handles: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
