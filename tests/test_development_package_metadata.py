"""Release-integrity check for package maturity, independent of v1.0 tag."""
import re
import unittest
from pathlib import Path


class DevelopmentPackageMetadataTests(unittest.TestCase):
    def test_unreleased_package_must_not_claim_stable_classifier(self):
        path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        source = path.read_text(encoding="utf-8")
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', source)
        self.assertIsNotNone(match, "Package must declare a version")
        version = match.group(1)
        prerelease = bool(re.search(r"(?:\.dev\d*|a\d+|b\d+|rc\d+)", version))
        if prerelease:
            self.assertNotIn("Development Status :: 5 - Production/Stable", source,
                             "Pre-release package must not claim entire codebase is stable")
            self.assertRegex(source, r"Development Status :: [234] - ",
                             "Pre-release package should identify development maturity")

    def test_public_version_and_hosted_preview_are_distinguished(self):
        source = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
        self.assertIn('experimental hosted-server development preview', source)


if __name__ == "__main__":
    unittest.main()
