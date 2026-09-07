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

Tool requirements
=================

Every requirement satisfies a use case or a process requirement and carries the
potential errors it mitigates as tags. The verification report lists the tests
that verify each requirement.

.. needtable:: Tool requirements overview
   :types: tool_req
   :columns: id;title;tags;implemented
   :style: table

Scope
-----

.. tool_req:: Transitive in-workspace sources define the scope
   :id: tool_req__coverage_scope_transitive
   :version: 1
   :implemented: YES
   :tags: scope, ERR-01
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_scope_completeness

   ``score_coverage_scope`` shall collect, for the listed targets and their
   transitive in-workspace dependencies reached through ``deps``,
   ``implementation_deps``, ``exported_deps``, ``components`` and
   ``implementation``, the checked-in source and header files of ``cc_library``
   and ``rust_library`` targets (``srcs``, ``hdrs``) and the ``CrateInfo``
   sources of ``rust_binary`` targets, and shall write them sorted and
   deduplicated, one workspace-relative path per line, to the allowlist file.

.. tool_req:: External and generated sources are excluded from the scope
   :id: tool_req__coverage_scope_excludes
   :version: 1
   :implemented: YES
   :tags: scope
   :safety: QM
   :satisfies: stkh_req__coverage__uc_scope_completeness

   ``score_coverage_scope`` shall not list files from external repositories or
   generated files in the allowlist.

.. tool_req:: Baseline objects accompany the scope
   :id: tool_req__coverage_scope_baseline_objects
   :version: 1
   :implemented: YES
   :tags: scope, ERR-01
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_scope_completeness

   ``score_coverage_scope`` shall list the static archives of in-workspace
   ``cc_library`` and ``rust_library`` targets and the coverage-built executable
   of ``rust_binary`` targets in the objects file, so the reporter can produce
   zero-coverage baselines for files no test links against.

Collection
----------

.. tool_req:: Per-test profiles are merged with llvm-profdata
   :id: tool_req__coverage_merge_profraw
   :version: 1
   :implemented: YES
   :tags: collection, ERR-02
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_unified_report

   For each test, the merger shall merge all ``*.profraw`` files of the test into
   one ``profdata`` file with ``llvm-profdata merge --sparse``, record the real
   paths of the instrumented objects of the test in ``meta/meta.json``, and
   package both into the test's coverage output. Object files come from the
   ``objects_list.txt`` entries of the coverage manifest (C++) or from ELF
   binaries listed in the manifest (Rust); entries under ``external/`` are
   skipped.

.. tool_req:: A test without instrumentation produces no coverage output
   :id: tool_req__coverage_merge_no_data
   :version: 1
   :implemented: YES
   :tags: collection
   :safety: QM
   :satisfies: stkh_req__coverage__uc_unified_report

   When a test has no instrumented objects or no ``profraw`` files, the merger
   shall exit 0 without writing an output file and shall say so on stderr, so
   non-instrumented tests (for example Python tests) do not fail the run.

.. tool_req:: A missing or failing llvm-profdata fails the test's collection
   :id: tool_req__coverage_merge_tool_error
   :version: 1
   :implemented: YES
   :tags: collection, ERR-02
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_gate

   When ``llvm-profdata`` cannot be located through ``LLVM_PROFDATA`` or
   ``RUST_LLVM_PROFDATA``, or exits non-zero, the merger shall exit 1 without
   writing an output file.

Report
------

.. tool_req:: One merged profile for all tests
   :id: tool_req__coverage_report_merged_profile
   :version: 1
   :implemented: YES
   :tags: report, ERR-02
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_unified_report

   The reporter shall extract the ``profdata`` and object lists of all valid
   per-test outputs, skip invalid or empty ones with a warning, merge the
   profiles into one, and produce the HTML, LCOV and text reports from that
   merged profile and the union of the instrumented objects.

.. tool_req:: The report is restricted to the scope allowlist
   :id: tool_req__coverage_report_allowlist
   :version: 1
   :implemented: YES
   :tags: report
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_scope_completeness

   The reporter shall exclude every file with coverage data that is not in the
   allowlist from all three report formats. An empty allowlist shall be an
   error (exit non-zero), not an empty report.

.. tool_req:: Untested in-scope files appear at exact 0 %
   :id: tool_req__coverage_report_baseline_zero
   :version: 1
   :implemented: YES
   :tags: report, ERR-01
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_scope_completeness

   For every allowlisted file that appears in the baseline objects but in no
   test binary, the reporter shall run ``llvm-cov`` with ``--empty-profile`` over
   the baseline objects and shall include the file in the HTML and LCOV output
   with all instrumented lines and branches at zero hits, so that the LCOV
   record shows ``LH:0``.

.. tool_req:: Rust rlib archives are expanded into object members
   :id: tool_req__coverage_report_rlib_expansion
   :version: 1
   :implemented: YES
   :tags: report, ERR-07
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_scope_completeness

   Before passing baseline archives to ``llvm-cov``, the reporter shall detect
   archives with a ``lib.rmeta`` member and replace them by their ``.o``
   members, so that Rust libraries are not rejected as having no coverage data.

.. tool_req:: A missing baseline object is an error
   :id: tool_req__coverage_report_missing_baseline
   :version: 1
   :implemented: YES
   :tags: report, ERR-01
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_scope_completeness

   When an entry of the baseline objects manifest cannot be resolved to an
   existing file, the reporter shall exit non-zero instead of silently dropping
   the object.

.. tool_req:: Report paths are workspace-relative
   :id: tool_req__coverage_report_relative_paths
   :version: 1
   :implemented: YES
   :tags: report, ERR-06
   :safety: QM
   :satisfies: stkh_req__coverage__uc_archive

   The reporter shall rewrite the absolute workspace root and the compiler's
   ``/proc/self/cwd/`` prefix in LCOV ``SF:`` records and in HTML page titles to
   workspace-relative paths, so that the archived report is portable and file
   identity does not depend on the machine.

.. tool_req:: Report contents
   :id: tool_req__coverage_report_outputs
   :version: 1
   :implemented: YES
   :tags: report
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_unified_report

   The reporter's output shall be a zip containing ``html_report/`` (llvm-cov
   HTML with branch counts), ``lcov_report/lcov.dat`` (LCOV with line and
   branch records) and ``text_report/summary.txt`` (llvm-cov text summary), with
   ``llvm-cov`` warnings kept out of the LCOV data. When no valid per-test
   output exists, the output shall be an empty zip.

Justifications
--------------

.. tool_req:: Justification YAML is validated
   :id: tool_req__coverage_just_yaml
   :version: 1
   :implemented: YES
   :tags: justification, ERR-04
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_justifications

   The justification processor shall reject, with exit 1 and a message per
   finding, a YAML that is not a mapping with an integer ``version`` and a
   ``justifications`` list, or that contains an entry without a kebab-case
   string ``id``, a known ``category``, a non-empty list of known ``platforms``
   or a non-blank ``reason``, or with malformed ``locations``. Duplicate ids
   shall be rejected.

.. tool_req:: In-code markers
   :id: tool_req__coverage_just_markers
   :version: 1
   :implemented: YES
   :tags: justification, ERR-04
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_justifications

   The justification processor shall resolve ``COV_JUSTIFIED <id>`` to the
   marker's line and ``COV_JUSTIFIED_START <id>`` / ``COV_JUSTIFIED_STOP`` to the
   lines strictly between the markers, in checked-in sources with the
   configured extensions, skipping Bazel output directories, and shall combine
   them with the explicit ``locations`` of the YAML into a manifest keyed by
   workspace-relative file and line.

.. tool_req:: Unknown marker ids do not justify anything
   :id: tool_req__coverage_just_unknown_id
   :version: 1
   :implemented: YES
   :tags: justification, ERR-04
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_justifications

   A marker whose id is not in the (platform-filtered) YAML, a ``STOP`` without
   ``START`` and a ``START`` without ``STOP`` shall be reported as warnings and
   shall justify no line.

.. tool_req:: Platform filter
   :id: tool_req__coverage_just_platform
   :version: 1
   :implemented: YES
   :tags: justification
   :safety: QM
   :satisfies: stkh_req__coverage__uc_justifications

   When a platform is given, only justifications listing that platform shall
   apply.

.. tool_req:: Justified locations exist
   :id: tool_req__coverage_just_missing_file
   :version: 1
   :implemented: YES
   :tags: justification, ERR-04
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_justifications

   A YAML location whose file does not exist shall be reported as an error and
   the processor shall exit 1 after writing the manifest.

Effective coverage
------------------

.. tool_req:: Effective coverage metric
   :id: tool_req__coverage_eff_metric
   :version: 1
   :implemented: YES
   :tags: effective, ERR-05
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_justifications

   Effective line coverage shall be ``(covered + justified) / total`` and
   effective branch coverage ``(covered + justified branches) / total branches``,
   with the totals taken from the report's own totals (llvm-cov index page, or
   the LCOV for gcovr reports), both floored to two decimals, never rounded up.
   Raw figures shall be reported alongside.

.. tool_req:: Stale justifications are reported and not counted
   :id: tool_req__coverage_eff_stale
   :version: 1
   :implemented: YES
   :tags: effective, ERR-04
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_justifications

   A justified line that is covered in any instantiation and has no uncovered
   branch shall be reported as stale and shall not increase the effective
   coverage.

.. tool_req:: Branch-only justifications
   :id: tool_req__coverage_eff_branch_only
   :version: 1
   :implemented: YES
   :tags: effective, ERR-05
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_justifications

   A justified line that is covered but has a branch direction no instantiation
   covers shall count its truly uncovered directions once as justified branches
   and shall not count as a justified line.

.. tool_req:: Justifications match files at path-component boundaries
   :id: tool_req__coverage_eff_path_match
   :version: 1
   :implemented: YES
   :tags: effective, ERR-04, ERR-06
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_justifications

   A justification for a file shall apply to a report page only when the page's
   source path equals the justified path or ends with it at a path-component
   boundary; ``bar.cpp`` shall not apply to ``foobar.cpp``.

.. tool_req:: Justified lines are visible in the HTML
   :id: tool_req__coverage_eff_html
   :version: 1
   :implemented: YES
   :tags: effective
   :safety: QM
   :satisfies: stkh_req__coverage__uc_justifications

   Justified lines shall be restyled in the HTML report with a ``J`` marker, the
   justification id and reason as tooltip and a distinct colour, the index page
   shall show the effective figures, and stale justifications shall be listed in
   ``summary.txt``.

.. tool_req:: gcovr HTML reports are supported
   :id: tool_req__coverage_eff_gcovr
   :version: 1
   :implemented: YES
   :tags: effective
   :safety: QM
   :satisfies: stkh_req__coverage__uc_justifications

   The post-processor shall detect gcovr ``--html-details`` reports and apply
   the same justification logic to them, reading totals from the LCOV file when
   given and from the summary rows of the index page otherwise.

Gate
----

.. tool_req:: Threshold from the environment
   :id: tool_req__coverage_gate_threshold
   :version: 1
   :implemented: YES
   :tags: gate, ERR-03
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_gate

   The threshold shall be read from ``COVERAGE_THRESHOLD`` and default to 100 %.
   A value that is not a number in ``[0, 100]`` shall be rejected before any
   report is produced (exit 2).

.. tool_req:: Gated metric
   :id: tool_req__coverage_gate_metric
   :version: 1
   :implemented: YES
   :tags: gate, ERR-01
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_gate

   With ``--yaml`` the gate shall use the effective line coverage from the
   justification report; without it the raw line coverage summed over all
   ``LF``/``LH`` records of the LCOV data, so that baseline-only files count.
   The llvm-cov text summary, which omits baseline files, shall not be used.

.. tool_req:: Unrounded comparison
   :id: tool_req__coverage_gate_unrounded
   :version: 1
   :implemented: YES
   :tags: gate, ERR-03
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_gate

   The gate shall compare the unrounded percentage with the threshold; a value
   that prints as 100.00 but is below 100 shall fail a threshold of 100.

.. tool_req:: Exit codes
   :id: tool_req__coverage_gate_exit_codes
   :version: 1
   :implemented: YES
   :tags: gate, ERR-03
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_gate

   ``generate_coverage_html`` shall exit 0 when the gate passes, 1 when it fails,
   and 2 when no verdict is possible. A tool failure shall never end in exit 0.

.. tool_req:: Broken input yields no verdict
   :id: tool_req__coverage_gate_no_verdict
   :version: 1
   :implemented: YES
   :tags: gate, ERR-03, ERR-08
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_gate

   A missing or non-zip coverage report, a report without ``html_report/``, LCOV
   data without instrumented lines, ``LH`` exceeding ``LF``, a missing
   justification YAML, a failing justification tool, or a missing
   ``summary.txt`` shall end the run with exit 2.

Summary and archive
-------------------

.. tool_req:: Summary is written before the verdict
   :id: tool_req__coverage_summary_first
   :version: 1
   :implemented: YES
   :tags: summary
   :safety: QM
   :satisfies: stkh_req__coverage__uc_summary, gd_req__verification_reporting

   The markdown summary (``--summary-md``, or appended to ``GITHUB_STEP_SUMMARY``
   when the flag is absent) shall be written before the gate decides, so a
   failing gate still leaves the summary; the explicit flag shall take
   precedence over the environment variable.

.. tool_req:: Artifacts tree
   :id: tool_req__coverage_artifacts
   :version: 1
   :implemented: YES
   :tags: archive, ERR-09
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_archive, gd_req__verification_report_archiving

   With ``--archive-dir`` the tool shall assemble the HTML report, the LCOV data
   as ``coverage_report.dat``, the justification report directory and the
   ``test.xml`` files of the selected ``bazel-testlogs`` subtree with their
   paths preserved, also when the gate fails; a missing test-logs directory
   shall be an error.

Validation
----------

.. tool_req:: Ground-truth validation
   :id: tool_req__coverage_validation_ground_truth
   :version: 1
   :implemented: YES
   :tags: validation, ERR-02, ERR-07
   :safety: ASIL_B
   :satisfies: stkh_req__coverage__uc_unified_report, stkh_req__coverage__uc_scope_completeness

   The pipeline shall be validated end to end against a fixture workspace with
   C++ and Rust units whose line and branch counts are derived by hand: the
   produced LCOV shall match the expected records exactly (``DA``, ``BRDA``,
   ``LF``, ``LH``, ``BRF``, ``BRH`` per file), including exact-0 % records for an
   untested C++ library and an untested Rust binary.
