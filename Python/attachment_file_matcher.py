#!/usr/bin/env python3
"""
attachment_matcher.py

Matches OpenProject ticket numbers (main sheet's first column) against
rows in an attachments table (matched via container_id), and writes the
resolved on-disk relative path into repeated "Attachment" header
columns (one column per match, for tickets with multiple attachments).

Accepts .csv or .xlsx for BOTH --main and --attachments (auto-detected
by file extension, can be mixed). --out is written as .csv or .xlsx
based on its extension.

attachments table schema (header row required):
    id            - subfolder name under the attachment root
    container_id  - OpenProject ticket number (matches main sheet col A)
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
        --attachments attachments.csv \
        --root /path/to/opt/openproject/files/attachment/file \
        --out output.csv \
        --container-type WorkPackage
"""

import argparse
import os
import sys
import unicodedata
from urllib.parse import unquote

import pandas as pd


# ---------------------------------------------------------------------------
# I/O helpers (CSV / XLSX interchangeable)
# ---------------------------------------------------------------------------

def read_table(path):
    """Read a .csv or .xlsx file into a DataFrame of strings, preserving
    column order and treating missing cells as empty strings (not NaN)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str)
        df = df.fillna("")
    else:
        raise ValueError(f"Unsupported file type: {path} (expected .csv or .xlsx)")
    # normalize headers to stripped strings, keep original for output
    df.columns = [str(c).strip() for c in df.columns]
    return df


def write_table(df, path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df.to_csv(path, index=False)
    elif ext in (".xlsx", ".xls"):
        df.to_excel(path, index=False)
    else:
        raise ValueError(f"Unsupported output type: {path} (expected .csv or .xlsx)")


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
    by walking the attachment root, laid out as <root>/<id>/<filename>.
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

def load_attachment_lookup(att_df, container_type_filter=None):
    """Build container_id -> [(id, filename), ...] from the attachments
    table. Header match is case-insensitive."""
    col_map = {c.lower(): c for c in att_df.columns}
    required = ["id", "container_id", "filename"]
    missing = [r for r in required if r not in col_map]
    if missing:
        raise ValueError(f"attachments table missing required column(s): {missing}")

    has_type_col = "container_type" in col_map

    lookup = {}
    for _, row in att_df.iterrows():
        att_id = row[col_map["id"]]
        container_id = row[col_map["container_id"]]
        filename = row[col_map["filename"]]
        if att_id == "" or container_id == "" or filename == "":
            continue

        if container_type_filter and has_type_col:
            ctype = row[col_map["container_type"]]
            if str(ctype).strip() != container_type_filter:
                continue

        container_id = str(container_id).strip()
        att_id = str(att_id).strip()
        filename = str(filename).strip()
        lookup.setdefault(container_id, []).append((att_id, filename))
    return lookup


def resolve_paths(pairs, disk_index, unresolved_log):
    """pairs: list of (id, filename). Returns verified relative paths
    that actually exist on disk under root/<id>/<filename>."""
    resolved = []
    for att_id, raw_filename in pairs:
        fname_norm = normalize_name(raw_filename)
        key = (att_id, fname_norm.lower())
        if key in disk_index:
            resolved.append(disk_index[key])
            continue

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

    att_df = read_table(attachments_path)
    attachment_lookup = load_attachment_lookup(att_df, container_type_filter=container_type)
    print(f"Loaded {sum(len(v) for v in attachment_lookup.values())} attachment rows "
          f"across {len(attachment_lookup)} tickets"
          + (f" (filtered to container_type='{container_type}')" if container_type else ""))

    main_df = read_table(main_path)
    if main_df.shape[1] == 0:
        raise ValueError("Main sheet has no columns")

    issue_col = main_df.columns[0]

    existing_attachment_cols = [c for c in main_df.columns if c.lower().startswith("attachment")]

    unresolved_log = []
    matched_tickets = 0
    max_needed = len(existing_attachment_cols)

    # First pass: figure out the max number of resolved attachments any
    # single row needs, so we can pre-create enough columns.
    per_row_resolved = {}
    for idx, row in main_df.iterrows():
        issue_key = str(row[issue_col]).strip()
        if issue_key == "":
            continue
        pairs = attachment_lookup.get(issue_key, [])
        if not pairs:
            continue
        resolved = resolve_paths(pairs, disk_index, unresolved_log)
        if resolved:
            per_row_resolved[idx] = resolved
            max_needed = max(max_needed, len(resolved))
            matched_tickets += 1

    # Add extra "Attachment" columns if needed
    while len(existing_attachment_cols) < max_needed:
        new_col_name = "Attachment" if not existing_attachment_cols else f"Attachment.{len(existing_attachment_cols)}"
        # avoid collisions if that name somehow already exists
        while new_col_name in main_df.columns:
            new_col_name += "_"
        main_df[new_col_name] = ""
        existing_attachment_cols.append(new_col_name)

    for idx, resolved in per_row_resolved.items():
        for i, path in enumerate(resolved):
            main_df.at[idx, existing_attachment_cols[i]] = path

    write_table(main_df, out_path)
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
    parser.add_argument("--main", required=True, help="Main migration sheet (.csv or .xlsx), col A = ticket number")
    parser.add_argument("--attachments", required=True, help="Attachments table (.csv or .xlsx) with id/container_id/container_type/filename columns")
    parser.add_argument("--root", required=True, help="Attachment root dir, laid out as <root>/<id>/<filename>")
    parser.add_argument("--out", required=True, help="Output path (.csv or .xlsx)")
    parser.add_argument("--container-type", default="WorkPackage", help="Filter attachments to this container_type (default: WorkPackage). Pass '' to disable filtering.")
    args = parser.parse_args()

    container_type = args.container_type if args.container_type else None
    process(args.main, args.attachments, args.root, args.out, container_type)


if __name__ == "__main__":
    main()