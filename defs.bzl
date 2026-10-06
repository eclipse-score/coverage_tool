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

"""Public API of the score_coverage LLVM source-based coverage pipeline.

Consumers instantiate two targets in their own repository (typically in a
tools/coverage/BUILD file):

    load("@score_coverage//:defs.bzl",
         "score_coverage_reporter", "score_coverage_scope")

    score_coverage_scope(
        name = "coverage_scope",
        testonly = True,
        deps = ["//src/mylib", "//src/rust/mycrate"],
    )

    score_coverage_reporter(
        name = "reporter_wrapper",
        testonly = True,
        coverage_scope = ":coverage_scope",
        llvm_cov = "@llvm_toolchain//:llvm-cov",
        llvm_profdata = "@llvm_toolchain//:llvm-profdata",
        llvm_cxxfilt = "@llvm_toolchain_llvm//:bin/llvm-cxxfilt",
    )

and point Bazel at them from their coverage bazelrc config:

    coverage:llvm_cov --coverage_output_generator=@score_coverage//:merger
    coverage:llvm_cov --coverage_report_generator=//tools/coverage:reporter_wrapper

For gcov-based toolchains (GCC on Linux, QCC on QNX with the tests executed
on target through score_qnx_unit_tests) a second reporter with
backend = "gcov" and the toolchain's gcov binary is declared, together with
a scope of its own that names the run's platform (Bazel analyses the scope in
the exec configuration; without `platform` every select() resolves for the
host); the gcov coverage config keeps Bazel's own per-test merger:

    score_coverage_scope(
        name = "coverage_scope_qnx",
        testonly = True,
        platform = "@score_bazel_platforms//:x86_64-qnx-sdp_8.0.0-posix",
        deps = SCOPE_DEPS,
    )


    coverage:qnx --coverage_output_generator=@bazel_tools//tools/test:lcov_merger
    coverage:qnx --coverage_report_generator=//tools/coverage:gcov_reporter_wrapper

See README.md for the complete adoption guide (toolchains, bazelrc,
justifications, CI) and COVERAGE_GUIDE.md for how the pipeline works.
"""

load("//score_coverage:coverage_scope.bzl", _coverage_scope = "coverage_scope")
load("//score_coverage:reporter_wrapper.bzl", _reporter_wrapper = "reporter_wrapper")

score_coverage_scope = _coverage_scope

def score_coverage_reporter(
        name,
        coverage_scope,
        llvm_cov = None,
        llvm_profdata = None,
        llvm_cxxfilt = None,
        module_bazel = "//:MODULE.bazel",
        backend = "llvm",
        gcov = None,
        **kwargs):
    """Declare the consumer-side coverage report generator.

    The generated executable is passed to Bazel as
    --coverage_report_generator=//<pkg>:<name>. It wires the consumer's
    coverage scope, workspace root and coverage tools into score_coverage's
    reporter for the chosen backend.

    Args:
        name: Target name, referenced by --coverage_report_generator.
        coverage_scope: A score_coverage_scope target listing the production
            targets that define the coverage scope.
        llvm_cov: Label of the llvm-cov binary (the consumer's LLVM toolchain,
            e.g. "@llvm_toolchain//:llvm-cov"). Must come from the same LLVM
            major version that produced the coverage instrumentation.
            Required for backend = "llvm".
        llvm_profdata: Label of the llvm-profdata binary. Required for
            backend = "llvm".
        llvm_cxxfilt: Optional label of llvm-cxxfilt for symbol demangling
            (C++ Itanium and Rust v0/legacy). toolchains_llvm exposes it as
            "@llvm_toolchain_llvm//:bin/llvm-cxxfilt".
        module_bazel: The consumer's root MODULE.bazel, used at runtime to
            locate the real workspace root. Requires
            exports_files(["MODULE.bazel"]) in the consumer's root BUILD file.
        backend: "llvm" (Clang / rustc coverage mapping, Linux host tests) or
            "gcov" (GCC / QCC .gcda counters, e.g. QNX on-target tests run
            through score_qnx_unit_tests). One reporter target per backend.
        gcov: Label of the gcov binary matching the compiler that produced the
            .gcno/.gcda files, e.g. "@score_qcc_x86_64_toolchain_pkg//:gcov" or
            "@score_gcc_x86_64_toolchain_pkg//:gcov". Required for
            backend = "gcov".
        **kwargs: Common rule attributes (testonly, visibility, tags, ...).
    """
    if backend == "llvm" and (not llvm_cov or not llvm_profdata):
        fail("score_coverage_reporter(%s): backend \"llvm\" needs llvm_cov and llvm_profdata" % name)
    if backend == "gcov" and not gcov:
        fail("score_coverage_reporter(%s): backend \"gcov\" needs gcov" % name)
    _reporter_wrapper(
        name = name,
        backend = backend,
        coverage_scope = coverage_scope,
        module_bazel = module_bazel,
        llvm_cov = llvm_cov,
        llvm_profdata = llvm_profdata,
        llvm_cxxfilt = llvm_cxxfilt,
        gcov = gcov,
        **kwargs
    )
