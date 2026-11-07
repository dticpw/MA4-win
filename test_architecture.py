import unittest
from tools.check_architecture import inspect, inspect_source


class ArchitectureTest(unittest.TestCase):
    def test_project_policy_obeys_dependency_boundary(self):
        self.assertEqual(inspect(), [])

    def test_reverse_dependency_and_io_imports_are_rejected_even_when_nested_or_aliased(self):
        for source in ("from controllers import Controllers", "import hub as h", "import pathlib",
                       "from . import runtime", "def rule():\n    import subprocess as run"):
            with self.subTest(source=source):
                result = inspect_source(source)
                self.assertEqual(result[0]["rule"], "policy-import")
                self.assertGreaterEqual(result[0]["line"], 1)
                self.assertIn("参数传入", result[0]["message"])

    def test_builtin_aliases_and_dynamic_execution_cannot_silently_bypass_check(self):
        for source in ("reader = open", "module = __import__('time')", "exec('import os')",
                       "eval('open')", "lookup = globals", "getattr(obj, 'read')"):
            with self.subTest(source=source):
                self.assertEqual(inspect_source(source)[0]["rule"], "policy-effect")

    def test_allowed_pure_helpers_and_comments_are_not_false_positives(self):
        self.assertEqual(inspect_source('import math\nfrom dataclasses import dataclass\n'
                                       '# open is forbidden, but describing it is fine\n'
                                       'def rule(now):\n    return math.isfinite(now)\n'), [])

    def test_invalid_python_fails_with_location(self):
        result = inspect_source('def broken(')
        self.assertEqual((result[0]["rule"], result[0]["line"]), ("syntax", 1))
