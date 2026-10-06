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

load("@score_coverage//:defs.bzl", "score_coverage_reporter", "score_coverage_scope")

# The production targets whose transitive sources define the coverage scope.
# Untested targets listed here (src:uncovered, rust:untested_tool) appear in
# the report at exact 0% via the --empty-profile baseline.
SCOPE_DEPS = [
    # Library in a package without tests, tested from //lib/test
    # (baselibs layout): needs the explicit --instrumentation_filter.
    "//lib:cross_pkg",
    "//rust:integration_lib",
    "//rust:untested_tool",
    "//src:coverable",
    "//src:uncovered",
    "//src:unused_api",
    "//src:vendored_math",
    # Wrapper of a third-party library: visited by the aspect, must
    # contribute nothing (coverage_tool#5).
    "//third_party:extlib",
    # Header vendored from an external module (baselibs#558).
    "//third_party:vendored_ext",
    # Platform-dependent library (coverage_tool#23): the scope must list
    # the variant of the platform the coverage run targets.
    "//src:platform_dep",
] + select({
    # One root per platform, the host root incompatible with the gcov
    # platform: this select() is resolved for the scope's platform.
    "//platforms:is_gcov_target": ["//src:target_root"],
    "//conditions:default": ["//src:host_root"],
})

# Scope of the LLVM run: no --platforms in coverage:llvm_cov, the tests run
# on the host platform, and so does the scope's exec configuration.
score_coverage_scope(
    name = "coverage_scope",
    testonly = True,
    visibility = ["//visibility:private"],
    deps = SCOPE_DEPS,
)

# Scope of the gcov run: coverage:gcov builds for //platforms:gcov_target.
# Bazel analyses the scope in the exec configuration (host platform); the
# platform attribute makes it follow the run's platform (coverage_tool#23).
score_coverage_scope(
    name = "coverage_scope_gcov",
    testonly = True,
    platform = "//platforms:gcov_target",
    # Manual: a wildcard build outside coverage:gcov would analyse the scope
    # for //platforms:gcov_target without the GCC toolchain registered.
    tags = ["manual"],
    visibility = ["//visibility:private"],
    deps = SCOPE_DEPS,
)

score_coverage_reporter(
    name = "reporter_wrapper",
    testonly = True,
    coverage_scope = ":coverage_scope",
    llvm_cov = "@llvm_toolchain//:llvm-cov",
    llvm_cxxfilt = "@llvm_toolchain_llvm//:bin/llvm-cxxfilt",
    llvm_profdata = "@llvm_toolchain//:llvm-profdata",
)

# gcov backend reporter: the same scope, the toolchain's gcov instead of the
# LLVM tools. Selected by the coverage:gcov config.
score_coverage_reporter(
    name = "gcov_reporter_wrapper",
    testonly = True,
    backend = "gcov",
    coverage_scope = ":coverage_scope_gcov",
    gcov = "@score_gcc_x86_64_toolchain_pkg//:gcov",
)
