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

load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@score_tooling//:defs.bzl", "dash_license_checker")

# Structural coverage of this repository's own Python (coverage.py via
# `bazel coverage --combined_report=lcov //tests/unit/score_coverage:all`).
py_binary(
    name = "self_coverage_gate",
    srcs = ["self_coverage_gate.py"],
)

# The gate's unit test imports this module from tests/unit/tools. Export it as
# a library so the test gets the tool through Bazel's dependency graph.
py_library(
    name = "self_coverage_gate_lib",
    srcs = ["self_coverage_gate.py"],
    imports = ["."],
    visibility = ["//tests/unit/tools:__pkg__"],
)

# Eclipse Dash license check over the Python dependencies (cicd-workflows
# license-check runs `bazel run //:license-check`; the root BUILD aliases here).
dash_license_checker(
    src = "//score_coverage:requirements_3_12.txt",
    file_type = "requirements",
    visibility = ["//visibility:public"],
)
