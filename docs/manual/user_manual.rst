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

.. _scope_platform:

**The scope is evaluated for a platform.** Bazel analyses the coverage report
generator, and with it the scope, in the exec configuration, that is for the
host platform, whatever ``--platforms`` the coverage run uses. On the Linux
run host and target coincide. For a run that targets another platform the
scope must say so, otherwise every ``select()`` on the platform resolves for
the host: the Linux variants of platform-specific code appear at 0 % and the
target's variants are missing. Declare one scope per platform:

.. code-block:: starlark

   score_coverage_scope(
       name = "coverage_scope_qnx",
       testonly = True,
       platform = "@score_bazel_platforms//:x86_64-qnx-sdp_8.0.0-posix",
       tags = ["manual"],  # see below
       deps = SCOPE_DEPS,
   )

``platform`` is the label the run passes as ``--platforms``. Roots that exist
on one platform only must sit behind a ``select()`` in ``deps``; that
``select()`` is resolved for ``platform`` too, because the transition applies
to the scope rule itself, not only to its dependencies. A root that
is incompatible with the platform makes the scope incompatible, and that
does **not** fail the coverage run: every test depends on the report
generator and inherits the incompatibility, so Bazel skips all tests
(``Executed 0 out of N tests: N were skipped``) and no report is written.
Build the scope explicitly to get the dependency chain to the offending
constraint:

.. code-block:: shell

   bazel build --config=<your QNX build config> --collect_code_coverage //tools/coverage:coverage_scope_qnx

On a Linux host without the QNX SDP the same analysis runs in seconds with
a stand-in: lend the host's GCC ``cc_toolchain`` to the QNX platform in a
scratch package (not committed) and pass it together with the QNX Rust
toolchain. Incompatibility and visibility are decided by constraints and
labels, not by the compiler, so the chain Bazel prints is the real one.

.. code-block:: starlark

   toolchain(
       name = "fake_qnx_cc",
       target_compatible_with = ["@platforms//cpu:x86_64", "@platforms//os:qnx"],
       toolchain = "@score_gcc_x86_64_toolchain//:cc_toolchain",
       toolchain_type = "@bazel_tools//tools/cpp:toolchain_type",
   )

.. code-block:: shell

   bazel build --nobuild --collect_code_coverage \
       --platforms=@score_bazel_platforms//:x86_64-qnx-sdp_8.0.0-posix \
       --extra_toolchains=//scratch:fake_qnx_cc \
       --extra_toolchains=@score_toolchains_rust//toolchains/ferrocene:ferrocene_x86_64_pc_nto_qnx800 \
       //tools/coverage:coverage_scope_qnx

Rust roots are the usual culprits on QNX: crate_universe marks crates
incompatible with platforms outside rules_rust's triple list, and the gcov
backend cannot measure Rust anyway, so keep Rust roots out of a QNX scope.
Tag such a scope ``manual``, like the gcov reporter: a wildcard ``bazel build //...``
on a Linux host would otherwise analyse it for the other platform in a
configuration where that platform's toolchains are not registered and fail
toolchain resolution. The coverage run names the reporter, and through it
the scope, explicitly, so the tag does not affect it.

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

.. _instrumentation_filter:

Set the instrumentation filter explicitly, to the module's root package:

.. code-block:: text

   coverage:llvm_cov --instrumentation_filter=^//score[/:]

Left unset, Bazel guesses the filter from the **packages of the test
targets** and strips only a trailing ``/tests`` (plural) to reach the code
under test; ``bazel coverage`` prints the guess as ``Using default value for
--instrumentation_filter``. A library whose tests live in a ``test``
subpackage (``score/os`` tested from ``score/os/test``) is then outside the
filter. rules_cc still compiles it with counters when one of its direct deps
is instrumented, which hides the problem for most libraries, but a library
without such a dep is compiled without instrumentation and appears as
``no-data``. On the gcov backend the consequence is worse (see step 4b). The
reporters warn when the pattern is visible in the data (files without test
data whose directory is tested from a ``test/`` or ``tests/`` subdirectory).

Step 4b (optional): QNX on-target coverage, the gcov backend
------------------------------------------------------------

QCC is GCC-based and cannot emit LLVM coverage mapping, so QNX coverage uses
gcov counters. The tests run inside QEMU through ``score_qnx_unit_tests``,
which brings the counters back; Bazel's own collector turns them into LCOV;
score_coverage's gcov reporter produces the same report zip as on Linux. C++
only: Rust sources in scope are listed as *not instrumentable* on this
backend and are measured by the Linux run.

Declare a second reporter next to the LLVM one, with the gcov binary of the
QCC package (add ``score_qcc_x86_64_toolchain_pkg`` to the ``use_repo`` of
the toolchain extension):

.. code-block:: starlark

   score_coverage_reporter(
       name = "gcov_reporter_wrapper",
       testonly = True,
       backend = "gcov",
       coverage_scope = ":coverage_scope_qnx",  # platform = the QNX platform, see step 3
       gcov = "@score_qcc_x86_64_toolchain_pkg//:gcov",
       tags = ["manual"],  # keeps `bazel build //...` on a Linux host from fetching the QNX SDP
   )

The ``manual`` tag matters: the target depends on the QNX SDP package, and a
wildcard build on a host without QNX credentials would otherwise fail on the
download. ``--coverage_report_generator`` names the target explicitly and is
not affected.

and a coverage config that resets the LLVM settings, keeps Bazel's per-test
collector and points the final step at that reporter (copy and adapt the
``coverage:gcov`` block of ``integration_tests/.bazelrc``):

.. code-block:: text

   coverage:qnx --config=<your QNX build config>       # QCC, IFS toolchain, platforms
   coverage:qnx --run_under=@score_qnx_unit_tests//src:run_under_qnx
   coverage:qnx --test_lang_filters=cc
   coverage:qnx --instrument_test_targets
   coverage:qnx --instrumentation_filter=^//score[/:]
   coverage:qnx --noexperimental_use_llvm_covmap
   coverage:qnx --noexperimental_generate_llvm_lcov
   coverage:qnx --test_env=GENERATE_LLVM_LCOV --test_env=COVERAGE_GCOV_PATH --test_env=LLVM_PROFILE_CONTINUOUS_MODE
   coverage:qnx --coverage_output_generator=@bazel_tools//tools/test:lcov_merger
   coverage:qnx --coverage_report_generator=//tools/coverage:gcov_reporter_wrapper

The instrumentation filter is **required** on this backend, not only
advisable: Bazel's own collector converts counters only for the targets
inside the filter, so a library outside Bazel's guessed filter shows 0 % even
though its counters came back from the target (baselibs' ``score/os``: 13 %
on QNX against 80 % on Linux before the line was added; see
:ref:`the instrumentation filter <instrumentation_filter>`).

The LLVM-only rustc flags (``-Zcoverage-options=branch`` and friends) stay
out of the way as long as they live in their own ``coverage:llvm_cov`` config,
as in Step 4. If your workspace puts them on the bare ``coverage`` command
instead, declare them with the list-typed
``--@rules_rust//rust/settings:extra_rustc_flags`` and add
``coverage:qnx --@rules_rust//rust/settings:extra_rustc_flags=`` to clear
them: an empty value resets that list, whereas the repeatable singular
``extra_rustc_flag`` accumulates and cannot be reset from a config.

Run and report as on Linux, with the platform filter for justifications:

.. code-block:: shell

   bazel coverage --config=qnx //score/... --build_tests_only
   bazel run @score_coverage//:generate_coverage_html -- --platform qnx \
       --yaml tools/coverage/coverage_justifications.yaml --archive-dir coverage_qnx_artifacts

Known differences to the LLVM backend: gcov has no lines for unused inline
functions and for closing braces; gcov counts every conditional jump the
compiler emits as a branch, including exception-handling edges, so branch
percentages are structurally lower than LLVM's; the report lists the
toolchain's line semantics, not LLVM's, so the two reports are compared per
file, not merged. Headers a workspace target vendors from an external
repository are measured as long as the vendoring target is inside the
instrumentation filter (Bazel's collector keeps the sources of instrumented
targets, external headers included).

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
     - Assemble HTML report, ``coverage_report.dat`` (LCOV),
       ``unmapped_files.txt`` (in-scope files without any coverage data),
       justification report and JUnit XMLs into ``<dir>`` for artifact upload.
   * - ``--archive <name>``
     - Same content as a local ``<name>.zip`` (do not upload it: upload-artifact
       zips again).
   * - ``--testlogs-subdir <dir>``
     - Subtree of ``bazel-testlogs`` whose ``test.xml`` files are archived.
   * - ``--platform linux|qnx``
     - Platform filter for justifications and default output directory
       ``coverage_<platform>``. Use ``qnx`` for reports of the gcov backend
       produced from QNX on-target runs.
   * - ``--summary-md <path>``
     - Write the markdown summary to ``<path>`` instead of the step summary.
   * - ``output-dir``
     - HTML output directory (default ``coverage_<platform>``).

Exit codes: ``0`` gate passed, ``1`` gate failed, ``2`` no verdict possible
(missing or non-zip report, invalid threshold, justification or tool failure).
