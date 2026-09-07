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

Release notes
=============

.. document:: score_coverage release notes
   :id: doc__coverage_release_notes
   :version: 1
   :status: draft
   :safety: ASIL_B
   :security: NO
   :realizes: wp__module_sw_release_note

0.1.0 (unreleased)
------------------

First release as a standalone module, extracted from ``@score_tooling//coverage``
(tooling commit ``9a61f42``).

Changes relative to the pipeline in score_tooling 2.2.x:

- Consumer labels move to the module root: ``@score_coverage//:defs.bzl``,
  ``//:merger``, ``//:generate_coverage_html``,
  ``//:enable_llvm_coverage_for_death_tests``.
- ``generate_coverage_html`` is Python and returns exit code 2 for runs without
  a verdict; the gate compares unrounded percentages; malformed thresholds and
  corrupt LCOV data are rejected.
- Justifications match files at path-component boundaries (a justification for
  ``bar.cpp`` no longer applies to ``foobar.cpp``).
- gcovr reports: the index totals of gcovr 8.x are read correctly without
  ``--lcov``; ``summary.txt`` is written for gcovr reports too.
- The repository-bound ``combined_report`` and ``llvm_profile_wrapper`` helpers
  are not part of the module.

Known problems: see :doc:`../manual/known_problems`.
