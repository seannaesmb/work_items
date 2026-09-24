#!/usr/bin/env python3
"""
attachment_matcher.py

Matches issue numbers (first column of the main migration sheet) against
an attachments sheet (matched via column B), and writes the resolved
on-disk relative path into repeated "Attachment" header columns
(one column per match, e.g. multiple attachments for the same issue).

Every path written is normalized and verified against what actually
exists on disk under ATTACHMENT_ROOT, so the values Jira's CSV importer
receives are guaranteed to resolve.

Usage:
    python attachment_matcher.py \
        --main main_sheet.xlsx \
        --attachments attachments_sheet.xlsx \
        --root /path/to/attachment/root \
        --out output.xlsx
"""

import argparse
import os
import sys
import unicodedata
from urllib.parse import unquote

import openpyxl
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_name(name: str, from_url: bool = False) -> str:
    """Normalize a filename/path for reliable cross-platform comparison.

    - Optionally URL-decodes (%20 -> space) if the value came from a URL
      or REST API response.
    - Converts backslashes to forward slashes (Windows-exported sheets).
    - Strips leading/trailing whitespace (common invisible sheet artifact).
    - Normalizes Unicode to NFC (macOS NFD vs Linux/Jira NFC mismatch).
    """
    if name is None:
        return ""
    name = str(name)
    if from_url:
        name = unquote(name)
    name = name.replace("\\", "/")
    name = name.strip()
    name = unicodedata.normalize("NFC", name)
    return name


def build_disk_index(attachment_root: str) -> dict:
    """Walk the attachment root and build a lookup of
    normalized-lowercased relative path -> actual on-disk relative path.

    Using the real on-disk name (not the sheet's version) guarantees
    correct case for Jira's case-sensitive importer.
    """
    index = {}
    for root, _, files in os.walk(attachment_root):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), attachment_root)
            rel = normalize_name(rel)
            key = rel.lower()
            if key in index and index[key] != rel:
                print(
                    f"WARNING: case-insensitive collision on disk: "
                    f"'{index[key]}' vs '{rel}'",
                    file=sys.stderr,
                )
            index[key] = rel
    return index


# ---------------------------------------------------------------------------
# Core matching logic
# ---------------------------------------------------------------------------

def load_attachment_lookup(attachments_ws) -> dict:
    """Build issue-number -> [raw attachment filenames] from the
    attachments sheet. Assumes column A = issue number/id, column B =
    attachment filename, one row per attachment (so an issue with 3
    attachments appears across 3 rows)."""
    lookup = {}
    for row in attachments_ws.iter_rows(min_row=2, values_only=True):
        if row is None or len(row) < 2:
            continue
        issue_key, filename = row[0], row[1]
        if issue_key is None or filename is None:
            continue
        issue_key = str(issue_key).strip()
        lookup.setdefault(issue_key, []).append(str(filename))
    return lookup


def resolve_paths(raw_filenames, disk_index, unresolved_log):
    """Given a list of raw filenames from the sheet, return the
    resolved, verified on-disk relative paths. Anything that doesn't
    match is recorded in unresolved_log and skipped."""
    resolved = []
    for raw in raw_filenames:
        normalized = normalize_name(raw)
        key = normalized.lower()
        if key in disk_index:
            resolved.append(disk_index[key])
        else:
            # retry treating it as URL-encoded, in case it came from
            # a REST export
            url_normalized = normalize_name(raw, from_url=True)
            url_key = url_normalized.lower()
            if url_key in disk_index:
                resolved.append(disk_index[url_key])
            else:
                unresolved_log.append(raw)
    return resolved


def process(main_path, attachments_path, attachment_root, out_path):
    disk_index = build_disk_index(attachment_root)
    print(f"Indexed {len(disk_index)} files under {attachment_root}")

    att_wb = openpyxl.load_workbook(attachments_path, data_only=True)
    att_ws = att_wb.active
    attachment_lookup = load_attachment_lookup(att_ws)

    main_wb = openpyxl.load_workbook(main_path)
    main_ws = main_wb.active

    # Find existing "Attachment" header columns, or determine where to
    # start writing new ones.
    header_row = 1
    existing_attachment_cols = []
    max_col = main_ws.max_column
    for col_idx in range(1, max_col + 1):
        header_val = main_ws.cell(row=header_row, column=col_idx).value
        if header_val and str(header_val).strip().lower().startswith("attachment"):
            existing_attachment_cols.append(col_idx)

    next_new_col = max_col + 1
    unresolved_log = []
    max_attachments_seen = len(existing_attachment_cols)

    for row_idx in range(2, main_ws.max_row + 1):
        issue_key = main_ws.cell(row=row_idx, column=1).value
        if issue_key is None:
            continue
        issue_key = str(issue_key).strip()

        raw_filenames = attachment_lookup.get(issue_key, [])
        if not raw_filenames:
            continue

        resolved = resolve_paths(raw_filenames, disk_index, unresolved_log)

        # Ensure we have enough "Attachment" columns for this row's count
        while len(existing_attachment_cols) < len(resolved):
            new_col = next_new_col
            next_new_col += 1
            existing_attachment_cols.append(new_col)
            main_ws.cell(row=header_row, column=new_col, value="Attachment")

        max_attachments_seen = max(max_attachments_seen, len(resolved))

        for i, path in enumerate(resolved):
            col = existing_attachment_cols[i]
            main_ws.cell(row=row_idx, column=col, value=path)

    main_wb.save(out_path)
    print(f"Wrote {out_path}")

    if unresolved_log:
        print(
            f"\n{len(unresolved_log)} filename(s) could not be resolved "
            f"against {attachment_root}:",
            file=sys.stderr,
        )
        for name in unresolved_log:
            print(f"  - {name}", file=sys.stderr)


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", required=True, help="Main migration sheet (.xlsx)")
    parser.add_argument("--attachments", required=True, help="Attachments sheet (.xlsx), col A=issue key, col B=filename")
    parser.add_argument("--root", required=True, help="Root directory of actual attachment files on disk")
    parser.add_argument("--out", required=True, help="Output .xlsx path")
    args = parser.parse_args()

    process(args.main, args.attachments, args.root, args.out)


if __name__ == "__main__":
    main()