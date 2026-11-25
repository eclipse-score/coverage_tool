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

load("@rules_python//python:defs.bzl", "py_library")
load("@score_tools//score_pytest:pytest.bzl", "score_pytest")

score_pytest(
    name = "blackbox_test",
    size = "large",
    timeout = "long",
    srcs = [
        "test_cli.py",
        "test_llvm_artifacts.py",
        "test_llvm_gates.py",
        "test_llvm_html.py",
        "test_llvm_lcov.py",
        "test_summary.py",
    ],
    # score_pytest passes srcs to pytest as collection paths. Keep shared
    # fixtures and helpers in runfiles without presenting them as test modules.
    data = [
        "_blackbox_support.py",
        "conftest.py",
        "expected/expected_lcov.dat",
        # Run the packaged CLI from runfiles to test its process exit code
        # with isolated inputs and without a nested Bazel invocation.
        "//:generate_coverage_html",
    ],
    imports = ["."],
    # The checkout and host Bazel installation are runtime inputs outside this
    # target's runfiles, so changes to them cannot invalidate a cached result.
    # `external` disables test caching; `local` keeps the host Bazel process
    # with the checkout instead of using sandboxed or remote execution.
    tags = [
        "external",
        "local",
    ],
)

score_pytest(
    name = "gcov_test",
    size = "large",
    timeout = "long",
    srcs = ["test_gcov.py"],
    # Both backends use the checked-in consumer and its nested Bazel output
    # base. Exclusive execution keeps gcov from replacing LLVM's report while
    # the LLVM tests are reading it. External disables test-result caching
    # because the consumer workspace lives outside the declared runfiles.
    data = [
        "_blackbox_support.py",
        "conftest.py",
        "expected/expected_lcov_gcov.dat",
    ],
    imports = ["."],
    tags = [
        "exclusive",
        "external",
        "local",
    ],
)

# Declare process helpers and requirement metadata as Python dependencies so
# runtime imports and static analysis see the same source inputs.
py_library(
    name = "blackbox_support",
    srcs = ["_blackbox_support.py"],
    imports = ["."],
    deps = ["@score_tools//score_pytest:attribute_plugin"],
)

score_pytest(
    name = "cpp_semantics_test",
    size = "large",
    timeout = "long",
    srcs = ["test_cpp_semantics.py"],
    data = ["conftest.py"],
    imports = ["."],
    # The consumer checkout and its toolchains are inputs outside runfiles:
    # local keeps the nested Bazel invocation on this host, and external
    # disables result caching. Exclusive prevents another E2E target from
    # replacing the coverage ZIP while this target snapshots its reports.
    tags = [
        "exclusive",
        "external",
        "local",
    ],
    deps = [
        ":blackbox_support",
        "//tests/end_to_end/test_framework:coverage_checks",
    ],
)

# Run the same scenarios with QCC in the QNX guest. The selection applies to
# the pytest parameter ID, so this job runs only the QNX configuration.
# Manual keeps wildcard tests and builds usable without the private SDP.
score_pytest(
    name = "cpp_semantics_qnx_test",
    size = "large",
    timeout = "long",
    srcs = ["test_cpp_semantics.py"],
    args = [
        "-k",
        "qcc_qnx",
    ],
    data = ["conftest.py"],
    env = {"SCORE_COVERAGE_QNX": "1"},
    imports = ["."],
    tags = [
        "exclusive",
        "external",
        "local",
        "manual",
    ],
    deps = [
        ":blackbox_support",
        "//tests/end_to_end/test_framework:coverage_checks",
    ],
)
