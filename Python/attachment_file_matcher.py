#!/usr/bin/env python3
"""
attachment_matcher.py

Matches OpenProject ticket numbers (main sheet's issue column) against
rows in attachments.xlsx (matched via container_id), and writes the
resolved on-disk relative path into repeated "Attachment" header
columns (one column per match, for tickets with multiple attachments).

attachments.xlsx schema:
    id            - subfolder name under the attachment root
    container_id  - OpenProject ticket number (matches main sheet)
    container_type- e.g. "WorkPackage" (filterable; others ignored by default)
    filename      - the file's actual name inside that subfolder

On-disk layout:
    <ATTACHMENT_ROOT>/<id>/<filename>
    e.g. root/38/archive.zip

Every path is verified against what actually exists on disk (case,
whitespace, and Unicode-normalized) before being written, so the
values Jira's importer receives are guaranteed to resolve.

Usage:
    python attachment_matcher.py \
        --main main_sheet.xlsx \
        --attachments attachments.xlsx \
        --root /path/to/opt/openproject/files/attachment/file \
        --out output.xlsx \
        --container-type WorkPackage
"""

import argparse
import os
import sys
import unicodedata
from urllib.parse import unquote

import openpyxl


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_name(name, from_url=False):
    """Normalize a filename/path for reliable cross-platform comparison."""
    if name is None:
        return ""
    name = str(name)
    if from_url:
        name = unquote(name)
    name = name.replace("\\", "/")
    name = name.strip()
    name = unicodedata.normalize("NFC", name)
    return name


def build_disk_index(attachment_root):
    """Build {(id_str, normalized_lower_filename): actual_relative_path}
    by walking the attachment root, which is expected to be laid out as
    <root>/<id>/<filename>.
    """
    index = {}
    if not os.path.isdir(attachment_root):
        print(f"WARNING: attachment root does not exist: {attachment_root}", file=sys.stderr)
        return index

    for entry in os.scandir(attachment_root):
        if not entry.is_dir():
            continue
        subfolder = entry.name  # this is the "id"
        for f in os.scandir(entry.path):
            if not f.is_file():
                continue
            fname_norm = normalize_name(f.name)
            key = (subfolder.strip(), fname_norm.lower())
            rel_path = f"{subfolder}/{f.name}"
            if key in index and index[key] != rel_path:
                print(
                    f"WARNING: case-insensitive collision on disk: "
                    f"'{index[key]}' vs '{rel_path}'",
                    file=sys.stderr,
                )
            index[key] = rel_path
    return index


# ---------------------------------------------------------------------------
# Core matching logic
# ---------------------------------------------------------------------------

def load_attachment_lookup(attachments_ws, container_type_filter=None):
    """Build container_id -> [(id, filename), ...] from attachments.xlsx.

    Assumes header row 1 with columns: id, container_id, container_type,
    filename (case-insensitive header match, order-independent).
    """
    headers = {}
    header_row = next(attachments_ws.iter_rows(min_row=1, max_row=1, values_only=True))
    for idx, h in enumerate(header_row):
        if h is not None:
            headers[str(h).strip().lower()] = idx

    required = ["id", "container_id", "filename"]
    missing = [r for r in required if r not in headers]
    if missing:
        raise ValueError(f"attachments sheet missing required column(s): {missing}")

    has_type_col = "container_type" in headers

    lookup = {}
    for row in attachments_ws.iter_rows(min_row=2, values_only=True):
        if row is None:
            continue
        att_id = row[headers["id"]]
        container_id = row[headers["container_id"]]
        filename = row[headers["filename"]]
        if att_id is None or container_id is None or filename is None:
            continue

        if container_type_filter and has_type_col:
            ctype = row[headers["container_type"]]
            if ctype is None or str(ctype).strip() != container_type_filter:
                continue

        container_id = str(container_id).strip()
        att_id = str(att_id).strip()
        filename = str(filename).strip()
        lookup.setdefault(container_id, []).append((att_id, filename))
    return lookup


def resolve_paths(pairs, disk_index, unresolved_log):
    """pairs: list of (id, filename). Returns list of verified relative
    paths that actually exist on disk under root/<id>/<filename>."""
    resolved = []
    for att_id, raw_filename in pairs:
        fname_norm = normalize_name(raw_filename)
        key = (att_id, fname_norm.lower())
        if key in disk_index:
            resolved.append(disk_index[key])
            continue

        # retry with URL-decoding in case filename came from a REST export
        url_norm = normalize_name(raw_filename, from_url=True)
        url_key = (att_id, url_norm.lower())
        if url_key in disk_index:
            resolved.append(disk_index[url_key])
            continue

        unresolved_log.append(f"{att_id}/{raw_filename}")
    return resolved


def process(main_path, attachments_path, attachment_root, out_path, container_type):
    disk_index = build_disk_index(attachment_root)
    print(f"Indexed {len(disk_index)} files under {attachment_root}")

    att_wb = openpyxl.load_workbook(attachments_path, data_only=True)
    att_ws = att_wb.active
    attachment_lookup = load_attachment_lookup(att_ws, container_type_filter=container_type)
    print(f"Loaded {sum(len(v) for v in attachment_lookup.values())} attachment rows "
          f"across {len(attachment_lookup)} tickets"
          + (f" (filtered to container_type='{container_type}')" if container_type else ""))

    main_wb = openpyxl.load_workbook(main_path)
    main_ws = main_wb.active

    header_row = 1
    existing_attachment_cols = []
    max_col = main_ws.max_column
    for col_idx in range(1, max_col + 1):
        header_val = main_ws.cell(row=header_row, column=col_idx).value
        if header_val and str(header_val).strip().lower().startswith("attachment"):
            existing_attachment_cols.append(col_idx)

    next_new_col = max_col + 1
    unresolved_log = []
    matched_tickets = 0

    for row_idx in range(2, main_ws.max_row + 1):
        issue_key = main_ws.cell(row=row_idx, column=1).value
        if issue_key is None:
            continue
        issue_key = str(issue_key).strip()

        pairs = attachment_lookup.get(issue_key, [])
        if not pairs:
            continue

        resolved = resolve_paths(pairs, disk_index, unresolved_log)
        if not resolved:
            continue

        matched_tickets += 1

        while len(existing_attachment_cols) < len(resolved):
            new_col = next_new_col
            next_new_col += 1
            existing_attachment_cols.append(new_col)
            main_ws.cell(row=header_row, column=new_col, value="Attachment")

        for i, path in enumerate(resolved):
            col = existing_attachment_cols[i]
            main_ws.cell(row=row_idx, column=col, value=path)

    main_wb.save(out_path)
    print(f"Matched attachments for {matched_tickets} ticket(s). Wrote {out_path}")

    if unresolved_log:
        print(
            f"\n{len(unresolved_log)} attachment(s) could not be verified on disk "
            f"under {attachment_root}:",
            file=sys.stderr,
        )
        for name in unresolved_log:
            print(f"  - {name}", file=sys.stderr)


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--main", required=True, help="Main migration sheet (.xlsx), col A = ticket number")
    parser.add_argument("--attachments", required=True, help="attachments.xlsx with id/container_id/container_type/filename columns")
    parser.add_argument("--root", required=True, help="Attachment root dir, laid out as <root>/<id>/<filename>")
    parser.add_argument("--out", required=True, help="Output .xlsx path")
    parser.add_argument("--container-type", default="WorkPackage", help="Filter attachments to this container_type (default: WorkPackage). Pass '' to disable filtering.")
    args = parser.parse_args()

    container_type = args.container_type if args.container_type else None
    process(args.main, args.attachments, args.root, args.out, container_type)


if __name__ == "__main__":
    main()