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

0.2.0 (unreleased)
------------------

- Fixed (eclipse-score/coverage_tool#5): a workspace rule that forwards the
  ``CcInfo`` of a third-party library (e.g. a transition wrapper around
  OpenSSL) no longer puts that library's headers into the scope; only headers
  a workspace target declares itself count.
- Fixed (eclipse-score/coverage_tool#5): every index link of the HTML report
  points at a generated page. The reporter stages the in-scope sources from
  the scope's exported files instead of reading them through the workspace
  directory, where generated headers and external repositories are not
  present at report time.
- Changed: headers compiled through ``strip_include_prefix`` /
  ``include_prefix`` are reported under their declared path (e.g.
  ``score/flatbuffers/include/flatbuffers/base.h`` or
  ``external/flatbuffers+/include/flatbuffers/base.h``), no longer under the
  generated ``_virtual_includes/`` path. Justifications written against a
  ``_virtual_includes/`` path must be updated.
- Changed: HTML pages live at ``coverage/<canonical path>.html``; the archive
  contains no directory of the producing machine any more.
- New: in-scope files that carry no coverage data at all (a header nothing
  includes, template-only code that is never instantiated) are no longer
  silently absent. The reporter writes ``text_report/unmapped_files.txt`` and
  warns; ``generate_coverage_html`` prints them, archives the list as
  ``unmapped_files.txt`` and adds a row and a section to the job summary
  (``tool_req__coverage_report_unmapped``). Declaration-only headers and
  placeholder sources compiled without code are categorised separately and
  are not findings.
- Fixed: a library archive with one member lacking a coverage mapping (the
  placeholder ``.cpp`` of a header-only library) was rejected by ``llvm-cov``
  as a whole, so the library's other untested files silently lost their 0 %
  baseline. Archive members are now inspected and only those with a mapping
  are passed on, the way Rust rlibs were already handled
  (``tool_req__coverage_report_rlib_expansion`` v2).
- Fixed: the exclusion filter matches each out-of-scope compiled file exactly;
  an excluded ``foo/bar.h`` no longer suppresses an in-scope ``src/foo/bar.h``.
- ``score_coverage_scope`` gained the ``path_map`` and ``source_files`` output
  groups; ``score_coverage_reporter`` passes them to the reporter
  (``--path_map``). Consumers only instantiate the macros; no change needed.

0.1.0 (2026-09-11)
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
- Headers reached through ``strip_include_prefix`` / ``include_prefix`` (Bazel's
  ``_virtual_includes/`` tree) and headers a workspace target vendors from an
  external repository are now part of the coverage scope; the reporter
  normalises the configuration-specific ``bazel-out/<config>/bin/`` prefix and
  suppresses the duplicate baseline entry of such headers
  (eclipse-score/baselibs#558).

Known problems: see :doc:`../manual/known_problems`.
