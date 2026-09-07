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
"""Unit tests for generate_coverage_html: the gate primitives and the end-to-end flow.

The end-to-end tests run against a synthetic consumer workspace: a fake
reporter zip (html_report/ + lcov_report/lcov.dat) under
bazel-out/_coverage/ and a fake bazel-testlogs tree. The justification tools
are replaced by fakes where the HTML post-processing itself is out of scope.
"""
# Test modules: docstrings on every test method add nothing, tests exercise
# private helpers on purpose, TemporaryDirectory is closed in tearDown, and setUp
# fixtures are attributes.
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access,consider-using-with
# pylint: disable=too-many-instance-attributes

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from score_coverage import generate_coverage_html as gch
from score_coverage.tests.traceability import verifies

LCOV_25_PERCENT = (
    "SF:src/covered.cpp\nDA:1,1\nDA:2,1\nLF:10\nLH:5\nend_of_record\n"
    "SF:src/uncovered.cpp\nDA:1,0\nLF:10\nLH:0\nend_of_record\n"
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_workspace(
    root: Path, lcov: str = LCOV_25_PERCENT, with_html: bool = True, with_testlogs: bool = True
) -> Path:
    """Create a fake consumer workspace with a reporter zip and test logs."""
    report = root / gch.COVERAGE_REPORT_REL
    report.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(report, "w") as zf:
        if with_html:
            zf.writestr("html_report/index.html", "<html>report</html>")
            zf.writestr("html_report/style.css", "body {}")
        zf.writestr("lcov_report/lcov.dat", lcov)
        zf.writestr("text_report/summary.txt", "TOTAL 50%")
    if with_testlogs:
        _write(root / "bazel-testlogs" / "pkg" / "some_test" / "test.xml", "<testsuites/>")
        _write(root / "bazel-testlogs" / "pkg" / "some_test" / "test.log", "log")
    return root


def _run(root: Path, argv, environ) -> tuple:
    """Run the tool quietly, returning (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = gch.run(gch.parse_args(argv), root, environ)
    return rc, out.getvalue(), err.getvalue()


@verifies("tool_req__coverage_gate_threshold", derivation="boundary-values")
class ParseThresholdTest(unittest.TestCase):
    def test_default_is_100(self):
        self.assertEqual(gch.parse_threshold(None), 100.0)
        self.assertEqual(gch.parse_threshold(""), 100.0)
        self.assertEqual(gch.parse_threshold("  "), 100.0)

    def test_numbers(self):
        self.assertEqual(gch.parse_threshold("85"), 85.0)
        self.assertEqual(gch.parse_threshold("99.5"), 99.5)
        self.assertEqual(gch.parse_threshold("0"), 0.0)
        self.assertEqual(gch.parse_threshold("100"), 100.0)

    def test_garbage_is_an_error_not_a_permissive_gate(self):
        for bad in ["abc", "85%", "1e999", "nan", "-1", "100.01", "inf"]:
            with self.subTest(bad=bad), self.assertRaises(gch.GenerateError):
                gch.parse_threshold(bad)


@verifies("tool_req__coverage_gate_metric", "tool_req__coverage_gate_no_verdict")
class RawLineCoverageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sums_all_records(self):
        lcov = _write(self.root / "lcov.dat", LCOV_25_PERCENT)
        self.assertAlmostEqual(gch.raw_line_coverage_from_lcov(lcov), 25.0)

    def test_baseline_only_records_count_towards_the_denominator(self):
        lcov = _write(self.root / "lcov.dat", "SF:a\nLF:1\nLH:1\nend_of_record\nSF:b\nLF:1\nLH:0\nend_of_record\n")
        self.assertAlmostEqual(gch.raw_line_coverage_from_lcov(lcov), 50.0)

    def test_result_is_not_rounded(self):
        lcov = _write(self.root / "lcov.dat", "SF:a\nLF:200000\nLH:199999\nend_of_record\n")
        pct = gch.raw_line_coverage_from_lcov(lcov)
        self.assertLess(pct, 100.0)
        self.assertEqual(f"{pct:.2f}", "100.00")  # the printed value rounds up, the gate value must not

    def test_missing_file(self):
        with self.assertRaises(gch.GenerateError):
            gch.raw_line_coverage_from_lcov(self.root / "nope.dat")

    def test_no_instrumented_lines_is_an_error(self):
        lcov = _write(self.root / "lcov.dat", "SF:a\nLF:0\nLH:0\nend_of_record\n")
        with self.assertRaises(gch.GenerateError):
            gch.raw_line_coverage_from_lcov(lcov)
        empty = _write(self.root / "empty.dat", "")
        with self.assertRaises(gch.GenerateError):
            gch.raw_line_coverage_from_lcov(empty)

    def test_corrupt_records_are_errors(self):
        for content in ["SF:a\nLF:1\nLH:2\nend_of_record\n", "SF:a\nLF:x\nLH:0\n", "SF:a\nLF:5\nLH:-1\n"]:
            with self.subTest(content=content):
                lcov = _write(self.root / "lcov.dat", content)
                with self.assertRaises(gch.GenerateError):
                    gch.raw_line_coverage_from_lcov(lcov)


@verifies("tool_req__coverage_gate_metric", "tool_req__coverage_gate_no_verdict")
class EffectiveLineCoverageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _report(self, payload) -> Path:
        return _write(self.root / "report.json", json.dumps(payload))

    def test_reads_summary_value(self):
        path = self._report({"summary": {"effective_line_coverage_pct": 61.76}})
        self.assertEqual(gch.effective_line_coverage_from_report(path), 61.76)

    def test_integer_is_accepted(self):
        path = self._report({"summary": {"effective_line_coverage_pct": 100}})
        self.assertEqual(gch.effective_line_coverage_from_report(path), 100.0)

    def test_missing_report(self):
        with self.assertRaises(gch.GenerateError):
            gch.effective_line_coverage_from_report(self.root / "missing.json")

    def test_malformed_reports(self):
        for payload in [
            {},
            {"summary": {}},
            {"summary": {"effective_line_coverage_pct": "95"}},
            {"summary": {"effective_line_coverage_pct": None}},
            {"summary": {"effective_line_coverage_pct": True}},
        ]:
            with self.subTest(payload=payload), self.assertRaises(gch.GenerateError):
                gch.effective_line_coverage_from_report(self._report(payload))
        bad_json = _write(self.root / "report.json", "{not json")
        with self.assertRaises(gch.GenerateError):
            gch.effective_line_coverage_from_report(bad_json)


@verifies("tool_req__coverage_gate_unrounded", derivation="boundary-values")
class GateTest(unittest.TestCase):
    def test_boundaries(self):
        self.assertTrue(gch.gate_passes(100.0, 100.0))
        self.assertTrue(gch.gate_passes(85.0, 85.0))
        self.assertTrue(gch.gate_passes(0.0, 0.0))
        self.assertFalse(gch.gate_passes(99.995, 100.0))
        self.assertFalse(gch.gate_passes(84.999, 85.0))


@verifies("tool_req__coverage_summary_first", "tool_req__coverage_artifacts")
class ParseArgsTest(unittest.TestCase):
    def test_defaults(self):
        opts = gch.parse_args([])
        self.assertIsNone(opts.yaml)
        self.assertIsNone(opts.archive)
        self.assertIsNone(opts.archive_dir)
        self.assertEqual(opts.platform, "linux")
        self.assertEqual(opts.testlogs_subdir, "")
        self.assertIsNone(opts.summary_md)
        self.assertIsNone(opts.output_dir)

    def test_all_flags(self):
        opts = gch.parse_args(
            [
                "--yaml",
                "j.yaml",
                "--archive",
                "cov",
                "--archive-dir",
                "d",
                "--platform",
                "qnx",
                "--testlogs-subdir",
                "score",
                "--summary-md",
                "s.md",
                "out",
            ]
        )
        self.assertEqual((opts.yaml, opts.archive, opts.archive_dir), ("j.yaml", "cov", "d"))
        self.assertEqual(
            (opts.platform, opts.testlogs_subdir, opts.summary_md, opts.output_dir), ("qnx", "score", "s.md", "out")
        )

    def test_unknown_platform_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            gch.parse_args(["--platform", "windows"])


@verifies(
    "tool_req__coverage_gate_metric",
    "tool_req__coverage_gate_exit_codes",
    "tool_req__coverage_summary_first",
    "tool_req__coverage_artifacts",
)
class RunWithoutYamlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = _make_workspace(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_gate_passes_at_low_threshold_and_writes_html(self):
        rc, out, _ = _run(self.root, [], {"COVERAGE_THRESHOLD": "10"})
        self.assertEqual(rc, gch.EXIT_OK)
        self.assertTrue((self.root / "coverage_linux" / "index.html").is_file())
        self.assertIn("Raw line coverage: 25.00%", out)

    def test_gate_fails_at_default_threshold(self):
        rc, _, err = _run(self.root, [], {})
        self.assertEqual(rc, gch.EXIT_GATE_FAILED)
        self.assertIn("Raw coverage 25.00% is below threshold 100%", err)

    def test_gate_fails_exactly_below_threshold(self):
        rc, _, _ = _run(self.root, [], {"COVERAGE_THRESHOLD": "25.01"})
        self.assertEqual(rc, gch.EXIT_GATE_FAILED)
        rc, _, _ = _run(self.root, [], {"COVERAGE_THRESHOLD": "25"})
        self.assertEqual(rc, gch.EXIT_OK)

    def test_invalid_threshold_is_an_error_before_any_output(self):
        with self.assertRaises(gch.GenerateError):
            _run(self.root, [], {"COVERAGE_THRESHOLD": "high"})
        self.assertFalse((self.root / "coverage_linux").exists())

    def test_custom_output_dir_and_platform_default(self):
        rc, _, _ = _run(self.root, ["--platform", "qnx"], {"COVERAGE_THRESHOLD": "0"})
        self.assertEqual(rc, gch.EXIT_OK)
        self.assertTrue((self.root / "coverage_qnx" / "index.html").is_file())
        rc, _, _ = _run(self.root, ["custom_out"], {"COVERAGE_THRESHOLD": "0"})
        self.assertEqual(rc, gch.EXIT_OK)
        self.assertTrue((self.root / "custom_out" / "index.html").is_file())

    def test_stale_output_dir_is_replaced(self):
        _write(self.root / "coverage_linux" / "stale.html", "old")
        _run(self.root, [], {"COVERAGE_THRESHOLD": "0"})
        self.assertFalse((self.root / "coverage_linux" / "stale.html").exists())

    def test_summary_md_is_written_even_when_gate_fails(self):
        rc, out, _ = _run(self.root, ["--summary-md", "summary.md"], {})
        self.assertEqual(rc, gch.EXIT_GATE_FAILED)
        summary = (self.root / "summary.md").read_text(encoding="utf-8")
        self.assertIn("## Coverage summary", summary)
        self.assertIn("Coverage summary written to:", out)

    def test_github_step_summary_is_appended_not_overwritten(self):
        step = _write(self.root / "step.md", "# existing content\n")
        rc, out, _ = _run(self.root, [], {"COVERAGE_THRESHOLD": "0", "GITHUB_STEP_SUMMARY": str(step)})
        self.assertEqual(rc, gch.EXIT_OK)
        text = step.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# existing content\n"))
        self.assertIn("## Coverage summary", text)
        self.assertIn("appended to GITHUB_STEP_SUMMARY", out)

    def test_explicit_summary_md_wins_over_step_summary(self):
        step = _write(self.root / "step.md", "# existing content\n")
        _run(self.root, ["--summary-md", "s.md"], {"COVERAGE_THRESHOLD": "0", "GITHUB_STEP_SUMMARY": str(step)})
        self.assertEqual(step.read_text(encoding="utf-8"), "# existing content\n")
        self.assertTrue((self.root / "s.md").is_file())

    def test_archive_dir_layout(self):
        rc, out, _ = _run(
            self.root, ["--archive-dir", "artifacts_dir", "--testlogs-subdir", "pkg"], {"COVERAGE_THRESHOLD": "0"}
        )
        self.assertEqual(rc, gch.EXIT_OK)
        base = self.root / "artifacts_dir"
        for rel in ["coverage_linux/index.html", "coverage_report.dat", "bazel-testlogs/pkg/some_test/test.xml"]:
            with self.subTest(rel=rel):
                self.assertTrue((base / rel).is_file())
        self.assertFalse((base / "bazel-testlogs/pkg/some_test/test.log").exists())
        self.assertEqual((base / "coverage_report.dat").read_text(encoding="utf-8"), LCOV_25_PERCENT)
        self.assertIn("Coverage artifacts written to: artifacts_dir/", out)

    def test_archive_zip_layout(self):
        rc, _, _ = _run(self.root, ["--archive", "coverage_artifacts"], {"COVERAGE_THRESHOLD": "0"})
        self.assertEqual(rc, gch.EXIT_OK)
        with zipfile.ZipFile(self.root / "coverage_artifacts.zip") as zf:
            names = set(zf.namelist())
        self.assertIn("artifacts/coverage_report.dat", names)
        self.assertIn("artifacts/coverage_linux/index.html", names)
        self.assertIn("artifacts/bazel-testlogs/pkg/some_test/test.xml", names)
        self.assertFalse((self.root / "artifacts").exists())

    def test_archive_is_still_produced_when_gate_fails(self):
        rc, _, _ = _run(self.root, ["--archive-dir", "out"], {})
        self.assertEqual(rc, gch.EXIT_GATE_FAILED)
        self.assertTrue((self.root / "out" / "coverage_report.dat").is_file())

    def test_missing_testlogs_when_archiving_is_an_error(self):
        with self.assertRaises(gch.GenerateError):
            _run(
                self.root, ["--archive-dir", "out", "--testlogs-subdir", "does_not_exist"], {"COVERAGE_THRESHOLD": "0"}
            )


@verifies("tool_req__coverage_gate_no_verdict", test_type="fault-injection", derivation="error-guessing")
class RunInputValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_report(self):
        with self.assertRaises(gch.GenerateError):
            _run(self.root, [], {"COVERAGE_THRESHOLD": "0"})

    def test_report_is_not_a_zip(self):
        _write(self.root / gch.COVERAGE_REPORT_REL, "TN:\nSF:foo\nend_of_record\n")
        with self.assertRaises(gch.GenerateError):
            _run(self.root, [], {"COVERAGE_THRESHOLD": "0"})

    def test_zip_without_html_report(self):
        _make_workspace(self.root, with_html=False)
        with self.assertRaises(gch.GenerateError):
            _run(self.root, [], {"COVERAGE_THRESHOLD": "0"})

    def test_lcov_with_no_instrumented_lines_yields_no_verdict(self):
        _make_workspace(self.root, lcov="SF:a\nLF:0\nLH:0\nend_of_record\n")
        with self.assertRaises(gch.GenerateError):
            _run(self.root, [], {"COVERAGE_THRESHOLD": "0"})


@verifies(
    "tool_req__coverage_gate_metric",
    "tool_req__coverage_gate_exit_codes",
    "tool_req__coverage_gate_no_verdict",
    "tool_req__coverage_artifacts",
)
class RunWithYamlTest(unittest.TestCase):
    """The justification layer is faked: these tests cover the orchestration around it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = _make_workspace(Path(self.tmp.name))
        _write(self.root / "tools" / "coverage" / "coverage_justifications.yaml", "version: 1\njustifications: []\n")
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_effective(self, pct):
        def fake(argv):
            self.calls.append(("effective_coverage", argv))
            output = Path(argv[argv.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "summary": {
                            "effective_line_coverage_pct": pct,
                            "raw_line_coverage_pct": 25.0,
                            "justified_lines": 3,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (output.parent / "summary.txt").write_text(f"Effective line coverage:  {pct}%\n", encoding="utf-8")

        return fake

    def _fake_justify(self, argv):
        self.calls.append(("justify", argv))
        Path(argv[argv.index("--output") + 1]).parent.mkdir(parents=True, exist_ok=True)
        Path(argv[argv.index("--output") + 1]).write_text("{}", encoding="utf-8")

    def _run_yaml(self, extra, environ, pct=90.0):
        with (
            mock.patch.object(gch.justify, "main", side_effect=self._fake_justify),
            mock.patch.object(gch.effective_coverage, "main", side_effect=self._fake_effective(pct)),
        ):
            return _run(self.root, ["--yaml", "tools/coverage/coverage_justifications.yaml"] + extra, environ)

    def test_gates_on_effective_coverage(self):
        rc, out, _ = self._run_yaml([], {"COVERAGE_THRESHOLD": "85"})
        self.assertEqual(rc, gch.EXIT_OK)
        self.assertIn("Effective line coverage:  90.0%", out)
        rc, _, err = self._run_yaml([], {"COVERAGE_THRESHOLD": "95"})
        self.assertEqual(rc, gch.EXIT_GATE_FAILED)
        self.assertIn("Effective coverage 90.00% is below threshold 95%", err)

    def test_tools_receive_workspace_relative_inputs(self):
        self._run_yaml(["--platform", "qnx"], {"COVERAGE_THRESHOLD": "0"})
        names = [c[0] for c in self.calls]
        self.assertEqual(names, ["justify", "effective_coverage"])
        justify_argv = self.calls[0][1]
        self.assertEqual(justify_argv[justify_argv.index("--platform") + 1], "qnx")
        self.assertEqual(justify_argv[justify_argv.index("--source-root") + 1], str(self.root))
        self.assertTrue(justify_argv[justify_argv.index("--yaml") + 1].endswith("coverage_justifications.yaml"))
        eff_argv = self.calls[1][1]
        self.assertEqual(eff_argv[eff_argv.index("--html-dir") + 1], str(self.root / "coverage_qnx"))

    def test_missing_yaml_is_an_error(self):
        with mock.patch.object(gch.justify, "main") as justify_main:
            with self.assertRaises(gch.GenerateError):
                _run(self.root, ["--yaml", "nope.yaml"], {"COVERAGE_THRESHOLD": "0"})
            justify_main.assert_not_called()

    def test_justify_failure_is_an_error_not_a_verdict(self):
        def failing(argv):
            raise SystemExit(1)

        with mock.patch.object(gch.justify, "main", side_effect=failing), self.assertRaises(gch.GenerateError):
            _run(self.root, ["--yaml", "tools/coverage/coverage_justifications.yaml"], {"COVERAGE_THRESHOLD": "0"})

    def test_missing_summary_is_an_error(self):
        def no_summary(argv):
            output = Path(argv[argv.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"summary": {"effective_line_coverage_pct": 99.0}}), encoding="utf-8")

        with (
            mock.patch.object(gch.justify, "main", side_effect=self._fake_justify),
            mock.patch.object(gch.effective_coverage, "main", side_effect=no_summary),
            self.assertRaises(gch.GenerateError),
        ):
            _run(self.root, ["--yaml", "tools/coverage/coverage_justifications.yaml"], {"COVERAGE_THRESHOLD": "0"})

    def test_archive_includes_justification_report(self):
        rc, _, _ = self._run_yaml(["--archive-dir", "out"], {"COVERAGE_THRESHOLD": "0"})
        self.assertEqual(rc, gch.EXIT_OK)
        self.assertTrue((self.root / "out" / "justification_report" / "summary.txt").is_file())
        self.assertTrue((self.root / "out" / "justification_report" / "report.json").is_file())


@verifies("tool_req__coverage_gate_exit_codes")
class MainTest(unittest.TestCase):
    def test_requires_build_workspace_directory(self):
        with mock.patch.dict("os.environ", {}, clear=True), redirect_stderr(io.StringIO()):
            self.assertEqual(gch.main([]), gch.EXIT_ERROR)

    def test_generate_error_maps_to_exit_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"BUILD_WORKSPACE_DIRECTORY": tmp, "COVERAGE_THRESHOLD": "0"}
            with mock.patch.dict("os.environ", env, clear=True), redirect_stderr(io.StringIO()):
                self.assertEqual(gch.main([]), gch.EXIT_ERROR)  # no report in an empty workspace

    def test_end_to_end_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_workspace(Path(tmp))
            with (
                mock.patch.dict(
                    "os.environ", {"BUILD_WORKSPACE_DIRECTORY": tmp, "COVERAGE_THRESHOLD": "10"}, clear=True
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(gch.main([]), gch.EXIT_OK)
            with (
                mock.patch.dict("os.environ", {"BUILD_WORKSPACE_DIRECTORY": tmp}, clear=True),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(gch.main([]), gch.EXIT_GATE_FAILED)


if __name__ == "__main__":
    unittest.main()
