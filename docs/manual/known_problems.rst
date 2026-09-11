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
   * - **QNX on-target coverage is not supported by this tool.** The
       orchestrator accepts only the LLVM zip report. The gcovr-based HTML
       post-processing exists but is reachable only through the consumer-side
       flow of the ``communication`` repository (tooling issue #427).
     - Exit 2 with ``is not the LLVM pipeline zip report`` on a gcov run.
     - Use the Linux host pipeline; QNX centralisation is tracked in tooling
       issue #427.
   * - **Rust rlib archives are rejected by llvm-cov** because of the leading
       ``lib.rmeta`` member.
     - ``no coverage data found`` on a Rust archive.
     - Handled since the pipeline expands rlibs into their object members; if
       seen, the installed version predates the fix.
   * - **Vendored headers appear under their virtual-includes path.** A header
       compiled through ``strip_include_prefix`` is reported as
       ``<pkg>/_virtual_includes/<target>/<path>``, not under the label it was
       declared with, because that is the identity the compiler records.
     - Report rows named ``_virtual_includes``.
     - Expected; justifications for such lines must use the reported path.
   * - **Instrumentation filter appears ignored.**
     - ``--instrumentation_filter`` has no visible effect.
     - Expected: ``--experimental_use_llvm_covmap`` instruments everything;
       filtering happens at report time through the scope allowlist.
