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
"""Unit tests for the gcov backend reporter (GCC on Linux, QCC on QNX)."""

# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access,consider-using-with
# pylint: disable=too-many-instance-attributes

import io
import os
import stat
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from score_coverage import gcov_reporter
from score_coverage.gcov_reporter import FileRecord, parse_lcov, render_lcov
from score_coverage.reporter import FileSelection
from score_coverage.tests.traceability import verifies

LCOV_A = """SF:src/a.cpp
FN:3,_Z1ai
FNDA:2,_Z1ai
FNF:1
FNH:1
DA:3,2
DA:4,1
DA:5,0
BRDA:4,0,0,1
BRDA:4,0,1,0
BRDA:6,0,0,-
BRF:3
BRH:1
LF:3
LH:2
end_of_record
"""

LCOV_A_AGAIN = """SF:src/a.cpp
FN:3,_Z1ai
FNDA:1,_Z1ai
DA:3,1
DA:4,0
DA:5,1
BRDA:4,0,0,0
BRDA:4,0,1,1
BRDA:6,0,0,-
LF:3
LH:2
end_of_record
"""


class _FakeRunfiles:
    def __init__(self, mapping):
        self.mapping = mapping

    def Rlocation(self, path):  # noqa: N802  # pylint: disable=invalid-name
        if os.path.isabs(path):
            return path
        return self.mapping.get(path)


GCOV_JSON = {
    "format_version": "1",
    "gcc_version": "12.2.0",
    "current_working_directory": "/proc/self/cwd",
    "data_file": "uncovered.pic.gcno",
    "files": [
        {
            "file": "src/uncovered.cpp",
            "functions": [{"name": "_Z1fv", "start_line": 16, "end_line": 20, "execution_count": 0}],
            "lines": [
                {"line_number": 16, "count": 0, "unexecuted_block": True, "branches": []},
                {
                    "line_number": 17,
                    "count": 0,
                    "unexecuted_block": True,
                    "branches": [
                        {"count": 0, "throw": False, "fallthrough": False},
                        {"count": 0, "throw": False, "fallthrough": True},
                    ],
                },
                {"line_number": 19, "count": 0, "unexecuted_block": True, "branches": []},
            ],
        },
        {
            "file": "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h",
            "functions": [],
            "lines": [{"line_number": 5, "count": 0, "unexecuted_block": True, "branches": []}],
        },
    ],
}


def _fake_gcov(path: Path, payload: dict) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\nimport json, sys\n"
        "sys.stderr.write('x.gcda:cannot open data file, assuming not executed\\n')\n"
        f"print(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@verifies("tool_req__coverage_gcov_merge")
class ParseAndRenderLcovTest(unittest.TestCase):
    def test_parse_records_lines_branches_functions(self):
        rec = parse_lcov(LCOV_A)["src/a.cpp"]
        self.assertEqual(rec.lines, {3: 2, 4: 1, 5: 0})
        self.assertEqual(rec.branches, {(4, "0", "0"): 1, (4, "0", "1"): 0, (6, "0", "0"): None})
        self.assertEqual(rec.functions, {"_Z1ai": (3, 2)})

    def test_records_of_two_tests_are_summed(self):
        merged = FileRecord()
        merged.add(parse_lcov(LCOV_A)["src/a.cpp"])
        merged.add(parse_lcov(LCOV_A_AGAIN)["src/a.cpp"])
        self.assertEqual(merged.lines, {3: 3, 4: 1, 5: 1})
        # a branch taken in either run is taken; a block never reached in both stays '-'
        self.assertEqual(merged.branches, {(4, "0", "0"): 1, (4, "0", "1"): 1, (6, "0", "0"): None})
        self.assertEqual(merged.functions, {"_Z1ai": (3, 3)})

    def test_never_reached_plus_count_is_count(self):
        rec = FileRecord(branches={(1, "0", "0"): None})
        rec.add(FileRecord(branches={(1, "0", "0"): 2}))
        self.assertEqual(rec.branches, {(1, "0", "0"): 2})

    def test_render_round_trip_and_totals(self):
        rec = parse_lcov(LCOV_A)["src/a.cpp"]
        text = render_lcov({"src/a.cpp": rec})
        self.assertEqual(parse_lcov(text)["src/a.cpp"], rec)
        self.assertIn("LF:3\nLH:2\n", text)
        self.assertIn("BRF:3\nBRH:1\n", text)
        self.assertIn("BRDA:6,0,0,-\n", text)
        self.assertIn("FNF:1\nFNH:1\n", text)

    def test_zeroed_keeps_structure(self):
        zero = parse_lcov(LCOV_A)["src/a.cpp"].zeroed()
        self.assertEqual(zero.lines, {3: 0, 4: 0, 5: 0})
        self.assertEqual(zero.branches, {(4, "0", "0"): 0, (4, "0", "1"): 0, (6, "0", "0"): None})
        self.assertEqual(zero.functions, {"_Z1ai": (3, 0)})

    def test_negative_counts_are_clamped(self):
        rec = parse_lcov("SF:x\nDA:1,-1\nBRDA:1,0,0,-3\nend_of_record\n")["x"]
        self.assertEqual(rec.lines, {1: 0})
        self.assertEqual(rec.branches, {(1, "0", "0"): 0})


@verifies("tool_req__coverage_report_relative_paths", "tool_req__coverage_gcov_merge")
class PathsTest(unittest.TestCase):
    def test_normalize_raw(self):
        for raw in ("/ws/src/a.cpp", "/proc/self/cwd/src/a.cpp", "./src/a.cpp", "src/a.cpp"):
            self.assertEqual(gcov_reporter.normalize_raw(raw, "/ws/"), "src/a.cpp")
        self.assertEqual(gcov_reporter.normalize_raw("/usr/include/x.h", "/ws"), "/usr/include/x.h")

    def test_canonical_names_use_path_map_and_foreign_trees(self):
        raws = {
            "src/a.cpp",
            "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h",
            "bazel-out/k8-fastbuild/bin/src/_virtual_includes/twin/w/w.h",
        }
        names = gcov_reporter.canonical_names(
            raws, {"src/_virtual_includes/v/api.h": "src/v/api.h"}, {"src/a.cpp", "src/v/api.h", "src/w/include/w/w.h"}
        )
        self.assertEqual(names["src/a.cpp"], "src/a.cpp")
        self.assertEqual(names["bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h"], "src/v/api.h")
        self.assertEqual(names["bazel-out/k8-fastbuild/bin/src/_virtual_includes/twin/w/w.h"], "src/w/include/w/w.h")

    def test_rust_sources_are_not_findings_on_gcov(self):
        sel = FileSelection(unmapped={"src/a.h", "rust/lib.rs"})
        self.assertEqual(gcov_reporter.mark_not_instrumented(sel), {"rust/lib.rs"})
        self.assertEqual(sel.unmapped, {"src/a.h"})


@verifies("tool_req__coverage_gcov_baseline", "tool_req__coverage_report_baseline_zero")
class BaselineTest(unittest.TestCase):
    def test_records_from_gcov_json(self):
        records = gcov_reporter.records_from_gcov_json(GCOV_JSON)
        unc = records["src/uncovered.cpp"]
        self.assertEqual(unc.lines, {16: 0, 17: 0, 19: 0})
        self.assertEqual(unc.branches, {(17, "0", "0"): 0, (17, "0", "1"): 0})
        self.assertEqual(unc.functions, {"_Z1fv": (16, 0)})
        self.assertIn("bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h", records)

    def test_gcov_baseline_runs_the_tool_and_tolerates_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            gcov = _fake_gcov(Path(tmp) / "gcov", GCOV_JSON)
            records = gcov_reporter.gcov_baseline(gcov, "x.gcno")
            self.assertEqual(
                set(records), {"src/uncovered.cpp", "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h"}
            )
            broken = Path(tmp) / "broken"
            broken.write_text("#!/bin/sh\necho not json\n", encoding="utf-8")
            broken.chmod(0o755)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(gcov_reporter.gcov_baseline(broken, "x.gcno"), {})
            failing = Path(tmp) / "failing"
            failing.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
            failing.chmod(0o755)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(gcov_reporter.gcov_baseline(failing, "x.gcno"), {})

    def test_gcno_manifest_resolution_and_missing_file_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.gcno").write_bytes(b"")
            manifest = root / "gcno.txt"
            manifest.write_text("# comment\npkg/a.gcno\n\n", encoding="utf-8")
            runfiles = _FakeRunfiles({"m/gcno.txt": str(manifest), "_main/pkg/a.gcno": str(root / "a.gcno")})
            self.assertEqual(
                gcov_reporter.load_gcno_manifest(runfiles, "m/gcno.txt"), {str(root / "a.gcno"): "pkg/a.gcno"}
            )
            self.assertEqual(gcov_reporter.load_gcno_manifest(runfiles, None), {})
            with redirect_stderr(io.StringIO()):
                self.assertEqual(gcov_reporter.load_gcno_manifest(runfiles, "m/nope.txt"), {})
            manifest.write_text("pkg/missing.gcno\n", encoding="utf-8")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                gcov_reporter.load_gcno_manifest(runfiles, "m/gcno.txt")

    def test_compiled_stems_from_gcno_paths(self):
        stems = gcov_reporter.compiled_stems_from_gcno(
            [
                "src/_objs/uncovered/empty_unit.pic.gcno",
                "src/_objs/uncovered/uncovered.gcno",
                "_objs/tool/main.pic.gcno",
                "src/not_a_gcno.o",
            ]
        )
        self.assertEqual(stems, {"src/empty_unit", "src/uncovered", "main"})

    def test_merge_prefers_test_data_and_zeroes_baseline_only_files(self):
        tested = {"src/a.cpp": parse_lcov(LCOV_A)["src/a.cpp"]}
        baseline = {
            "src/a.cpp": FileRecord(lines={3: 5}),  # must not be added on top of test data
            "src/uncovered.cpp": FileRecord(lines={16: 0, 17: 0}, functions={"_Z1fv": (16, 0)}),
        }
        sel = FileSelection(staged={"src/a.cpp": "src/a.cpp", "src/uncovered.cpp": "src/uncovered.cpp"})
        merged = gcov_reporter.merge_records(tested, baseline, sel)
        self.assertEqual(merged["src/a.cpp"].lines, {3: 2, 4: 1, 5: 0})
        self.assertEqual(merged["src/uncovered.cpp"].lines, {16: 0, 17: 0})
        self.assertEqual(merged["src/uncovered.cpp"].functions, {"_Z1fv": (16, 0)})


@verifies("tool_req__coverage_gcov_html", "tool_req__coverage_report_outputs")
class GcovrRenderingTest(unittest.TestCase):
    def test_tracefile_shape(self):
        rec = parse_lcov(LCOV_A)["src/a.cpp"]
        data = gcov_reporter.gcovr_tracefile({"src/a.cpp": rec})
        self.assertEqual(data["gcovr/format_version"], "0.14")
        entry = data["files"][0]
        self.assertEqual(entry["file"], "src/a.cpp")
        self.assertEqual([line["line_number"] for line in entry["lines"]], [3, 4, 5])
        self.assertEqual([b["count"] for b in entry["lines"][1]["branches"]], [1, 0])
        self.assertEqual(
            [(b["source_block_id"], b["destination_block_id"]) for b in entry["lines"][1]["branches"]], [(0, 0), (0, 1)]
        )
        self.assertEqual(entry["functions"], [{"name": "_Z1ai", "lineno": 3, "execution_count": 2}])

    def test_render_html_with_real_gcovr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sources" / "src").mkdir(parents=True)
            (root / "sources" / "src" / "a.cpp").write_text(
                "int a;\nint b;\nint c(int x) {\n  if (x) {\n    return 1;\n  }\n  return 0;\n}\n", encoding="utf-8"
            )
            html_dir = root / "html_report"
            html_dir.mkdir()
            cwd = os.getcwd()
            os.chdir(root)
            try:
                with redirect_stderr(io.StringIO()):
                    gcov_reporter.render_html(
                        {"src/a.cpp": parse_lcov(LCOV_A)["src/a.cpp"]}, root / "sources", html_dir, root / "summary.txt"
                    )
            finally:
                os.chdir(cwd)
            names = sorted(p.name for p in html_dir.iterdir())
            self.assertIn("index.html", names)
            self.assertTrue(any(n.startswith("index.a.cpp.") and n.endswith(".html") for n in names), names)
            summary = (root / "summary.txt").read_text(encoding="utf-8")
            self.assertIn("src/a.cpp", summary)
            self.assertIn("TOTAL", summary)


@verifies(
    "tool_req__coverage_gcov_merge",
    "tool_req__coverage_gcov_baseline",
    "tool_req__coverage_report_allowlist",
    "tool_req__coverage_report_unmapped",
)
class GcovReporterMainTest(unittest.TestCase):
    """main() end to end with two per-test LCOV files, a fake gcov and a scope."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "ws"
        for rel, text in {
            "src/a.cpp": "int a;\n" * 8,
            "src/uncovered.cpp": "int u;\n" * 20,
            "src/v/api.h": "int api();\n" * 6,
            "src/uncovered.h": "int u();\n",
            "rust/lib.rs": "fn x() {}\n",
        }.items():
            (self.ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.ws / rel).write_text(text, encoding="utf-8")
        (self.root / "t0.dat").write_text(
            LCOV_A + "SF:external/gtest+/x.cc\nDA:1,1\nLF:1\nLH:1\nend_of_record\n", encoding="utf-8"
        )
        (self.root / "t1.dat").write_text(
            LCOV_A_AGAIN
            + "SF:bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h\nDA:5,3\nLF:1\nLH:1\nend_of_record\n",
            encoding="utf-8",
        )
        (self.root / "reports.txt").write_text(
            f"{self.root}/t0.dat\n{self.root}/t1.dat\n{self.root}/baseline_coverage.dat\n", encoding="utf-8"
        )
        (self.root / "baseline_coverage.dat").write_text("SF:src/a.cpp\nend_of_record\n", encoding="utf-8")
        self.gcov = _fake_gcov(self.root / "gcov", GCOV_JSON)
        (self.root / "uncovered.pic.gcno").write_bytes(b"gcno")
        (self.root / "empty_unit.pic.gcno").write_bytes(b"gcno")
        (self.root / "gcno.txt").write_text(
            "src/_objs/uncovered/uncovered.pic.gcno\nsrc/_objs/uncovered/empty_unit.pic.gcno\n", encoding="utf-8"
        )
        (self.ws / "src" / "empty_unit.cpp").write_text('#include "u.h"\n', encoding="utf-8")
        (self.root / "allow.txt").write_text(
            "src/a.cpp\nsrc/uncovered.cpp\nsrc/uncovered.h\nsrc/v/api.h\nrust/lib.rs\nsrc/empty_unit.cpp\n",
            encoding="utf-8",
        )
        (self.root / "map.txt").write_text("src/_virtual_includes/v/api.h\tsrc/v/api.h\n", encoding="utf-8")
        self.runfiles = _FakeRunfiles(
            {
                "m/gcov": str(self.gcov),
                "m/gcno.txt": str(self.root / "gcno.txt"),
                "_main/src/_objs/uncovered/uncovered.pic.gcno": str(self.root / "uncovered.pic.gcno"),
                "_main/src/_objs/uncovered/empty_unit.pic.gcno": str(self.root / "empty_unit.pic.gcno"),
                "m/allow.txt": str(self.root / "allow.txt"),
                "m/map.txt": str(self.root / "map.txt"),
            }
        )
        self.output = self.root / "out.zip"
        self.workdir = self.root / "work"
        self.workdir.mkdir()
        self.cwd = os.getcwd()
        os.chdir(self.workdir)
        self.patch = mock.patch.object(gcov_reporter.Runfiles, "Create", return_value=self.runfiles)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def _argv(self, **extra):
        argv = [
            "--output_file",
            str(self.output),
            "--reports_file",
            str(self.root / "reports.txt"),
            "--workspace_root",
            str(self.ws),
            "--gcov",
            "m/gcov",
            "--gcno_manifest",
            "m/gcno.txt",
            "--coverage_allowlist",
            "m/allow.txt",
            "--path_map",
            "m/map.txt",
        ]
        for k, v in extra.items():
            argv += [f"--{k}", str(v)]
        return argv

    def test_full_report(self):
        err = io.StringIO()
        with redirect_stderr(err):
            gcov_reporter.main(self._argv())
        with zipfile.ZipFile(self.output) as zf:
            names = set(zf.namelist())
            lcov = zf.read("lcov_report/lcov.dat").decode()
            unmapped = zf.read("text_report/unmapped_files.txt").decode()
            summary = zf.read("text_report/summary.txt").decode()
        self.assertIn("html_report/index.html", names)
        self.assertTrue(any(n.startswith("html_report/index.a.cpp.") for n in names), names)
        # two tests summed for a.cpp; the virtual-include header under its declared path;
        # the untested TU from the gcno baseline at 0; gtest excluded
        self.assertIn("SF:src/a.cpp\n", lcov)
        self.assertIn("DA:3,3\n", lcov)
        self.assertIn("SF:src/v/api.h\nDA:5,3\n", lcov)
        self.assertIn("SF:src/uncovered.cpp\n", lcov)
        self.assertIn("DA:16,0\n", lcov)
        self.assertIn("FNDA:0,_Z1fv\n", lcov)
        self.assertNotIn("gtest", lcov)
        self.assertNotIn("_virtual_includes", lcov)
        # uncovered.h: declaration-only (its .cpp has data); lib.rs: not instrumentable
        self.assertIn("declaration-only\tsrc/uncovered.h\n", unmapped)
        self.assertIn("not-instrumented\trust/lib.rs\n", unmapped)
        self.assertIn("compiled-without-code\tsrc/empty_unit.cpp\n", unmapped)
        self.assertNotIn("no-data", unmapped)
        self.assertIn("TOTAL", summary)
        self.assertIn("2 per-test reports cover", err.getvalue())
        self.assertIn("1 allowlisted files only in baseline", err.getvalue())
        # the staged sources sit under the raw layout so gcovr found them
        self.assertTrue((self.workdir / "sources" / "src" / "a.cpp").exists())

    def test_no_reports_writes_empty_zip(self):
        (self.root / "reports.txt").write_text(f"{self.root}/baseline_coverage.dat\n", encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            gcov_reporter.main(self._argv())
        with zipfile.ZipFile(self.output) as zf:
            self.assertEqual(zf.namelist(), [])

    def test_missing_gcov_is_an_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            gcov_reporter.main(self._argv(gcov="m/nope"))
        self.assertEqual(ctx.exception.code, 1)

    def test_empty_allowlist_is_an_error(self):
        (self.root / "allow.txt").write_text("# nothing\n", encoding="utf-8")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            gcov_reporter.main(self._argv())


if __name__ == "__main__":
    unittest.main()
