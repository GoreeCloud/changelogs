"""Cross-client GoreeCloud UI dark-role bridge source contract."""
import unittest
from importlib.resources import files
from pathlib import Path


class DarkRoleBridgeTests(unittest.TestCase):
    def test_hosted_page_uses_explicit_verified_dark_role_bridge(self):
        root = files("goreecloud_changelogs").joinpath("hosted_web")
        css = root.joinpath("app.css").read_text(encoding="utf-8")
        html = root.joinpath("index.html").read_text(encoding="utf-8")
        self.assertIn('data-gc-theme="dark"', html)
        self.assertIn("9e51ef78196e41bb7e402014dac482aff5e65941", css)
        values = {
            "--gc-canvas": "#0D121D", "--gc-surface": "#171D2A",
            "--gc-surface-tonal": "#252D3D", "--gc-text": "#F2F4FB",
            "--gc-text-soft": "#CED5E5", "--gc-outline-soft": "#505B70",
            "--gc-brand": "#BFB8FF", "--gc-on-brand": "#272057",
            "--gc-focus-ring": "#BFCBFF",
        }
        for name, value in values.items():
            self.assertIn(name + ":" + value, css)
        self.assertIn("--canvas:var(--gc-canvas)", css)
        self.assertIn("--accent:var(--gc-brand)", css)
        self.assertNotIn("@import", css)

    def test_native_hosted_preview_matches_verified_dark_palette(self):
        native = (Path(__file__).resolve().parents[1] / "android-app" / "app"
                  / "src" / "main" / "java" / "com" / "goreecloud" /
                  "changelogs" / "HostedActivity.java").read_text(encoding="utf-8")
        for value in ("Color.rgb(13, 18, 29)", "Color.rgb(23, 29, 42)",
                      "Color.rgb(242, 244, 251)", "Color.rgb(206, 213, 229)",
                      "Color.rgb(191, 184, 255)"):
            self.assertIn(value, native)


if __name__ == "__main__":
    unittest.main()
