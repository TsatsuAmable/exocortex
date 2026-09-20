#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_profile


class ProfileInstallTests(unittest.TestCase):
    def test_install_replaces_skill_surface_and_preserves_backup(self):
        manifest = install_profile.load_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile"
            generic = root / "generic"
            skills = profile / "skills"
            skills.mkdir(parents=True)
            (profile / "SOUL.md").write_text("old soul\n")
            (profile / "config.yaml").write_text(
                "agent:\n  personalities:\n    exocortex: old\n"
                "display:\n  personality: exocortex\n"
            )
            extra = skills / "creative" / "noise"
            extra.mkdir(parents=True)
            (extra / "SKILL.md").write_text(
                "---\nname: noise\ndescription: noise\n---\n"
            )

            for rel in manifest["generic_skills"]:
                dst = generic / rel
                dst.mkdir(parents=True, exist_ok=True)
                name = dst.name
                (dst / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: test\n"
                    "platforms: [linux, macos, windows]\n---\n"
                )

            backup = install_profile.install(profile, generic)
            self.assertTrue(backup.is_dir())
            self.assertTrue((backup / "SOUL.md").is_file())
            self.assertFalse((skills / "creative" / "noise").exists())
            self.assertEqual(
                install_profile.current_skill_paths(profile),
                install_profile.desired_paths(manifest),
            )
            self.assertEqual(
                (profile / "SOUL.md").read_text(),
                install_profile.SOUL.read_text(),
            )
            self.assertFalse((profile / ".skills_prompt_snapshot.json").exists())
            self.assertEqual(install_profile.check(profile, generic), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
