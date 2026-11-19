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
