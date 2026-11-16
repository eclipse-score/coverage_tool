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
    scope = Label(ctx.attr.coverage_scope)

    # The scope is built by the coverage invocation itself, in the configuration
    # of the tests, not as a dependency of this (exec-configured) wrapper; the
    # launcher locates its outputs at run time.
    if backend == "llvm":
        scope_flag = "--baseline_objects"
        scope_manifest = scope.name + "_objects.txt"
        tool_args = [
            '--llvm_cov="{}"'.format(_rlocation_path(ctx, ctx.file.llvm_cov)),
            '--llvm_profdata="{}"'.format(_rlocation_path(ctx, ctx.file.llvm_profdata)),
        ]
        if ctx.file.llvm_cxxfilt:
            tool_args.append('--llvm_cxxfilt="{}"'.format(_rlocation_path(ctx, ctx.file.llvm_cxxfilt)))
        tools = [ctx.attr.llvm_cov, ctx.attr.llvm_profdata, ctx.attr.llvm_cxxfilt]
        direct_files = [ctx.file.llvm_cov, ctx.file.llvm_profdata]
        if ctx.file.llvm_cxxfilt:
            direct_files.append(ctx.file.llvm_cxxfilt)
    else:
        scope_flag = "--gcno_manifest"
        scope_manifest = scope.name + "_gcno.txt"
        tool_args = ['--gcov="{}"'.format(_rlocation_path(ctx, ctx.file.gcov))]
        tools = [ctx.attr.gcov]
        direct_files = [ctx.file.gcov]
    tool_lines = "".join(["  {} \\\n".format(arg) for arg in tool_args])

    # Bazel invokes the coverage report generator from within its coverage
    # machinery, where an inherited RUNFILES_DIR may point at ANOTHER tool's
    # runfiles tree. Derive our own runfiles directory from $0 first and only
    # fall back to the inherited value.
    #
    # The generator runs unsandboxed in the execroot. The configuration the
    # scope was built in is taken from the per-test coverage files it is given
    # (bazel-out/<config>/testlogs/...), so the scope always matches the tests.
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

REPORTS_FILE=""
for arg in "$@"; do
  case "${{arg}}" in --reports_file=*) REPORTS_FILE="${{arg#--reports_file=}}" ;; esac
done
SCOPE_ARGS=()
CONFIG=""
if [[ -n "${{REPORTS_FILE}}" && -f "${{REPORTS_FILE}}" ]]; then
  CONFIG="$(sed -n -E 's#.*bazel-out/([^/]+)/testlogs/.*#\\1#p' "${{REPORTS_FILE}}" | head -n 1)"
fi
if [[ -n "${{CONFIG}}" ]]; then
  SCOPE_ROOT="${{PWD}}/bazel-out/${{CONFIG}}/bin"
  SCOPE_DIR="${{SCOPE_ROOT}}/{scope_package}"
  if [[ ! -f "${{SCOPE_DIR}}/{scope_name}_allowlist.txt" ]]; then
    echo "ERROR: ${{SCOPE_DIR}}/{scope_name}_allowlist.txt not found." >&2
    echo "Build {scope_label} in the same invocation as the tests, e.g." >&2
    echo "  bazel coverage <tests> {scope_label}" >&2
    exit 1
  fi
  SCOPE_ARGS=(
    --scope_root="${{SCOPE_ROOT}}"
    --coverage_allowlist="${{SCOPE_DIR}}/{scope_name}_allowlist.txt"
    --path_map="${{SCOPE_DIR}}/{scope_name}_path_map.txt"
    {scope_flag}="${{SCOPE_DIR}}/{scope_manifest}"
  )
fi
exec "${{RUNFILES_DIR}}/{reporter}" \\
  --workspace_root="${{WORKSPACE_ROOT}}" \\
{tool_lines}  "${{SCOPE_ARGS[@]}}" \\
  "$@"
""".format(
        module_bazel = _rlocation_path(ctx, module_bazel),
        reporter = _rlocation_path(ctx, reporter),
        scope_package = scope.package,
        scope_name = scope.name,
        scope_label = str(scope),
        scope_flag = scope_flag,
        scope_manifest = scope_manifest,
        tool_lines = tool_lines,
    )

    ctx.actions.write(
        output = launcher,
        content = script,
        is_executable = True,
    )

    runfiles = ctx.runfiles(
        files = [reporter, module_bazel] + direct_files,
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
        "coverage_scope": attr.string(
            mandatory = True,
            doc = "Label (as a string) of the score_coverage_scope target. Not a dependency: the scope " +
                  "is built by the coverage invocation, in the configuration of the tests.",
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
