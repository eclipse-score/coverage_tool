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

"""
Coverage scope rule for deriving file-level allowlists from implementation targets.

This rule uses an aspect to traverse the build graph starting from the listed
implementation targets (cc_library, rust_library, rust_binary) through their
transitive deps. At each node it collects the actual source files.

- cc_library (and rust_library, which also provides CcInfo in rules_rust
  0.68.x): source files come from the srcs/hdrs attributes; static archives
  (including the rlib exposed as a .a symlink) are collected for baseline
  (zero-coverage) reporting.
- rust_binary (no CcInfo): source files come from CrateInfo.srcs; the
  coverage-built executable itself serves as the baseline object.

The rule writes three text files the reporter consumes:

- ``<name>_allowlist.txt``: one canonical source file path per line
  (``<pkg>/<file>`` for the main repository, ``external/<repo>/<file>`` for a
  header a workspace target vendors from an external repository).
- ``<name>_path_map.txt``: ``<virtual path>\t<canonical path>`` per header a
  workspace target exposes through ``strip_include_prefix`` / ``include_prefix``.
  The compiler records the generated ``<pkg>/_virtual_includes/<target>/...``
  path; the reporter maps it back to the declared header.
- ``<name>_objects.txt``: archives / executables for the zero-coverage baseline.

The source files themselves are exported in the ``source_files`` output group
so the reporter can stage them for llvm-cov from its runfiles, independent of
what happens to exist in the workspace directory at report time.
"""

load("@rules_rust//rust:rust_common.bzl", "CrateInfo")

# =============================================================================
# Provider to carry collected source file paths through the aspect
# =============================================================================

_CoverageScopeInfo = provider(
    doc = "Carries source file paths and object files collected by the coverage scope aspect.",
    fields = {
        "source_files": "Depset of canonical source file path strings.",
        "source_file_objects": "Depset of the File objects behind source_files (staged by the reporter).",
        "path_map": "Depset of '<virtual path>\\t<canonical path>' strings for headers behind include prefixes.",
        "object_files": "Depset of compiled archive/executable File objects for baseline coverage.",
    },
)

# =============================================================================
# Aspect: traverses library/binary deps to collect files
# =============================================================================

def _is_workspace_target(target):
    """True for targets of the main repository (not of an external module)."""
    label = str(target.label)
    return not label.startswith("@@") or label.startswith("@@//")

def _workspace_relative(f):
    """short_path in the form the reporter compares against covmap paths.

    Main-repository files: "<pkg>/<file>". External files have a short_path
    of "../<repo>/<file>"; the compiler records them as "external/<repo>/<file>".
    """
    if f.short_path.startswith("../"):
        return "external/" + f.short_path[3:]
    return f.short_path

def _match_declared(tail, declared_paths):
    """The declared header a virtual-includes path ends with, at a path-component boundary."""
    for path in declared_paths:
        if path == tail or path.endswith("/" + tail):
            return path
    return None

def _virtual_include_map(target, ctx, declared_hdrs):
    """'<virtual path>\\t<canonical path>' for the headers THIS target exposes via a _virtual_includes/ tree.

    Only headers the target generated itself are considered (``owner``), so a
    workspace rule that merely forwards the CcInfo of an external library does
    not contribute that library's headers.
    """
    marker = "/_virtual_includes/" + target.label.name + "/"
    include_prefix = getattr(ctx.rule.attr, "include_prefix", "") or ""
    include_prefix = include_prefix.strip("/")
    entries = []
    for f in target[CcInfo].compilation_context.direct_public_headers:
        if f.owner != target.label or marker not in f.short_path:
            continue
        tail = f.short_path.split(marker, 1)[1]
        if include_prefix and tail.startswith(include_prefix + "/"):
            tail = tail[len(include_prefix) + 1:]
        canonical = _match_declared(tail, declared_hdrs)
        if canonical:
            entries.append(f.short_path + "\t" + canonical)
    return entries

def _coverage_scope_aspect_impl(target, ctx):
    """Collects source file paths and archive files from the build graph."""
    direct_files = []
    direct_file_objects = []
    direct_map = []
    direct_archives = []
    transitive = []
    transitive_file_objects = []
    transitive_map = []
    transitive_archives = []

    # At cc_library / rust_library targets (rust_library provides CcInfo with
    # its rlib exposed as a .a symlink): collect srcs, hdrs, and static archive
    if CcInfo in target:
        in_workspace = _is_workspace_target(target)
        declared_hdrs = []
        if in_workspace:
            # The checked-in files the target declares. A header a workspace
            # target vendors from an external repository is part of that
            # target and therefore in scope (eclipse-score/baselibs#558);
            # files of external TARGETS never are (the aspect still visits
            # them, but in_workspace is False there).
            for attr_name in ["srcs", "hdrs"]:
                if hasattr(ctx.rule.attr, attr_name):
                    for src in getattr(ctx.rule.attr, attr_name):
                        for f in src.files.to_list():
                            if f.is_source:
                                path = _workspace_relative(f)
                                direct_files.append(path)
                                direct_file_objects.append(f)
                                if attr_name == "hdrs":
                                    declared_hdrs.append(path)

            # With strip_include_prefix / include_prefix, Bazel compiles
            # against a generated _virtual_includes/ symlink tree and the
            # coverage mapping records THAT path, never the declared header.
            # Record the mapping so the reporter can report the declared file.
            direct_map.extend(_virtual_include_map(target, ctx, declared_hdrs))

            # Collect .a archive files for baseline coverage.
            for linker_input in target[CcInfo].linking_context.linker_inputs.to_list():
                for lib in linker_input.libraries:
                    for archive in [lib.static_library, lib.pic_static_library]:
                        if archive and "/external/" not in archive.path and not archive.path.startswith("external/"):
                            direct_archives.append(archive)
                            break
    elif CrateInfo in target:
        # rust_binary: no CcInfo, collect .rs sources from CrateInfo and use the
        # coverage-built executable as the baseline object.
        for f in target[CrateInfo].srcs.to_list():
            if not f.path.startswith("external/") and f.is_source:
                direct_files.append(f.short_path)
                direct_file_objects.append(f)
        out = target[CrateInfo].output
        if out and "/external/" not in out.path and not out.path.startswith("external/"):
            direct_archives.append(out)

    # Propagate from children traversed by the aspect
    for attr_name in ["components", "implementation", "deps", "implementation_deps", "exported_deps"]:
        if hasattr(ctx.rule.attr, attr_name):
            for dep in getattr(ctx.rule.attr, attr_name):
                if _CoverageScopeInfo in dep:
                    transitive.append(dep[_CoverageScopeInfo].source_files)
                    transitive_file_objects.append(dep[_CoverageScopeInfo].source_file_objects)
                    transitive_map.append(dep[_CoverageScopeInfo].path_map)
                    transitive_archives.append(dep[_CoverageScopeInfo].object_files)

    return [_CoverageScopeInfo(
        source_files = depset(direct_files, transitive = transitive),
        source_file_objects = depset(direct_file_objects, transitive = transitive_file_objects),
        path_map = depset(direct_map, transitive = transitive_map),
        object_files = depset(direct_archives, transitive = transitive_archives),
    )]

_coverage_scope_aspect = aspect(
    implementation = _coverage_scope_aspect_impl,
    attr_aspects = ["components", "implementation", "deps", "implementation_deps", "exported_deps"],
    doc = "Traverses cc_library/rust_library/rust_binary hierarchy to collect implementation source files.",
)

# =============================================================================
# Rule: aggregates aspect results into an allowlist file
# =============================================================================

def _coverage_scope_impl(ctx):
    """Aggregates aspect results into the allowlist, path map and baseline objects manifest."""
    all_files = {}
    all_map = {}
    all_objects = []
    all_sources = []

    for dep in ctx.attr.deps:
        if _CoverageScopeInfo in dep:
            for path in dep[_CoverageScopeInfo].source_files.to_list():
                if path:
                    all_files[path] = True
            for entry in dep[_CoverageScopeInfo].path_map.to_list():
                all_map[entry] = True
            all_objects.append(dep[_CoverageScopeInfo].object_files)
            all_sources.append(dep[_CoverageScopeInfo].source_file_objects)

    sorted_files = sorted(all_files.keys())
    sorted_map = sorted(all_map.keys())
    object_depset = depset(transitive = all_objects)
    source_depset = depset(transitive = all_sources)

    # Write the allowlist file
    output = ctx.actions.declare_file(ctx.attr.name + "_allowlist.txt")
    ctx.actions.write(
        output = output,
        content = "\n".join(sorted_files) + "\n" if sorted_files else "",
    )

    # Write the virtual-includes -> declared header map
    map_output = ctx.actions.declare_file(ctx.attr.name + "_path_map.txt")
    ctx.actions.write(
        output = map_output,
        content = "\n".join(sorted_map) + "\n" if sorted_map else "",
    )

    # Write archive file paths for baseline coverage (reporter uses these as --object args)
    archive_paths = sorted(set([f.short_path for f in object_depset.to_list()]))
    objects_output = ctx.actions.declare_file(ctx.attr.name + "_objects.txt")
    ctx.actions.write(
        output = objects_output,
        content = "\n".join(archive_paths) + "\n" if archive_paths else "",
    )

    return [
        DefaultInfo(files = depset([output, map_output, objects_output], transitive = [object_depset])),
        OutputGroupInfo(
            allowlist = depset([output]),
            path_map = depset([map_output]),
            objects = depset([objects_output]),
            object_files = object_depset,
            source_files = source_depset,
        ),
    ]

def _coverage_transition_impl(settings, attr):
    # This dictionary modifies the build configuration
    return {
        "//command_line_option:collect_code_coverage": True,
    }

# Define the transition
coverage_transition = transition(
    implementation = _coverage_transition_impl,
    inputs = [],
    outputs = ["//command_line_option:collect_code_coverage"],
)

def _coverage_wrapper_impl(ctx):
    # Forward the executable or providers from the underlying target
    actual_target = ctx.attr.actual[0]
    return [actual_target[DefaultInfo]]

# Define a rule that applies the transition to its 'actual' dependency
coverage_wrapper = rule(
    implementation = _coverage_wrapper_impl,
    attrs = {
        "actual": attr.label(
            mandatory = True,
            cfg = coverage_transition,  # Applying the transition here
        ),
        # Mandatory attribute needed when a rule uses a transition
        "_allowlist_function_transition": attr.label(
            default = "@bazel_tools//tools/allowlists/function_transition_allowlist",
        ),
    },
)

coverage_scope = rule(
    implementation = _coverage_scope_impl,
    doc = """Generates a file-level coverage allowlist from implementation targets.

    Uses an aspect to traverse the listed targets (cc_library, rust_library,
    rust_binary) and their transitive deps, collecting all source files
    (srcs + hdrs / CrateInfo.srcs). Outputs the allowlist (one canonical file
    path per line), the virtual-includes path map and the baseline objects
    manifest, and exports the source files themselves in the ``source_files``
    output group.

    The coverage reporter restricts reporting to exactly the allowlisted
    files, reports headers behind include prefixes under their declared path,
    and stages the sources so every HTML page can be rendered.
    """,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            aspects = [_coverage_scope_aspect],
            cfg = coverage_transition,
            doc = "Implementation targets whose transitive deps define the coverage scope.",
        ),
    },
)
