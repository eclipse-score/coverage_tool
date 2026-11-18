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

# The E2E assertions consume these helpers, which have no dependency on Bazel
# processes, compilers, consumer fixtures or the production coverage tool.
py_library(
    name = "coverage_checks",
    srcs = ["coverage_checks.py"],
    imports = ["."],
    visibility = ["//tests/end_to_end/tests:__pkg__"],
)

# These are unit tests of the test support code. They validate CHECK parsing
# and reject malformed expectations and LCOV counters independently of E2E.
score_pytest(
    name = "coverage_checks_test",
    size = "small",
    srcs = ["test_coverage_checks.py"],
    deps = [":coverage_checks"],
)
