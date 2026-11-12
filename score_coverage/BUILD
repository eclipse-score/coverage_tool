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

load("@pip_score_coverage//:requirements.bzl", "requirement")
load("@rules_python//python:defs.bzl", "py_binary")
load("@rules_python//python:pip.bzl", "compile_pip_requirements")

package(default_visibility = ["//visibility:public"])

# =============================================================================
# LLVM source-based coverage pipeline (C++ + Rust) — implementation package.
# Consumers use the root-level labels (//:merger, //:generate_coverage_html,
# //:defs.bzl, //:enable_llvm_coverage_for_death_tests); see //:BUILD.
# =============================================================================

# Python executables expose PyInfo, including their sources and imports.
# Tests and in-process callers depend on these same targets; imports = [".."]
# makes the score_coverage package available through that dependency graph.

# Per-test coverage output generator (--coverage_output_generator). Locates
# llvm-profdata via the LLVM_PROFDATA / RUST_LLVM_PROFDATA environment
# variables exported by the toolchains, so it needs no consumer-supplied labels.
py_binary(
    name = "merger",
    srcs = ["merger.py"],
    imports = [".."],
)

# Final report generator. Not referenced directly by consumers: the
# score_coverage_reporter macro wraps it with the consumer's coverage scope,
# workspace root and LLVM tool labels.
py_binary(
    name = "reporter",
    srcs = ["reporter.py"],
    imports = [".."],
    deps = ["@rules_python//python/runfiles"],
)

py_binary(
    name = "gcov_reporter",
    srcs = ["gcov_reporter.py"],
    imports = [".."],
    deps = [
        ":reporter",
        "@rules_python//python/runfiles",
        requirement("gcovr"),
    ],
)

py_binary(
    name = "justify",
    srcs = ["justify.py"],
    imports = [".."],
    deps = [requirement("pyyaml")],
)

py_binary(
    name = "effective_coverage",
    srcs = ["effective_coverage.py"],
    imports = [".."],
)

# Markdown job summary (GITHUB_STEP_SUMMARY / --summary-md), invoked by
# generate_coverage_html. Stdlib only.
py_binary(
    name = "coverage_summary",
    srcs = ["coverage_summary.py"],
    imports = [".."],
)

# Orchestrator + threshold gate: unpacks the reporter zip, runs justify /
# effective_coverage / coverage_summary in-process and enforces
# COVERAGE_THRESHOLD. Consumers run it as @score_coverage//:generate_coverage_html.
py_binary(
    name = "generate_coverage_html",
    srcs = ["generate_coverage_html.py"],
    imports = [".."],
    deps = [
        ":coverage_summary",
        ":effective_coverage",
        ":justify",
    ],
)

# In order to update the requirements, change the `requirements.in` file and run:
# `bazel run //score_coverage:requirements_3_12.update`.
compile_pip_requirements(
    name = "requirements_3_12",
    src = "requirements.in",
    python_version = "3.12",
    requirements_txt = "requirements_3_12.txt",
    tags = ["manual"],
)
