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
load(":forward.bzl", "forward_cc")

package(default_visibility = ["//visibility:public"])

# Forwarded third-party library: compiled with coverage, linked into the
# test binary, and NOT part of the report (coverage_tool#5).
forward_cc(
    name = "extlib",
    dep = "@itest_external//:extlib",
)

# Header vendored from the external module behind strip_include_prefix: part
# of this workspace target and therefore IN the report, under its source path
# (baselibs#558).
cc_library(
    name = "vendored_ext",
    hdrs = ["@itest_external//:include/vext/vext.h"],
    strip_include_prefix = "/include",
)
