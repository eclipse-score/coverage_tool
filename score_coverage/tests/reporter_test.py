#!/usr/bin/env python3
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
"""Unit tests for the final coverage reporter."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from score_coverage.reporter import (
    _filter_lcov,
    _make_html_paths_relative,
    _make_lcov_paths_relative,
    _read_ar_members,
    expand_rlib_archives,
    write_empty_output,
)


def _ar_header(name: str, size: int) -> bytes:
    """Build a 60-byte Unix ar member header."""
    return (f"{name:<16}{'0':<12}{'0':<6}{'0':<6}{'100644':<8}{size:<10}`\n").encode()


def _make_archive(members) -> bytes:
    """Build a Unix ar archive from (name, data) tuples."""
    blob = b"!<arch>\n"
    for name, data in members:
        blob += _ar_header(name, len(data)) + data
        if len(data) % 2 == 1:
            blob += b"\n"
    return blob


class ReadArMembersTest(unittest.TestCase):
    def test_non_archive_returns_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".a") as f:
            f.write(b"\x7fELF not an archive")
            f.flush()
            self.assertEqual(_read_ar_members(f.name), [])

    def test_members_are_listed_with_sizes(self):
        blob = _make_archive([("lib.rmeta/", b"META"), ("foo.o/", b"OBJDATA")])
        with tempfile.NamedTemporaryFile(suffix=".a") as f:
            f.write(blob)
            f.flush()
            members = _read_ar_members(f.name)
        self.assertEqual([(m[0], m[2]) for m in members], [("lib.rmeta", 4), ("foo.o", 7)])

    def test_gnu_long_name_table_is_resolved(self):
        longnames = b"a_very_long_object_file_name.o/\n"
        blob = _make_archive([("//", longnames), ("/0", b"LONGOBJ")])
        with tempfile.NamedTemporaryFile(suffix=".a") as f:
            f.write(blob)
            f.flush()
            members = _read_ar_members(f.name)
        self.assertEqual([m[0] for m in members], ["a_very_long_object_file_name.o"])


class ExpandRlibArchivesTest(unittest.TestCase):
    def test_rlib_is_expanded_to_object_members(self):
        """Archives with a lib.rmeta member are replaced by their .o members."""
        blob = _make_archive([("lib.rmeta/", b"META"), ("crate.o/", b"OBJ1"), ("notes.txt/", b"TXT")])
        with tempfile.TemporaryDirectory() as tmp:
            rlib = Path(tmp) / "libcrate.a"
            rlib.write_bytes(blob)
            workdir = Path(tmp) / "extracted"
            result = expand_rlib_archives([str(rlib)], workdir)
            self.assertEqual(len(result), 1)
            self.assertTrue(result[0].endswith(".o"))
            self.assertEqual(Path(result[0]).read_bytes(), b"OBJ1")

    def test_plain_cc_archive_passes_through(self):
        blob = _make_archive([("mylib.o/", b"OBJ1")])
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "libcc.a"
            archive.write_bytes(blob)
            result = expand_rlib_archives([str(archive)], Path(tmp) / "x")
            self.assertEqual(result, [str(archive)])

    def test_executable_passes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "my_tool"
            binary.write_bytes(b"\x7fELF" + b"\x00" * 12)
            result = expand_rlib_archives([str(binary)], Path(tmp) / "x")
            self.assertEqual(result, [str(binary)])


class FilterLcovTest(unittest.TestCase):
    LCOV = "SF:src/foo.cpp\nDA:1,1\nLF:1\nLH:1\nend_of_record\nSF:src/bar.cpp\nDA:1,0\nLF:1\nLH:0\nend_of_record\n"

    def test_only_target_records_survive(self):
        result = _filter_lcov(self.LCOV, {"src/bar.cpp"})
        self.assertIn("SF:src/bar.cpp", result)
        self.assertNotIn("SF:src/foo.cpp", result)

    def test_suffix_matching(self):
        result = _filter_lcov("SF:/abs/prefix/src/foo.cpp\nend_of_record\n", {"src/foo.cpp"})
        self.assertIn("SF:/abs/prefix/src/foo.cpp", result)


class MakeLcovPathsRelativeTest(unittest.TestCase):
    def test_workspace_paths_become_relative(self):
        lcov = "SF:/ws/root/src/foo.cpp\nDA:1,1\nend_of_record\n"
        result = _make_lcov_paths_relative(lcov, "/ws/root/")
        self.assertEqual(result, "SF:src/foo.cpp\nDA:1,1\nend_of_record\n")

    def test_workspace_root_without_trailing_slash(self):
        lcov = "SF:/ws/root/src/foo.cpp\nend_of_record\n"
        result = _make_lcov_paths_relative(lcov, "/ws/root")
        self.assertEqual(result, "SF:src/foo.cpp\nend_of_record\n")

    def test_external_paths_are_unchanged(self):
        lcov = "SF:/other/place/dep.cpp\nend_of_record\n"
        self.assertEqual(_make_lcov_paths_relative(lcov, "/ws/root/"), lcov)

    def test_non_sf_lines_are_preserved(self):
        lcov = "TN:test\nSF:/ws/root/a.cpp\nDA:5,0\nLF:1\nLH:0\nend_of_record\n"
        result = _make_lcov_paths_relative(lcov, "/ws/root/")
        self.assertIn("TN:test\n", result)
        self.assertIn("DA:5,0\n", result)


class MakeHtmlPathsRelativeTest(unittest.TestCase):
    def test_source_title_is_rewritten_and_hrefs_untouched(self):
        html = (
            "<div class='source-name-title'><pre>/ws/root/src/foo.cpp</pre></div>"
            "<a href='coverage/ws/root/src/foo.cpp.html'>link</a>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text(html)
            _make_html_paths_relative(Path(tmp), "/ws/root/")
            result = page.read_text()
        self.assertIn("<pre>src/foo.cpp</pre>", result)
        # The href embeds the path components without a leading slash and must
        # never be rewritten.
        self.assertIn("href='coverage/ws/root/src/foo.cpp.html'", result)

    def test_missing_dir_is_a_noop(self):
        _make_html_paths_relative(Path("/nonexistent/html_dir"), "/ws/root/")


class WriteEmptyOutputTest(unittest.TestCase):
    def test_produces_valid_empty_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.zip"
            write_empty_output(out)
            self.assertTrue(zipfile.is_zipfile(out))
            with zipfile.ZipFile(out) as zf:
                self.assertEqual(zf.namelist(), [])


# ---------------------------------------------------------------------------
# Added for the score_coverage qualification: helpers around llvm-cov and an
# end-to-end run of main() against fake llvm tools.
# ---------------------------------------------------------------------------

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
import sys  # noqa: E402
from contextlib import redirect_stderr  # noqa: E402
from unittest import mock  # noqa: E402

from score_coverage import reporter  # noqa: E402


class _FakeRunfiles:
    """Minimal stand-in for python.runfiles.Runfiles: maps rlocation paths to files."""

    def __init__(self, mapping):
        self.mapping = mapping

    def Rlocation(self, path):  # noqa: N802 (mirrors the real API)
        if os.path.isabs(path):
            return path
        return self.mapping.get(path)


def _write_tool(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\nimport sys, os\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


REPORT_TABLE = """Filename                      Regions    Missed Regions     Cover   Functions  Missed Functions  Executed       Lines      Missed Lines     Cover
-------------------------------------------------------------------------------------------------------------------------------------------------------
/proc/self/cwd/src/a.cpp            4                 1    75.00%           1                 0   100.00%          10                 2    80.00%
/ws/src/b.cpp                       2                 2     0.00%           1                 1     0.00%           5                 5     0.00%
rust/lib.rs                         3                 0   100.00%           2                 0   100.00%           8                 0   100.00%
-------------------------------------------------------------------------------------------------------------------------------------------------------
TOTAL                               9                 3    66.67%           4                 1    75.00%          23                 7    69.57%
"""


def _fake_llvm_cov(path: Path) -> Path:
    """Fake llvm-cov: records argv, answers report/show/export plausibly."""
    body = f"""
args = sys.argv[1:]
with open(os.environ["FAKE_LLVM_COV_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
sub = args[0]
if sub == "report":
    sys.stdout.write({REPORT_TABLE!r})
elif sub == "export":
    empty = "--empty-profile" in args
    sys.stderr.write("warning: something cosmetic\\n")
    if empty:
        sys.stdout.write("SF:/ws/src/b.cpp\\nDA:1,0\\nLF:1\\nLH:0\\nend_of_record\\n")
    else:
        sys.stdout.write("SF:/ws/src/a.cpp\\nDA:1,1\\nLF:1\\nLH:1\\nend_of_record\\n")
elif sub == "show":
    out = [a for a in args if a.startswith("--output-dir=")][0].split("=", 1)[1]
    os.makedirs(os.path.join(out, "coverage", "ws", "src"), exist_ok=True)
    open(os.path.join(out, "index.html"), "w").write("<html>index</html>")
    open(os.path.join(out, "style.css"), "w").write("body {{}}")
    open(os.path.join(out, "coverage", "ws", "src", "a.cpp.html"), "w").write(
        "<div class='source-name-title'><pre>/ws/src/a.cpp</pre></div>")
else:
    sys.exit(2)
"""
    return _write_tool(path, body)


def _fake_llvm_profdata(path: Path) -> Path:
    return _write_tool(
        path,
        "args = sys.argv[1:]\nout = args[args.index('--output') + 1]\n"
        "open(out, 'wb').write(b''.join(open(i, 'rb').read() for i in args[args.index('--output') + 2:]))\n",
    )


class ReadReportsFileTest(unittest.TestCase):
    def test_blank_lines_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "reports.txt"
            f.write_text("a.zip\n\n  b.zip  \n", encoding="utf-8")
            self.assertEqual(reporter.read_reports_file(f), ["a.zip", "b.zip"])


class ExtractReportsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.obj = self.root / "libx.a"
        self.obj.write_bytes(b"!<arch>\n")
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def _zip(self, name, meta=None, profdata=b"PROF"):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as zf:
            if meta is not None:
                zf.writestr("meta/meta.json", json.dumps(meta))
            if profdata is not None:
                zf.writestr("profdata/target.profdata", profdata)
        return str(path)

    def test_valid_reports_are_extracted(self):
        good = self._zip("good.zip", {"object_files": [str(self.obj), str(self.root / "missing.a"), ""]})
        with redirect_stderr(io.StringIO()):
            profdata, objects = reporter.extract_reports([good])
        self.assertEqual(len(profdata), 1)
        self.assertTrue(Path(next(iter(profdata))).read_bytes() == b"PROF")
        self.assertEqual(objects, {os.path.realpath(self.obj)})

    def test_invalid_inputs_are_skipped(self):
        empty = self.root / "empty.zip"
        empty.write_bytes(b"")
        notzip = self.root / "notzip.zip"
        notzip.write_text("nope", encoding="utf-8")
        no_meta = self._zip("nometa.zip", meta=None)
        no_prof = self._zip("noprof.zip", meta={"object_files": []}, profdata=None)
        bad_json = self.root / "badjson.zip"
        with zipfile.ZipFile(bad_json, "w") as zf:
            zf.writestr("meta/meta.json", "{bad")
            zf.writestr("profdata/target.profdata", b"P")
        err = io.StringIO()
        with redirect_stderr(err):
            profdata, objects = reporter.extract_reports(
                [
                    str(empty),
                    str(notzip),
                    no_meta,
                    no_prof,
                    str(bad_json),
                    str(self.root / "missing.zip"),
                    str(self.root / "baseline_coverage.dat"),
                ]
            )
        self.assertEqual((profdata, objects), (set(), set()))
        self.assertEqual(err.getvalue().count("WARNING: Skipping invalid report"), 3)


class ResolveToolTest(unittest.TestCase):
    def test_preference_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "llvm-cov"
            real.write_text("", encoding="utf-8")
            fallback = Path(tmp) / "fallback-cov"
            fallback.write_text("", encoding="utf-8")
            rf = _FakeRunfiles({"toolchain/llvm-cov": str(real), "llvm_toolchain/llvm-cov": str(fallback)})
            self.assertEqual(reporter.resolve_tool(rf, "toolchain/llvm-cov", "llvm_toolchain/llvm-cov"), real)
            self.assertEqual(reporter.resolve_tool(rf, None, "llvm_toolchain/llvm-cov"), fallback)
            self.assertEqual(reporter.resolve_tool(rf, str(real), ""), real)  # plain path
            self.assertIsNone(reporter.resolve_tool(rf, "unknown", "also-unknown"))
            self.assertIsNone(reporter.resolve_tool(None, "unknown", ""))


class FindCxxfiltTest(unittest.TestCase):
    def test_explicit_then_sibling_then_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir()
            cov = root / "bin" / "llvm-cov"
            cov.write_text("", encoding="utf-8")
            explicit = root / "explicit-cxxfilt"
            explicit.write_text("", encoding="utf-8")
            rf = _FakeRunfiles({"x/llvm-cxxfilt": str(explicit)})
            self.assertEqual(reporter.find_cxxfilt(cov, rf, "x/llvm-cxxfilt"), str(explicit))
            sibling = root / "bin" / "llvm-cxxfilt"
            sibling.write_text("", encoding="utf-8")
            self.assertEqual(reporter.find_cxxfilt(cov, rf, None), str(sibling))
            sibling.unlink()
            self.assertEqual(reporter.find_cxxfilt(cov, rf, None), "")


class LoadAllowlistAndBaselineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_allowlist_comments_and_blank_lines_ignored(self):
        f = self.root / "allow.txt"
        f.write_text("# comment\nsrc/a.cpp\n\n  src/b.h \n", encoding="utf-8")
        rf = _FakeRunfiles({"main/allow.txt": str(f)})
        self.assertEqual(reporter.load_coverage_allowlist(rf, "main/allow.txt"), ["src/a.cpp", "src/b.h"])
        self.assertEqual(reporter.load_coverage_allowlist(rf, "missing"), [])

    def test_baseline_objects_resolved_via_main_repo(self):
        obj = self.root / "bazel-out" / "bin" / "libz.a"
        obj.parent.mkdir(parents=True)
        obj.write_bytes(b"")
        manifest = self.root / "objects.txt"
        manifest.write_text("# c\nbazel-out/bin/libz.a\n", encoding="utf-8")
        rf = _FakeRunfiles({"main/objects.txt": str(manifest), "_main/bazel-out/bin/libz.a": str(obj)})
        self.assertEqual(reporter.load_baseline_objects(rf, "main/objects.txt", "/ws"), [str(obj)])
        self.assertEqual(reporter.load_baseline_objects(rf, None, "/ws"), [])
        with redirect_stderr(io.StringIO()):
            self.assertEqual(reporter.load_baseline_objects(rf, "missing", "/ws"), [])

    def test_missing_baseline_object_is_a_hard_error(self):
        manifest = self.root / "objects.txt"
        manifest.write_text("bazel-out/bin/gone.a\n", encoding="utf-8")
        rf = _FakeRunfiles({"main/objects.txt": str(manifest), "_main/bazel-out/bin/gone.a": str(self.root / "gone")})
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                reporter.load_baseline_objects(rf, "main/objects.txt", "/ws")


class RunCommandTest(unittest.TestCase):
    def test_separate_stderr_keeps_stdout_clean(self):
        err = io.StringIO()
        with redirect_stderr(err):
            result = reporter.run_command(
                [sys.executable, "-c", "import sys; print('data'); print('warn', file=sys.stderr)"],
                separate_stderr=True,
            )
        self.assertEqual(result.stdout, "data\n")
        self.assertIn("warn", err.getvalue())

    def test_failure_exits(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                reporter.run_command([sys.executable, "-c", "import sys; sys.exit(4)"])


class LlvmCovInvocationsTest(unittest.TestCase):
    """The exact llvm-cov command lines, checked through the fake tool's log."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cov = _fake_llvm_cov(self.root / "llvm-cov")
        self.log = self.root / "log.txt"
        self.env = mock.patch.dict(os.environ, {"FAKE_LLVM_COV_LOG": str(self.log)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _last(self):
        return self.log.read_text(encoding="utf-8").splitlines()[-1].split(" ")

    def test_get_covered_files_normalises_paths(self):
        with redirect_stderr(io.StringIO()):
            files = reporter.get_covered_files(self.cov, ["/o/a.a", "/o/b.a"], None, "/ws/")
        self.assertEqual(files, {"src/a.cpp", "src/b.cpp", "rust/lib.rs"})
        argv = self._last()
        self.assertEqual(argv[:3], ["report", "--path-equivalence=/proc/self/cwd/,/ws/", "--empty-profile"])
        self.assertEqual(argv[3:], ["/o/a.a", "--object", "/o/b.a"])

    def test_show_html_flags(self):
        out = self.root / "html"
        with redirect_stderr(io.StringIO()):
            reporter.run_llvm_cov_show(
                self.cov, ["/o/a.a"], "/p/merged.profdata", ["src/x\\.cpp$"], "/ws", "html", out, cxxfilt="/bin/cxxfilt"
            )
        argv = self._last()
        for flag in [
            "show",
            "--format=html",
            "--compilation-dir=/ws",
            "--show-branches=count",
            "--Xdemangler=/bin/cxxfilt",
            "--ignore-filename-regex=src/x\\.cpp$",
            f"--output-dir={out}",
            "--coverage-watermark=100,50",
            "--show-expansions",
            "--instr-profile",
            "/p/merged.profdata",
        ]:
            self.assertIn(flag, argv)
        self.assertTrue((out / "index.html").is_file())

    def test_export_separates_stderr(self):
        err = io.StringIO()
        with redirect_stderr(err):
            result = reporter.run_llvm_cov_export(self.cov, ["/o/a.a"], "/p/m.profdata", [], "/ws")
        self.assertTrue(result.stdout.startswith("SF:"))
        self.assertNotIn("warning", result.stdout)
        self.assertIn("warning: something cosmetic", err.getvalue())
        self.assertIn("--format=lcov", self._last())

    def test_report_flags(self):
        with redirect_stderr(io.StringIO()):
            reporter.run_llvm_cov_report(self.cov, ["/o/a.a"], None, ["r$"], "/ws")
        argv = self._last()
        self.assertEqual(argv[0], "report")
        for flag in [
            "--show-region-summary=0",
            "--show-branch-summary=1",
            "--ignore-filename-regex=r$",
            "--empty-profile",
        ]:
            self.assertIn(flag, argv)


class ReporterMainTest(unittest.TestCase):
    """main() end to end with fake llvm tools and two per-test reports."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cov = _fake_llvm_cov(self.root / "llvm-cov")
        self.profdata = _fake_llvm_profdata(self.root / "llvm-profdata")
        self.log = self.root / "log.txt"
        self.obj = self.root / "test_bin"
        self.obj.write_bytes(b"\x7fELF")
        reports = []
        for i in range(2):
            z = self.root / f"t{i}.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("meta/meta.json", json.dumps({"object_files": [str(self.obj)]}))
                zf.writestr("profdata/target.profdata", f"P{i}".encode())
            reports.append(str(z))
        self.reports_file = self.root / "reports.txt"
        self.reports_file.write_text("\n".join(reports) + "\n", encoding="utf-8")
        self.allowlist = self.root / "allow.txt"
        self.allowlist.write_text("src/a.cpp\nsrc/b.cpp\n", encoding="utf-8")
        self.output = self.root / "out.zip"
        self.workdir = self.root / "work"
        self.workdir.mkdir()
        self.cwd = os.getcwd()
        os.chdir(self.workdir)
        self.env = mock.patch.dict(os.environ, {"FAKE_LLVM_COV_LOG": str(self.log)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def _argv(self, **extra):
        argv = [
            "--output_file",
            str(self.output),
            "--reports_file",
            str(self.reports_file),
            "--workspace_root",
            "/ws",
            "--llvm_cov",
            str(self.cov),
            "--llvm_profdata",
            str(self.profdata),
            "--coverage_allowlist",
            str(self.allowlist),
        ]
        for k, v in extra.items():
            argv += [f"--{k}", str(v)]
        return argv

    def test_full_report(self):
        err = io.StringIO()
        with redirect_stderr(err):
            reporter.main(self._argv())
        with zipfile.ZipFile(self.output) as zf:
            names = set(zf.namelist())
            lcov = zf.read("lcov_report/lcov.dat").decode()
            summary = zf.read("text_report/summary.txt").decode()
            page = zf.read("html_report/coverage/ws/src/a.cpp.html").decode()
        self.assertIn("html_report/index.html", names)
        self.assertIn("html_report/style.css", names)
        # SF paths are made workspace-relative, llvm-cov's stderr warning is not in the data.
        self.assertIn("SF:src/a.cpp\n", lcov)
        self.assertNotIn("warning", lcov)
        self.assertIn("TOTAL", summary)
        # HTML title rewritten to a relative path.
        self.assertIn("<pre>src/a.cpp</pre>", page)
        # The merged profdata combined both per-test inputs.
        self.assertEqual((self.workdir / "merged_coverage.profdata").read_bytes(), b"P0P1")
        # rust/lib.rs is not in the allowlist and must be excluded from the report.
        log = self.log.read_text(encoding="utf-8")
        self.assertIn("--ignore-filename-regex=rust/lib\\.rs$", log)
        self.assertIn("Using coverage allowlist with 2 source files", err.getvalue())

    def test_no_reports_writes_empty_zip(self):
        self.reports_file.write_text("", encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            reporter.main(self._argv())
        with zipfile.ZipFile(self.output) as zf:
            self.assertEqual(zf.namelist(), [])

    def test_invalid_reports_write_empty_zip(self):
        (self.root / "t0.zip").write_text("junk", encoding="utf-8")
        (self.root / "t1.zip").write_text("junk", encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            reporter.main(self._argv())
        with zipfile.ZipFile(self.output) as zf:
            self.assertEqual(zf.namelist(), [])

    def test_missing_llvm_tools_is_an_error(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                reporter.main(self._argv(llvm_cov=str(self.root / "nope")))
        self.assertEqual(ctx.exception.code, 1)

    def test_empty_allowlist_is_an_error(self):
        self.allowlist.write_text("# nothing\n", encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                reporter.main(self._argv())


if __name__ == "__main__":
    unittest.main()
