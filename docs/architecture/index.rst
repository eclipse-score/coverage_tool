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

The coverage tool shows which production code was exercised by tests and
checks whether line coverage meets a configured minimum. The repository using
the tool selects the production code to assess and may provide reviewed
explanations for code that is not exercised.

**Line coverage** is the share of measurable source lines that executed during
these tests. Measurable lines are those for which the compiler provides
coverage information; they are not simply all lines in a source file. Comments
and blank lines, for example, do not count as executable code.

The pipeline has two phases:

1. **Collect coverage.** Build code with execution counters, run the selected
   tests, and combine their measurements into a report. Either the LLVM or
   gcov backend performs this phase, depending on the compiler and platform.
2. **Evaluate coverage.** Prepare the HTML report, optionally apply the reviewed
   explanations, and compare line coverage with the required minimum. This
   comparison is the **coverage gate**. It decides whether coverage is high
   enough for the build or CI job to proceed.

The first diagram shows the inputs and results of these phases. The next two
expand collection and evaluation respectively. In the data-flow diagrams,
blue boxes are inputs or outputs, yellow boxes are processing steps, and
arrows show what each step receives or produces.

.. uml::

   @startuml
   top to bottom direction
   skinparam componentStyle rectangle
   skinparam artifactBackgroundColor #EAF2F8
   skinparam artifactBorderColor #4E79A7
   skinparam componentBackgroundColor #FFF2CC
   skinparam componentBorderColor #B58B00

   artifact "Code whose coverage we assess\n(coverage scope)" as scope
   artifact "Tests to run" as tests
   component "1. Collect coverage" as collect
   artifact "Coverage report zip\nmeasurements + HTML pages" as report
   artifact "Optional explanations\nfor unexecuted code" as justifications
   artifact "Required minimum\nline coverage" as threshold
   component "2. Evaluate coverage" as evaluate
   artifact "HTML report" as html
   artifact "Gate result" as verdict

   scope --> collect
   tests --> collect
   collect --> report
   report --> evaluate
   justifications --> evaluate
   threshold --> evaluate
   evaluate --> html
   evaluate --> verdict
   @enduml

Collection produces the measurements; evaluation applies the coverage policy.
Both backends use the same evaluation phase.

Code whose coverage we assess
-----------------------------

The **coverage scope** is the set of production source files whose coverage we
assess, including code that no selected test exercises. It can span several
units under test and their dependencies. The repository defines this set with
``score_coverage_scope(deps = [...])``.
The listed Bazel targets are build units such as libraries or binaries. The
scope follows their dependencies and collects declared source files from
supported targets in the repository. The repository must select production
targets and keep test code out of this scope: the tool follows declarations,
rather than deciding whether a file is production or test code.

The scope and the selected tests answer different questions:

- **Scope:** which production code should be assessed?
- **Tests:** which executions provide measurements for that code?

**Instrumentation** means adding counters to record execution. The supplied
coverage configurations instrument tests as well as production code. This
also captures production code from headers compiled into a test binary.
The report includes only files in the configured scope, so test sources stay
out of the result when the scope contains only production code.

Why untested code needs a baseline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A production library can be in scope even if no selected test depends on it.
Using only the test results would omit that library and could make coverage
look better than it is. The tool therefore also builds scoped production code
and reads the compiler's coverage information for it. This **baseline** supplies
zero counts for measurable files missing from the test results.

For example, if tests cover all 80 measurable lines in library A and never use
library B with 20 measurable lines, the combined report must show 80 %, with
B at 0 %.

A baseline requires compiler coverage information. A header that is never
included, or template code that is never instantiated, may have none. A file
with no such information cannot be assigned a measured 0 % and is listed
separately in ``unmapped_files.txt``. Files without coverage data do not contribute measurable
lines to the percentage. The report distinguishes unexplained missing data
from cases such as declaration-only headers and Rust code unsupported by the
gcov backend.

**A passing gate does not establish that every scoped file was measured.**
Missing-data warnings and the scope itself must also be reviewed. Files outside
the scope are excluded entirely. See :doc:`../manual/constraints` and
:doc:`../manual/known_problems` for the required checks and known limitations.

Phase 1: collect coverage
-------------------------

``bazel coverage`` builds and runs the selected tests. Each test produces its
own measurements. A **reporter** combines them into a report, applies the
scope, and adds baseline entries where available. The baseline supplies zero counts only for
files missing from the test data, so it does not overwrite measured hits.

.. uml::

   @startuml
   top to bottom direction
   skinparam componentStyle rectangle
   skinparam artifactBackgroundColor #EAF2F8
   skinparam artifactBorderColor #4E79A7
   skinparam componentBackgroundColor #FFF2CC
   skinparam componentBorderColor #B58B00

   together {
     artifact "Selected tests" as tests
     artifact "Code whose coverage we assess\n(production targets)" as scope
   }
   tests -[hidden]right-> scope

   component "Build with execution counters\nand run tests" as run_tests
   artifact "Execution counters\nfrom each test" as counters
   component "Collect per-test measurements" as collect
   artifact "Per-test measurements" as measurements

   component "Build scoped code and\ncollect its source files" as prepare
   artifact "Source files + file selection\nCompiler information for\nuntested code" as baseline

   component "Combine measurements\nKeep scoped files\nAdd baseline where data is missing" as merge
   artifact "Coverage report zip\nmeasurements + HTML pages" as report

   tests --> run_tests
   run_tests --> counters
   counters --> collect
   collect --> measurements
   scope --> prepare
   prepare --> baseline
   measurements --> merge
   baseline --> merge
   merge --> report
   @enduml

The two inputs meet at the reporter: test measurements show what executed;
compiler information lets it also report untested files with zero counts.
This is why selecting tests alone is not enough to define the report.

Two backends, one report interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A **backend** is the compiler-specific implementation of collection. Both
backends follow the diagram above and produce the same archive structure.

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Choice
     - LLVM backend
     - gcov backend
   * - Supported code and execution
     - C++ and Rust; tests run on Linux
     - C++; tests run on Linux or in QEMU for QNX
   * - Compiler
     - Clang for C++, Ferrocene/rustc for Rust
     - GCC on Linux, QCC on QNX

The archive contains HTML pages for readers, measurements in **LCOV** (a text format for file names, line and branch
counts), a text summary and a list of files without data.
On QNX, the test runner brings execution counters back from the QEMU virtual
machine to the host. Report generation and evaluation then run on the host.

The common interface does **not** mean identical percentages. LLVM and gcov
can count different sets of lines, for example for unused inline functions.
Compare reports with that difference in mind; do not merge LLVM and gcov
results into one percentage. Rust is not measured by this gcov backend, and
Bazel's gcov collector can discard measurements for headers from external
repositories even when those headers are explicitly in scope. These cases
are described in :doc:`../manual/known_problems`.

Phase 2: evaluate coverage
--------------------------

The ``generate_coverage_html`` command unpacks the report zip and prepares the
HTML output. It can also apply **justifications**: reviewed engineering explanations for
specific code that was not exercised. These are defined in a YAML file and
associated with source locations, including through in-code markers. The
repository's reviewers assess the engineering argument. The tool checks the
input structure and applies the entries to matching code locations; it does
not decide whether the argument is sound.

- **Raw line coverage** is the proportion of measured lines that executed.
- **Effective line coverage** also credits validly justified, unexecuted lines.
  Those lines remain unexecuted; the report marks them separately.

For libraries A and B combined, the report contains 100 measurable lines:
all 80 lines in A executed, while none of the 20 lines in B executed.
Suppose 5 of B's unexecuted lines have applicable justifications:

- **Combined raw coverage:** 80 executed lines / 100 total lines = **80 %**.
- **Combined effective coverage:** (80 executed + 5 justified) / 100 total
  lines = **85 %**.

Library A remains at 100 % coverage. The increase from 80 % to 85 % applies to
the combined effective result. Justifications give credit for 5 lines in B;
they do not change execution counts or remove lines from the total.

The gate checks effective line coverage when a justification YAML is supplied
and raw line coverage otherwise. Branch coverage is reported where available,
but this gate checks lines. The diagram shows the decision for a usable report;
error handling and current limitations are described below.

.. uml::

   @startuml
   skinparam activityBackgroundColor #FFF2CC
   skinparam activityBorderColor #B58B00
   skinparam activityDiamondBackgroundColor #E2F0D9
   skinparam activityDiamondBorderColor #548235

   start
   :Read coverage report zip;
   if (Justification YAML supplied?) then (yes)
     :Apply justifications and mark them in HTML;
     :Use effective line coverage\n(executed + justified lines);
   else (no)
     :Use raw line coverage\n(executed lines);
   endif
   if (Coverage meets required minimum?) then (yes)
     :Pass;
   else (no)
     :Fail;
   endif
   stop
   @enduml

The YAML selects which metric the gate checks; the configured minimum decides
whether that metric passes. The minimum is ``COVERAGE_THRESHOLD`` (100 % by
default). A justification credits a line without making it an executed line.

The command defines the following exit-code contract. Current deviations are
listed under :ref:`architecture_evaluation_limits`.

.. list-table::
   :header-rows: 1
   :widths: 12 18 70

   * - Code
     - Meaning
     - Example
   * - 0
     - Pass
     - The selected coverage meets the minimum.
   * - 1
     - Fail
     - Coverage was evaluated and is below the minimum.
   * - 2
     - Error
     - A missing report, invalid threshold or justification-processing failure
       prevents the run from completing successfully.

The command can also write a Markdown summary and assemble an archive for
both passing and failing coverage results. The archive can contain HTML, LCOV, the missing-data list, justification details and JUnit test
results. An error can interrupt this process, so a complete archive is not
guaranteed. Missing data for individual source files can be
reported as warnings without causing exit code 2.

.. important::

   The effective-coverage path has known defects affecting missing data and
   gate decisions, including a possible pass when untested files are absent
   from the HTML. See :ref:`architecture_evaluation_limits` for the precise
   conditions and tracked fixes.

Responsibilities of the tool and its consumer
---------------------------------------------

The **consumer** is the repository using ``@score_coverage``. The tool supplies
the collection and evaluation logic; the consumer decides what code to assess,
which tests to run, and what coverage is acceptable.

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Concern
     - Provided by the tool
     - Defined by the consumer
   * - Scope
     - Dependency traversal and file selection
     - Production targets in ``score_coverage_scope``
   * - Collection
     - Per-test LLVM collector and final reporters for both backends
     - Test selection, compiler/tool versions and coverage configuration
   * - Evaluation
     - Justification processing, HTML annotation and coverage gate
     - Reviewed justification YAML and ``COVERAGE_THRESHOLD``
   * - Publication
     - Summary and archive generation
     - Output locations and CI artifact upload

Configuration examples and commands belong to the
:doc:`../manual/user_manual`. The following details are intended for readers
maintaining or extending the integration.

Implementation details and design decisions
-------------------------------------------

Scope traversal and source paths
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``coverage_scope.bzl`` implements a Bazel **aspect**, which visits supported
build targets along their dependencies. It collects checked-in files declared
in C++ ``srcs`` / ``hdrs`` and supported Rust source declarations. Generated
source files are not collected by this traversal. Files belonging to external
targets are excluded, but a workspace target can explicitly declare a header
from an external repository and thereby include it in scope. Merely forwarding
an external library's headers does not include them.

The scope exports a file allowlist, the source files, a header path map and
backend-specific baseline manifests. The path map translates Bazel-generated
``_virtual_includes/`` names back to declared header paths. This lets a header
appear under its source name even when include-prefix settings change the
path seen by the compiler.

Reporters stage sources using Bazel **runfiles**, the files made available to a
tool when it runs. Source lookup prefers runfiles and falls back to the
consumer workspace for local files. HTML pages are placed under canonical
source paths so report links do not depend on the original build directory.
Missing sources are warned about rather than guaranteed to produce a page.

Instrumentation and baseline collection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The consumer's coverage configuration must instrument the production packages
as well as the tests. In the integration workspace,
``--instrumentation_filter=^//`` covers workspace packages; a consumer with
production code under ``//score`` can use ``^//score[/:]``. Relying on Bazel's
guessed filter can omit libraries tested from a separate ``test/`` package.
Report-time scope filtering then selects which instrumented files count.
The reporters warn about suspected omissions of this kind (ERR-13).

For LLVM, ``--experimental_use_llvm_covmap`` and the C++ ``coverage`` feature
enable coverage maps; ``rules_rust`` enables Rust coverage instrumentation when
the toolchain provides coverage tools. Continuous profiling and runtime counter
relocation preserve counters through abnormal termination, such as death
tests. Rust branch coverage additionally needs the unstable
``-Zcoverage-options=branch`` option supported by the configured rolling
Ferrocene toolchain.

For each test, ``merger.py`` merges raw LLVM profiles (``.profraw``) with
``llvm-profdata`` and records the instrumented objects in a zip. The final
``reporter.py`` merges the profiles from all tests and invokes ``llvm-cov``
for HTML, LCOV and text output.

The LLVM baseline uses ``llvm-cov --empty-profile`` on compiled scope objects.
Archives with members lacking coverage maps are expanded, and only members
with maps are passed on. This handles Rust's ``lib.rmeta`` member as well as
empty C++ translation units. Files found only in the baseline are added to the
LCOV output with zero counts.

For gcov, the compiler emits ``.gcno`` notes and the running binary writes
``.gcda`` counters. The scope obtains notes through Bazel's
``InstrumentedFilesInfo``. Running ``gcov --json-format`` on notes without the
runtime counters supplies the baseline. On QNX, the runner sets
``GCOV_PREFIX`` in the guest and transports the counter archive back into the
host's ``COVERAGE_DIR``. Bazel's existing collector then handles the per-test
conversion to LCOV. ``gcov_reporter.py`` merges these per-test LCOV records,
adds baseline-only files and uses gcovr to render HTML and the text summary.
The QNX transport is provided by ``score_qnx_unit_tests``.

Bazel integration and the report interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bazel exposes two extension points: ``--coverage_output_generator`` for
per-test output and ``--coverage_report_generator`` for the combined report.
LLVM uses ``merger.py`` for the former; gcov keeps Bazel's ``lcov_merger``.
The consumer defines a ``score_coverage_reporter`` target for each backend in
use and connects it to the scope and tool labels. The final-report extension
point selects that target, which
launches ``reporter.py`` or ``gcov_reporter.py`` with the scope and tool paths.

The launcher resolves files from the consumer, the coverage module and the
toolchain repositories using Bazel runfile names. Baseline manifest entries
are resolved against the consumer repository (``_main``). The consumer keeps
its toolchain pins in ``MODULE.bazel`` and its coverage flags in its own
bazelrc; the integration workspace provides configuration examples.

Both reporters write a zip at ``bazel-out/_coverage/_coverage_report.dat``.
Despite the ``.dat`` extension, this is an archive containing ``html_report/``,
``lcov_report/lcov.dat`` and ``text_report/``. The latter includes the text
summary and ``unmapped_files.txt``. This shared interface allows both backends
to use the same evaluation and archive code.

Evaluation modules
~~~~~~~~~~~~~~~~~~

``generate_coverage_html.py`` calls the evaluation modules in the same Python
process, avoiding nested ``bazel run`` invocations:

- ``justify.py`` resolves YAML entries and code markers into ``manifest.json``.
- ``effective_coverage.py`` reads the HTML, annotates justified lines, flags
  stale justifications and writes ``report.json`` and ``summary.txt``.
- ``coverage_summary.py`` reads LCOV, the optional justification report and
  the missing-data list to produce the requested Markdown summary.

Without YAML, the gate calculates raw line coverage from LCOV, which includes
baseline-only files. LLVM's text summary omits those files and is therefore
unsuitable for this decision. With YAML, the gate reads effective coverage
from ``report.json``, computed from the HTML report and applied justifications.
Thus the two paths use different report representations.

The optional Markdown summary is written before the gate decision. The archive
is assembled afterwards for either verdict, so a coverage failure still leaves
reviewable results unless a separate processing error interrupts the run.

.. _architecture_evaluation_limits:

Current evaluation limitations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These implementation defects affect the evaluation described above:

- **HTML can omit untested files that are present in LCOV.** If LLVM cannot
  render HTML with the baseline archives, the reporter retries using only
  test binaries. LCOV still includes baseline-only files, but effective
  coverage reads the reduced HTML totals. Even an empty justification YAML
  can then change a failing raw result into a passing effective result.
  Tracked in `issue #14 <https://github.com/eclipse-score/coverage_tool/issues/14>`_.
- **Missing effective-coverage totals can be treated as 0 %.** Missing or
  unparseable HTML totals can produce exit 1 instead of exit 2, or even exit 0
  when the threshold is 0. The raw LCOV path rejects zero measurable lines.
  Tracked in `issue #15 <https://github.com/eclipse-score/coverage_tool/issues/15>`_.
- **Malformed YAML can bypass the error-code handling.** A YAML syntax error
  can terminate the command with a traceback and exit 1 instead of exit 2.
  Tracked in `issue #16 <https://github.com/eclipse-score/coverage_tool/issues/16>`_.
- **The effective gate uses a floored percentage.** The raw gate compares
  without display rounding, but the effective gate reads the percentage from
  ``report.json``, already floored to two decimal places. For example,
  99.999 % becomes 99.99 % and fails a threshold of 99.995 %. The intended
  gate comparison uses the unrounded value for both paths.
  Tracked in `issue #17 <https://github.com/eclipse-score/coverage_tool/issues/17>`_.
