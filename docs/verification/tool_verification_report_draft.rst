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
   The tool runs on a Linux host. The LLVM backend uses ``llvm-cov`` for C++
   and Rust tested on Linux. The gcov backend handles C++ tested on Linux
   or in QEMU for QNX.

   The tool consumes the declared Bazel coverage scope, coverage data collected
   by Bazel, and optional coverage justifications and a gate threshold. It
   produces coverage reports in LCOV (the common format for line and branch
   counts) and HTML, along with raw and effective coverage summaries,
   archivable evidence, and a gate exit code.

The :doc:`user manual <../manual/user_manual>` describes backend configuration
and invocation. The analysis of
:doc:`potential errors <../requirements/potential_errors>` provides the starting
point for the evaluation.

The draft uses the existing security classification provisionally. The
evaluation will confirm security relevance and record the exact tool release
or source revision.

Intended use
------------

The draft records selected malfunctions for each use and how they can
affect the user's decision.

.. tool_usecase:: Find test gaps during pull request development
   :id: tool_usecase__score_coverage__author_review
   :version: 1
   :belongs_to: doc_tool__score_coverage

   Contributors use a locally generated coverage report to find lines
   and branches that still need tests or justifications. The
   `Lifecycle coverage guide <https://github.com/eclipse-score/lifecycle/blob/7d7f67d364e5999ca8665bf35fe98098f12a0208/quality/coverage/README.md#usage>`__
   shows how to generate and open the report.

   .. potential_tool_malfunction:: The tool leaves a required dependency out of the coverage scope
      :id: potential_tool_malfunction__coverage__scope
      :version: 1
      :violates: tool_req__coverage_scope_transitive
      :safety_affected: YES
      :detection_sufficient: NO

      A source file from a required dependency falls outside the scope
      the tool measures. The author's expected files can all be present
      while a test gap in the omitted dependency goes unnoticed.

   .. potential_tool_malfunction:: An untested file is missing without a warning
      :id: potential_tool_malfunction__coverage__silent
      :version: 1
      :violates: tool_req__coverage_report_baseline_zero, tool_req__coverage_gcov_baseline, tool_req__coverage_report_unmapped
      :safety_affected: YES
      :detection_sufficient: NO

      The tool recognizes an untested file as in scope. The report leaves
      it out without indicating that coverage data is missing. The author
      can overlook the test gap because the report appears complete.

   .. potential_tool_malfunction:: An unexecuted branch appears covered
      :id: potential_tool_malfunction__coverage__badhit
      :version: 1
      :violates: tool_req__coverage_report_merged_profile, tool_req__coverage_gcov_merge
      :safety_affected: YES
      :detection_sufficient: NO

      The report marks an unexecuted branch as covered. The author can
      submit a change without adding a test for that branch because its
      reported coverage looks plausible.

   .. potential_tool_malfunction:: The local report makes a test gap look justified
      :id: potential_tool_malfunction__coverage__jauthor
      :version: 1
      :violates: tool_req__coverage_eff_path_match
      :safety_affected: YES
      :detection_sufficient: NO

      If a :need:`justification is credited to the wrong file <potential_tool_malfunction__coverage__jpath>`,
      the contributor can skip a needed test because the report shows
      the gap as justified.

.. tool_usecase:: Assess module coverage from the verification report
   :id: tool_usecase__score_coverage__module_evidence
   :version: 1
   :belongs_to: doc_tool__score_coverage

   Committers use archived coverage results as evidence in the module
   verification report. Reviewers use the reported coverage and any
   justifications to assess whether each component meets its coverage
   goals. The S-CORE workflow :need:`wf__verification_mod_ver_report`
   includes unit code coverage, and :need:`wp__verification_module_ver_report`
   requires C0 and C1 per component.

   .. potential_tool_malfunction:: Archived coverage omits an in-scope file
      :id: potential_tool_malfunction__coverage__evfile
      :version: 1
      :violates: tool_req__coverage_scope_transitive, tool_req__coverage_scope_baseline_objects, tool_req__coverage_report_baseline_zero, tool_req__coverage_gcov_baseline
      :safety_affected: YES
      :detection_sufficient: NO

      An in-scope file is absent from the archived results. The resulting
      line or branch coverage can be too high, leading readers to accept
      a safety-related coverage claim based on incomplete evidence.

   .. potential_tool_malfunction:: An approved justification is credited to the wrong file
      :id: potential_tool_malfunction__coverage__jpath
      :version: 1
      :violates: tool_req__coverage_eff_path_match
      :safety_affected: YES
      :detection_sufficient: NO

      The tool credits uncovered lines in a file the approved justification
      does not cover. Reviewers can accept a test gap as justified in the
      module verification report.

.. tool_usecase:: Gate module CI on line coverage
   :id: tool_usecase__score_coverage__ci_gate
   :version: 1
   :belongs_to: doc_tool__score_coverage

   Module CI uses the gate's exit code to decide whether the coverage
   check passed. The gate compares the configured threshold with raw line
   coverage, or with effective line coverage when run with ``--yaml``.
   For example, `Lifecycle's pull request workflow <https://github.com/eclipse-score/lifecycle/blob/7d7f67d364e5999ca8665bf35fe98098f12a0208/.github/workflows/on-pr.yml#L132-L136>`__
   calls a coverage job that enforces a configured threshold.

   .. potential_tool_malfunction:: A misapplied justification lets the coverage gate pass
      :id: potential_tool_malfunction__coverage__jgate
      :version: 1
      :violates: tool_req__coverage_eff_path_match
      :safety_affected: YES
      :detection_sufficient: NO

      If a :need:`justification is credited to the wrong file <potential_tool_malfunction__coverage__jpath>`,
      effective line coverage can be high enough for CI to report a pass
      even though the correctly calculated value is below the threshold.

   .. potential_tool_malfunction:: A missing file lets the coverage gate pass
      :id: potential_tool_malfunction__coverage__cifile
      :version: 1
      :violates: tool_req__coverage_scope_transitive, tool_req__coverage_scope_baseline_objects, tool_req__coverage_report_baseline_zero, tool_req__coverage_gcov_baseline
      :safety_affected: YES
      :detection_sufficient: NO

      An untested file is absent from the coverage total. CI sees a pass
      even though coverage across the intended scope falls below the
      threshold.

   .. potential_tool_malfunction:: The gate accepts a valid report below the threshold
      :id: potential_tool_malfunction__coverage__compare
      :version: 1
      :violates: tool_req__coverage_gate_metric, tool_req__coverage_gate_threshold, tool_req__coverage_gate_unrounded, tool_req__coverage_gate_exit_codes
      :safety_affected: YES
      :detection_sufficient: NO

      The gate reports a pass even though the valid coverage result falls
      below the configured threshold. CI can accept a change with
      insufficient coverage.

   .. potential_tool_malfunction:: The gate reports success without a valid verdict
      :id: potential_tool_malfunction__coverage__verdict
      :version: 1
      :violates: tool_req__coverage_gate_exit_codes, tool_req__coverage_gate_no_verdict
      :safety_affected: YES
      :detection_sufficient: NO

      The gate signals a pass when it cannot determine whether coverage
      meets the threshold. CI can accept a change with unknown coverage.
