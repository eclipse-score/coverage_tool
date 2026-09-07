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

Potential errors
================

Potential errors of the tool, derived from the use cases with the HazOp guide
words *invalid*, *changed*, *more* and *less* applied to inputs, outputs and
actions. The dangerous direction for a coverage tool is always **more coverage
than real**: an error in that direction hides a verification gap. Errors
towards less coverage cost effort but no safety.

Tool impact is *high* when the error can make a violated structural-coverage
requirement go undetected. *Detection before qualification* describes what a
user could notice without the mitigations; the last column lists the tool
requirements and constraints of use that mitigate the error.

.. list-table::
   :header-rows: 1
   :widths: 8 32 8 12 40

   * - Id
     - Error
     - Impact
     - Detection
     - Mitigation
   * - ERR-01
     - An in-scope file is silently missing from the report (the scope aspect
       misses a dependency, a ``select`` branch, or visibility hides a target).
     - high
     - weak
     - :need:`tool_req__coverage_scope_transitive`,
       :need:`tool_req__coverage_scope_baseline_objects`,
       :need:`tool_req__coverage_report_baseline_zero`,
       :ref:`CSTR-02 <cstr_coverage_scope_list>`,
       :ref:`CSTR-08 <cstr_coverage_check_baselines>`
   * - ERR-02
     - A line or branch is reported covered although it was never executed
       (stale profile data, wrong object, wrong test merged, clashing
       instrumentation of shared objects).
     - high
     - none
     - :need:`tool_req__coverage_merge_profraw`,
       :need:`tool_req__coverage_report_merged_profile`,
       :need:`tool_req__coverage_validation_ground_truth`,
       :ref:`CSTR-05 <cstr_coverage_dynamic_mode>`
   * - ERR-03
     - The gate passes although the threshold is not met (rounding, parsing,
       unset or malformed threshold, tool failure mistaken for a pass).
     - high
     - none
     - :need:`tool_req__coverage_gate_threshold`,
       :need:`tool_req__coverage_gate_unrounded`,
       :need:`tool_req__coverage_gate_exit_codes`,
       :need:`tool_req__coverage_gate_no_verdict`,
       :ref:`CSTR-10 <cstr_coverage_exit_codes>`
   * - ERR-04
     - A justification is applied to the wrong lines, to a file with the same
       name, or a stale marker is counted as covered.
     - high
     - weak
     - :need:`tool_req__coverage_just_markers`,
       :need:`tool_req__coverage_just_unknown_id`,
       :need:`tool_req__coverage_eff_stale`,
       :need:`tool_req__coverage_eff_path_match`,
       :ref:`CSTR-07 <cstr_coverage_review_justifications>`
   * - ERR-05
     - The effective metric overstates coverage (justified and covered lines
       double counted, rounding up).
     - medium
     - weak
     - :need:`tool_req__coverage_eff_metric`,
       :need:`tool_req__coverage_eff_branch_only`
   * - ERR-06
     - Path normalisation maps two source files onto one record.
     - medium
     - weak
     - :need:`tool_req__coverage_report_relative_paths`,
       :need:`tool_req__coverage_eff_path_match`
   * - ERR-07
     - A Rust rlib is skipped, so its crate appears complete by absence.
     - high
     - none
     - :need:`tool_req__coverage_report_rlib_expansion`,
       :need:`tool_req__coverage_validation_ground_truth`,
       :ref:`CSTR-08 <cstr_coverage_check_baselines>`
   * - ERR-08
     - The wrong toolchain wins resolution; gcov data is silently mixed in or
       dropped.
     - high
     - weak
     - :need:`tool_req__coverage_gate_no_verdict`,
       :ref:`CSTR-01 <cstr_coverage_environment>`,
       :ref:`CSTR-03 <cstr_coverage_build_tests_only>`,
       :ref:`CSTR-04 <cstr_coverage_toolchain_config>`
   * - ERR-09
     - The report is regenerated from stale data or unpinned tool versions.
     - low
     - good
     - :need:`tool_req__coverage_artifacts`,
       :ref:`CSTR-06 <cstr_coverage_lockfile>`,
       :ref:`CSTR-09 <cstr_coverage_archive>`
   * - ERR-10
     - Coverage is reported too low (false gaps).
     - none
     - good
     - Informational; costs review effort only.

Classification
--------------

Tool impact: **yes**. An error in the *more coverage than real* direction lets a
violation of the structural-coverage verification requirement go undetected.
Tool error detection before qualification: **no** for ERR-02, ERR-03 and
ERR-07. The expected tool confidence level is therefore **TCL LOW**, and the
qualification method of the S-CORE process, validation of the software tool,
applies. The evaluation itself is recorded in the Tool Verification Report.
