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

package(default_visibility = ["//visibility:public"])

cc_library(
    name = "coverable",
    srcs = ["coverable.cpp"],
    hdrs = ["coverable.h"],
)

# No test links against this library — it must show up at exact 0% in the
# report via the --empty-profile baseline.
cc_library(
    name = "uncovered",
    srcs = [
        "empty_unit.cpp",
        "uncovered.cpp",
    ],
    hdrs = ["uncovered.h"],
)

# Header-only library whose header is reached through strip_include_prefix:
# the compiler sees it via Bazel's generated _virtual_includes/ tree, the same
# mechanism vendored third-party headers use (eclipse-score/baselibs#558).
# One inline function is called by the test, the other never.
# In scope, but no source includes it and it is template-only: reported as
# "in-scope file without coverage data" (coverage_tool#5 follow-up).
cc_library(
    name = "unused_api",
    hdrs = ["unused_api.h"],
)

cc_library(
    name = "vendored_math",
    hdrs = ["vendored/include/vendored/inline_math.h"],
    strip_include_prefix = "vendored/include",
)

# Test-only twin of vendored_math (same header, test copts), the pattern of
# baselibs' futurecpp_internal. Tests compile the header through THIS
# target's _virtual_includes/ tree, which is outside the coverage scope; the
# reporter must still attribute the data to the declared header.
cc_library(
    name = "vendored_math_internal",
    testonly = True,
    hdrs = ["vendored/include/vendored/inline_math.h"],
    defines = ["VENDORED_MATH_INTERNAL_TEST=1"],
    strip_include_prefix = "vendored/include",
)

# Platform-dependent library: one source per variant, selected on the
# platform of the build. The LLVM run (host platform) compiles and measures
# platform_host.cpp, the gcov run (//platforms:gcov_target) platform_target.cpp.
# The scope must list the variant of the run's platform, not the host's
# (coverage_tool#23).
cc_library(
    name = "platform_dep",
    srcs = select({
        "//platforms:is_gcov_target": ["platform_target.cpp"],
        "//conditions:default": ["platform_host.cpp"],
    }),
    hdrs = ["platform_dep.h"],
)

# One root per platform, selected in the SCOPE's deps (tools/coverage/BUILD),
# the baselibs layout: the host root is incompatible with the gcov platform.
# The select() must resolve for the scope's platform or the scope, the report
# generator and every test become incompatible and bazel coverage silently
# skips all tests (coverage_tool#23).
cc_library(
    name = "host_root",
    srcs = ["host_root.cpp"],
    target_compatible_with = select({
        "//platforms:is_gcov_target": ["@platforms//:incompatible"],
        "//conditions:default": [],
    }),
)

cc_library(
    name = "target_root",
    srcs = ["target_root.cpp"],
)

cc_test(
    name = "coverable_test",
    srcs = ["coverable_test.cpp"],
    deps = [
        ":coverable",
        ":platform_dep",
        ":vendored_math_internal",
        "//third_party:extlib",
        "//third_party:vendored_ext",
    ],
)
