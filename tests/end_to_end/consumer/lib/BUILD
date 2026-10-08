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

# A library in a package WITHOUT tests, exercised from the "test" subpackage
# (the baselibs layout: score/os is tested from score/os/test). Bazel guesses
# --instrumentation_filter from the packages of the test targets and strips
# only a trailing "/tests" (plural), so //lib is outside the guessed filter.
# No deps on purpose: a dependency on an instrumented target would get the
# library compiled with coverage anyway (rules_cc instruments a target whose
# direct dep is instrumented). Without an explicit filter this library shows
# 0 % on the gcov backend (its counters are dropped by Bazel's collector) and
# is missing on the LLVM backend (compiled without instrumentation).
cc_library(
    name = "cross_pkg",
    srcs = ["cross_pkg.cpp"],
    hdrs = ["cross_pkg.h"],
    visibility = ["//visibility:public"],
)
