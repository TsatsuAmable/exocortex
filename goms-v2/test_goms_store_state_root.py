#!/usr/bin/env python3
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import goms_store


class StateRootTests(unittest.TestCase):
    def test_deployed_code_requires_explicit_goms_home(self):
        with mock.patch.dict(os.environ, {"EXOCORTEX_GOMS_ROOT": "/tmp/release/goms-v2"}, clear=False):
            with mock.patch.dict(os.environ, {"GOMS_HOME": ""}, clear=False):
                os.environ.pop("GOMS_HOME", None)
                with self.assertRaisesRegex(RuntimeError, "GOMS_HOME is required"):
                    goms_store._state_root()

    def test_explicit_goms_home_wins_for_deployed_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {
                "EXOCORTEX_GOMS_ROOT": "/tmp/release/goms-v2",
                "GOMS_HOME": tmp,
            }, clear=False):
                self.assertEqual(goms_store._state_root(), Path(tmp).resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
