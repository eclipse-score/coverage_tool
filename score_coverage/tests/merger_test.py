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
"""Unit tests for the per-test coverage merger."""
# Test modules: docstrings on every test method add nothing, tests exercise
# private helpers on purpose, TemporaryDirectory is closed in tearDown, and setUp
# fixtures are attributes.
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access,consider-using-with
# pylint: disable=too-many-instance-attributes

import io
import json
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from score_coverage import merger
from score_coverage.merger import find_llvm_profdata, get_object_files_from_manifest, is_elf


class IsElfTest(unittest.TestCase):
    def test_elf_magic_is_detected(self):
        with tempfile.NamedTemporaryFile(suffix=".bin") as f:
            f.write(b"\x7fELF" + b"\x00" * 12)
            f.flush()
            self.assertTrue(is_elf(Path(f.name)))

    def test_text_file_is_not_elf(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            f.write(b"just some text")
            f.flush()
            self.assertFalse(is_elf(Path(f.name)))

    def test_missing_file_is_not_elf(self):
        self.assertFalse(is_elf(Path("/nonexistent/path/binary")))


class FindLlvmProfdataTest(unittest.TestCase):
    def test_llvm_profdata_env_wins(self):
        with tempfile.NamedTemporaryFile() as f, mock.patch.dict(os.environ, {"LLVM_PROFDATA": f.name}, clear=True):
            self.assertEqual(find_llvm_profdata(), f.name)

    def test_rust_llvm_profdata_resolved_against_root(self):
        with tempfile.TemporaryDirectory() as root:
            tool = Path(root) / "bin" / "llvm-profdata"
            tool.parent.mkdir()
            tool.write_bytes(b"\x7fELF")
            env = {"RUST_LLVM_PROFDATA": "bin/llvm-profdata", "ROOT": root}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(find_llvm_profdata(), str(tool))

    def test_returns_empty_when_nothing_resolves(self):
        env = {"RUST_LLVM_PROFDATA": "does/not/exist"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(find_llvm_profdata(), "")


class GetObjectFilesFromManifestTest(unittest.TestCase):
    def test_missing_root_env_is_a_hard_error(self):
        """Without ROOT the merger cannot resolve manifest paths — must exit."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt") as manifest:
            manifest.write("some/path\n")
            manifest.flush()
            with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit):
                get_object_files_from_manifest(Path(manifest.name))

    def test_rust_elf_manifest_entry_is_collected(self):
        """rules_rust lists the instrumented test executable in the manifest."""
        with tempfile.TemporaryDirectory() as root:
            binary = Path(root) / "pkg" / "my_test"
            binary.parent.mkdir()
            binary.write_bytes(b"\x7fELF" + b"\x00" * 12)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt") as manifest:
                manifest.write("pkg/my_test\n")
                manifest.flush()
                with mock.patch.dict(os.environ, {"ROOT": root}, clear=True):
                    objects = get_object_files_from_manifest(Path(manifest.name))
        self.assertEqual(objects, {str(binary)})

    def test_external_manifest_entries_are_skipped(self):
        """Toolchain-provided metadata files (external/) are not instrumented objects."""
        with tempfile.TemporaryDirectory() as root:
            binary = Path(root) / "external" / "tool"
            binary.parent.mkdir()
            binary.write_bytes(b"\x7fELF" + b"\x00" * 12)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt") as manifest:
                manifest.write("external/tool\n")
                manifest.flush()
                with mock.patch.dict(os.environ, {"ROOT": root}, clear=True):
                    objects = get_object_files_from_manifest(Path(manifest.name))
        self.assertEqual(objects, set())

    def test_objects_list_entries_are_resolved(self):
        """C++ tests provide an objects_list.txt with one object path per line."""
        with tempfile.TemporaryDirectory() as root:
            obj = Path(root) / "bazel-out" / "lib.a"
            obj.parent.mkdir()
            obj.write_bytes(b"!<arch>\n")
            objects_list = Path(root) / "objects_list.txt"
            objects_list.write_text("bazel-out/lib.a\n")
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt") as manifest:
                manifest.write(f"{objects_list}\n")
                manifest.flush()
                with mock.patch.dict(os.environ, {"ROOT": root}, clear=True):
                    objects = get_object_files_from_manifest(Path(manifest.name))
        self.assertEqual(objects, {str(obj)})


# ---------------------------------------------------------------------------
# Added for the score_coverage qualification: end-to-end behaviour of main()
# with a fake llvm-profdata, plus the helpers that were not covered.
# ---------------------------------------------------------------------------


def _fake_profdata(path: Path, fail: bool = False) -> Path:
    """A stand-in llvm-profdata that concatenates its inputs into --output."""
    body = "#!/usr/bin/env python3\nimport sys\n"
    if fail:
        body += "print('boom'); sys.exit(3)\n"
    else:
        body += (
            "args = sys.argv[1:]\n"
            "assert args[0] == 'merge' and '--sparse' in args, args\n"
            "out = args[args.index('--output') + 1]\n"
            "inputs = args[args.index('--output') + 2:]\n"
            "with open(out, 'wb') as o:\n"
            "    for i in inputs:\n"
            "        o.write(open(i, 'rb').read())\n"
        )
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class CleanupDanglingSymlinksTest(unittest.TestCase):
    def test_gcov_and_sandbox_links_removed_others_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.txt").write_text("x", encoding="utf-8")
            (root / "gcov").symlink_to("/nonexistent/sandbox/gcov")
            (root / "into_sandbox").symlink_to("/tmp/bazel-sandbox/123/thing")
            (root / "other_link").symlink_to("/usr/bin")
            merger.cleanup_dangling_symlinks(root)
            self.assertFalse((root / "gcov").is_symlink())
            self.assertFalse((root / "into_sandbox").is_symlink())
            self.assertTrue((root / "other_link").is_symlink())
            self.assertTrue((root / "keep.txt").is_file())


class CreateZipTest(unittest.TestCase):
    def test_only_listed_directories_relative_to_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "sub").mkdir(parents=True)
            (root / "a" / "sub" / "f.txt").write_text("f", encoding="utf-8")
            (root / "b").mkdir()
            (root / "b" / "g.txt").write_text("g", encoding="utf-8")
            (root / "c").mkdir()
            (root / "c" / "h.txt").write_text("h", encoding="utf-8")
            out = root / "out.zip"
            merger.create_zip(root, [root / "a", root / "b", root / "missing"], out)
            with zipfile.ZipFile(out) as zf:
                self.assertEqual(sorted(zf.namelist()), ["a/sub/f.txt", "b/g.txt"])


class RunCommandTest(unittest.TestCase):
    def test_failure_exits_with_1(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            merger.run_command([sys.executable, "-c", "import sys; print('bad'); sys.exit(7)"])
        self.assertEqual(ctx.exception.code, 1)

    def test_success_returns_output(self):
        result = merger.run_command([sys.executable, "-c", "print('ok')"])
        self.assertEqual(result.stdout.strip(), "ok")


class MergerMainTest(unittest.TestCase):
    """main() against a fake Bazel coverage directory and a fake llvm-profdata."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.coverage_dir = self.root / "coverage_dir"
        self.coverage_dir.mkdir()
        # An "instrumented object" listed through objects_list.txt.
        self.exec_root = self.root / "execroot"
        (self.exec_root / "bazel-out" / "k8" / "bin").mkdir(parents=True)
        self.obj = self.exec_root / "bazel-out" / "k8" / "bin" / "libfoo.a"
        self.obj.write_bytes(b"!<arch>\n")
        objects_list = self.root / "objects_list.txt"
        objects_list.write_text("bazel-out/k8/bin/libfoo.a\n\n", encoding="utf-8")
        self.manifest = self.root / "manifest.txt"
        self.manifest.write_text(f"{objects_list}\n", encoding="utf-8")
        self.output = self.root / "coverage.zip"
        self.profdata = _fake_profdata(self.root / "llvm-profdata")
        self.env = {
            "ROOT": str(self.exec_root),
            "RUNFILES_DIR": str(self.root / "no_runfiles"),
            "TEST_WORKSPACE": "_main",
            "LLVM_PROFDATA": str(self.profdata),
            "TEST_TARGET": "//pkg:t",
            "PATH": os.environ.get("PATH", ""),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _argv(self):
        return [
            "--coverage_dir",
            str(self.coverage_dir),
            "--output_file",
            str(self.output),
            "--source_file_manifest",
            str(self.manifest),
            "--filter_sources",
            "external/.*",
        ]

    def _run(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), redirect_stderr(err):
            try:
                merger.main(self._argv())
            except SystemExit as exc:
                return exc.code, err.getvalue()
        return None, err.getvalue()

    def test_merges_profraw_and_packages_meta(self):
        (self.coverage_dir / "b.profraw").write_bytes(b"BBBB")
        (self.coverage_dir / "a.profraw").write_bytes(b"AAAA")
        (self.coverage_dir / "gcov").symlink_to("/sandbox/gone/gcov")
        code, err = self._run()
        self.assertIsNone(code, err)
        self.assertIn("Coverage merger completed for '//pkg:t'", err)
        with zipfile.ZipFile(self.output) as zf:
            names = sorted(zf.namelist())
            self.assertEqual(names, ["meta/meta.json", "profdata/target.profdata"])
            self.assertEqual(zf.read("profdata/target.profdata"), b"AAAABBBB")  # sorted input order
            meta = json.loads(zf.read("meta/meta.json"))
        self.assertEqual(meta, {"object_files": [os.path.realpath(self.obj)]})
        self.assertFalse((self.coverage_dir / "gcov").is_symlink())

    def test_no_profraw_skips_quietly_with_exit_0(self):
        code, err = self._run()
        self.assertEqual(code, 0)
        self.assertIn("No *.profraw files found", err)
        self.assertFalse(self.output.exists())

    def test_no_objects_skips_quietly_with_exit_0(self):
        self.manifest.write_text("", encoding="utf-8")
        (self.coverage_dir / "a.profraw").write_bytes(b"A")
        code, err = self._run()
        self.assertEqual(code, 0)
        self.assertIn("No instrumented object files found", err)

    def test_missing_llvm_profdata_is_an_error(self):
        (self.coverage_dir / "a.profraw").write_bytes(b"A")
        self.env["LLVM_PROFDATA"] = str(self.root / "does_not_exist")
        code, err = self._run()
        self.assertEqual(code, 1)
        self.assertIn("llvm-profdata not found", err)

    def test_failing_llvm_profdata_is_an_error(self):
        (self.coverage_dir / "a.profraw").write_bytes(b"A")
        _fake_profdata(self.profdata, fail=True)
        code, err = self._run()
        self.assertEqual(code, 1)
        self.assertIn("Command failed with code 3", err)
        self.assertFalse(self.output.exists())

    def test_rust_llvm_profdata_fallback_is_used(self):
        (self.coverage_dir / "a.profraw").write_bytes(b"A")
        del self.env["LLVM_PROFDATA"]
        self.env["RUST_LLVM_PROFDATA"] = str(self.profdata)
        code, _ = self._run()
        self.assertIsNone(code)
        self.assertTrue(self.output.exists())


if __name__ == "__main__":
    unittest.main()
