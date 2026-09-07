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
load("@rules_rust//rust:defs.bzl", "rust_binary", "rust_library")

# Fixtures for the coverage_scope analysis tests. They are only analyzed,
# never built: `manual` keeps them out of wildcard builds.
package(default_visibility = ["//score_coverage/tests/starlark:__subpackages__"])

MANUAL = ["manual"]

cc_library(
    name = "leaf",
    srcs = ["leaf.cpp"],
    hdrs = ["leaf.h"],
    tags = MANUAL,
)

cc_library(
    name = "mid",
    srcs = ["mid.cpp"],
    hdrs = ["mid.h"],
    tags = MANUAL,
    deps = [":leaf"],
)

cc_library(
    name = "impl_dep_user",
    srcs = ["user.cpp"],
    implementation_deps = [":leaf"],
    tags = MANUAL,
)

cc_library(
    name = "header_only",
    hdrs = ["only.h"],
    tags = MANUAL,
)

# A generated source must NOT enter the allowlist (only checked-in sources
# are coverage subjects).
genrule(
    name = "gen_source",
    outs = ["generated.cpp"],
    cmd = "echo 'int g() { return 1; }' > $@",
    tags = MANUAL,
)

cc_library(
    name = "with_generated",
    srcs = ["generated.cpp"],
    tags = MANUAL,
    deps = [":leaf"],
)

rust_library(
    name = "rlib",
    srcs = ["lib.rs"],
    edition = "2021",
    tags = MANUAL,
)

rust_binary(
    name = "rbin",
    srcs = ["main.rs"],
    edition = "2021",
    tags = MANUAL,
    deps = [":rlib"],
)
