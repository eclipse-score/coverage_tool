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

Architecture
============

.. document:: score_coverage architecture
   :id: doc__coverage_architecture
   :version: 1
   :status: draft
   :safety: ASIL_B
   :security: NO
   :realizes: wp__sw_implementation

The pipeline replaces Bazel's two coverage hooks, ``--coverage_output_generator``
and ``--coverage_report_generator``, with its own tools and adds a
justification and gating layer on top. It has two phases.

.. uml::

   @startuml
   skinparam componentStyle rectangle
   package "Phase 1: bazel coverage --config=llvm_cov" {
     [Clang / rustc\ncovmap instrumentation] --> [test binaries]
     [test binaries] --> (profraw per test)
     (profraw per test) --> [merger.py\n--coverage_output_generator]
     [merger.py\n--coverage_output_generator] --> (coverage.dat zip\nprofdata + meta.json)
     [score_coverage_scope\naspect] --> (allowlist.txt\nobjects.txt)
     (coverage.dat zip\nprofdata + meta.json) --> [reporter.py\n--coverage_report_generator]
     (allowlist.txt\nobjects.txt) --> [reporter.py\n--coverage_report_generator]
     [reporter.py\n--coverage_report_generator] --> (_coverage_report.dat zip\nhtml_report, lcov_report, text_report)
   }
   package "Phase 2: bazel run //:generate_coverage_html" {
     (_coverage_report.dat zip\nhtml_report, lcov_report, text_report) --> [generate_coverage_html.py]
     [generate_coverage_html.py] --> [justify.py]
     [justify.py] --> (manifest.json)
     (manifest.json) --> [effective_coverage.py]
     [effective_coverage.py] --> (report.json\nsummary.txt)
     [generate_coverage_html.py] --> [coverage_summary.py]
     [generate_coverage_html.py] --> (gate verdict\nexit 0 / 1 / 2)
     [generate_coverage_html.py] --> (archive dir)
   }
   @enduml

Phase 1: collection
-------------------

The ``llvm_cov`` bazelrc config, copied by the consumer from the integration
workspace, does four things:

1. **Swaps the compilers.** C++ is compiled with a hermetic Clang/LLVM toolchain
   instead of GCC; Rust with the Ferrocene toolchain of ``score_toolchains_rust``,
   which has LLVM coverage tools attached. Both emit the same covmap format.
2. **Turns on instrumentation.** ``--experimental_use_llvm_covmap`` plus the
   ``coverage`` feature for C++; ``rules_rust`` adds ``-Cinstrument-coverage`` to
   rustc once the toolchain declares coverage tools. Runtime counter relocation
   (``-mllvm -runtime-counter-relocation`` via the ``cc_feature``,
   ``-Cllvm-args=-runtime-counter-relocation`` for Rust) enables continuous mode
   so coverage survives abnormal termination. Rust branch regions need
   ``-Zcoverage-options=branch`` on a rolling Ferrocene.
3. **Installs the per-test tool.** ``merger.py`` merges the test's ``profraw``
   files with ``llvm-profdata``, records the instrumented objects, and zips both
   as the test's ``coverage.dat``.
4. **Installs the final tool.** The consumer's ``score_coverage_reporter`` target
   wraps ``reporter.py`` with the scope, workspace root and LLVM tool labels.
   The reporter merges all per-test profiles and runs ``llvm-cov`` three times:
   ``show`` (HTML), ``export`` (LCOV), ``report`` (text).

**Scope.** Covmap instruments everything. Filtering happens at report time
through the allowlist written by ``score_coverage_scope``: an aspect walks the
dependency graph from the listed production targets and collects every
in-workspace source file they own. Everything else, test sources, googletest,
external dependencies, is excluded.

**Baseline.** A file that no test executes produces no profile data. The scope
aspect therefore also collects the compiled archives and executables, and the
reporter runs ``llvm-cov --empty-profile`` over them, so untested files show up
with exact 0 % entries whose denominators come from the compiler's coverage
map. Rust rlibs are expanded into their object members first because their
leading ``lib.rmeta`` member makes ``llvm-cov`` reject the archive.

Phase 2: report generation and gate
-----------------------------------

``generate_coverage_html.py`` unpacks the HTML from the zip and, when a
justification YAML is given, calls ``justify.py`` (YAML plus in-code markers to
a manifest of justified lines) and ``effective_coverage.py`` (recolours justified
lines, computes raw and effective figures, flags stale justifications, writes
``report.json`` and ``summary.txt``). The markdown summary is written next, then
the gate compares the unrounded gated percentage against ``COVERAGE_THRESHOLD``.
Optionally the HTML, LCOV, justification report and JUnit XMLs are assembled
into an artifacts tree.

Exit code 2 is reserved for runs without a verdict, so a broken report, a bad
threshold or a tool failure can never look like a pass.

Module and consumer split
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Lives in ``@score_coverage``
     - Role
   * - ``score_coverage/merger.py``
     - per-test profraw to profdata; C++ ``objects_list.txt`` and Rust ELF
       manifest discovery
   * - ``score_coverage/reporter.py``
     - final merge, llvm-cov show/export/report, allowlist filtering,
       ``--empty-profile`` baselines, rlib expansion, path normalisation
   * - ``score_coverage/coverage_scope.bzl``
     - the scope aspect and rule (CcInfo and CrateInfo)
   * - ``score_coverage/reporter_wrapper.bzl``, ``defs.bzl``
     - the consumer-facing ``score_coverage_scope`` / ``score_coverage_reporter``
       API
   * - ``score_coverage/justify.py``, ``effective_coverage.py``,
       ``coverage_summary.py``, ``generate_coverage_html.py``
     - justification, summary and gating layer
   * - ``//:enable_llvm_coverage_for_death_tests``
     - ``cc_feature`` for continuous-mode profiling

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Lives in the consumer repository
     - Why it cannot move
   * - ``score_coverage_scope(deps = [...])``
     - names the repository's production targets
   * - ``score_coverage_reporter(...)``
     - carries the repository's LLVM tool labels and workspace root
   * - ``coverage_justifications.yaml``
     - reviewed, repository-specific engineering arguments
   * - MODULE.bazel toolchain blocks
     - LLVM and Ferrocene pins are per-repository decisions
   * - the ``coverage:llvm_cov`` bazelrc block
     - bazelrc cannot be imported across modules

Two wiring details make the external hosting work: every path in the generated
reporter launcher uses rlocation form because it mixes files from the consumer
(``_main``), ``score_coverage`` and toolchain repositories, and the baseline
manifest is resolved against ``_main`` explicitly because its entries are
consumer files.

Design decisions
----------------

- **Report-time filtering, not instrumentation filtering.** Instrumenting
  everything and filtering by allowlist is what makes exact 0 % baselines
  possible; ``--instrumentation_filter`` would hide untested files.
- **Fail loud, never fail green.** Every input problem ends in exit 2. The gate
  compares unrounded values and floors displayed percentages.
- **Gate on the LCOV, not on llvm-cov's text summary.** The text summary omits
  baseline-only files; the LCOV includes them.
- **In-process tool calls.** ``generate_coverage_html`` imports the justification
  tools instead of nesting ``bazel run``; this keeps one process, one exit code
  and testable seams.
