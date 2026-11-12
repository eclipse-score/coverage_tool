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

# Opt-in fixtures: manual keeps them out of the normal consumer test suite
# and its hand-derived coverage expectations. Both tests measure the same
# object, but execute different branches so selection is observable.
cc_library(
    name = "subject",
    srcs = ["subject.cpp"],
    tags = ["manual"],
)

[
    cc_test(
        name = name,
        srcs = ["test.cpp"],
        args = [value],
        # GCC 12's text output needs source contents. Bazel otherwise supplies
        # counters and notes to this hook, but not the compilation sources.
        data = [
            "subject.cpp",
            "test.cpp",
        ],
        tags = ["manual"],
        deps = [":subject"],
    )
    for name, value in [
        ("positive_test", "1"),
        ("negative_test", "-1"),
    ]
]
