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

score_coverage
==============

``score_coverage`` is the LLVM source-based code coverage pipeline of Eclipse
S-CORE: one ``bazel coverage`` run produces one line and branch coverage report
for C++ and Rust, lists every in-scope file that no test executes at exactly
0 %, tracks reviewed justifications in an effective-coverage metric and gates
CI on a threshold.

The tool produces the structural-coverage evidence (statement and branch
coverage, C0 and C1) that S-CORE module verification reports rely on. It is
therefore developed and documented as a software tool under the S-CORE
tool-management process (ISO 26262-8, clause 11); its Tool Verification Report
lives in the S-CORE platform documentation and links here.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   manual/index
   requirements/index
   architecture/index
   verification/index
   release/index

Quick reference
---------------

.. code-block:: bash

   bazel coverage --config=llvm_cov //... --build_tests_only
   bazel run @score_coverage//:generate_coverage_html -- \
       --yaml tools/coverage/coverage_justifications.yaml --archive-dir coverage_artifact

Exit codes of ``generate_coverage_html``: ``0`` gate passed, ``1`` gate failed,
``2`` no verdict possible (broken input, invalid threshold, tool failure).
