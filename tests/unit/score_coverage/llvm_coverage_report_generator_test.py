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
# Test modules: docstrings on every test method add nothing, tests exercise
# private helpers on purpose, TemporaryDirectory is closed in tearDown, and setUp
# fixtures are attributes.
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access,consider-using-with
# pylint: disable=too-many-instance-attributes

import io
import json
import os
import re
import stat
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from score_coverage import llvm_coverage_report_generator as reporter
from score_coverage.llvm_coverage_report_generator import (
    _filter_lcov,
    _make_html_paths_relative,
    _make_lcov_paths_relative,
    _read_ar_members,
    expand_rlib_archives,
)
from tests.unit.score_coverage.traceability import verifies


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


def _make_elf(section_names) -> bytes:
    """Build a minimal ELF64 relocatable object whose section table names ``section_names``."""
    names = [".shstrtab"] + list(section_names)
    strtab = b"\x00"
    name_offsets = []
    for name in names:
        name_offsets.append(len(strtab))
        strtab += name.encode() + b"\x00"
    shnum = len(names) + 1  # + the null section
    shoff = 64 + len(strtab)
    shoff += (-shoff) % 8
    header = (
        b"\x7fELF"
        + bytes([2, 1, 1, 0])  # ELFCLASS64, little endian, version 1, SysV ABI
        + b"\x00" * 8
        + (1).to_bytes(2, "little")  # ET_REL
        + (0x3E).to_bytes(2, "little")  # x86-64
        + (1).to_bytes(4, "little")
        + (0).to_bytes(8, "little")  # e_entry
        + (0).to_bytes(8, "little")  # e_phoff
        + shoff.to_bytes(8, "little")
        + (0).to_bytes(4, "little")  # e_flags
        + (64).to_bytes(2, "little")  # e_ehsize
        + (0).to_bytes(2, "little")  # e_phentsize
        + (0).to_bytes(2, "little")  # e_phnum
        + (64).to_bytes(2, "little")  # e_shentsize
        + shnum.to_bytes(2, "little")
        + (1).to_bytes(2, "little")  # e_shstrndx
    )
    assert len(header) == 64
    blob = header + strtab
    blob += b"\x00" * (shoff - len(blob))

    def shdr(name_off, offset, size):
        return (
            name_off.to_bytes(4, "little")
            + (1).to_bytes(4, "little")  # SHT_PROGBITS
            + (0).to_bytes(8, "little")
            + (0).to_bytes(8, "little")
            + offset.to_bytes(8, "little")
            + size.to_bytes(8, "little")
            + (0).to_bytes(4, "little")
            + (0).to_bytes(4, "little")
            + (1).to_bytes(8, "little")
            + (0).to_bytes(8, "little")
        )

    blob += b"\x00" * 64  # null section
    blob += shdr(name_offsets[0], 64, len(strtab))  # .shstrtab
    for name_off in name_offsets[1:]:
        blob += shdr(name_off, 0, 0)
    return blob


COVMAP_OBJ = _make_elf([".text", "__llvm_covmap", "__llvm_covfun"])
PLAIN_OBJ = _make_elf([".text", "__llvm_covfun"])


@verifies("tool_req__coverage_report_rlib_expansion")
class ReadArMembersTest(unittest.TestCase):
    def test_non_archive_returns_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".a") as f:
            f.write(b"\x7fELF not an archive")
            f.flush()
            self.assertEqual(_read_ar_members(f.name), [])

    def test_members_are_listed_with_sizes(self):
        # "/" is the GNU symbol table, not a member
        blob = _make_archive([("/", b"SYMS"), ("lib.rmeta/", b"META"), ("foo.o/", b"OBJDATA")])
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


@verifies("tool_req__coverage_report_rlib_expansion")
class ObjectHasCovmapTest(unittest.TestCase):
    def test_detects_the_section_by_name(self):
        self.assertTrue(reporter.object_has_covmap(COVMAP_OBJ))
        self.assertFalse(reporter.object_has_covmap(PLAIN_OBJ))
        self.assertFalse(reporter.object_has_covmap(_make_elf([".text", "__llvm_covmap_not"])))

    def test_non_elf_and_truncated_input(self):
        self.assertFalse(reporter.object_has_covmap(b"META"))
        self.assertFalse(reporter.object_has_covmap(b""))
        self.assertFalse(reporter.object_has_covmap(b"\x7fELF" + b"\x01" * 60))  # ELFCLASS32
        self.assertFalse(reporter.object_has_covmap(COVMAP_OBJ[:100]))  # section table cut off


@verifies("tool_req__coverage_report_rlib_expansion", "tool_req__coverage_report_baseline_zero")
class ExpandBaselineArchivesTest(unittest.TestCase):
    """llvm-cov gets only archive members that carry a coverage mapping."""

    def _expand(self, tmp, name, members, short_path=None):
        archive = Path(tmp) / name
        archive.write_bytes(_make_archive(members))
        manifest = {str(archive): short_path or f"pkg/{name}"}
        return reporter.expand_baseline_archives(manifest, Path(tmp) / "extracted"), archive

    def test_rlib_is_expanded_to_object_members(self):
        """lib.rmeta has no mapping, so the rlib is replaced by its .o members."""
        with tempfile.TemporaryDirectory() as tmp:
            (result, empty), _ = self._expand(
                tmp, "libcrate.a", [("lib.rmeta/", b"META"), ("crate.rcgu.o/", COVMAP_OBJ), ("notes.txt/", b"TXT")]
            )
            self.assertEqual(len(result), 1)
            self.assertTrue(result[0].endswith(".o"))
            self.assertEqual(Path(result[0]).read_bytes(), COVMAP_OBJ)
            self.assertEqual(empty, set())  # rlib codegen units are not sources

    def test_plain_cc_archive_passes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            (result, compiled), archive = self._expand(
                tmp, "libcc.a", [("/", b"SYMS"), ("mylib.o/", COVMAP_OBJ), ("other.o/", COVMAP_OBJ)]
            )
            self.assertEqual(result, [str(archive)])  # the symbol table is not a member without mapping
            self.assertEqual(compiled, {"pkg/mylib", "pkg/other"})

    def test_member_without_mapping_is_dropped_and_the_rest_kept(self):
        """The empty placeholder object would make llvm-cov reject the whole archive."""
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with redirect_stderr(err):
                (result, empty), _ = self._expand(
                    tmp,
                    "libuncovered.a",
                    [("empty_unit.o/", PLAIN_OBJ), ("uncovered.o/", COVMAP_OBJ)],
                    short_path="src/libuncovered.a",
                )
            self.assertEqual(len(result), 1)
            self.assertEqual(Path(result[0]).read_bytes(), COVMAP_OBJ)
            self.assertEqual(empty, {"src/empty_unit", "src/uncovered"})  # both were compiled
            self.assertIn("1 baseline archive(s) had members without a coverage mapping", err.getvalue())

    def test_archive_without_any_mapping_contributes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stderr(io.StringIO()):
                (result, empty), _ = self._expand(
                    tmp, "libexecutor.a", [("executor.o/", PLAIN_OBJ), ("task.o/", PLAIN_OBJ)], "score/c/libexecutor.a"
                )
            self.assertEqual(result, [])
            self.assertEqual(empty, {"score/c/executor", "score/c/task"})

    def test_executable_passes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "my_tool"
            binary.write_bytes(b"\x7fELF" + b"\x00" * 12)
            result, empty = reporter.expand_baseline_archives({str(binary): "pkg/my_tool"}, Path(tmp) / "x")
            self.assertEqual(result, [str(binary)])
            self.assertEqual(empty, set())
            # the plain-list wrapper keeps working
            self.assertEqual(expand_rlib_archives([str(binary)], Path(tmp) / "y"), [str(binary)])


@verifies("tool_req__coverage_report_baseline_zero")
class FilterLcovTest(unittest.TestCase):
    LCOV = "SF:src/foo.cpp\nDA:1,1\nLF:1\nLH:1\nend_of_record\nSF:src/bar.cpp\nDA:1,0\nLF:1\nLH:0\nend_of_record\n"

    def test_only_target_records_survive(self):
        result = _filter_lcov(self.LCOV, {"src/bar.cpp"})
        self.assertIn("SF:src/bar.cpp", result)
        self.assertNotIn("SF:src/foo.cpp", result)

    def test_suffix_matching(self):
        result = _filter_lcov("SF:/abs/prefix/src/foo.cpp\nend_of_record\n", {"src/foo.cpp"})
        self.assertIn("SF:/abs/prefix/src/foo.cpp", result)


@verifies("tool_req__coverage_report_relative_paths")
class MakeLcovPathsRelativeTest(unittest.TestCase):
    def test_workspace_paths_become_relative(self):
        lcov = "SF:/ws/root/src/foo.cpp\nDA:1,1\nend_of_record\n"
        result = _make_lcov_paths_relative(lcov, "/ws/root/")
        self.assertEqual(result, "SF:src/foo.cpp\nDA:1,1\nend_of_record\n")

    def test_workspace_root_without_trailing_slash(self):
        lcov = "SF:/ws/root/src/foo.cpp\nend_of_record\n"
        result = _make_lcov_paths_relative(lcov, "/ws/root")
        self.assertEqual(result, "SF:src/foo.cpp\nend_of_record\n")

    def test_proc_self_cwd_prefix_and_path_map(self):
        lcov = (
            "SF:/proc/self/cwd/src/a.cpp\nend_of_record\n"
            "SF:/ws/bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h\nend_of_record\n"
        )
        self.assertEqual(
            reporter._make_lcov_paths_relative(lcov, "/ws", {"src/_virtual_includes/v/api.h": "src/v/api.h"}),
            "SF:src/a.cpp\nend_of_record\nSF:src/v/api.h\nend_of_record\n",
        )

    def test_external_paths_are_unchanged(self):
        lcov = "SF:/other/place/dep.cpp\nend_of_record\n"
        self.assertEqual(_make_lcov_paths_relative(lcov, "/ws/root/"), lcov)

    def test_non_sf_lines_are_preserved(self):
        lcov = "TN:test\nSF:/ws/root/a.cpp\nDA:5,0\nLF:1\nLH:0\nend_of_record\n"
        result = _make_lcov_paths_relative(lcov, "/ws/root/")
        self.assertIn("TN:test\n", result)
        self.assertIn("DA:5,0\n", result)


@verifies("tool_req__coverage_report_relative_paths")
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


# ---------------------------------------------------------------------------
# Added for the score_coverage qualification: helpers around llvm-cov and an
# end-to-end run of main() against fake llvm tools.
# ---------------------------------------------------------------------------


class _FakeRunfiles:
    """Minimal stand-in for python.runfiles.Runfiles: maps rlocation paths to files."""

    def __init__(self, mapping):
        self.mapping = mapping

    def Rlocation(self, path):  # noqa: N802  # pylint: disable=invalid-name
        if os.path.isabs(path):
            return path
        return self.mapping.get(path)


def _write_tool(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\nimport sys, os\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


REPORT_TABLE = """Filename                     Regions  Missed   Cover  Functions  Missed  Executed  Lines  Missed Cover
-------------------------------------------------------------------------------------------------------
/proc/self/cwd/src/a.cpp           4       1  75.00%          1       0   100.00%     10       2  80.00%
/ws/src/b.cpp                      2       2   0.00%          1       1     0.00%      5       5   0.00%
rust/lib.rs                        3       0 100.00%          2       0   100.00%      8       0 100.00%
bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h  2  0 100.00%  1  0  100.00%  3  0 100.00%
bazel-out/k8-fastbuild/bin/src/_virtual_includes/twin/w/w.h  2  0 100.00%  1  0  100.00%  3  0 100.00%
-------------------------------------------------------------------------------------------------------
TOTAL                              9       3  66.67%          4       1    75.00%     23       7  69.57%
"""


# The same data once a system header is part of it: llvm-cov report strips the
# longest common directory prefix, which is now "/", from every displayed name.
ROOT_RELATIVE_REPORT_TABLE = """\
Filename                     Regions  Missed   Cover  Functions  Missed  Executed  Lines  Missed Cover
-------------------------------------------------------------------------------------------------------
proc/self/cwd/src/a.cpp            4       1  75.00%          1       0   100.00%     10       2  80.00%
ws/src/b.cpp                       2       2   0.00%          1       1     0.00%      5       5   0.00%
usr/include/c++/13/vector          3       0 100.00%          2       0   100.00%      8       0 100.00%
proc/self/cwd/bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h  2  0 100.00%  1  0  100.00%  3  0 100.00%
-------------------------------------------------------------------------------------------------------
TOTAL                              9       3  66.67%          4       1    75.00%     23       7  69.57%
"""


def _fake_llvm_cov(path: Path) -> Path:
    """Fake llvm-cov: records argv, answers report/show/export plausibly."""
    body = f"""
args = sys.argv[1:]
with open(os.environ["FAKE_LLVM_COV_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
sub = args[0]
if sub == "report":
    sys.stdout.write(os.environ.get("FAKE_LLVM_COV_TABLE") or {REPORT_TABLE!r})
elif sub == "export":
    empty = "--empty-profile" in args
    root = [a for a in args if a.startswith("--path-equivalence=")][0].split(",", 1)[1].rstrip("/")
    sys.stderr.write("warning: something cosmetic\\n")
    if empty:
        sys.stdout.write("SF:" + root + "/src/b.cpp\\nDA:1,0\\nLF:1\\nLH:0\\nend_of_record\\n")
    else:
        sys.stdout.write("SF:" + root + "/src/a.cpp\\nDA:1,1\\nLF:1\\nLH:1\\nend_of_record\\n")
elif sub == "show":
    out = [a for a in args if a.startswith("--output-dir=")][0].split("=", 1)[1]
    root = [a for a in args if a.startswith("--path-equivalence=")][0].split(",", 1)[1].strip("/")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "style.css"), "w").write("body {{}}")
    open(os.path.join(out, "control.js"), "w").write("")
    rows = []
    for rel in ("src/a.cpp", "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h"):
        page = os.path.join(out, "coverage", root, rel + ".html")
        os.makedirs(os.path.dirname(page), exist_ok=True)
        up = "../" * len(os.path.relpath(os.path.dirname(page), out).split(os.sep))
        open(page, "w").write(
            "<html><head><link rel='stylesheet' type='text/css' href='" + up + "style.css'>"
            "<script src='" + up + "control.js'></script></head><body>"
            "<div class='source-name-title'><pre>/" + root + "/" + rel + "</pre></div></body></html>")
        rows.append("<td><pre><a href='coverage/" + root + "/" + rel + ".html'>" + rel + "</a></pre></td>")
    open(os.path.join(out, "index.html"), "w").write(
        "<html><head><link rel='stylesheet' type='text/css' href='style.css'></head>"
        "<table>" + "".join(rows) + "</table></html>")
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


class ReportRecognitionTest(unittest.TestCase):
    """Archive recognition belongs to the LLVM backend, including non-ZIP rejection."""

    def test_lcov_is_not_an_llvm_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "coverage.dat"
            report.write_text("SF:src/a.cpp\nDA:1,1\nend_of_record\n", encoding="utf-8")
            self.assertFalse(reporter.is_coverage_report(report))


@verifies("tool_req__coverage_report_merged_profile", derivation="error-guessing")
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
        return path

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
                    empty,
                    notzip,
                    no_meta,
                    no_prof,
                    bad_json,
                    self.root / "missing.zip",
                    self.root / "baseline_coverage.dat",
                ]
            )
        self.assertEqual((profdata, objects), (set(), set()))
        self.assertEqual(err.getvalue().count("WARNING: Skipping invalid report"), 3)


@verifies("tool_req__coverage_report_outputs")
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


@verifies("tool_req__coverage_report_missing_baseline")
class LoadBaselineObjectsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_baseline_objects_resolved_via_main_repo(self):
        obj = self.root / "bazel-out" / "bin" / "libz.a"
        obj.parent.mkdir(parents=True)
        obj.write_bytes(b"")
        manifest = self.root / "objects.txt"
        manifest.write_text("# c\nbazel-out/bin/libz.a\n", encoding="utf-8")
        rf = _FakeRunfiles({"main/objects.txt": str(manifest), "_main/bazel-out/bin/libz.a": str(obj)})
        self.assertEqual(reporter.load_baseline_objects(rf, "main/objects.txt"), [str(obj)])
        self.assertEqual(reporter.load_baseline_objects(rf, None), [])
        with redirect_stderr(io.StringIO()):
            self.assertEqual(reporter.load_baseline_objects(rf, "missing"), [])

    def test_missing_baseline_object_is_a_hard_error(self):
        manifest = self.root / "objects.txt"
        manifest.write_text("bazel-out/bin/gone.a\n", encoding="utf-8")
        rf = _FakeRunfiles({"main/objects.txt": str(manifest), "_main/bazel-out/bin/gone.a": str(self.root / "gone")})
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            reporter.load_baseline_objects(rf, "main/objects.txt")


@verifies("tool_req__coverage_report_outputs", test_type="fault-injection", derivation="error-guessing")
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
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            reporter.run_command([sys.executable, "-c", "import sys; sys.exit(4)"])


def _index(rows: list[tuple[str, str, str, str]], totals: tuple[str, str, str]) -> str:
    def cell(value: str) -> str:
        colour = "gray" if value.startswith("-") else ("red" if value.startswith("   0") else "yellow")
        return f"<td class='column-entry-{colour}'><pre>{value}</pre></td>"

    body = "".join(
        f"<tr class='light-row'><td><pre><a href='coverage/{name}.html'>{name}</a></pre></td>"
        + cell(fn)
        + cell(ln)
        + cell(br)
        + "</tr>"
        for name, fn, ln, br in rows
    )
    tot = "<tr class='light-row-bold'><td><pre>Totals</pre></td>" + "".join(cell(v) for v in totals) + "</tr>"
    head = "<html><body><table><tr><td class='column-entry-bold'>Filename</td></tr>"
    return head + body + tot + "</table></body></html>"


@verifies("tool_req__coverage_report_baseline_zero")
class MergeBaselineHtmlTest(unittest.TestCase):
    """Baseline-only pages come from their own --empty-profile run and are spliced into the index."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.html = Path(self.tmp.name) / "html"
        self.base = Path(self.tmp.name) / "baseline"
        for d in (self.html / "coverage" / "src", self.base / "coverage" / "src"):
            d.mkdir(parents=True)
        (self.html / "index.html").write_text(
            _index(
                [("src/a.cpp", "  50.00% (1/2)", "  80.00% (8/10)", "- (0/0)")],
                ("  50.00% (1/2)", "  80.00% (8/10)", "- (0/0)"),
            ),
            encoding="utf-8",
        )
        (self.html / "coverage" / "src" / "a.cpp.html").write_text("page a", encoding="utf-8")
        (self.base / "index.html").write_text(
            _index(
                [
                    ("src/a.cpp", "   0.00% (0/2)", "   0.00% (0/10)", "- (0/0)"),  # also covered by tests: not taken
                    ("src/main.cpp", "   0.00% (0/1)", "   0.00% (0/3)", "- (0/0)"),
                    ("src/other.cpp", "   0.00% (0/1)", "   0.00% (0/4)", "   0.00% (0/2)"),  # not baseline-only
                ],
                ("   0.00% (0/4)", "   0.00% (0/17)", "   0.00% (0/2)"),
            ),
            encoding="utf-8",
        )
        for name in ("a", "main", "other"):
            (self.base / "coverage" / "src" / f"{name}.cpp.html").write_text(f"baseline page {name}", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_baseline_only_rows_and_pages_are_added_and_totals_recomputed(self):
        added = reporter.merge_baseline_html(self.html, self.base, {"src/main.cpp", "src/a.cpp"})
        self.assertEqual(added, 1)
        index = (self.html / "index.html").read_text(encoding="utf-8")
        rows = reporter._index_rows(index)
        self.assertEqual(list(rows), ["src/a.cpp", "src/main.cpp"])
        self.assertIn("<a href='coverage/src/main.cpp.html'>src/main.cpp</a>", index)
        self.assertIn("   0.00% (0/3)", rows["src/main.cpp"])
        # Totals over both rows: functions 1/3, lines 8/13, branches 0/0.
        match = reporter._INDEX_TOTALS_RE.search(index)
        self.assertIsNotNone(match)
        assert match is not None  # for the type checker
        totals = match.group(0)
        self.assertIn("  33.33% (1/3)", totals)
        self.assertIn("  61.54% (8/13)", totals)
        self.assertIn("- (0/0)", totals)
        # The test-covered page is untouched, the baseline page moved in.
        self.assertEqual((self.html / "coverage" / "src" / "a.cpp.html").read_text(encoding="utf-8"), "page a")
        self.assertEqual(
            (self.html / "coverage" / "src" / "main.cpp.html").read_text(encoding="utf-8"), "baseline page main"
        )
        self.assertFalse((self.html / "coverage" / "src" / "other.cpp.html").exists())

    def test_nothing_to_add_leaves_the_index_alone(self):
        before = (self.html / "index.html").read_text(encoding="utf-8")
        self.assertEqual(reporter.merge_baseline_html(self.html, self.base, {"src/a.cpp"}), 0)
        self.assertEqual((self.html / "index.html").read_text(encoding="utf-8"), before)

    def test_index_cell_follows_the_watermark(self):
        self.assertIn("column-entry-green", reporter._index_cell(3, 3))
        self.assertIn("column-entry-yellow", reporter._index_cell(1, 2))
        self.assertIn("column-entry-red", reporter._index_cell(0, 3))
        self.assertEqual(reporter._index_cell(0, 0), "<td class='column-entry-gray'><pre>- (0/0)</pre></td>")


@verifies(
    "tool_req__coverage_report_allowlist",
    "tool_req__coverage_report_baseline_zero",
    "tool_req__coverage_report_outputs",
)
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
        # raw (workspace-root / /proc/self/cwd/ stripped) -> normalized (config prefix stripped)
        self.assertEqual(
            files,
            {
                "src/a.cpp": "src/a.cpp",
                "src/b.cpp": "src/b.cpp",
                "rust/lib.rs": "rust/lib.rs",
                "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h": "src/_virtual_includes/v/api.h",
                "bazel-out/k8-fastbuild/bin/src/_virtual_includes/twin/w/w.h": "src/_virtual_includes/twin/w/w.h",
            },
        )
        argv = self._last()
        self.assertEqual(argv[:3], ["report", "--path-equivalence=/proc/self/cwd/,/ws/", "--empty-profile"])
        self.assertEqual(argv[3:], ["/o/a.a", "--object", "/o/b.a"])

    def test_get_covered_files_restores_names_displayed_relative_to_the_root(self):
        """A system header in the data makes llvm-cov drop the leading slash of every name."""
        with (
            mock.patch.dict(os.environ, {"FAKE_LLVM_COV_TABLE": ROOT_RELATIVE_REPORT_TABLE}),
            redirect_stderr(io.StringIO()),
        ):
            files = reporter.get_covered_files(self.cov, ["/o/a.a"], None, "/ws/")
        self.assertEqual(
            files,
            {
                "src/a.cpp": "src/a.cpp",
                "src/b.cpp": "src/b.cpp",
                # Outside the workspace: kept absolute so the exclusion regex matches the covmap name.
                "/usr/include/c++/13/vector": "/usr/include/c++/13/vector",
                "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h": "src/_virtual_includes/v/api.h",
            },
        )

    def test_get_covered_files_applies_the_path_map(self):
        with redirect_stderr(io.StringIO()):
            files = reporter.get_covered_files(
                self.cov, ["/o/a.a"], None, "/ws/", {"src/_virtual_includes/v/api.h": "src/v/api.h"}
            )
        self.assertEqual(files["bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h"], "src/v/api.h")
        self.assertEqual(files["src/a.cpp"], "src/a.cpp")

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


@verifies(
    "tool_req__coverage_report_merged_profile",
    "tool_req__coverage_report_allowlist",
    "tool_req__coverage_report_relative_paths",
    "tool_req__coverage_report_outputs",
)
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
            page = zf.read("html_report/coverage/src/a.cpp.html").decode()
            index = zf.read("html_report/index.html").decode()
        self.assertIn("html_report/index.html", names)
        self.assertIn("html_report/style.css", names)
        # Every in-scope file has data here, so the unmapped list exists and is empty.
        self.assertIn("text_report/unmapped_files.txt", names)
        # Pages are filed under canonical paths: no machine-specific directory
        # remains, the index links there, and the page's asset links still resolve.
        self.assertNotIn("html_report/coverage/" + str(self.workdir).strip("/") + "/", "\n".join(names))
        self.assertIn("<a href='coverage/src/a.cpp.html'>src/a.cpp</a>", index)
        self.assertIn("href='../../style.css'", page)
        self.assertIn("src='../../control.js'", page)
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
        self.assertIn(f"--ignore-filename-regex=^(/proc/self/cwd/|/ws/|{self.workdir}/sources/)?rust/lib\\.rs$", log)
        # llvm-cov reads the sources through the staging directory, not the workspace.
        self.assertIn(f"--path-equivalence=/proc/self/cwd/,{self.workdir}/sources", log)
        self.assertIn(f"--compilation-dir={self.workdir}/sources", log)
        self.assertIn("Using coverage allowlist with 2 source files", err.getvalue())

    def test_path_map_files_headers_under_declared_path(self):
        # The scope maps the generated virtual-includes path to the declared
        # header; the page, the index link and the LCOV use the declared path.
        self.allowlist.write_text("src/a.cpp\nsrc/v/api.h\n", encoding="utf-8")
        path_map = self.root / "map.txt"
        path_map.write_text("src/_virtual_includes/v/api.h\tsrc/v/api.h\n", encoding="utf-8")
        ws = self.root / "ws"
        (ws / "src" / "v").mkdir(parents=True)
        (ws / "src" / "a.cpp").write_text("int a;\n", encoding="utf-8")
        (ws / "src" / "v" / "api.h").write_text("int api();\n", encoding="utf-8")
        argv = self._argv(path_map=str(path_map))
        argv[argv.index("--workspace_root") + 1] = str(ws)
        err = io.StringIO()
        with redirect_stderr(err):
            reporter.main(argv)
        with zipfile.ZipFile(self.output) as zf:
            names = set(zf.namelist())
            index = zf.read("html_report/index.html").decode()
            page = zf.read("html_report/coverage/src/v/api.h.html").decode()
        self.assertIn("html_report/coverage/src/v/api.h.html", names)
        self.assertNotIn("html_report/coverage/src/_virtual_includes/v/api.h.html", names)
        self.assertIn("<a href='coverage/src/v/api.h.html'>src/v/api.h</a>", index)
        self.assertIn("<pre>src/v/api.h</pre>", page)
        self.assertIn("href='../../../style.css'", page)
        # The header is in scope: no exclusion regex names it, and its source
        # was staged under the raw covmap path for llvm-cov to read.
        log = self.log.read_text(encoding="utf-8")
        self.assertNotIn("api", "\n".join(a for a in log.split() if a.startswith("--ignore-filename-regex")))
        staged = self.workdir / "sources" / "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h"
        self.assertTrue(staged.is_symlink())
        self.assertEqual(os.path.realpath(staged), os.path.realpath(ws / "src" / "v" / "api.h"))
        self.assertTrue((self.workdir / "sources" / "src" / "a.cpp").is_symlink())
        self.assertIn("1 headers behind include prefixes", err.getvalue())

    def test_in_scope_file_without_coverage_data_is_listed(self):
        self.allowlist.write_text("src/a.cpp\nsrc/a.h\nsrc/b.cpp\nsrc/never.h\n", encoding="utf-8")
        err = io.StringIO()
        with redirect_stderr(err):
            reporter.main(self._argv())
        with zipfile.ZipFile(self.output) as zf:
            self.assertEqual(
                zf.read("text_report/unmapped_files.txt").decode(),
                "declaration-only\tsrc/a.h\nno-data\tsrc/never.h\n",
            )
        self.assertIn("1 in-scope files have no coverage data at all", err.getvalue())
        self.assertIn("src/never.h", err.getvalue())
        self.assertIn("1 in-scope headers hold declarations only", err.getvalue())

    def test_foreign_virtual_include_is_resolved_against_the_allowlist(self):
        # No path map entry for the "twin" tree (its target is outside the
        # scope), but the allowlist has the declared header: resolved by tail.
        self.allowlist.write_text("src/a.cpp\nsrc/w/include/w/w.h\n", encoding="utf-8")
        ws = self.root / "ws"
        (ws / "src" / "w" / "include" / "w").mkdir(parents=True)
        (ws / "src" / "w" / "include" / "w" / "w.h").write_text("int w();\n", encoding="utf-8")
        argv = self._argv()
        argv[argv.index("--workspace_root") + 1] = str(ws)
        err = io.StringIO()
        with redirect_stderr(err):
            reporter.main(argv)
        self.assertIn("1 headers reached through virtual-include trees of targets outside the scope", err.getvalue())
        log = self.log.read_text(encoding="utf-8")
        self.assertNotIn("twin", "\n".join(a for a in log.split() if a.startswith("--ignore-filename-regex")))
        staged = self.workdir / "sources" / "bazel-out/k8-fastbuild/bin/src/_virtual_includes/twin/w/w.h"
        self.assertEqual(os.path.realpath(staged), os.path.realpath(ws / "src/w/include/w/w.h"))

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
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            reporter.main(self._argv(llvm_cov=str(self.root / "nope")))
        self.assertEqual(ctx.exception.code, 1)

    def test_empty_allowlist_is_an_error(self):
        self.allowlist.write_text("# nothing\n", encoding="utf-8")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            reporter.main(self._argv())


@verifies("tool_req__coverage_report_allowlist")
class ExclusionRegexTest(unittest.TestCase):
    """--ignore-filename-regex must hit exactly one compiled file."""

    def _matches(self, regex, filename):
        # llvm-cov uses POSIX ERE; the pattern must not need Python-only syntax.
        self.assertNotIn("(?", regex)
        return re.search(regex, filename) is not None

    def test_matches_the_raw_path_under_every_known_prefix(self):
        regex = reporter.exclusion_regex("foo/bar.h", ["/ws/", "/work/sources"])
        for filename in ("/proc/self/cwd/foo/bar.h", "/ws/foo/bar.h", "/work/sources/foo/bar.h", "foo/bar.h"):
            self.assertTrue(self._matches(regex, filename), filename)

    def test_does_not_hit_a_longer_in_scope_path_with_the_same_suffix(self):
        regex = reporter.exclusion_regex("foo/bar.h", ["/ws"])
        for filename in ("/proc/self/cwd/src/foo/bar.h", "src/foo/bar.h", "/ws/src/foo/bar.h", "foo/bar.hpp"):
            self.assertFalse(self._matches(regex, filename), filename)

    def test_special_characters_are_literal(self):
        regex = reporter.exclusion_regex("external/openssl+/crypto/x.h", ["/ws"])
        self.assertTrue(self._matches(regex, "/proc/self/cwd/external/openssl+/crypto/x.h"))
        self.assertFalse(self._matches(regex, "/proc/self/cwd/external/opensslX/crypto/x.h"))


@verifies("tool_req__coverage_report_relative_paths", "tool_req__coverage_report_outputs")
class RelocateHtmlPagesTest(unittest.TestCase):
    """llvm-cov pages move from coverage/<abs source root>/<raw>.html to coverage/<canonical>.html."""

    ROOT = "/tmp/work/sources"

    def _page(self, html_dir, rel, depth):
        page = html_dir / "coverage" / self.ROOT.strip("/") / (rel + ".html")
        page.parent.mkdir(parents=True, exist_ok=True)
        up = "../" * depth
        page.write_text(
            f"<link rel='stylesheet' type='text/css' href='{up}style.css'><script src='{up}control.js'></script>"
            f"<div class='source-name-title'><pre>{self.ROOT}/{rel}</pre></div>",
            encoding="utf-8",
        )
        return page

    def test_pages_index_and_asset_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_dir = Path(tmp)
            (html_dir / "style.css").write_text("", encoding="utf-8")
            (html_dir / "control.js").write_text("", encoding="utf-8")
            raw_v = "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h"
            self._page(html_dir, "src/a.cpp", 6)
            self._page(html_dir, raw_v, 10)
            self._page(html_dir, "external/ext+/inc/x.h", 8)
            (html_dir / "index.html").write_text(
                "<table>"
                f"<td><pre><a href='coverage/tmp/work/sources/src/a.cpp.html'>src/a.cpp</a></pre></td>"
                f"<td><pre><a href='coverage/tmp/work/sources/{raw_v}.html'>{raw_v}</a></pre></td>"
                f"<td><pre><a href='coverage/tmp/work/sources/external/ext+/inc/x.h.html'>external/ext+/inc/x.h</a>"
                "</pre></td>"
                "<td><pre><a href='coverage/tmp/work/sources/src/missing.cpp.html'>src/missing.cpp</a></pre></td>"
                "</table>",
                encoding="utf-8",
            )
            moves = reporter.relocate_html_pages(html_dir, self.ROOT, {"src/_virtual_includes/v/api.h": "src/v/api.h"})
            reporter._make_html_paths_relative(html_dir, self.ROOT, {"src/_virtual_includes/v/api.h": "src/v/api.h"})

            self.assertEqual(
                moves,
                {
                    "coverage/tmp/work/sources/src/a.cpp.html": "coverage/src/a.cpp.html",
                    f"coverage/tmp/work/sources/{raw_v}.html": "coverage/src/v/api.h.html",
                    "coverage/tmp/work/sources/external/ext+/inc/x.h.html": "coverage/external/ext+/inc/x.h.html",
                },
            )
            self.assertFalse((html_dir / "coverage" / "tmp").exists())
            a = (html_dir / "coverage/src/a.cpp.html").read_text(encoding="utf-8")
            self.assertIn("href='../../style.css'", a)
            self.assertIn("src='../../control.js'", a)
            self.assertIn("<pre>src/a.cpp</pre>", a)
            v = (html_dir / "coverage/src/v/api.h.html").read_text(encoding="utf-8")
            self.assertIn("href='../../../style.css'", v)
            self.assertIn("<pre>src/v/api.h</pre>", v)
            x = (html_dir / "coverage/external/ext+/inc/x.h.html").read_text(encoding="utf-8")
            self.assertIn("href='../../../../style.css'", x)
            index = (html_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("<a href='coverage/src/a.cpp.html'>src/a.cpp</a>", index)
            self.assertIn("<a href='coverage/src/v/api.h.html'>src/v/api.h</a>", index)
            self.assertIn("<a href='coverage/external/ext+/inc/x.h.html'>external/ext+/inc/x.h</a>", index)
            self.assertNotIn("tmp/work/sources", index)
            self.assertIn("<td><pre>src/missing.cpp</pre></td>", index)
            # every link resolves
            for href in re.findall(r"href='(coverage/[^']+)'", index):
                self.assertTrue((html_dir / href).is_file(), href)

    def test_second_page_for_the_same_file_is_dropped_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_dir = Path(tmp)
            self._page(html_dir, "src/v/api.h", 7)
            self._page(html_dir, "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h", 10)
            (html_dir / "index.html").write_text("", encoding="utf-8")
            err = io.StringIO()
            with redirect_stderr(err):
                reporter.relocate_html_pages(html_dir, self.ROOT, {"src/_virtual_includes/v/api.h": "src/v/api.h"})
            self.assertEqual(sorted(p.name for p in (html_dir / "coverage").rglob("*.html")), ["api.h.html"])
            self.assertIn("rendered twice", err.getvalue())

    def test_missing_coverage_dir_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(reporter.relocate_html_pages(Path(tmp), self.ROOT, {}), {})


@verifies("tool_req__coverage_report_relative_paths")
class SummaryCanonicalizationTest(unittest.TestCase):
    """Name files consistently in the LLVM text summary."""

    def test_summary_names_are_canonical_and_aligned(self):
        text = (
            "Filename                     Regions\n"
            "-------------------------------------\n"
            "/tmp/work/sources/src/a.cpp        4\n"
            "/proc/self/cwd/bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h  2\n"
            "rust/lib.rs                        3\n"
            "TOTAL                              9\n"
        )
        path_map = {"src/_virtual_includes/v/api.h": "src/v/api.h"}
        out = reporter._canonicalize_summary(text, "/tmp/work/sources", path_map)
        lines = out.splitlines()
        padding = " " * (len("/tmp/work/sources/src/a.cpp") - len("src/a.cpp"))
        self.assertEqual(lines[2], "src/a.cpp" + padding + "        4")
        self.assertTrue(lines[3].startswith("src/v/api.h "))
        self.assertTrue(lines[3].endswith("  2"))
        self.assertEqual(lines[4], "rust/lib.rs                        3")
        self.assertEqual(lines[5], "TOTAL                              9")
        self.assertEqual(lines[0], text.splitlines()[0])


@verifies("tool_req__coverage_report_relative_paths")
class RootRelativeOutputPathsTest(unittest.TestCase):
    """Remove workspace prefixes from LLVM LCOV records and source-page titles."""

    def test_lcov_and_html_paths_drop_the_config_prefix(self):
        lcov = "SF:/ws/bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/x.h\nDA:1,1\nend_of_record\n"
        self.assertEqual(
            reporter._make_lcov_paths_relative(lcov, "/ws"),
            "SF:src/_virtual_includes/v/x.h\nDA:1,1\nend_of_record\n",
        )
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "p.html"
            page.write_text(
                "<div class='source-name-title'><pre>/ws/bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/x.h"
                "</pre></div>",
                encoding="utf-8",
            )
            reporter._make_html_paths_relative(Path(tmp), "/ws")
            self.assertIn("<pre>src/_virtual_includes/v/x.h</pre>", page.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
