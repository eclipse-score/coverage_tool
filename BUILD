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

load("@rules_cc//cc/toolchains:args.bzl", "cc_args")
load("@rules_cc//cc/toolchains:feature.bzl", "cc_feature")

# IMPORTANT: this file is loaded by every consumer of @score_coverage. It must
# only load from the module's runtime dependencies (never from dev
# dependencies such as score_tooling): dev deps are dropped when this module is
# not the root, and a failing load here breaks the whole @score_coverage//
# package for the consumer. Repository hygiene targets live in //tools.
package(default_visibility = ["//visibility:public"])

exports_files([
    "MODULE.bazel",
    "pyproject.toml",
])

# =============================================================================
# Consumer-facing labels. Everything a consumer references lives at the root
# of this module:
#   load("@score_coverage//:defs.bzl", "score_coverage_scope", "score_coverage_reporter")
#   coverage:llvm_cov --coverage_output_generator=@score_coverage//:merger
#   bazel run @score_coverage//:generate_coverage_html -- ...
#   llvm.toolchain(extra_known_features = ["@score_coverage//:enable_llvm_coverage_for_death_tests"])
# The implementation lives in //score_coverage.
# =============================================================================

alias(
    name = "merger",
    actual = "//score_coverage:merger",
)

alias(
    name = "generate_coverage_html",
    actual = "//score_coverage:generate_coverage_html",
)

# Used by generate_coverage_html.sh through nested `bazel run` invocations.
alias(
    name = "justify",
    actual = "//score_coverage:justify",
)

alias(
    name = "effective_coverage",
    actual = "//score_coverage:effective_coverage",
)

alias(
    name = "coverage_summary",
    actual = "//score_coverage:coverage_summary",
)

# These compile time options are required to cover abnormal termination cases
# (death tests). LLVM provides them in combination with a specific profile
# setting which is enabled in Bazel via LLVM_PROFILE_CONTINUOUS_MODE.
cc_args(
    name = "runtime_relocation_args",
    actions = [
        "@rules_cc//cc/toolchains/actions:compile_actions",
        "@rules_cc//cc/toolchains/actions:link_actions",
    ],
    args = [
        "-mllvm",
        "-runtime-counter-relocation",
    ],
)

cc_feature(
    name = "enable_llvm_coverage_for_death_tests",
    args = [":runtime_relocation_args"],
    feature_name = "enable_llvm_coverage_for_death_tests",
)
