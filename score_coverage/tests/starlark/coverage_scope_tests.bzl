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

"""Analysis tests for the coverage_scope rule and its aspect.

The rule writes two text files; rules_testing lets us read the content of
the FileWrite actions without executing anything, so these tests pin down
exactly which source files and archives end up in the coverage scope.
"""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test", "test_suite")
load("@rules_testing//lib:truth.bzl", "matching")
load("//score_coverage:coverage_scope.bzl", "coverage_scope")

_FIX = "//score_coverage/tests/starlark/fixtures"
_PKG = "score_coverage/tests/starlark"

def _allowlist(env, target):
    return env.expect.that_target(target).action_generating(
        _PKG + "/" + target.label.name + "_allowlist.txt",
    ).content()

def _objects(env, target):
    return env.expect.that_target(target).action_generating(
        _PKG + "/" + target.label.name + "_objects.txt",
    ).content()

# --- transitive deps -------------------------------------------------------

def _test_transitive_deps_are_collected(name):
    coverage_scope(name = name + "_subject", testonly = True, deps = [_FIX + ":mid"])
    analysis_test(name = name, impl = _test_transitive_deps_are_collected_impl, target = name + "_subject")

def _test_transitive_deps_are_collected_impl(env, target):
    _allowlist(env, target).equals(
        "\n".join([
            _PKG + "/fixtures/leaf.cpp",
            _PKG + "/fixtures/leaf.h",
            _PKG + "/fixtures/mid.cpp",
            _PKG + "/fixtures/mid.h",
        ]) + "\n",
    )
    objects = _objects(env, target)
    objects.contains("libleaf.a")
    objects.contains("libmid.a")

# --- implementation_deps ---------------------------------------------------

def _test_implementation_deps_are_followed(name):
    coverage_scope(name = name + "_subject", testonly = True, deps = [_FIX + ":impl_dep_user"])
    analysis_test(name = name, impl = _test_implementation_deps_are_followed_impl, target = name + "_subject")

def _test_implementation_deps_are_followed_impl(env, target):
    _allowlist(env, target).equals(
        "\n".join([
            _PKG + "/fixtures/leaf.cpp",
            _PKG + "/fixtures/leaf.h",
            _PKG + "/fixtures/user.cpp",
        ]) + "\n",
    )

# --- deduplication across roots -------------------------------------------

def _test_shared_dependency_listed_once(name):
    coverage_scope(
        name = name + "_subject",
        testonly = True,
        deps = [_FIX + ":mid", _FIX + ":impl_dep_user", _FIX + ":leaf"],
    )
    analysis_test(name = name, impl = _test_shared_dependency_listed_once_impl, target = name + "_subject")

def _test_shared_dependency_listed_once_impl(env, target):
    _allowlist(env, target).equals(
        "\n".join([
            _PKG + "/fixtures/leaf.cpp",
            _PKG + "/fixtures/leaf.h",
            _PKG + "/fixtures/mid.cpp",
            _PKG + "/fixtures/mid.h",
            _PKG + "/fixtures/user.cpp",
        ]) + "\n",
    )

# --- header-only library ---------------------------------------------------

def _test_header_only_library_has_no_archive(name):
    coverage_scope(name = name + "_subject", testonly = True, deps = [_FIX + ":header_only"])
    analysis_test(name = name, impl = _test_header_only_library_has_no_archive_impl, target = name + "_subject")

def _test_header_only_library_has_no_archive_impl(env, target):
    _allowlist(env, target).equals(_PKG + "/fixtures/only.h\n")
    _objects(env, target).equals("")

# --- generated sources are excluded ---------------------------------------

def _test_generated_sources_are_excluded(name):
    coverage_scope(name = name + "_subject", testonly = True, deps = [_FIX + ":with_generated"])
    analysis_test(name = name, impl = _test_generated_sources_are_excluded_impl, target = name + "_subject")

def _test_generated_sources_are_excluded_impl(env, target):
    # Exactly the checked-in sources: generated.cpp is absent.
    _allowlist(env, target).equals(
        "\n".join([
            _PKG + "/fixtures/leaf.cpp",
            _PKG + "/fixtures/leaf.h",
        ]) + "\n",
    )

    # The archive of the library with the generated source is still a baseline object.
    _objects(env, target).contains("libwith_generated.a")

# --- providers / output groups --------------------------------------------

def _test_output_groups(name):
    coverage_scope(name = name + "_subject", testonly = True, deps = [_FIX + ":mid"])
    analysis_test(name = name, impl = _test_output_groups_impl, target = name + "_subject")

def _test_output_groups_impl(env, target):
    subject = env.expect.that_target(target)
    subject.output_group("allowlist").contains_exactly([_PKG + "/" + target.label.name + "_allowlist.txt"])
    subject.output_group("objects").contains_exactly([_PKG + "/" + target.label.name + "_objects.txt"])
    subject.output_group("object_files").contains_predicate(matching.file_basename_equals("libleaf.a"))
    subject.default_outputs().contains_at_least([
        _PKG + "/" + target.label.name + "_allowlist.txt",
        _PKG + "/" + target.label.name + "_objects.txt",
    ])

def coverage_scope_test_suite(name):
    test_suite(
        name = name,
        tests = [
            _test_transitive_deps_are_collected,
            _test_implementation_deps_are_followed,
            _test_shared_dependency_listed_once,
            _test_header_only_library_has_no_archive,
            _test_generated_sources_are_excluded,
            _test_output_groups,
        ],
    )
