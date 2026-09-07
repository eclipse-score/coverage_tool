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

Verification report
===================

.. document:: score_coverage verification report
   :id: doc__coverage_verification_report
   :version: 1
   :status: draft
   :safety: ASIL_B
   :security: NO
   :realizes: wp__verification_module_ver_report

This report is regenerated with every release. It doubles as the qualification
verification report of the tool: the Tool Verification Report in the S-CORE
platform documentation refers to it as the evidence of the validation.

Scope and environment
---------------------

Validated environment: Linux x86_64, Bazel 8.7.0, ``toolchains_llvm`` 1.8.0
with LLVM 22.1.7, ``score_toolchains_rust`` 0.10.0 (Ferrocene built by
``ferrocene_toolchain_builder`` 1.3.1), Python 3.11 and 3.12 (``rules_python``
1.8.5), ``rules_rust`` 0.68.2-score.

Test inventory
--------------

.. list-table::
   :header-rows: 1
   :widths: 45 15 40

   * - Test target
     - Cases
     - Verifies
   * - ``//score_coverage/tests:merger_test``
     - 20
     - merge_profraw, merge_no_data, merge_tool_error
   * - ``//score_coverage/tests:reporter_test``
     - 34
     - report_merged_profile, report_allowlist, report_rlib_expansion,
       report_missing_baseline, report_relative_paths, report_outputs
   * - ``//score_coverage/tests:justify_test``
     - 41
     - just_yaml, just_markers, just_unknown_id, just_platform,
       just_missing_file
   * - ``//score_coverage/tests:effective_coverage_test``
     - 52
     - eff_metric, eff_stale, eff_branch_only, eff_path_match, eff_html,
       eff_gcovr
   * - ``//score_coverage/tests:generate_coverage_html_test``
     - 43
     - gate_threshold, gate_metric, gate_unrounded, gate_exit_codes,
       gate_no_verdict, summary_first, artifacts
   * - ``//score_coverage/tests:coverage_summary_test``
     - 17
     - summary_first
   * - ``//score_coverage/tests/starlark:coverage_scope_tests`` (8 analysis tests)
     - 8
     - scope_transitive, scope_excludes, scope_baseline_objects
   * - ``integration_tests/run_integration_test.sh`` (15 end-to-end checks)
     - 15
     - validation_ground_truth, report_baseline_zero, gate_exit_codes,
       gate_no_verdict, just_unknown_id, artifacts, summary_first

Requirement coverage
--------------------

Every tool requirement is verified by at least one test listed above. The
machine-readable link from test case to requirement (``Verifies`` test
properties) is planned for the next iteration; until then the mapping above is
maintained by hand and reviewed with each change.

.. needtable:: Requirements and their verification state
   :types: tool_req
   :columns: id;title;implemented;testcovered
   :style: table

Structural coverage of the tool
-------------------------------

Measured with coverage.py through ``bazel coverage --combined_report=lcov`` and
gated in CI by ``//tools:self_coverage_gate`` (current ratchet 95 % lines,
87 % branches; target 100 % with documented deviations).

.. list-table::
   :header-rows: 1
   :widths: 40 30 30

   * - File
     - Lines (C0)
     - Branches (C1)
   * - ``score_coverage/coverage_summary.py``
     - 95.65 % (198/207)
     - 88.78 % (87/98)
   * - ``score_coverage/effective_coverage.py``
     - 95.09 % (523/550)
     - 81.16 % (224/276)
   * - ``score_coverage/generate_coverage_html.py``
     - 98.56 % (205/208)
     - 92.59 % (75/81)
   * - ``score_coverage/justify.py``
     - 98.35 % (238/242)
     - 94.56 % (139/147)
   * - ``score_coverage/merger.py``
     - 98.35 % (119/121)
     - 93.65 % (59/63)
   * - ``score_coverage/reporter.py``
     - 91.95 % (354/385)
     - 84.97 % (164/193)
   * - **Total**
     - **95.56 % (1637/1713)**
     - **87.18 % (748/858)**

Static analysis
---------------

ruff (rule set of the S-CORE Python guideline: E, W, F, I, B, C90, UP, SIM,
RET; McCabe ceiling 15), pylint and ty run as Bazel aspects with findings
failing the build. Current state: zero findings. buildifier checks the Starlark,
yamlfmt the workflows; copyright headers are checked on every file.

End-to-end validation
---------------------

``integration_tests/run_integration_test.sh`` builds a consumer workspace with a
tested and an untested C++ library, a tested Rust library and an untested Rust
binary, one justified line, and asserts:

1. the gate fails at 100 % and passes at 10 % (effective and raw mode);
2. the HTML, the summary and the archive tree are produced, the summary also
   when the gate fails;
3. the untested C++ file and the untested Rust binary appear with ``LH:0``;
4. the LCOV matches ``expected_lcov.dat``, a hand-derived ground truth, record
   by record;
5. the justified line raises effective above raw coverage;
6. fault injection: a corrupt report and a non-numeric threshold exit 2, and a
   misspelt justification id is reported and does not raise the effective
   coverage.

Deviations
----------

- Structural coverage of the Python is below 100 %. The remaining lines are
  error-handling and llvm-cov fallback paths in ``reporter.py`` and
  ``effective_coverage.py``; they are covered by the fault-injection checks of
  the integration test where they are reachable and will be closed or justified
  before the first qualified release.
- Starlark (``coverage_scope.bzl``, ``reporter_wrapper.bzl``) has no structural
  coverage tooling. The rule and aspect are verified by eight analysis tests
  and by the end-to-end run.
- The gcovr backend of ``effective_coverage.py`` is unit-tested against real
  gcovr 8.6 markup but is not reachable through ``generate_coverage_html`` in
  this release (QNX flow, tooling issue #427).
