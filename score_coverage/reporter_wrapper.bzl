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

"""Executable wrapper rule for the coverage reporter.

Instantiated in the CONSUMER repository (via the score_coverage_reporter
macro) so that the consumer's coverage_scope, MODULE.bazel and coverage tool
labels can be wired into the reporter, which itself lives in score_coverage.

Two backends share the wrapper: ``llvm`` (Clang / rustc covmap, llvm-cov and
llvm-profdata; Linux) and ``gcov`` (GCC / QCC ``.gcda`` counters, the
toolchain's ``gcov``; Linux with GCC, QNX on target). Both reporters consume
the same scope outputs and produce the same report zip.
"""

BACKENDS = ["llvm", "gcov"]

def _rlocation_path(ctx, file):
    """Return the Runfiles.Rlocation()-compatible path for a Bazel File.

    External-repo files have short_path = "../<repo>/<path>" — strip the
    "../". Main-workspace files have short_path = "<pkg>/<file>" — prepend
    the workspace name. Required because this rule mixes files from the
    consumer repo (_main) and from score_coverage / toolchain repos.
    """
    if file.short_path.startswith("../"):
        return file.short_path[3:]
    return ctx.workspace_name + "/" + file.short_path

def _reporter_wrapper_impl(ctx):
    launcher = ctx.actions.declare_file(ctx.label.name + ".sh")

    backend = ctx.attr.backend
    if backend == "llvm":
        if not ctx.file.llvm_cov or not ctx.file.llvm_profdata:
            fail("backend = \"llvm\" needs llvm_cov and llvm_profdata")
        reporter_attr = ctx.attr.reporter or ctx.attr._llvm_reporter
    elif backend == "gcov":
        if not ctx.file.gcov:
            fail("backend = \"gcov\" needs gcov (the toolchain's gcov binary)")
        reporter_attr = ctx.attr.reporter or ctx.attr._gcov_reporter
    else:
        fail("backend must be one of %s, got %s" % (BACKENDS, backend))
    reporter = reporter_attr[DefaultInfo].files_to_run.executable
    module_bazel = ctx.file.module_bazel
    coverage_scope = ctx.attr.coverage_scope
    allowlist_group = coverage_scope[OutputGroupInfo].allowlist.to_list()
    path_map_group = coverage_scope[OutputGroupInfo].path_map.to_list()
    objects_group = coverage_scope[OutputGroupInfo].objects.to_list()
    gcno_group = coverage_scope[OutputGroupInfo].gcno.to_list()
    object_files = coverage_scope[OutputGroupInfo].object_files
    gcno_files = coverage_scope[OutputGroupInfo].gcno_files
    source_files = coverage_scope[OutputGroupInfo].source_files

    if len(allowlist_group) != 1:
        fail("coverage_scope must provide exactly one allowlist file")
    if len(path_map_group) != 1:
        fail("coverage_scope must provide exactly one path map file")
    if len(objects_group) != 1:
        fail("coverage_scope must provide exactly one objects manifest file")
    if len(gcno_group) != 1:
        fail("coverage_scope must provide exactly one gcno manifest file")

    allowlist = allowlist_group[0]
    path_map = path_map_group[0]
    baseline_objects = objects_group[0]
    gcno_manifest = gcno_group[0]

    # Backend-specific tool arguments, every path in rlocation form.
    if backend == "llvm":
        tool_lines = '  --llvm_cov="{}" \\\n  --llvm_profdata="{}" \\\n  --baseline_objects="{}" \\\n'.format(
            _rlocation_path(ctx, ctx.file.llvm_cov),
            _rlocation_path(ctx, ctx.file.llvm_profdata),
            _rlocation_path(ctx, baseline_objects),
        )
        if ctx.file.llvm_cxxfilt:
            tool_lines += '  --llvm_cxxfilt="{}" \\\n'.format(_rlocation_path(ctx, ctx.file.llvm_cxxfilt))
    else:
        tool_lines = '  --gcov="{}" \\\n  --gcno_manifest="{}" \\\n'.format(
            _rlocation_path(ctx, ctx.file.gcov),
            _rlocation_path(ctx, gcno_manifest),
        )

    # Bazel invokes the coverage report generator from within its coverage
    # machinery, where an inherited RUNFILES_DIR may point at ANOTHER tool's
    # runfiles tree. Derive our own runfiles directory from $0 first and only
    # fall back to the inherited value.
    script = """#!/usr/bin/env bash
set -euo pipefail
SELF_RUNFILES_DIR="$(cd "$(dirname "$0")" && pwd)/$(basename "$0").runfiles"
if [[ -d "${{SELF_RUNFILES_DIR}}" ]]; then
  RUNFILES_DIR="${{SELF_RUNFILES_DIR}}"
elif [[ -z "${{RUNFILES_DIR:-}}" || ! -d "${{RUNFILES_DIR}}" ]]; then
  echo "ERROR: could not locate the reporter_wrapper runfiles directory" >&2
  exit 1
fi
export RUNFILES_DIR
WORKSPACE_ROOT="$(cd "$(dirname "$(readlink -f "${{RUNFILES_DIR}}/{module_bazel}")")" && pwd)/"
exec "${{RUNFILES_DIR}}/{reporter}" \\
  --coverage_allowlist="{allowlist}" \\
  --path_map="{path_map}" \\
  --workspace_root="${{WORKSPACE_ROOT}}" \\
{tool_lines}  "$@"
""".format(
        module_bazel = _rlocation_path(ctx, module_bazel),
        reporter = _rlocation_path(ctx, reporter),
        allowlist = _rlocation_path(ctx, allowlist),
        path_map = _rlocation_path(ctx, path_map),
        tool_lines = tool_lines,
    )

    ctx.actions.write(
        output = launcher,
        content = script,
        is_executable = True,
    )

    direct_files = [reporter, allowlist, path_map, module_bazel]
    if backend == "llvm":
        direct_files += [baseline_objects, ctx.file.llvm_cov, ctx.file.llvm_profdata]
        tools = [ctx.attr.llvm_cov, ctx.attr.llvm_profdata, ctx.attr.llvm_cxxfilt]
        if ctx.file.llvm_cxxfilt:
            direct_files.append(ctx.file.llvm_cxxfilt)
        baseline_inputs = object_files
    else:
        direct_files += [gcno_manifest, ctx.file.gcov]
        tools = [ctx.attr.gcov]
        baseline_inputs = gcno_files

    # The in-scope source files travel with the reporter: the coverage tool
    # must read them at report time, and neither generated headers nor
    # external repositories are reachable through the workspace directory then.
    runfiles = ctx.runfiles(
        files = direct_files,
        transitive_files = depset(transitive = [baseline_inputs, source_files]),
    ).merge(reporter_attr[DefaultInfo].default_runfiles)
    for tool in tools:
        if tool:
            runfiles = runfiles.merge(tool[DefaultInfo].default_runfiles)

    return [DefaultInfo(
        executable = launcher,
        runfiles = runfiles,
    )]

reporter_wrapper = rule(
    implementation = _reporter_wrapper_impl,
    executable = True,
    attrs = {
        "backend": attr.string(
            default = "llvm",
            values = BACKENDS,
            doc = "Coverage data format: llvm (Clang/rustc covmap) or gcov (GCC/QCC .gcda counters).",
        ),
        "reporter": attr.label(
            executable = True,
            cfg = "exec",
            doc = "Override of the reporter binary; defaults to score_coverage's reporter for the backend.",
        ),
        "_llvm_reporter": attr.label(
            executable = True,
            cfg = "exec",
            default = Label("//score_coverage:reporter"),
        ),
        "_gcov_reporter": attr.label(
            executable = True,
            cfg = "exec",
            default = Label("//score_coverage:gcov_reporter"),
        ),
        "coverage_scope": attr.label(
            cfg = "target",
            mandatory = True,
            doc = "A score_coverage_scope target defining the in-scope sources/archives.",
        ),
        "module_bazel": attr.label(
            allow_single_file = True,
            mandatory = True,
            doc = "The consumer's root MODULE.bazel; used to locate the real workspace root.",
        ),
        "llvm_cov": attr.label(
            allow_single_file = True,
            doc = "llvm-cov binary, e.g. @llvm_toolchain//:llvm-cov (llvm backend).",
        ),
        "llvm_profdata": attr.label(
            allow_single_file = True,
            doc = "llvm-profdata binary, e.g. @llvm_toolchain//:llvm-profdata (llvm backend).",
        ),
        "gcov": attr.label(
            allow_single_file = True,
            doc = "gcov binary of the compiler that produced the .gcno/.gcda files, e.g. " +
                  "@score_qcc_x86_64_toolchain_pkg//:gcov (gcov backend).",
        ),
        "llvm_cxxfilt": attr.label(
            allow_single_file = True,
            doc = "Optional llvm-cxxfilt for demangling, e.g. " +
                  "@llvm_toolchain_llvm//:bin/llvm-cxxfilt.",
        ),
    },
)
