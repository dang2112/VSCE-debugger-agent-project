import difflib
import unittest
from tools.patches import apply_diff


class PatchValidationTests(unittest.TestCase):
    def test_valid_multifile_and_crlf(self):
        a = 'def ratio(a, b):\r\n    return a // b\r\n'
        diff = ''.join(difflib.unified_diff(a.replace('\r\n','\n').splitlines(True),
            a.replace('\r\n','\n').replace('//', '/').splitlines(True), fromfile='a/calc.py', tofile='b/calc.py'))
        self.assertEqual(apply_diff(diff, {'calc.py': a})['calc.py'], a.replace('//', '/'))

    def test_rejects_traversal_test_changes_and_bad_context(self):
        for path in ('../calc.py', 'tests/test_calc.py', 'conftest.py', 'pyproject.toml'):
            diff = f'--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n'
            with self.subTest(path=path), self.assertRaises(ValueError):
                apply_diff(diff, {path: 'old\n'})
        with self.assertRaisesRegex(ValueError, 'context mismatch'):
            apply_diff('--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-wrong\n+new\n', {'calc.py': 'old\n'})
        with self.assertRaises(ValueError):
            apply_diff('--- a/calc.py\n+++ b/calc.py\n@@ -1,3 +1 @@\n-old\n+new\n', {'calc.py': 'old\n'})

    def test_no_newline_marker_and_insert(self):
        diff = '--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n'
        self.assertEqual(apply_diff(diff, {'calc.py': 'old'})['calc.py'], 'new')
        insert = '--- a/calc.py\n+++ b/calc.py\n@@ -0,0 +1 @@\n+# comment\n'
        self.assertEqual(apply_diff(insert, {'calc.py': 'old\n'})['calc.py'], '# comment\nold\n')
