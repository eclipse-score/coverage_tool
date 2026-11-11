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

"""Tests for shared reporting inputs behavior."""
# pylint: disable=missing-function-docstring,missing-class-docstring,consider-using-with

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from score_coverage import reporting_inputs
from tests.unit.score_coverage.traceability import verifies


class _FakeRunfiles:
    """Minimal stand-in for python.runfiles.Runfiles: maps rlocation paths to files."""

    def __init__(self, mapping):
        self.mapping = mapping

    def Rlocation(self, path):  # noqa: N802  # pylint: disable=invalid-name
        if os.path.isabs(path):
            return path
        return self.mapping.get(path)


@verifies("tool_req__coverage_report_merged_profile")
class ReadReportsFileTest(unittest.TestCase):
    def test_blank_lines_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "reports.txt"
            f.write_text("a.zip\n\n  b.zip  \n", encoding="utf-8")
            self.assertEqual(reporting_inputs.read_reports_file(f), ["a.zip", "b.zip"])


@verifies("tool_req__coverage_report_merged_profile")
class ResolveToolTest(unittest.TestCase):
    def test_preference_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "llvm-cov"
            real.write_text("", encoding="utf-8")
            fallback = Path(tmp) / "fallback-cov"
            fallback.write_text("", encoding="utf-8")
            rf = _FakeRunfiles({"toolchain/llvm-cov": str(real), "llvm_toolchain/llvm-cov": str(fallback)})
            self.assertEqual(reporting_inputs.resolve_tool(rf, "toolchain/llvm-cov", "llvm_toolchain/llvm-cov"), real)
            self.assertEqual(reporting_inputs.resolve_tool(rf, None, "llvm_toolchain/llvm-cov"), fallback)
            self.assertEqual(reporting_inputs.resolve_tool(rf, str(real), ""), real)  # plain path
            self.assertIsNone(reporting_inputs.resolve_tool(rf, "unknown", "also-unknown"))
            self.assertIsNone(reporting_inputs.resolve_tool(None, "unknown", ""))


@verifies("tool_req__coverage_report_relative_paths", "tool_req__coverage_report_outputs")
class StageSourcesTest(unittest.TestCase):
    """In-scope sources are linked under their raw covmap path for llvm-cov to read."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runfiles_dir = self.root / "runfiles"
        (self.runfiles_dir / "_main" / "src").mkdir(parents=True)
        (self.runfiles_dir / "ext+" / "inc").mkdir(parents=True)
        (self.runfiles_dir / "_main" / "src" / "a.cpp").write_text("a", encoding="utf-8")
        (self.runfiles_dir / "ext+" / "inc" / "x.h").write_text("x", encoding="utf-8")
        self.ws = self.root / "ws"
        (self.ws / "rust").mkdir(parents=True)
        (self.ws / "rust" / "lib.rs").write_text("r", encoding="utf-8")
        self.runfiles = _FakeRunfiles(
            {
                "_main/src/a.cpp": str(self.runfiles_dir / "_main" / "src" / "a.cpp"),
                "ext+/inc/x.h": str(self.runfiles_dir / "ext+" / "inc" / "x.h"),
                "_main/rust/lib.rs": str(self.runfiles_dir / "_main" / "rust" / "lib.rs"),  # not present
            }
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolution_order_runfiles_then_workspace(self):
        self.assertEqual(
            reporting_inputs.resolve_source(self.runfiles, "src/a.cpp", str(self.ws)),
            str(self.runfiles_dir / "_main" / "src" / "a.cpp"),
        )
        self.assertEqual(
            reporting_inputs.resolve_source(self.runfiles, "external/ext+/inc/x.h", str(self.ws)),
            str(self.runfiles_dir / "ext+" / "inc" / "x.h"),
        )
        self.assertEqual(
            reporting_inputs.resolve_source(self.runfiles, "rust/lib.rs", str(self.ws)), str(self.ws / "rust/lib.rs")
        )
        self.assertIsNone(reporting_inputs.resolve_source(self.runfiles, "src/missing.cpp", str(self.ws)))

    def test_links_follow_the_raw_layout_and_missing_files_are_reported(self):
        stage = self.root / "sources"
        staged = {
            "src/a.cpp": "src/a.cpp",
            "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/x.h": "external/ext+/inc/x.h",
            "rust/lib.rs": "rust/lib.rs",
            "src/missing.cpp": "src/missing.cpp",
            "/usr/include/abs.h": "/usr/include/abs.h",
        }
        missing = reporting_inputs.stage_sources(stage, staged, self.runfiles, str(self.ws))
        self.assertEqual(missing, ["src/missing.cpp"])
        self.assertEqual((stage / "src" / "a.cpp").read_text(encoding="utf-8"), "a")
        virtual = stage / "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/x.h"
        self.assertTrue(virtual.is_symlink())
        self.assertEqual(virtual.read_text(encoding="utf-8"), "x")
        self.assertEqual((stage / "rust" / "lib.rs").read_text(encoding="utf-8"), "r")
        self.assertFalse((stage / "usr").exists())
        # idempotent
        self.assertEqual(
            reporting_inputs.stage_sources(stage, staged, self.runfiles, str(self.ws)), ["src/missing.cpp"]
        )


@verifies("tool_req__coverage_report_relative_paths")
class LoadPathMapTest(unittest.TestCase):
    def test_load_path_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "map.txt"
            f.write_text("# comment\n\nsrc/_virtual_includes/v/api.h\tsrc/v/api.h\nbroken-line\n", encoding="utf-8")
            runfiles = _FakeRunfiles({"m/map.txt": str(f)})
            self.assertEqual(
                reporting_inputs.load_path_map(runfiles, "m/map.txt"), {"src/_virtual_includes/v/api.h": "src/v/api.h"}
            )
            with redirect_stderr(io.StringIO()):
                self.assertEqual(reporting_inputs.load_path_map(runfiles, "m/nope.txt"), {})
            self.assertEqual(reporting_inputs.load_path_map(runfiles, None), {})


@verifies("tool_req__coverage_report_allowlist")
class LoadAllowlistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_allowlist_comments_and_blank_lines_ignored(self):
        f = self.root / "allow.txt"
        f.write_text("# comment\nsrc/a.cpp\n\n  src/b.h \n", encoding="utf-8")
        rf = _FakeRunfiles({"main/allow.txt": str(f)})
        self.assertEqual(reporting_inputs.load_coverage_allowlist(rf, "main/allow.txt"), ["src/a.cpp", "src/b.h"])
        self.assertEqual(reporting_inputs.load_coverage_allowlist(rf, "missing"), [])
