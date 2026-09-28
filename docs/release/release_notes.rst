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

Release notes
=============

.. document:: score_coverage release notes
   :id: doc__coverage_release_notes
   :version: 1
   :status: draft
   :safety: ASIL_B
   :security: NO
   :realizes: wp__module_sw_release_note

0.3.0 (unreleased)
------------------

In plain words
~~~~~~~~~~~~~~

**Coverage of tests that run on QNX.** Until now the tool measured only what
runs on the Linux host. QNX's compiler (QCC) is GCC-based and produces gcov
counters instead of LLVM's coverage mapping, and the tests run inside a QEMU
virtual machine. This release adds a second *backend*: the QNX runner of
``score_qnx_unit_tests`` brings the counters back, Bazel's own collector turns
them into per-test data, and score_coverage's new gcov reporter produces the
same report as on Linux: the same HTML archive, the same LCOV file, the same
job summary, the same justifications and gate. A module declares one more
reporter target (``backend = "gcov"``) and one bazelrc block; see the user
manual, step 4b.

What the QNX report does not contain: Rust sources (rustc cannot produce gcov
counters; they are listed as *not instrumentable* and measured by the Linux
run) and headers a module vendors from an external repository (Bazel's
collector drops them; also measured by the Linux run). gcov counts lines
differently from LLVM (no unused inline functions, no closing braces), so the
two reports are compared per file, not merged.

Validated with the S-CORE GCC toolchain on Linux, which takes exactly the same
collection path as QCC on QNX, against a hand-derived ground truth; the QNX
transport itself is the one ``communication`` has used since 2026.

Details for integrators
~~~~~~~~~~~~~~~~~~~~~~~

- New ``score_coverage/gcov_reporter.py`` (``//:gcov_reporter``): sums per-test
  LCOV records, applies the scope, adds a zero-coverage baseline from the
  ``.gcno`` notes of in-scope translation units, renders HTML and summary with
  gcovr 8.6 (new pip dependency), writes ``unmapped_files.txt`` with the new
  ``not-instrumented`` category.
- ``score_coverage_reporter`` gained ``backend`` and ``gcov``; ``llvm_cov`` /
  ``llvm_profdata`` are required only for the LLVM backend. Existing consumer
  BUILD files need no change.
- ``score_coverage_scope`` writes ``<name>_gcno.txt`` and exports the ``gcno`` /
  ``gcno_files`` output groups.
- Integration workspace: ``coverage:gcov`` config with the S-CORE GCC
  toolchain, ``expected_lcov_gcov.dat`` ground truth, gcov checks in the
  end-to-end script.
- New requirements ``tool_req__coverage_scope_gcno``,
  ``tool_req__coverage_backend_select``, ``tool_req__coverage_gcov_merge``,
  ``tool_req__coverage_gcov_baseline``, ``tool_req__coverage_gcov_html``;
  potential errors ERR-11 and ERR-12; constraint CSTR-11.

0.2.0 (2026-09-16)
------------------

In plain words
~~~~~~~~~~~~~~

This release fixes what the first baselibs reports showed, and adds one new
piece of information to every report.

**Third-party code no longer leaks into a module's report.** A module that
wraps a third-party library (baselibs wraps OpenSSL this way) got that
library's 72 header files counted as its own code, at 0 %. They are gone.
Only files a module lists itself in its build targets are part of its
report.

**Every link in the HTML report opens.** Some rows of the report pointed at
pages that had never been generated: files that Bazel generates during the
build and files from other repositories were not readable at the moment the
report was produced. The report now brings every source file along, so every
row opens. File names in the report are the paths of the source files, no
longer build-internal paths such as ``bazel-out/.../_virtual_includes/...``.
If a justification was written against such a build-internal path, it needs
the source path now.

**Untested files that the old report could not show are listed.** This is
the new piece. A coverage tool can only measure files that were compiled into
a test or a library. A file that nothing compiles has no lines to count, and
llvm-cov cannot show it, not even at 0 %. Until now such files were simply
absent from the report and nobody noticed. The report now lists them,
see :ref:`unmapped_files` below.

**Headers tested through a test-only twin target are measured.** A common
pattern declares a library's headers a second time in a test-only target with
test flags (baselibs' ``futurecpp_internal``). Tests then compile the headers
through that second target, and the report did not recognise the result as
belonging to the library: 172 futurecpp headers appeared untested. They are
now attributed to the library's declared header files.

**More untested files show their 0 %.** A library archive with one object that
contains no code (typical for header-only libraries, see below) was rejected
by llvm-cov as a whole, so the other files of that library lost their 0 %
entries. This is fixed; in baselibs 15 files reappeared.

.. _unmapped_files:

The file ``unmapped_files.txt``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The archive of every coverage run now contains ``unmapped_files.txt``, and the
job summary shows the same information as a table row and three collapsible
sections. It lists every file that belongs to the module's coverage scope but
for which no coverage data exists anywhere: no test and no library contains
compiled code from it. Such a file counts in no percentage. Each line reads
``<category>`` TAB ``<file>``; there are three categories.

.. list-table::
   :header-rows: 1
   :widths: 22 48 30

   * - Category
     - What it means
     - What to do
   * - ``no-data``
     - **The findings.** Nothing in the module compiles this file: no source
       includes the header, or it holds only templates that no test ever
       uses with a concrete type. For a public API this means no test
       exercises it. It also catches headers that contain nothing executable
       (forward declarations, type traits, test mocks); the tool cannot tell
       those apart from unused API.
     - Look at each file: write a test that uses it, remove it if nobody
       needs it, or note that it holds nothing testable.
   * - ``declaration-only``
     - A header that only announces functions. The code behind it lives in a
       source file with the same name (``timerfd.h`` next to ``timerfd.cpp``),
       and that source file is measured.
     - Nothing. Listed for completeness.
   * - ``compiled-without-code``
     - A source file that Bazel compiled but that contains no code of its
       own, only ``#include`` lines. Header-only libraries carry such a
       placeholder file so that Bazel produces a library archive.
     - Nothing. Listed for completeness.

Two things this list is not: it is not part of the coverage percentage, and
it does not say *why* a ``no-data`` file was never compiled. That needs a
look at the file.

Details for integrators
~~~~~~~~~~~~~~~~~~~~~~~

- Fixed (eclipse-score/coverage_tool#5): a workspace rule that forwards the
  ``CcInfo`` of a third-party library (e.g. a transition wrapper around
  OpenSSL) no longer puts that library's headers into the scope; only headers
  a workspace target declares itself count.
- Fixed (eclipse-score/coverage_tool#5): every index link of the HTML report
  points at a generated page. The reporter stages the in-scope sources from
  the scope's exported files instead of reading them through the workspace
  directory, where generated headers and external repositories are not
  present at report time.
- Changed: headers compiled through ``strip_include_prefix`` /
  ``include_prefix`` are reported under their declared path (e.g.
  ``score/flatbuffers/include/flatbuffers/base.h`` or
  ``external/flatbuffers+/include/flatbuffers/base.h``), no longer under the
  generated ``_virtual_includes/`` path. Justifications written against a
  ``_virtual_includes/`` path must be updated.
- Changed: HTML pages live at ``coverage/<canonical path>.html``; the archive
  contains no directory of the producing machine any more.
- New: in-scope files that carry no coverage data at all (a header nothing
  includes, template-only code that is never instantiated) are no longer
  silently absent. The reporter writes ``text_report/unmapped_files.txt`` and
  warns; ``generate_coverage_html`` prints them, archives the list as
  ``unmapped_files.txt`` and adds a row and a section to the job summary
  (``tool_req__coverage_report_unmapped``). Declaration-only headers and
  placeholder sources compiled without code are categorised separately and
  are not findings.
- Fixed: a library archive with one member lacking a coverage mapping (the
  placeholder ``.cpp`` of a header-only library) was rejected by ``llvm-cov``
  as a whole, so the library's other untested files silently lost their 0 %
  baseline. Archive members are now inspected and only those with a mapping
  are passed on, the way Rust rlibs were already handled
  (``tool_req__coverage_report_rlib_expansion`` v2).
- Fixed: a ``_virtual_includes/`` path of a target outside the scope (test-only
  twin of an in-scope library) is resolved to the allowlisted header with the
  same path tail instead of being excluded; ambiguous tails are warned about.
- Fixed: the exclusion filter matches each out-of-scope compiled file exactly;
  an excluded ``foo/bar.h`` no longer suppresses an in-scope ``src/foo/bar.h``.
- ``score_coverage_scope`` gained the ``path_map`` and ``source_files`` output
  groups; ``score_coverage_reporter`` passes them to the reporter
  (``--path_map``). Consumers only instantiate the macros; no change needed.

0.1.0 (2026-09-11)
------------------

First release as a standalone module, extracted from ``@score_tooling//coverage``
(tooling commit ``9a61f42``).

Changes relative to the pipeline in score_tooling 2.2.x:

- Consumer labels move to the module root: ``@score_coverage//:defs.bzl``,
  ``//:merger``, ``//:generate_coverage_html``,
  ``//:enable_llvm_coverage_for_death_tests``.
- ``generate_coverage_html`` is Python and returns exit code 2 for runs without
  a verdict; the gate compares unrounded percentages; malformed thresholds and
  corrupt LCOV data are rejected.
- Justifications match files at path-component boundaries (a justification for
  ``bar.cpp`` no longer applies to ``foobar.cpp``).
- gcovr reports: the index totals of gcovr 8.x are read correctly without
  ``--lcov``; ``summary.txt`` is written for gcovr reports too.
- The repository-bound ``combined_report`` and ``llvm_profile_wrapper`` helpers
  are not part of the module.
- Headers reached through ``strip_include_prefix`` / ``include_prefix`` (Bazel's
  ``_virtual_includes/`` tree) and headers a workspace target vendors from an
  external repository are now part of the coverage scope; the reporter
  normalises the configuration-specific ``bazel-out/<config>/bin/`` prefix and
  suppresses the duplicate baseline entry of such headers
  (eclipse-score/baselibs#558).

Known problems: see :doc:`../manual/known_problems`.
