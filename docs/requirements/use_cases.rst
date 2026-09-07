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

Use cases
=========

The use cases are modelled as stakeholder requirements of the tool user, a
module CI pipeline or a developer on a Linux host. Tool requirements satisfy
them.

.. stkh_req:: UC1 One report for C++ and Rust
   :id: stkh_req__coverage__uc_unified_report
   :version: 1
   :valid_from: v0.1.0
   :reqtype: Functional
   :safety: ASIL_B
   :security: NO
   :status: valid
   :rationale: Module verification reports need one C0/C1 figure per unit regardless of language.

   The user shall obtain, from one ``bazel coverage`` run, one report with line
   and branch coverage for the C++ and Rust units of the module.

.. stkh_req:: UC2 Untested code is visible
   :id: stkh_req__coverage__uc_scope_completeness
   :version: 1
   :valid_from: v0.1.0
   :reqtype: Functional
   :safety: ASIL_B
   :security: NO
   :status: valid
   :rationale: A file no test executes must not disappear from the evidence; it must count with 0 %.

   The user shall see every source file of the declared coverage scope in the
   report, including files that no test links against, with exact 0 % line and
   branch coverage for those.

.. stkh_req:: UC3 Reviewed justifications
   :id: stkh_req__coverage__uc_justifications
   :version: 1
   :valid_from: v0.1.0
   :reqtype: Functional
   :safety: ASIL_B
   :security: NO
   :status: valid
   :rationale: Intentionally uncovered code needs a written, reviewable argument instead of a lowered threshold.

   The user shall be able to justify intentionally uncovered lines with a
   reviewed argument, and obtain an effective coverage figure that counts
   justified lines as covered while reporting the raw figure alongside.

.. stkh_req:: UC4 CI gate
   :id: stkh_req__coverage__uc_gate
   :version: 1
   :valid_from: v0.1.0
   :reqtype: Functional
   :safety: ASIL_B
   :security: NO
   :status: valid
   :rationale: The platform quality criteria (85 % QM, 100 % safety) are enforced automatically.

   The user shall be able to fail a CI job when the gated coverage is below a
   configured threshold, and shall be able to tell a failed gate from a run
   that could not be evaluated.

.. stkh_req:: UC5 Archived evidence
   :id: stkh_req__coverage__uc_archive
   :version: 1
   :valid_from: v0.1.0
   :reqtype: Functional
   :safety: ASIL_B
   :security: NO
   :status: valid
   :rationale: The module verification report cites the archived LCOV and justification report.

   The user shall be able to archive the HTML report, the LCOV data, the
   justification report and the JUnit results of a run as one CI artifact.

.. stkh_req:: UC6 Job summary
   :id: stkh_req__coverage__uc_summary
   :version: 1
   :valid_from: v0.1.0
   :reqtype: Functional
   :safety: QM
   :security: NO
   :status: valid
   :rationale: Reviewers read the numbers on the workflow page without downloading artifacts.

   The user shall obtain a markdown summary of the run, on the GitHub Actions
   step summary or in a file, even when the gate fails.
