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

.. tool_usecase:: Find gaps in test coverage
   :id: tool_usecase__score_coverage__coverage_review
   :version: 1
   :belongs_to: doc_tool__score_coverage

   Contributors use line and branch coverage to find test gaps while
   writing code. Committers use the results when reviewing changes or
   improving a module's test coverage. The results help them decide
   where to add tests or justify remaining gaps.

   Both usually inspect the HTML report, with justification
   annotations when enabled. An IDE can also import the tool's LCOV
   report and display the raw coverage data.

.. tool_usecase:: Enforce a line coverage threshold in CI
   :id: tool_usecase__score_coverage__ci_gate
   :version: 1
   :belongs_to: doc_tool__score_coverage

   The CI job sets the minimum line coverage and uses the tool's exit
   status as the result of the coverage check. The threshold applies to
   raw line coverage, or to effective line coverage when the job supplies
   justifications. The check fails if coverage is below the threshold or
   the run produces no verdict.

   For example, the `Lifecycle coverage workflow <https://github.com/eclipse-score/lifecycle/blob/7d7f67d364e5999ca8665bf35fe98098f12a0208/.github/workflows/code_coverage.yml#L49-L53>`__
   sets ``COVERAGE_THRESHOLD`` when it runs coverage in CI.

.. tool_usecase:: Provide structural coverage evidence for safety-related use
   :id: tool_usecase__score_coverage__module_evidence
   :version: 1
   :belongs_to: doc_tool__score_coverage

   ``score_coverage`` supplies the archived coverage data and, where
   applicable, the justification report. The module's reporting
   automation generates the module verification report
   (:need:`wp__verification_module_ver_report`). That report records line
   and branch coverage for the revision under verification and cites the
   archived artifacts. The coverage evidence helps assess whether that
   revision is suitable for safety-related use.
