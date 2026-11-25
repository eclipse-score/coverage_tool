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

load("@rules_cc//cc:cc_library.bzl", "cc_library")
load("@rules_cc//cc:cc_test.bzl", "cc_test")
load("@score_coverage//:defs.bzl", "score_coverage_reporter", "score_coverage_scope")

# Two library translation units instantiate the same inline function and int
# template; the second also instantiates the long template. Coverage must
# attribute every invocation to the declared header and combine the instances.
cc_library(
    name = "subject",
    srcs = [
        "exception_paths.cpp",
        "int_template_caller.cpp",
        "mixed_template_caller.cpp",
    ],
    hdrs = ["inline_and_templates.h"],
)

# Both targets compile main.cpp and link the same library. They are separate
# test executables whose only intentional behavioral difference is argv[1].
# Explicit labels let the E2E suite measure either test or their union. Manual
# keeps them out of the consumer's ordinary wildcard coverage runs.
cc_test(
    name = "test_a",
    srcs = ["main.cpp"],
    args = ["2"],
    tags = ["manual"],
    deps = [":subject"],
)

cc_test(
    name = "test_b",
    srcs = ["main.cpp"],
    args = ["-2"],
    tags = ["manual"],
    deps = [":subject"],
)

# A dedicated scope makes these C++ semantics scenarios usable independently
# of the main consumer's broader source-scope and baseline fixtures.
# Both backends are selected explicitly by the E2E suite; manual keeps their
# scopes and reporters out of unrelated wildcard builds.
score_coverage_scope(
    name = "scope_llvm",
    testonly = True,
    tags = ["manual"],
    deps = [":subject"],
)

# gcov's target platform differs from the host platform, so the scope must
# follow the same platform as the instrumented binaries and their notes.
score_coverage_scope(
    name = "scope_gcov",
    testonly = True,
    platform = "//platforms:gcov_target",
    tags = ["manual"],
    deps = [":subject"],
)

score_coverage_reporter(
    name = "reporter_llvm",
    testonly = True,
    coverage_scope = ":scope_llvm",
    llvm_cov = "@llvm_toolchain//:llvm-cov",
    llvm_cxxfilt = "@llvm_toolchain_llvm//:bin/llvm-cxxfilt",
    llvm_profdata = "@llvm_toolchain//:llvm-profdata",
    tags = ["manual"],
)

score_coverage_reporter(
    name = "reporter_gcov",
    testonly = True,
    backend = "gcov",
    coverage_scope = ":scope_gcov",
    gcov = "@score_gcc_x86_64_toolchain_pkg//:gcov",
    tags = ["manual"],
)

# The scope uses the same subject as the Linux runs and compiles it for QNX.
# The reporter runs on Linux and reads the QNX counters with the SDK's gcov.
# Keep both targets manual so wildcard builds do not require the SDK.
score_coverage_scope(
    name = "scope_qnx",
    testonly = True,
    platform = "@score_bazel_platforms//:x86_64-qnx-sdp_8.0.0-posix",
    tags = ["manual"],
    deps = [":subject"],
)

score_coverage_reporter(
    name = "reporter_qnx",
    testonly = True,
    backend = "gcov",
    coverage_scope = ":scope_qnx",
    gcov = "@qnx_sdp_8_0_5_pkg//:gcov_x86_64",
    tags = ["manual"],
)
