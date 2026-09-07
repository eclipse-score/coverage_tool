..
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

Adoption guide
==============

.. document:: score_coverage user manual
   :id: doc__coverage_user_manual
   :version: 1
   :status: draft
   :safety: ASIL_B
   :security: NO
   :realizes: wp__sw_development_plan

What the pipeline provides
--------------------------

- **One report for C++ and Rust** (line and branch coverage), produced by
  ``llvm-cov`` directly from covmap instrumentation, without gcov or genhtml.
- **Untested in-scope files appear at exact 0 %**: all targets are instrumented
  at build time, and the reporter runs ``llvm-cov --empty-profile`` over the
  archives of libraries no test links against. The denominators come from the
  compiler's own coverage map, not from a source-text heuristic.
- **Justifications**: ``COV_JUSTIFIED`` in-code markers plus a YAML database turn
  intentionally uncovered lines into *justified* lines, tracked in an
  **effective coverage** metric with stale-justification detection.
- **Gating**: the report generator exits non-zero when the gated coverage is
  below ``COVERAGE_THRESHOLD`` (default 100).

A complete working consumer setup is the ``integration_tests/`` workspace of the
repository; every snippet below is taken from it.

Components
----------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Target
     - Purpose
   * - ``@score_coverage//:merger``
     - Per-test coverage output generator (profraw to profdata plus object
       metadata). Referenced directly from the consumer's bazelrc.
   * - ``score_coverage_scope`` (``defs.bzl``)
     - Declares which targets are in scope; emits the source allowlist and the
       baseline-archive manifest through an aspect.
   * - ``score_coverage_reporter`` (``defs.bzl``)
     - Consumer-side wrapper wiring scope, workspace root and LLVM tools into
       the final report generator.
   * - ``@score_coverage//:generate_coverage_html``
     - Orchestration: unpacks the report, applies justifications, writes the
       summary, enforces the threshold, optionally archives.
   * - ``@score_coverage//:justify``, ``//:effective_coverage``, ``//:coverage_summary``
     - Standalone entry points of the justification and summary layer (called
       in-process by ``generate_coverage_html``).
   * - ``@score_coverage//:enable_llvm_coverage_for_death_tests``
     - ``cc_feature`` adding ``-mllvm -runtime-counter-relocation`` (continuous
       mode profiling for death tests).

Prerequisites
-------------

1. A Bzlmod workspace (``MODULE.bazel``).
2. A Linux x86_64 host. The pipeline runs on the host platform; do not combine
   it with QNX or other cross-platform configs.
3. For Rust: a Ferrocene toolchain built by ``ferrocene_toolchain_builder``
   1.3.1 or newer, wired through ``score_toolchains_rust`` 0.10.0 or newer.
   Its coverage-tools tarball ships ``llvm-cov`` and ``llvm-profdata`` built
   from the same LLVM as ``rustc``.

Step 1: depend on score_coverage
--------------------------------

.. code-block:: starlark

   bazel_dep(name = "score_coverage", version = "<version>")

Add one line to the **root** ``BUILD`` file so the reporter can locate the
workspace root at runtime:

.. code-block:: starlark

   exports_files(["MODULE.bazel"])

Step 2: declare the coverage toolchains
---------------------------------------

.. code-block:: starlark

   bazel_dep(name = "score_toolchains_rust", version = "0.10.0", dev_dependency = True)
   bazel_dep(name = "toolchains_llvm", version = "1.8.0", dev_dependency = True)

   llvm = use_extension("@toolchains_llvm//toolchain/extensions:llvm.bzl", "llvm", dev_dependency = True)
   llvm.toolchain(
       cxx_standard = {"": "c++17"},
       extra_known_features = ["@score_coverage//:enable_llvm_coverage_for_death_tests"],
       llvm_version = "22.1.7",
       stdlib = {"": "stdc++"},
   )
   use_repo(llvm, "llvm_toolchain", "llvm_toolchain_llvm")

For Rust no coverage-specific toolchain is needed. Register the standard
Ferrocene toolchain as usual:

.. code-block:: text

   common --extra_toolchains=@score_toolchains_rust//toolchains/ferrocene:ferrocene_x86_64_unknown_linux_gnu

``rules_rust`` only instruments crates when the ``rust_toolchain`` declares
``llvm_cov``. A Ferrocene toolchain from an older ``score_toolchains_rust``, or a
custom instance without ``coverage_tools_url``, silently produces no Rust
coverage (see :ref:`coverage_constraints`).

Step 3: declare scope and reporter
----------------------------------

In ``tools/coverage/BUILD``:

.. code-block:: starlark

   load("@score_coverage//:defs.bzl", "score_coverage_reporter", "score_coverage_scope")

   score_coverage_scope(
       name = "coverage_scope",
       testonly = True,
       deps = [
           "//src/mylib",           # cc_library
           "//src/rust/mycrate",    # rust_library
           "//src/rust/tool:tool",  # rust_binary
       ],
   )

   score_coverage_reporter(
       name = "reporter_wrapper",
       testonly = True,
       coverage_scope = ":coverage_scope",
       llvm_cov = "@llvm_toolchain//:llvm-cov",
       llvm_profdata = "@llvm_toolchain//:llvm-profdata",
       llvm_cxxfilt = "@llvm_toolchain_llvm//:bin/llvm-cxxfilt",
   )

The scope aspect walks the listed targets and their transitive in-workspace
dependencies, collecting source files (allowlist) and compiled archives
(baselines). Everything in scope but untested shows up at 0 %; everything
outside the scope (tests, mocks, external dependencies) is filtered out of the
report. The scope list is the written record of what is covered: a production
library missing from it silently vanishes from the report, so every new
library must be added, and exclusions need a written decision.

Step 4: import the bazelrc config
---------------------------------

Copy the ``coverage:llvm_cov`` block from ``integration_tests/.bazelrc`` into the
repository's bazelrc, directly or via ``import``. Place the import **before** any
``try-import %workspace%/user.bazelrc``: bazelrc resolves last-wins and the local
override file must stay last. The two labels to adapt:

.. code-block:: text

   coverage:llvm_cov --coverage_output_generator=@score_coverage//:merger
   coverage:llvm_cov --coverage_report_generator=//tools/coverage:reporter_wrapper

Do **not** combine ``--config=llvm_cov`` with configs that append other
``--extra_toolchains`` (for example a GCC host config): the last toolchain wins
resolution and a GCC toolchain produces no covmap data.

Step 5 (optional): justifications
---------------------------------

``tools/coverage/coverage_justifications.yaml``:

.. code-block:: yaml

   version: 1
   justifications:
     - id: hw-unreachable-on-x86
       category: platform_specific
       platforms: [linux]
       reason: |
         ARM-only error path; cannot be exercised by x86 CI.

Mark the code in place:

.. code-block:: cpp

   return false;  // COV_JUSTIFIED hw-unreachable-on-x86

   // or a region:
   // COV_JUSTIFIED_START hw-unreachable-on-x86
   if (running_on_arm()) { ... }
   // COV_JUSTIFIED_STOP

Valid categories: ``defensive_programming``, ``tool_false_positive``,
``platform_specific``, ``other``. Ids are kebab-case. Justified lines render
orange in the HTML and count as covered in the *effective* metric. A
justification on a line that is meanwhile covered is flagged as **stale**. A
marker whose id is unknown is reported as a warning and does not count.

Step 6: run it
--------------

.. code-block:: bash

   bazel coverage --config=llvm_cov //... --build_tests_only

   bazel run @score_coverage//:generate_coverage_html -- \
       --yaml tools/coverage/coverage_justifications.yaml

   # CI variant: HTML + LCOV + JUnit XMLs for artifact upload, gate at 95 %
   COVERAGE_THRESHOLD=95 bazel run @score_coverage//:generate_coverage_html -- \
       --yaml tools/coverage/coverage_justifications.yaml \
       --archive-dir coverage_artifacts

``--yaml`` is optional: without it, justification processing is skipped and the
gate applies to the **raw** line coverage computed from the LCOV data.
``--build_tests_only`` is mandatory: without it, coverage builds every target
matched by the pattern, including manual-tagged or platform-incompatible test
binaries.

Inside GitHub Actions a markdown summary is appended to ``GITHUB_STEP_SUMMARY``
automatically when ``--summary-md`` is absent. The summary is written before the
gate decides the exit code, so a failing gate still leaves it on the run page.

Command reference
-----------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Effect
   * - ``COVERAGE_THRESHOLD=<pct>``
     - Minimum gated coverage in percent (default 100). Effective line coverage
       with ``--yaml``, raw line coverage without. Must be a number in
       ``[0, 100]``; anything else is rejected with exit 2.
   * - ``--yaml <path>``
     - Justification YAML, relative to the workspace root.
   * - ``--archive-dir <dir>``
     - Assemble HTML report, ``coverage_report.dat`` (LCOV), justification
       report and JUnit XMLs into ``<dir>`` for artifact upload.
   * - ``--archive <name>``
     - Same content as a local ``<name>.zip`` (do not upload it: upload-artifact
       zips again).
   * - ``--testlogs-subdir <dir>``
     - Subtree of ``bazel-testlogs`` whose ``test.xml`` files are archived.
   * - ``--platform linux|qnx``
     - Platform filter for justifications and default output directory
       ``coverage_<platform>``.
   * - ``--summary-md <path>``
     - Write the markdown summary to ``<path>`` instead of the step summary.
   * - ``output-dir``
     - HTML output directory (default ``coverage_<platform>``).

Exit codes: ``0`` gate passed, ``1`` gate failed, ``2`` no verdict possible
(missing or non-zip report, invalid threshold, justification or tool failure).
