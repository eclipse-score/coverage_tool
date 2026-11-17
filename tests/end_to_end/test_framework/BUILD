# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# SPDX-License-Identifier: Apache-2.0

load("@rules_python//python:defs.bzl", "py_library")
load("@score_tools//score_pytest:pytest.bzl", "score_pytest")

# The E2E assertions consume this reader, but it has no dependency on Bazel
# processes, compilers, consumer fixtures or the production coverage tool.
py_library(
    name = "coverage_checks",
    srcs = ["coverage_checks.py"],
    imports = ["."],
    visibility = ["//tests/end_to_end/testcases:__pkg__"],
)

# These are unit tests of the test support code. They validate CHECK parsing
# and rejection of malformed expectations, independently of the E2E suite.
score_pytest(
    name = "coverage_checks_test",
    size = "small",
    srcs = ["test_coverage_checks.py"],
    deps = [":coverage_checks"],
)
