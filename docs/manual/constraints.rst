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

.. _coverage_constraints:

Constraints of use
==================

The correctness of the coverage figures depends on the environment and on how
the tool is invoked. Each constraint below mitigates one of the potential errors
in :doc:`../requirements/potential_errors`; the Tool Verification Report refers
to them by their anchors.

.. _cstr_coverage_environment:

CSTR-01 Qualified environment
-----------------------------

Use the tool only in the environment it was validated in: Linux x86_64 host,
Bazel 8.6, ``toolchains_llvm`` 1.8.0 with LLVM 22.1.7 for C++, the standard
Ferrocene toolchain of ``score_toolchains_rust`` 0.10.0 or newer (built by
``ferrocene_toolchain_builder`` 1.3.1 or newer) for Rust. QNX on-target coverage
is outside this environment. Mitigates ERR-08.

.. _cstr_coverage_scope_list:

CSTR-02 Maintain the scope list
-------------------------------

List every shipped production library or binary in ``score_coverage_scope``.
A target missing from the list is not reported at all, not even at 0 %. Add
new libraries when they are created; document exclusions in writing next to the
target. For large repositories, run a completeness check comparing the
reachable universe against the scope. Mitigates ERR-01.

.. _cstr_coverage_build_tests_only:

CSTR-03 Run coverage with ``--build_tests_only``
------------------------------------------------

Always invoke ``bazel coverage --config=llvm_cov <targets> --build_tests_only``.
Without the flag Bazel builds manual-tagged or incompatible test binaries, which
fails or pollutes the run. Mitigates ERR-08.

.. _cstr_coverage_toolchain_config:

CSTR-04 Do not combine with other toolchain configs
---------------------------------------------------

Never combine ``--config=llvm_cov`` with a config that registers another C++
toolchain (for example a GCC host config). The last ``--extra_toolchains`` wins
resolution; a GCC toolchain produces no covmap data and the run is rejected
with exit 2. Mitigates ERR-08.

.. _cstr_coverage_dynamic_mode:

CSTR-05 Keep ``--dynamic_mode=off``
-----------------------------------

The canonical ``llvm_cov`` config disables dynamic linking. Per-test shared
objects can carry clashing instrumentation between production and test code,
and the first object loaded wins, causing flaky coverage gaps. Mitigates ERR-02.

.. _cstr_coverage_lockfile:

CSTR-06 Pin dependencies
------------------------

Run CI with ``--lockfile_mode=error`` so the LLVM and Ferrocene versions that
produced the evidence cannot drift silently. Mitigates ERR-08 and ERR-09.

.. _cstr_coverage_review_justifications:

CSTR-07 Review justifications
-----------------------------

A justification is a reviewed engineering argument. Every entry in the YAML
needs an id, a category, the platforms it applies to and a written reason, and
every change to the YAML or to ``COV_JUSTIFIED`` markers is reviewed like code.
Remove justifications the report flags as stale. Mitigates ERR-04 and ERR-05.

.. _cstr_coverage_check_baselines:

CSTR-08 Check the baseline entries
----------------------------------

When a file is known to be untested, confirm it appears in the LCOV
(``coverage_report.dat``) with an ``SF:`` record and ``LH:0``. If an expected
file is missing entirely, the baseline mechanism is broken; stop and diagnose
instead of accepting the percentage. Mitigates ERR-01 and ERR-07.

.. _cstr_coverage_archive:

CSTR-09 Archive the report with the verification report
-------------------------------------------------------

Use ``--archive-dir`` and upload the directory as the CI artifact. The archived
``coverage_report.dat`` and ``justification_report/`` are the evidence a module
verification report cites; the HTML alone is not sufficient. Mitigates ERR-09.

.. _cstr_coverage_exit_codes:

CSTR-10 Treat exit code 2 as a failed run
-----------------------------------------

Exit code 2 means the tool could not produce a verdict. CI must fail on it
exactly like on exit code 1. Never map it to a pass. Mitigates ERR-03.
