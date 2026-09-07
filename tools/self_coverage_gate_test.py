# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Apache License Version 2.0 which is available at
# https://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
# *******************************************************************************
"""Tests for the repository's own coverage gate."""
# Test modules: docstrings on every test method add nothing, tests exercise
# private helpers on purpose, TemporaryDirectory is closed in tearDown, and setUp
# fixtures are attributes.
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access,consider-using-with
# pylint: disable=too-many-instance-attributes

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import self_coverage_gate as gate

LCOV = (
    "SF:score_coverage/a.py\nLF:10\nLH:8\nBRF:4\nBRH:2\nend_of_record\n"
    "SF:score_coverage/a.py\nLF:10\nLH:9\nBRF:4\nBRH:3\nend_of_record\n"  # same file from a second test
    "SF:score_coverage/tests/a_test.py\nLF:50\nLH:50\nBRF:0\nBRH:0\nend_of_record\n"  # excluded
    "SF:external/other.py\nLF:5\nLH:0\nend_of_record\n"  # out of scope
    "SF:score_coverage/b.py\nLF:10\nLH:0\nBRF:2\nBRH:0\nend_of_record\n"
)


class ParseLcovTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lcov = Path(self.tmp.name) / "lcov.dat"
        self.lcov.write_text(LCOV, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_scope_and_aggregation(self):
        totals = gate.parse_lcov(self.lcov)
        self.assertEqual([f.path for f in totals.files], ["score_coverage/a.py", "score_coverage/b.py"])
        a = totals.files[0]
        self.assertEqual((a.lines_found, a.lines_hit, a.branches_found, a.branches_hit), (20, 17, 8, 5))
        self.assertEqual((totals.lines_found, totals.lines_hit), (30, 17))
        self.assertEqual((totals.branches_found, totals.branches_hit), (10, 5))

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            gate.parse_lcov(self.lcov.parent / "missing")

    def test_corrupt_record(self):
        self.lcov.write_text("SF:score_coverage/a.py\nLF:1\nLH:2\nend_of_record\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            gate.parse_lcov(self.lcov)


class EvaluateTest(unittest.TestCase):
    def _totals(self, lh, lf, bh, bf):
        return gate.Totals(files=[gate.FileCoverage("score_coverage/x.py", lf, lh, bf, bh)])

    def test_pass_and_fail(self):
        self.assertEqual(gate.evaluate(self._totals(17, 30, 5, 10), 50, 50), [])
        problems = gate.evaluate(self._totals(17, 30, 5, 10), 60, 51)
        self.assertEqual(len(problems), 2)
        self.assertIn("line coverage 56.67%", problems[0])
        self.assertIn("branch coverage 50.00%", problems[1])

    def test_no_data_is_a_failure(self):
        self.assertEqual(len(gate.evaluate(gate.Totals(), 0, 0)), 2)


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "lcov.dat").write_text(LCOV, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = gate.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_exit_codes_and_summary(self):
        lcov = str(self.root / "lcov.dat")
        rc, out, _ = self._main(["--lcov", lcov, "--min-lines", "50", "--min-branches", "50"])
        self.assertEqual(rc, 0)
        self.assertIn("TOTAL", out)
        self.assertIn("score_coverage/b.py", out)
        rc, _, err = self._main(["--lcov", lcov, "--min-lines", "90", "--min-branches", "50"])
        self.assertEqual(rc, 1)
        self.assertIn("below the minimum", err)
        md = self.root / "summary.md"
        md.write_text("# before\n", encoding="utf-8")
        rc, _, _ = self._main(["--lcov", lcov, "--min-lines", "0", "--min-branches", "0", "--summary-md", str(md)])
        self.assertEqual(rc, 0)
        text = md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# before\n"))
        self.assertIn("| `score_coverage/a.py` | 85.00% (17/20) | 62.50% (5/8) |", text)

    def test_bad_inputs(self):
        rc, _, _ = self._main(["--lcov", str(self.root / "nope"), "--min-lines", "0", "--min-branches", "0"])
        self.assertEqual(rc, 2)
        rc, _, _ = self._main(["--lcov", str(self.root / "lcov.dat"), "--min-lines", "101", "--min-branches", "0"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
