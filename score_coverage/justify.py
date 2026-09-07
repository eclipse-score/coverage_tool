#!/usr/bin/env python3
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
"""Coverage justification processor.

Parses the YAML justification database and source files for COV_JUSTIFIED markers.
Resolves all justified lines and produces a manifest mapping file:line → justification.

Usage:
    python justify.py --yaml <justifications.yaml> --source-root <path> --output <manifest.json>

Supports two ways to specify justified lines:
1. YAML locations: directly specify file + line ranges in the YAML
2. In-code markers: COV_JUSTIFIED <id>, COV_JUSTIFIED_START <id> / COV_JUSTIFIED_STOP
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

import yaml

# Marker patterns
COV_JUSTIFIED_LINE_RE = re.compile(r"COV_JUSTIFIED\s+([\w-]+)")
COV_JUSTIFIED_START_RE = re.compile(r"COV_JUSTIFIED_START\s+([\w-]+)")
COV_JUSTIFIED_STOP_RE = re.compile(r"COV_JUSTIFIED_STOP")

VALID_CATEGORIES = {
    "defensive_programming",
    "tool_false_positive",
    "platform_specific",
    "other",
}

VALID_PLATFORMS = {
    "linux",
    "qnx",
}


def main(argv: list[str] | None = None) -> None:
    """Main entry point. ``argv`` defaults to ``sys.argv[1:]``."""
    args = parse_args(argv)

    justifications_data = load_yaml(args.yaml)
    validate_yaml(justifications_data)
    justifications_by_id = _justifications_by_id(justifications_data, args.platform)

    resolved, errors = _resolve_yaml_locations(justifications_by_id, Path(args.source_root))
    warnings = _scan_sources(Path(args.source_root), args.file_filter, justifications_by_id, resolved)
    _write_manifest(Path(args.output), Path(args.source_root), resolved, warnings, errors)

    # Print diagnostics
    total_justified_lines = sum(len(lines) for lines in resolved.values())
    print(
        f"INFO: Resolved {total_justified_lines} justified lines across {len(resolved)} files.",
        file=sys.stderr,
    )
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _justifications_by_id(data: dict[str, Any], platform: str | None) -> dict[str, dict[str, Any]]:
    """Index the entries by id, keeping only those that apply to ``platform`` (if given)."""
    by_id: dict[str, dict[str, Any]] = {entry["id"]: entry for entry in data.get("justifications", [])}
    if platform:
        by_id = {jid: entry for jid, entry in by_id.items() if _matches_platform(entry, platform)}
    return by_id


def _resolve_yaml_locations(
    justifications_by_id: dict[str, dict[str, Any]], source_root: Path
) -> tuple[dict[str, dict[int, dict[str, str]]], list[str]]:
    """Resolve the explicit ``locations`` of the YAML entries to file -> line -> justification."""
    resolved: dict[str, dict[int, dict[str, str]]] = {}
    errors: list[str] = []
    for entry in justifications_by_id.values():
        for location in entry.get("locations", []):
            file_path = location["file"]
            if not (source_root / file_path).exists():
                errors.append(f"File not found for justification '{entry['id']}': {file_path}")
                continue
            lines = resolved.setdefault(file_path, {})
            for line in resolve_location_lines(location):
                lines[line] = {
                    "id": entry["id"],
                    "category": entry["category"],
                    "reason": entry["reason"].strip(),
                }
    return resolved, errors


def _scan_sources(
    source_root: Path,
    file_filter: str,
    justifications_by_id: dict[str, dict[str, Any]],
    resolved: dict[str, dict[int, dict[str, str]]],
) -> list[str]:
    """Scan the source tree for COV_JUSTIFIED markers, merging results into ``resolved``."""
    warnings: list[str] = []
    for source_file in collect_source_files(source_root, file_filter):
        rel_path = str(source_file.relative_to(source_root))
        scan_warnings, scan_lines = scan_file_for_markers(source_file, rel_path, justifications_by_id)
        warnings.extend(scan_warnings)
        if scan_lines:
            resolved.setdefault(rel_path, {}).update(scan_lines)
    return warnings


def _write_manifest(
    output_path: Path,
    source_root: Path,
    resolved: dict[str, dict[int, dict[str, str]]],
    warnings: list[str],
    errors: list[str],
) -> None:
    """Write the manifest consumed by effective_coverage (line keys as strings, files sorted)."""
    manifest = {
        "version": 1,
        "source_root": str(source_root),
        "justified_files": {
            filepath: {str(k): v for k, v in lines.items()} for filepath, lines in sorted(resolved.items())
        },
        "warnings": warnings,
        "errors": errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def resolve_location_lines(location: dict[str, Any]) -> list[int]:
    """Resolve line numbers from a YAML location entry."""
    if "lines" in location:
        return location["lines"]
    if "line_start" in location and "line_end" in location:
        return list(range(location["line_start"], location["line_end"] + 1))
    if "line" in location:
        return [location["line"]]
    return []


def _matches_platform(entry: dict[str, Any], platform: str) -> bool:
    """Check if a justification entry applies to the given platform.

    The ``platforms`` field is mandatory and validated by ``validate_yaml``.
    """
    platforms = entry.get("platforms", [])
    return platform in platforms


def scan_file_for_markers(
    file_path: Path,
    rel_path: str,
    justifications_by_id: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[int, dict[str, str]]]:
    """Scan a source file for COV_JUSTIFIED markers."""
    warnings = []
    justified_lines: dict[int, dict[str, str]] = {}

    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return warnings, justified_lines

    region_stack: list[tuple[int, str]] = []  # (start_line, justification_id)

    for line_num, line in enumerate(lines, start=1):
        # Check for COV_JUSTIFIED_START
        start_match = COV_JUSTIFIED_START_RE.search(line)
        if start_match:
            jid = start_match.group(1)
            if jid not in justifications_by_id:
                warnings.append(f"{rel_path}:{line_num}: COV_JUSTIFIED_START references unknown ID '{jid}'")
            else:
                region_stack.append((line_num, jid))
            continue

        # Check for COV_JUSTIFIED_STOP
        stop_match = COV_JUSTIFIED_STOP_RE.search(line)
        if stop_match:
            if not region_stack:
                warnings.append(f"{rel_path}:{line_num}: COV_JUSTIFIED_STOP without matching START")
            else:
                start_line, jid = region_stack.pop()
                if jid in justifications_by_id:
                    entry = justifications_by_id[jid]
                    for ln in range(start_line + 1, line_num):
                        justified_lines[ln] = {
                            "id": jid,
                            "category": entry["category"],
                            "reason": entry["reason"].strip(),
                        }
            continue

        # Check for single-line COV_JUSTIFIED (but not START/STOP)
        if "COV_JUSTIFIED_START" not in line and "COV_JUSTIFIED_STOP" not in line:
            line_match = COV_JUSTIFIED_LINE_RE.search(line)
            if line_match:
                jid = line_match.group(1)
                if jid not in justifications_by_id:
                    warnings.append(f"{rel_path}:{line_num}: COV_JUSTIFIED references unknown ID '{jid}'")
                else:
                    entry = justifications_by_id[jid]
                    justified_lines[line_num] = {
                        "id": jid,
                        "category": entry["category"],
                        "reason": entry["reason"].strip(),
                    }

    # Check for unclosed regions
    for start_line, jid in region_stack:
        warnings.append(f"{rel_path}:{start_line}: COV_JUSTIFIED_START '{jid}' without matching STOP")

    return warnings, justified_lines


def collect_source_files(source_root: Path, file_filter: str) -> list[Path]:
    """Collect source files to scan for markers."""
    extensions = file_filter.split(",") if file_filter else ["cpp", "h", "hpp", "cc", "rs"]
    files = []
    for ext in extensions:
        for path in source_root.rglob(f"*.{ext.strip()}"):
            # Skip Bazel convenience symlinks (bazel-bin, bazel-out, bazel-<repo>, ...)
            # so the marker scan does not descend into build outputs.
            rel_parts = path.relative_to(source_root).parts
            if rel_parts and rel_parts[0].startswith("bazel-"):
                continue
            files.append(path)
    return sorted(files)


def load_yaml(yaml_path: Path) -> dict[str, Any]:
    """Load YAML justification database."""
    if not yaml_path.exists():
        print(f"ERROR: Justification YAML not found: {yaml_path}", file=sys.stderr)
        sys.exit(1)

    with open(yaml_path, encoding="utf-8") as f:
        content = f.read()

    return yaml.safe_load(content)


def validate_yaml(data: Any) -> None:
    """Validate the justification YAML structure and types; exit(1) with all findings on failure."""
    try:
        errors = _validate_document(data)
    except Exception as error:  # pylint: disable=broad-exception-caught
        # Any malformed shape must end in a validation failure, never in a traceback.
        print(f"ERROR: YAML validation: {error}", file=sys.stderr)
        sys.exit(1)
    if errors:
        for e in errors:
            print(f"ERROR: YAML validation: {e}", file=sys.stderr)
        sys.exit(1)


def _validate_document(data: Any) -> list[str]:
    """Return all validation errors of the document (empty when valid)."""
    if not isinstance(data, dict):
        return ["root must be a mapping"]
    errors: list[str] = []
    if "version" not in data:
        errors.append("Missing 'version' field")
    elif not isinstance(data["version"], int):
        errors.append(f"'version' must be an integer, got {type(data['version']).__name__}")
    if "justifications" not in data:
        errors.append("Missing 'justifications' field")
        return errors
    justifications = data["justifications"]
    if not isinstance(justifications, list):
        errors.append(f"'justifications' must be a list, got {type(justifications).__name__}")
        return errors
    seen_ids: set[str] = set()
    for i, entry in enumerate(justifications):
        errors.extend(_validate_entry(f"justifications[{i}]", entry, seen_ids))
    return errors


def _validate_entry(prefix: str, entry: Any, seen_ids: set[str]) -> list[str]:
    """Validate one justification entry."""
    if not isinstance(entry, dict):
        return [f"{prefix}: must be a mapping, got {type(entry).__name__}"]
    if "id" not in entry:
        return [f"{prefix}: missing 'id'"]
    jid = entry["id"]
    if not isinstance(jid, str):
        return [f"{prefix}: 'id' must be a string, got {type(jid).__name__}"]
    errors: list[str] = []
    if jid in seen_ids:
        errors.append(f"{prefix}: duplicate ID '{jid}'")
    seen_ids.add(jid)
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", jid):
        errors.append(f"{prefix}: ID '{jid}' must be kebab-case")
    errors.extend(_validate_choice(prefix, entry, "category", VALID_CATEGORIES))
    errors.extend(_validate_platforms(prefix, entry))
    errors.extend(_validate_reason(prefix, entry))
    if "locations" in entry:
        errors.extend(_validate_locations(prefix, entry["locations"]))
    return errors


def _validate_choice(prefix: str, entry: dict[str, Any], field: str, valid: set[str]) -> list[str]:
    """A mandatory string field restricted to ``valid`` values."""
    if field not in entry:
        return [f"{prefix}: missing '{field}'"]
    value = entry[field]
    if not isinstance(value, str):
        return [f"{prefix}: '{field}' must be a string, got {type(value).__name__}"]
    if value not in valid:
        return [f"{prefix}: invalid {field} '{value}'. Must be one of: {sorted(valid)}"]
    return []


def _validate_platforms(prefix: str, entry: dict[str, Any]) -> list[str]:
    """``platforms``: a non-empty list of known platform names."""
    if "platforms" not in entry:
        return [f"{prefix}: missing 'platforms'"]
    platforms = entry["platforms"]
    if not isinstance(platforms, list):
        return [f"{prefix}: 'platforms' must be a list, got {type(platforms).__name__}"]
    if not platforms:
        return [f"{prefix}: 'platforms' must not be empty"]
    errors: list[str] = []
    for p in platforms:
        if not isinstance(p, str):
            errors.append(f"{prefix}: 'platforms' entries must be strings, got {type(p).__name__}")
        elif p not in VALID_PLATFORMS:
            errors.append(f"{prefix}: invalid platform '{p}'. Must be one of: {sorted(VALID_PLATFORMS)}")
    return errors


def _validate_reason(prefix: str, entry: dict[str, Any]) -> list[str]:
    """``reason``: a non-blank string."""
    if "reason" not in entry:
        return [f"{prefix}: missing 'reason'"]
    reason = entry["reason"]
    if not isinstance(reason, str):
        return [f"{prefix}: 'reason' must be a string, got {type(reason).__name__}"]
    if not reason.strip():
        return [f"{prefix}: 'reason' must not be empty"]
    return []


def _validate_locations(prefix: str, locations: Any) -> list[str]:
    """``locations``: a list of mappings with a ``file`` and integer line selectors."""
    if not isinstance(locations, list):
        return [f"{prefix}: 'locations' must be a list, got {type(locations).__name__}"]
    errors: list[str] = []
    for j, loc in enumerate(locations):
        loc_prefix = f"{prefix}.locations[{j}]"
        if not isinstance(loc, dict):
            errors.append(f"{loc_prefix}: must be a mapping, got {type(loc).__name__}")
            continue
        loc_map = cast(dict[str, Any], loc)  # ty cannot narrow Any through isinstance
        if "file" not in loc_map:
            errors.append(f"{loc_prefix}: missing 'file'")
        elif not isinstance(loc_map["file"], str):
            errors.append(f"{loc_prefix}: 'file' must be a string, got {type(loc_map['file']).__name__}")
        for int_field in ("line", "line_start", "line_end"):
            if int_field in loc and not isinstance(loc_map[int_field], int):
                errors.append(
                    f"{loc_prefix}: '{int_field}' must be an integer, got {type(loc_map[int_field]).__name__}"
                )
        if "lines" in loc:
            if not isinstance(loc_map["lines"], list):
                errors.append(f"{loc_prefix}: 'lines' must be a list, got {type(loc_map['lines']).__name__}")
            elif not all(isinstance(ln, int) for ln in loc_map["lines"]):
                errors.append(f"{loc_prefix}: 'lines' must contain only integers")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments (``argv`` defaults to ``sys.argv[1:]``)."""
    parser = argparse.ArgumentParser(description="Coverage justification processor")
    parser.add_argument(
        "--yaml",
        type=Path,
        required=True,
        help="Path to coverage_justifications.yaml",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Root directory of source files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for resolved justification manifest (JSON)",
    )
    parser.add_argument(
        "--file-filter",
        type=str,
        default="cpp,h,hpp,cc,rs",
        help="Comma-separated file extensions to scan (default: cpp,h,hpp,cc,rs)",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        choices=sorted(VALID_PLATFORMS),
        help="Target platform for filtering justifications (default: all platforms apply)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
