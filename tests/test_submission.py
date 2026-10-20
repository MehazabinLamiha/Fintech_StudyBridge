"""The submission zip leaves out macOS and Python junk, the git folder and local runtime files."""
import unittest

from tools.make_submission import ROOT, files, keep


class TestSubmissionZip(unittest.TestCase):
    def test_junk_is_left_out(self):
        for junk in ("__MACOSX/x/._run.py", ".DS_Store", "studybridge/.DS_Store", "studybridge/__pycache__/a.pyc",
                     "tools/x.pyc", "._README.md", ".git/config", "var/audit.jsonl"):
            self.assertFalse(keep(junk), junk)
        for good in ("README.md", "studybridge/agent.py", "evidence/README.md", "data/sample_profile.json"):
            self.assertTrue(keep(good), good)

    @unittest.skipUnless((ROOT / ".git").exists(), "needs the git repository")
    def test_the_file_list_has_the_code_and_no_junk(self):
        names = files()
        self.assertIn("studybridge/agent.py", names)
        self.assertIn("tools/make_submission.py", names)
        self.assertTrue(all(keep(n) for n in names))


if __name__ == "__main__":
    unittest.main()
