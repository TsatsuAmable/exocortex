#!/usr/bin/env python3
"""Tests for scripts/state_bundle.py (create/verify/restore roundtrip)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "state_bundle.py"


def run(args, expect_ok=True):
    proc = subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)
    if expect_ok:
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    return proc


class StateBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="statebundle-test-"))
        self.item_a = self.tmp / "goms"
        self.item_b = self.tmp / "authority"
        self.item_a.mkdir(parents=True, exist_ok=True)
        self.item_b.mkdir(parents=True, exist_ok=True)
        (self.item_a / "nested").mkdir(parents=True, exist_ok=True)
        (self.item_a / "db.sqlite3").write_bytes(b"GOMS-CANONICAL-BYTES" * 100)
        (self.item_a / "nested" / "events.jsonl").write_text(
            '{"at":"2026-09-20T00:00:00+00:00"}\n', encoding="utf-8")
        (self.item_b / "state.json").write_text('{"mode":"OBSERVE"}\n',
                                                encoding="utf-8")
        (self.item_b / "audit.jsonl").write_text('{"action":"mode_change"}\n',
                                                 encoding="utf-8")
        self.passfile = self.tmp / "passphrase"
        self.passfile.write_text("test-passphrase-not-a-secret\n", encoding="utf-8")
        self.bundle = self.tmp / "bundle.statebundle"

    def test_create_verify_restore_roundtrip(self):
        summary = json.loads(run([
            "create", "--output", str(self.bundle), "--passfile", str(self.passfile),
            "--item", f"goms_root={self.item_a}", "--item", f"hermes_authority={self.item_b}",
            "--host", "test-host", "--git-commit", "deadbeef",
        ]).stdout)
        self.assertTrue(self.bundle.exists())
        self.assertEqual(summary["host"], "test-host")
        self.assertEqual(summary["git_commit"], "deadbeef")
        self.assertEqual(summary["files"], 4)
        self.assertTrue(summary["bundle_sha256"])

        verify = json.loads(run([
            "verify", "--bundle", str(self.bundle), "--passfile", str(self.passfile),
        ]).stdout)
        self.assertTrue(verify["ok"])
        self.assertEqual(verify["files_checked"], 4)

        dest = self.tmp / "restored"
        restore = json.loads(run([
            "restore", "--bundle", str(self.bundle), "--passfile", str(self.passfile),
            "--dest-root", str(dest),
        ]).stdout)
        self.assertEqual(restore["restored"], ["goms_root", "hermes_authority"])
        self.assertEqual(
            (dest / "goms_root" / "db.sqlite3").read_bytes(),
            (self.item_a / "db.sqlite3").read_bytes())
        self.assertEqual(
            (dest / "goms_root" / "nested" / "events.jsonl").read_text(),
            (self.item_a / "nested" / "events.jsonl").read_text())
        self.assertEqual(
            (dest / "hermes_authority" / "state.json").read_text(),
            '{"mode":"OBSERVE"}\n')

    def test_create_excludes_archive_tier_directories(self):
        for name in ("raw", "deployments", "cold", "quarantine", "storage-governance"):
            target = self.item_a / name
            target.mkdir(parents=True, exist_ok=True)
            (target / "large.bin").write_bytes((name.encode() + b"-") * 100)
        summary = json.loads(run([
            "create", "--output", str(self.bundle),
            "--passfile", str(self.passfile),
            "--item", f"goms_root={self.item_a}",
            "--item", f"hermes_authority={self.item_b}",
            "--host", "test-host", "--git-commit", "deadbeef",
        ]).stdout)
        self.assertEqual(summary["files"], 4)
        dest = self.tmp / "archive-tier-restored"
        run(["restore", "--bundle", str(self.bundle),
             "--passfile", str(self.passfile), "--dest-root", str(dest)])
        for name in ("raw", "deployments", "cold", "quarantine", "storage-governance"):
            self.assertFalse((dest / "goms_root" / name).exists())

    def test_create_excludes_sqlite_sidecars(self):
        (self.item_a / "state.db-wal").write_bytes(b"WAL-BYTES")
        (self.item_a / "state.db-shm").write_bytes(b"SHM-BYTES")
        try:
            summary = json.loads(run([
                "create", "--output", str(self.bundle),
                "--passfile", str(self.passfile),
                "--item", f"goms_root={self.item_a}",
                "--item", f"hermes_authority={self.item_b}",
                "--host", "test-host", "--git-commit", "deadbeef",
            ]).stdout)
            self.assertEqual(summary["files"], 4)
            verify = json.loads(run([
                "verify", "--bundle", str(self.bundle),
                "--passfile", str(self.passfile),
            ]).stdout)
            self.assertTrue(verify["ok"])
        finally:
            (self.item_a / "state.db-wal").unlink(missing_ok=True)
            (self.item_a / "state.db-shm").unlink(missing_ok=True)

    def test_create_skips_unstreamable_special_files(self):
        import socket as _socket
        sock_path = self.item_a / "gateway.sock"
        sock = _socket.socket(_socket.AF_UNIX)
        sock.bind(str(sock_path))
        try:
            summary = json.loads(run([
                "create", "--output", str(self.bundle),
                "--passfile", str(self.passfile),
                "--item", f"goms_root={self.item_a}",
                "--item", f"hermes_authority={self.item_b}",
                "--host", "test-host", "--git-commit", "deadbeef",
            ]).stdout)
            self.assertEqual(summary["files"], 4)
            self.assertEqual(summary["skipped_specials"], 1)
            verify = json.loads(run([
                "verify", "--bundle", str(self.bundle),
                "--passfile", str(self.passfile),
            ]).stdout)
            self.assertTrue(verify["ok"])
        finally:
            sock.close()
            sock_path.unlink(missing_ok=True)

    def test_verify_detects_tampering(self):
        run(["create", "--output", str(self.bundle), "--passfile", str(self.passfile),
             "--item", f"goms_root={self.item_a}"])
        original = self.bundle.read_bytes()
        # Encrypt with a different plaintext tail: same passphrase, different bytes.
        tampered = self.tmp / "tampered.statebundle"
        tampered.write_bytes(original[:-4] + b"xxxx")
        proc = run(["verify", "--bundle", str(tampered),
                    "--passfile", str(self.passfile)], expect_ok=False)
        self.assertNotEqual(proc.returncode, 0)

    def test_verify_rejects_wrong_passphrase(self):
        run(["create", "--output", str(self.bundle), "--passfile", str(self.passfile),
             "--item", f"goms_root={self.item_a}"])
        other = self.tmp / "other-passphrase"
        other.write_text("different-passphrase\n", encoding="utf-8")
        proc = run(["verify", "--bundle", str(self.bundle),
                    "--passfile", str(other)], expect_ok=False)
        self.assertNotEqual(proc.returncode, 0)

    def test_restore_refuses_existing_destination_without_force(self):
        run(["create", "--output", str(self.bundle), "--passfile", str(self.passfile),
             "--item", f"goms_root={self.item_a}"])
        dest = self.tmp / "restored"
        (dest / "goms_root").mkdir(parents=True)
        proc = run(["restore", "--bundle", str(self.bundle),
                    "--passfile", str(self.passfile), "--dest-root", str(dest)],
                   expect_ok=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--force", proc.stderr + proc.stdout)

    def test_restore_overwrites_with_force(self):
        run(["create", "--output", str(self.bundle), "--passfile", str(self.passfile),
             "--item", f"goms_root={self.item_a}"])
        dest = self.tmp / "restored"
        dest.mkdir()
        (dest / "goms_root").mkdir()
        (dest / "goms_root" / "db.sqlite3").write_bytes(b"stale")
        run(["restore", "--bundle", str(self.bundle), "--passfile", str(self.passfile),
             "--dest-root", str(dest), "--force"])
        self.assertEqual((dest / "goms_root" / "db.sqlite3").read_bytes(),
                         (self.item_a / "db.sqlite3").read_bytes())

    def test_create_fails_when_no_state_exists(self):
        proc = run(["create", "--output", str(self.bundle),
                    "--passfile", str(self.passfile),
                    "--item", "nothing=/definitely/not/here"],
                   expect_ok=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no state files", proc.stderr + proc.stdout)

    def test_bundle_is_not_plaintext_tar(self):
        run(["create", "--output", str(self.bundle), "--passfile", str(self.passfile),
             "--item", f"goms_root={self.item_a}"])
        head = self.bundle.read_bytes()[:300]
        self.assertNotIn(b"GOMS-CANONICAL-BYTES", head)
        self.assertNotIn(b"db.sqlite3", head)


if __name__ == "__main__":
    unittest.main(verbosity=2)