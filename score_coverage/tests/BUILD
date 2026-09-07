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
load("@score_tooling//:defs.bzl", "score_py_pytest")

# Requirement-to-test links: the unittest classes carry @verifies(...) which
# writes PartiallyVerifies/TestType/DerivationTechnique into the JUnit XML that
# docs-as-code turns into testcase needs (gd_req__verification_link_tests_python).
# score_py_pytest runs the unittest classes under pytest with score_tooling's
# attribute plugin and --junitxml=$XML_OUTPUT_FILE.
py_library(
    name = "traceability",
    srcs = ["traceability.py"],
    imports = ["../.."],
)

score_py_pytest(
    name = "merger_test",
    srcs = ["merger_test.py"],
    deps = [
        ":traceability",
        "//score_coverage:merger_lib",
    ],
)

score_py_pytest(
    name = "reporter_test",
    srcs = ["reporter_test.py"],
    deps = [
        ":traceability",
        "//score_coverage:reporter_lib",
    ],
)

score_py_pytest(
    name = "coverage_summary_test",
    srcs = ["coverage_summary_test.py"],
    deps = [
        ":traceability",
        "//score_coverage:coverage_summary_lib",
    ],
)

score_py_pytest(
    name = "generate_coverage_html_test",
    srcs = ["generate_coverage_html_test.py"],
    deps = [
        ":traceability",
        "//score_coverage:generate_coverage_html_lib",
    ],
)

score_py_pytest(
    name = "justify_test",
    srcs = ["justify_test.py"],
    deps = [
        ":traceability",
        "//score_coverage:justify_lib",
    ],
)

score_py_pytest(
    name = "effective_coverage_test",
    srcs = ["effective_coverage_test.py"],
    deps = [
        ":traceability",
        "//score_coverage:effective_coverage_lib",
    ],
)
