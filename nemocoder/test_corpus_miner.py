#!/usr/bin/env python3
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("corpus_miner_under_test", HERE / "corpus_miner.py")
miner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(miner)

def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()

class CorpusMinerTests(unittest.TestCase):
    def make_repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        git(repo, "remote", "add", "origin", "https://github.com/example/project.git")
        (repo / "base.txt").write_text("base\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "initial")
        git(repo, "checkout", "-qb", "feature")
        (repo / "feature.txt").write_text("feature\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "feature work")
        git(repo, "checkout", "-q", "-")
        git(repo, "merge", "--no-ff", "feature", "-m", "Merge pull request #42 from example/feature\n\nfix bounded thing")
        return repo

    def test_collects_provenance_without_patches(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.make_repo(Path(td))
            rows = miner.collect(repo, max_records=10)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["pr_number"], 42)
            self.assertIn("fix bounded thing", row["task_text"])
            self.assertEqual(row["admission"], "metadata_admitted")
            self.assertEqual(row["changed_paths"][0]["path"], "feature.txt")
            self.assertNotIn("patch", row)

    def test_secret_like_task_text_is_quarantined(self):
        text, admission = miner._normalize_task_text(
            "Merge pull request #7\n\napi_key=ABCDEFGHIJKLMNOPQRSTUV"
        )
        self.assertIsNone(text)
        self.assertEqual(admission, "quarantined_secret_pattern")

    def test_manifest_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.make_repo(Path(td))
            rows = miner.collect(repo, max_records=10)
            out1, out2 = Path(td) / "one.jsonl", Path(td) / "two.jsonl"
            head = git(repo, "rev-parse", "HEAD")
            m1 = miner.write_manifest(rows, out1, repository="x", head=head)
            m2 = miner.write_manifest(rows, out2, repository="x", head=head)
            self.assertEqual(m1["records_sha256"], m2["records_sha256"])
            self.assertEqual(out1.read_text(), out2.read_text())
            self.assertEqual(json.loads(out1.read_text().splitlines()[0])["pr_number"], 42)

if __name__ == "__main__":
    unittest.main()
