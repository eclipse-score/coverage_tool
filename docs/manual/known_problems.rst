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

Known problems
==============

Known problems of the current release, with detection and workaround. Entries
are removed when a release fixes them; problems in the underlying LLVM tools
stay listed with their upstream references.

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Problem
     - Detection
     - Workaround / status
   * - **Per-instantiation counting in llvm-cov.** Template-heavy C++ files can
       show lower line coverage than under gcov; ``LF``/``LH`` totals may
       disagree with the file's own ``DA`` rows.
     - Compare the per-file summary with the ``DA`` rows of the LCOV.
     - Upstream behaviour (llvm-project #93843, #111743, #119299). The error is
       towards **under**-reporting; numbers are reported as llvm-cov produces
       them.
   * - **Rust branch coverage needs an unstable rustc flag.**
       ``-Zcoverage-options=branch`` works on rolling (nightly-based) Ferrocene
       builds only.
     - Rust rows show ``-`` in the branch columns.
     - On a stable-channel Ferrocene drop the flag; Rust branch coverage is then
       not available.
   * - **Clang warns where GCC does not.** Repositories with
       ``treat_warnings_as_errors`` fail to compile under the coverage config.
     - ``-Werror`` failures only under ``--config=llvm_cov``.
     - Add ``--features=-treat_warnings_as_errors`` and
       ``--host_features=-treat_warnings_as_errors`` to the coverage config.
   * - **Containerised tests produce no coverage.** Instrumented binaries inside
       stock containers lack runtime dependencies and profraw files never reach
       the host.
     - Exit 127 in the test log; no profraw.
     - Exclude containerised or system tests from the coverage run; they keep
       running in the regular test jobs.
   * - **QNX on-target coverage covers C++ only.** rustc emits no gcov
       counters, and the LLVM profile transport from the QEMU guest is not
       established yet (tooling issue #427, track 2).
     - Rust sources listed as ``not-instrumented`` in ``unmapped_files.txt``
       of a QNX report.
     - Measure Rust with the Linux (LLVM) run of the same tree.
   * - **gcov discards test measurements when the instrumentation filter is
       too narrow.** This affects source files and headers, including headers
       imported from another repository. Bazel's gcov collector keeps only
       measurements for files declared by targets included in
       ``--instrumentation_filter``. Adding files to the coverage scope alone
       is not enough. The tool's LLVM collector does not apply this additional
       file filter, but both backends need instrumentation enabled at compile
       time to produce measurements.
     - Tests execute code in a file, but the gcov report shows no test data
       for it, or only zero counts from the baseline.
     - Make sure ``--instrumentation_filter`` includes the package of the
       target declaring the affected files. For example, if
       ``//third_party:headers`` declares imported
       headers, a filter of ``^//score[/:]`` misses it. Use
       ``--instrumentation_filter=^//`` to include all workspace packages,
       or extend the narrower filter to include ``//third_party``.
   * - **gcov and LLVM count different lines.** gcov reports only lines the
       compiler emitted code for: unused inline functions and closing braces
       have no line, while LLVM's mapping keeps unused functions at 0 %.
     - Different totals for the same file on QNX and Linux.
     - Expected; compare the two reports per file, do not merge them.
   * - **An archive is rejected by llvm-cov** because one member has no
       coverage mapping: the ``lib.rmeta`` of a Rust rlib, or the object of an
       empty translation unit.
     - ``no coverage data found`` on an archive; untested files of that library
       missing from the report.
     - Handled since the pipeline passes only members with a mapping to
       llvm-cov; if seen, the installed version predates the fix.
   * - **A header compiled under two different paths is reported once.** When
       a translation unit includes a header through its ``_virtual_includes/``
       path and another through the declared path, the compiler produces two
       coverage entries for one file; the reporter keeps the declared-path
       variant and drops the other.
     - ``WARNING: <file> is compiled under several paths`` in the reporter log.
     - Expected; hits recorded only through the dropped variant are not
       counted. Include the header consistently.
   * - **An in-scope header is absent from the report.** A header no
       translation unit includes, or one that contains only templates that are
       never instantiated, produces no code and therefore no coverage mapping;
       ``llvm-cov`` cannot show it, not even at 0 %.
     - The file is named in the job summary under "In-scope files without
       coverage data", in ``unmapped_files.txt`` of the archive and in a
       reporter ``WARNING``. Headers whose same-named source file has data
       (declaration-only) and placeholder sources that were compiled but hold
       no code of their own are listed in the same file under their own
       category and are not findings.
     - Decide per file: write a test that instantiates it (it is shipped API),
       or remove it from the target's ``hdrs`` (it is not needed).
   * - **A header reached through several targets is compiled under several
       names.** Virtual-include trees of targets outside the scope are
       resolved to the declared header by their path tail; if two in-scope
       files share that tail the header stays unresolved.
     - ``WARNING: ... matches several in-scope files`` in the reporter log; the
       header appears as ``no-data``.
     - Rename one of the files, or declare the header only once.
   * - **A source could not be staged for llvm-cov.** The reporter reads the
       sources from the scope's exported files; a file that is neither there
       nor in the workspace directory gets no HTML page (its numbers stay in
       the index and the LCOV).
     - ``WARNING: N in-scope sources were not found`` in the reporter log, an
       index row without a link.
     - Report it; every declared source is expected to be exported.
   * - **Libraries tested from a** ``test`` **subpackage show 0 % or no-data.**
       Bazel guesses ``--instrumentation_filter`` from the packages of the
       test targets and strips only a trailing ``/tests``; ``score/os`` tested
       from ``score/os/test`` is outside the guess. On the gcov backend Bazel's
       collector then drops the library's counters; on both backends a library
       without an instrumented direct dep is compiled without counters.
     - Whole directories at 0 % on QNX that are covered on Linux;
       ``WARNING: N in-scope files have no test data although their directory
       is tested from a test/ or tests/ subdirectory`` in the reporter log;
       ``Using default value for --instrumentation_filter`` in the Bazel
       output.
     - Set ``--instrumentation_filter=^//<root>[/:]`` in every coverage
       config (user manual, step 4).
