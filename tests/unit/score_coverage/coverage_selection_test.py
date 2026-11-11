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

"""Tests for shared coverage selection behavior."""
# pylint: disable=missing-function-docstring,missing-class-docstring,consider-using-with

import io
import unittest
from contextlib import redirect_stderr

from score_coverage import coverage_selection
from tests.unit.score_coverage.traceability import verifies


@verifies("tool_req__coverage_scope_transitive", "tool_req__coverage_report_relative_paths")
class CanonicalPathTest(unittest.TestCase):
    """The reported name of a file: config prefix dropped, virtual path mapped to the declared header."""

    MAP = {"src/_virtual_includes/v/api.h": "src/v/include/api.h"}

    def test_plain_paths_are_unchanged(self):
        self.assertEqual(coverage_selection.canonical_path("src/a.cpp", self.MAP), "src/a.cpp")
        self.assertEqual(coverage_selection.canonical_path("external/ext+/x.h", None), "external/ext+/x.h")

    def test_virtual_path_maps_to_declared_header_under_any_config(self):
        for cfg in ("k8-fastbuild", "k8-opt-exec-ST-1234"):
            self.assertEqual(
                coverage_selection.canonical_path(f"bazel-out/{cfg}/bin/src/_virtual_includes/v/api.h", self.MAP),
                "src/v/include/api.h",
            )

    def test_instrumentation_filter_suspects_flags_libraries_tested_from_a_test_subdirectory(self):
        # score/os tested from score/os/test (baselibs layout): no file of
        # score/os has data, the test sources below score/os/test have.
        with_data = {"score/os/test/acl_test.cpp", "score/os/utils/acl/acl.cpp", "score/json/tests/j_test.cpp"}
        no_data = {
            "score/os/acl_impl.cpp",  # suspect: tested from score/os/test/
            "score/json/model.cpp",  # suspect: tested from score/json/tests/
            "score/os/utils/acl/other.cpp",  # sibling has data: an ordinary untested file
            "score/net/socket.cpp",  # nothing tested below it: ordinary untested file
        }
        self.assertEqual(
            coverage_selection.instrumentation_filter_suspects(no_data, with_data),
            ["score/json/model.cpp", "score/os/acl_impl.cpp"],
        )
        self.assertEqual(coverage_selection.instrumentation_filter_suspects(set(), with_data), [])

    def test_warn_instrumentation_filter_names_the_flag(self):
        selection = coverage_selection.FileSelection(
            baseline_only={"score/os/acl_impl.cpp"}, unmapped={"score/os/glob.cpp"}
        )
        err = io.StringIO()
        with redirect_stderr(err):
            suspects = coverage_selection.warn_instrumentation_filter(selection, {"score/os/test/acl_test.cpp"})
        self.assertEqual(suspects, ["score/os/acl_impl.cpp", "score/os/glob.cpp"])
        self.assertIn("--instrumentation_filter=^//<root package>[/:]", err.getvalue())
        self.assertIn("2 in-scope files", err.getvalue())
        # Nothing to say when the directory itself has data.
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(coverage_selection.warn_instrumentation_filter(selection, {"score/os/errno.cpp"}), [])
        self.assertEqual(err.getvalue(), "")

    def test_unmapped_virtual_path_keeps_its_config_free_form(self):
        self.assertEqual(
            coverage_selection.canonical_path("bazel-out/k8-fastbuild/bin/src/_virtual_includes/u/y.h", self.MAP),
            "src/_virtual_includes/u/y.h",
        )


@verifies("tool_req__coverage_scope_transitive", "tool_req__coverage_report_relative_paths")
class ForeignVirtualIncludesTest(unittest.TestCase):
    """Virtual-include trees of targets outside the scope resolve to the declared in-scope file."""

    ALLOW = {
        "lib/include/score/apply.hpp",
        "lib/include/score/private/invoke.hpp",
        "other/include/score/apply.hpp",  # a second apply.hpp elsewhere
        "src/vendor/include/vendored/api.h",
        "src/plain.cpp",
    }

    def test_unique_tail_resolves(self):
        resolved, ambiguous = coverage_selection.resolve_foreign_virtual_includes(
            {"lib/_virtual_includes/lib_internal/score/private/invoke.hpp", "src/plain.cpp"}, self.ALLOW
        )
        self.assertEqual(
            resolved,
            {"lib/_virtual_includes/lib_internal/score/private/invoke.hpp": "lib/include/score/private/invoke.hpp"},
        )
        self.assertEqual(ambiguous, {})

    def test_ambiguous_tail_is_reported_not_guessed(self):
        resolved, ambiguous = coverage_selection.resolve_foreign_virtual_includes(
            {"lib/_virtual_includes/lib_internal/score/apply.hpp"}, self.ALLOW
        )
        self.assertEqual(resolved, {})
        self.assertEqual(
            ambiguous,
            {
                "lib/_virtual_includes/lib_internal/score/apply.hpp": [
                    "lib/include/score/apply.hpp",
                    "other/include/score/apply.hpp",
                ]
            },
        )

    def test_include_prefix_components_are_skipped(self):
        # include_prefix = "pfx" adds a component the declared path does not have
        resolved, _ = coverage_selection.resolve_foreign_virtual_includes(
            {"src/_virtual_includes/twin/pfx/vendored/api.h"}, self.ALLOW
        )
        self.assertEqual(
            resolved, {"src/_virtual_includes/twin/pfx/vendored/api.h": "src/vendor/include/vendored/api.h"}
        )

    def test_no_match_and_non_virtual_names_are_left_alone(self):
        resolved, ambiguous = coverage_selection.resolve_foreign_virtual_includes(
            {"x/_virtual_includes/t/unknown.h", "src/plain.cpp", "lib/include/score/apply.hpp"}, self.ALLOW
        )
        self.assertEqual((resolved, ambiguous), ({}, {}))


@verifies("tool_req__coverage_report_allowlist", "tool_req__coverage_report_baseline_zero")
class SelectFilesTest(unittest.TestCase):
    """Which raw compiled files stay, which are suppressed, which come from the baseline only."""

    def test_out_of_scope_and_redundant_variants_are_excluded(self):
        test = {
            "src/a.cpp": "src/a.cpp",
            "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h": "src/v/api.h",
            "external/openssl+/x.h": "external/openssl+/x.h",
        }
        baseline = {
            "src/a.cpp": "src/a.cpp",
            "src/untested.cpp": "src/untested.cpp",
            "bazel-out/k8-opt-exec-ST-1/bin/src/_virtual_includes/v/api.h": "src/v/api.h",
            "external/openssl+/y.h": "external/openssl+/y.h",
        }
        sel = coverage_selection.select_files(test, baseline, {"src/a.cpp", "src/v/api.h", "src/untested.cpp"})
        self.assertEqual(
            sel.excluded,
            {
                "external/openssl+/x.h",
                "external/openssl+/y.h",
                "bazel-out/k8-opt-exec-ST-1/bin/src/_virtual_includes/v/api.h",
            },
        )
        self.assertEqual(
            sel.staged,
            {
                "src/a.cpp": "src/a.cpp",
                "src/untested.cpp": "src/untested.cpp",
                "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h": "src/v/api.h",
            },
        )
        self.assertEqual(sel.baseline_only, {"src/untested.cpp"})
        self.assertEqual(sel.duplicates, {})
        self.assertEqual(sel.unmapped, set())

    def test_allowlisted_file_without_any_coverage_data_is_reported(self):
        # A header nothing includes (or template-only code) has no coverage
        # mapping anywhere; llvm-cov cannot show it, so the selection must.
        test = {"src/a.cpp": "src/a.cpp"}
        baseline = {"src/a.cpp": "src/a.cpp", "src/b.cpp": "src/b.cpp"}
        allowlist = {
            "src/a.cpp",
            "src/a.h",
            "src/b.cpp",
            "src/b.hpp",
            "src/never.h",
            "src/tmpl.h",
            "src/orphan.cpp",
            "src/empty.cpp",
        }
        # a.h / b.hpp sit next to compiled a.cpp / b.cpp: declarations only.
        # empty.cpp was compiled (its object is an archive member) but has no
        # data of its own: no code. never.h, tmpl.h and a source nobody built
        # (orphan.cpp: no object anywhere) remain findings.
        sel = coverage_selection.select_files(test, baseline, allowlist, compiled_stems={"src/a", "src/b", "src/empty"})
        self.assertEqual(sel.unmapped, {"src/never.h", "src/tmpl.h", "src/orphan.cpp"})
        self.assertEqual(sel.declaration_only, {"src/a.h", "src/b.hpp"})
        self.assertEqual(sel.empty_units, {"src/empty.cpp"})
        self.assertEqual(
            coverage_selection.format_unmapped_files(sel),
            "compiled-without-code\tsrc/empty.cpp\ndeclaration-only\tsrc/a.h\ndeclaration-only\tsrc/b.hpp\n"
            "no-data\tsrc/never.h\nno-data\tsrc/orphan.cpp\nno-data\tsrc/tmpl.h\n",
        )
        self.assertEqual(sel.baseline_only, {"src/b.cpp"})
        self.assertEqual(sel.excluded, set())

    def test_duplicate_test_variants_keep_the_declared_path(self):
        test = {
            "src/v/api.h": "src/v/api.h",
            "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h": "src/v/api.h",
            "bazel-out/k8-fastbuild/bin/src/_virtual_includes/w/w.h": "src/w/w.h",
            "bazel-out/k8-fastbuild-ST-2/bin/src/_virtual_includes/w/w.h": "src/w/w.h",
        }
        self.assertEqual(
            coverage_selection.duplicate_test_variants(test),
            {
                "src/v/api.h": ["bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/api.h"],
                # no declared-path variant: the first in sort order is kept ('-' < '/')
                "src/w/w.h": ["bazel-out/k8-fastbuild/bin/src/_virtual_includes/w/w.h"],
            },
        )
        sel = coverage_selection.select_files(test, {}, None)
        self.assertEqual(
            set(sel.staged), {"src/v/api.h", "bazel-out/k8-fastbuild-ST-2/bin/src/_virtual_includes/w/w.h"}
        )
        self.assertEqual(len(sel.excluded), 2)

    def test_no_allowlist_keeps_everything(self):
        sel = coverage_selection.select_files({"a": "a"}, {"b": "b"}, None)
        self.assertEqual(sel.staged, {"a": "a", "b": "b"})
        self.assertEqual(sel.excluded, set())
        self.assertEqual(sel.baseline_only, {"b"})
        self.assertEqual(sel.unmapped, set())


@verifies("tool_req__coverage_report_baseline_zero", "tool_req__coverage_report_allowlist")
class RedundantBaselineVariantsTest(unittest.TestCase):
    """A header covered by a test must not get a second 0 % row from the baseline archive."""

    def test_generated_header_variant_from_baseline_is_redundant(self):
        test_covered = {
            "bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/x.h": "src/_virtual_includes/v/x.h",
            "src/a.cpp": "src/a.cpp",
        }
        baseline = {
            "bazel-out/k8-opt-exec-ST-1/bin/src/_virtual_includes/v/x.h": "src/_virtual_includes/v/x.h",
            "src/a.cpp": "src/a.cpp",
            "src/uncovered.cpp": "src/uncovered.cpp",
        }
        self.assertEqual(
            coverage_selection.redundant_baseline_variants(test_covered, baseline),
            {"bazel-out/k8-opt-exec-ST-1/bin/src/_virtual_includes/v/x.h"},
        )

    def test_plain_sources_and_untested_files_are_kept(self):
        test_covered = {"src/a.cpp": "src/a.cpp"}
        baseline = {
            "src/a.cpp": "src/a.cpp",
            "bazel-out/k8-opt-exec-ST-1/bin/src/_virtual_includes/u/y.h": "src/_virtual_includes/u/y.h",
        }
        # a.cpp: identical raw path -> not redundant; y.h: not covered by any test -> kept as baseline
        self.assertEqual(coverage_selection.redundant_baseline_variants(test_covered, baseline), set())

    def test_empty_inputs(self):
        self.assertEqual(coverage_selection.redundant_baseline_variants({}, {}), set())
        self.assertEqual(coverage_selection.redundant_baseline_variants({"a": "a"}, {}), set())


@verifies("tool_req__coverage_scope_transitive", "tool_req__coverage_report_relative_paths")
class ConfigPrefixTest(unittest.TestCase):
    def test_strip_config_prefix(self):
        self.assertEqual(
            coverage_selection.strip_config_prefix("bazel-out/k8-fastbuild/bin/src/_virtual_includes/v/x.h"),
            "src/_virtual_includes/v/x.h",
        )
        self.assertEqual(
            coverage_selection.strip_config_prefix(
                "bazel-out/k8-opt-exec-ST-db392155ee03/bin/src/_virtual_includes/v/x.h"
            ),
            "src/_virtual_includes/v/x.h",
        )
        self.assertEqual(coverage_selection.strip_config_prefix("src/a.cpp"), "src/a.cpp")
        self.assertEqual(
            coverage_selection.strip_config_prefix("external/flatbuffers+/include/flatbuffers/base.h"),
            "external/flatbuffers+/include/flatbuffers/base.h",
        )
        # only a leading prefix is stripped, once
        unchanged = "x/bazel-out/k8-fastbuild/bin/y.h"
        self.assertEqual(coverage_selection.strip_config_prefix(unchanged), unchanged)
