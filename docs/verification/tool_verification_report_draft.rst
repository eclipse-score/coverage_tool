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

New Tool Verification Report (Draft)
====================================

This draft is being developed alongside the :doc:`existing verification report
<verification_report>`, which records the validation environment and test
evidence.

.. doc_tool:: score_coverage (new draft)
   :id: doc_tool__score_coverage
   :version: 1
   :status: draft
   :security_affected: NO
   :realizes: wp__tool_verification_report[version==1]
   :tool_version: check bazel dependency graph for currently used tool version

   S-CORE modules use ``score_coverage`` to produce line and branch coverage
   evidence for module verification reports and to enforce coverage thresholds.
   The scope covers the LLVM backend for C++ and Rust and the gcov backend for C++.

   The tool consumes the declared Bazel coverage scope, coverage data collected
   by Bazel, and optional coverage justifications and a gate threshold. It
   produces LCOV and HTML reports, raw and effective coverage summaries,
   archivable evidence, and a gate exit code.

The :doc:`user manual <../manual/user_manual>` describes backend configuration
and invocation. The :ref:`constraints of use <coverage_constraints>` describe
the supported environment and usage conditions. The analysis of
:doc:`potential errors <../requirements/potential_errors>` provides the starting
point for the evaluation.

The draft uses the existing security classification provisionally. The
evaluation will confirm security relevance and record the exact tool release
or source revision.

Intended use
------------

.. tool_usecase:: Check coverage before submitting a change
   :id: tool_usecase__score_coverage__author_review
   :version: 1
   :belongs_to: doc_tool__score_coverage

   Before submitting a change, the author checks that the files they expect
   to measure appear in the coverage report. They use the report to find
   lines and branches that still need a test or a justification. If a file
   is missing or a branch is wrongly shown as covered, the author can
   submit the change without addressing that test gap.

   .. potential_tool_malfunction:: An in-scope dependency is missing from the author's report
      :id: potential_tool_malfunction__coverage__scope
      :version: 1
      :violates: tool_req__coverage_scope_transitive
      :safety_affected: YES
      :detection_sufficient: NO

      The scope aspect omits a source file from a dependency of a listed
      target. The author can miss a test gap in safety-related code when the
      file is outside the set they expect to find. Maintaining the target list
      as required by :ref:`CSTR-02 <cstr_coverage_scope_list>` does not confirm
      that the report includes every source file from those targets.

   .. potential_tool_malfunction:: LCOV omits a known untested file
      :id: potential_tool_malfunction__coverage__zero
      :version: 1
      :violates: tool_req__coverage_scope_baseline_objects, tool_req__coverage_report_baseline_zero, tool_req__coverage_gcov_baseline
      :safety_affected: YES
      :detection_sufficient: YES
      :safety_measures: CSTR-08 requires the author to check the LCOV record for each known untested file and stop if it is missing.

      The LCOV data lacks the ``SF:`` record for a file that the author
      already knows is untested. This can conceal a test gap in safety-related
      code. The author knows which path to look for independently of the
      coverage tool, so the check in :ref:`CSTR-08 <cstr_coverage_check_baselines>`
      catches the missing record before the author relies on the percentage.

.. tool_usecase:: Assess module coverage from the verification report
   :id: tool_usecase__score_coverage__module_evidence
   :version: 1
   :belongs_to: doc_tool__score_coverage

   The module verification report automatically displays line and branch
   coverage per unit from the archived results. Readers and auditors use
   those figures and any associated justifications to assess coverage for
   the module version under review. If the report overstates coverage,
   readers and auditors may conclude that the module meets its coverage
   goals even when it falls short.

   .. potential_tool_malfunction:: Archived coverage omits an in-scope file
      :id: potential_tool_malfunction__coverage__evfile
      :version: 1
      :violates: tool_req__coverage_scope_transitive, tool_req__coverage_scope_baseline_objects, tool_req__coverage_report_baseline_zero, tool_req__coverage_gcov_baseline
      :safety_affected: YES
      :detection_sufficient: NO

      The archived results omit an in-scope file, for example when the LLVM
      baseline is missing the file's object. The verification report can
      then overstate the unit's line or branch coverage, and readers may accept
      the safety-related coverage claim. The displayed figures and the
      archived results share the omission. This use does not require readers
      to check the archive against an independent inventory of expected files.

.. tool_usecase:: Gate module CI on line coverage
   :id: tool_usecase__score_coverage__ci_gate
   :version: 1
   :belongs_to: doc_tool__score_coverage

   Module CI requires line coverage to meet the configured threshold. It uses
   raw coverage by default and effective coverage when the module supplies
   reviewed justifications. A false pass can let maintainers merge a change
   with coverage below the threshold or with no reliable coverage result.

   .. potential_tool_malfunction:: A missing file lets the coverage gate pass
      :id: potential_tool_malfunction__coverage__cifile
      :version: 1
      :violates: tool_req__coverage_scope_transitive, tool_req__coverage_scope_baseline_objects, tool_req__coverage_report_baseline_zero, tool_req__coverage_gcov_baseline
      :safety_affected: YES
      :detection_sufficient: NO

      When the coverage data omits an untested file, for example because its
      LLVM baseline object was omitted, its instrumentable lines are left out
      of the total. The gate can pass a safety-related change that would fail
      with the complete report. CI compares the reported coverage with the
      threshold without a required check that every in-scope file is present.

   .. potential_tool_malfunction:: Rounding turns a failed comparison into a pass
      :id: potential_tool_malfunction__coverage__round
      :version: 1
      :violates: tool_req__coverage_gate_unrounded
      :safety_affected: YES
      :detection_sufficient: NO

      The gate compares a rounded value with the threshold. For example, it
      accepts coverage that displays as 100.00 % but is below 100 %. This
      can hide a test gap in a safety-related module. The displayed
      percentage can agree with the false verdict, and CI does not require
      an independent comparison.

   .. potential_tool_malfunction:: The gate accepts an incorrect threshold
      :id: potential_tool_malfunction__coverage__limit
      :version: 1
      :violates: tool_req__coverage_gate_threshold
      :safety_affected: YES
      :detection_sufficient: NO

      The gate misreads a configured threshold as a lower value, uses a
      threshold below 100 % when ``COVERAGE_THRESHOLD`` is unset or blank,
      or accepts a malformed or out-of-range value. A safety-related
      change can pass with insufficient coverage or without a valid
      threshold. CI relies on the tool to interpret the configuration.

   .. potential_tool_malfunction:: The gate overstates coverage when reading the report
      :id: potential_tool_malfunction__coverage__metric
      :version: 1
      :violates: tool_req__coverage_gate_metric
      :safety_affected: YES
      :detection_sufficient: NO

      The gate misreads the line counts in a valid LCOV report or the
      effective line coverage in a valid justification report. The value
      used for the comparison can reach the threshold while the value in
      the report falls short. CI does not require a separate check of the
      value used by the gate, so a safety-related test gap can go unnoticed.

   .. potential_tool_malfunction:: An unsuccessful run exits with success
      :id: potential_tool_malfunction__coverage__verdict
      :version: 1
      :violates: tool_req__coverage_gate_exit_codes, tool_req__coverage_gate_no_verdict
      :safety_affected: YES
      :detection_sufficient: NO

      The gate returns exit code 0 after a failed comparison or when it
      cannot produce a verdict, for example because the report is missing
      or corrupt or the justification tool failed. CI can then accept a
      safety-related change with insufficient or unknown coverage.
      :ref:`CSTR-10 <cstr_coverage_exit_codes>` requires CI to fail on exit
      code 2. It relies on the gate returning the correct exit code.
