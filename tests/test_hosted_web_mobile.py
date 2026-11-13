"""Source-level regression guards for hosted mobile feedback and session hygiene."""

import unittest
from importlib.resources import files


class HostedMobileExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = files("goreecloud_changelogs").joinpath("hosted_web")
        cls.html = root.joinpath("index.html").read_text(encoding="utf-8")
        cls.css = root.joinpath("app.css").read_text(encoding="utf-8")
        cls.js = root.joinpath("app.js").read_text(encoding="utf-8")

    def test_singular_and_plural_release_counts(self):
        self.assertIn('count === 1 ? "change" : "changes"', self.js)
        self.assertNotIn('data.entries.length + " changes on this page"', self.js)

    def test_inline_save_status_is_accessible_and_separate_from_history_status(self):
        self.assertIn('id="save-status"', self.html)
        self.assertIn('aria-live="polite" aria-atomic="true"', self.html)
        self.assertIn('setSaveStatus("Change saved to the server.", "success")', self.js)
        self.assertIn('setSaveStatus(error.message || "Unable to save the change.", "error")', self.js)
        self.assertIn('id="save-submit"', self.html)
        self.assertIn('$("save-submit").disabled = true', self.js)

    def test_logout_clears_drafts_and_mobile_workspace_state(self):
        self.assertIn('$("create-form").reset();', self.js)
        self.assertIn('$("filters").reset();', self.js)
        self.assertIn('document.body.classList.remove("is-authenticated")', self.js)
        self.assertIn('document.body.classList.add("is-authenticated")', self.js)
        self.assertIn('initialEpoch === sessionEpoch', self.js)

    def test_admin_mobile_shortcut_respects_role_and_touch_target(self):
        self.assertIn('id="jump-create"', self.html)
        self.assertIn('$("jump-create").hidden = role !== "admin";', self.js)
        self.assertIn('.is-authenticated .masthead h1', self.css)
        self.assertIn('min-height:46px', self.css)


if __name__ == "__main__":
    unittest.main()
