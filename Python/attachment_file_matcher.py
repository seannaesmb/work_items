#!/usr/bin/env python3
"""
attachment_matcher.py

Matches OpenProject ticket numbers (main sheet's first column) against
rows in an attachments table (matched via container_id), and writes the
verified attachment location into repeated "Attachment" header columns
(one column per attachment, for tickets with more than one).

OPTIONS
-------
Required:
  --main FILE            Main migration sheet (.csv or .xlsx). Column A must be
                         the OpenProject ticket number. Existing columns whose
                         header starts with "Attachment" are reused; more are
                         added when a ticket has more attachments.
  --attachments FILE     Attachments table (.csv or .xlsx) with a header row
                         containing: id, container_id, container_type, filename
                         (header names are case-insensitive). An optional
                         disk_filename column is used first when present.
  --root DIR             Attachment root on disk, laid out as
                         <root>/<id>/<filename>   e.g. root/38/archive.zip
                         Quote it if it contains spaces. Under native Windows
                         Python, /cygdrive/<letter>/... paths are converted to
                         C:\\... automatically.
  --out FILE             Output file (.csv or .xlsx, chosen by extension).
                         A report of failures is written beside it as
                         <out>_unresolved.csv.

Optional:
  --container-type TYPE  Only use attachment rows with this container_type.
                         Default: WorkPackage. Pass '' to disable filtering.
  --prefix TEXT          Text written before <id>/<filename> in each Attachment
                         cell (a trailing "/" is added if missing). Only the
                         cell value changes; files are still verified on disk
                         using --root. Example:
                         --prefix "file:///var/atlassian/application-data/shared-home/data/attachments/file/"
  --encode               Percent-encode the <id>/<filename> part of the cell
                         (space -> %20, etc.). Use with URL-style prefixes if
                         Jira has trouble with special characters.
  -h, --help             Show the option summary and exit.

HOW A FILENAME IS MATCHED (first hit wins)
------------------------------------------
  1. disk_filename column (if the attachments table has one)
  2. exact name (whitespace/Unicode normalized, case-insensitive)
  3. URL-decoded name
  4. OpenProject/CarrierWave rename: characters other than letters, digits,
     "." "-" "+" become "_"  (e.g. "My Report (v2).pdf" -> "My_Report__v2_.pdf")
  5. Loose match: ignores case, spaces, underscores and punctuation/dash
     variants; accepted only if exactly one file in the folder fits.
Matches from steps 4-5 are printed as NOTE lines on stderr.

UNRESOLVED REPORT (<out>_unresolved.csv)
----------------------------------------
Columns: ticket, id, filename_in_sheet, filename_repr (hidden characters shown),
reason, detail, suggested_path. Reasons:
  SUBFOLDER_MISSING  no <id> folder under --root
  FOLDER_EMPTY       folder exists but has no files
  NAME_MISMATCH      folder exists, name differs (see suggested_path)
  FILE_MISSING       folder has other files, none resemble the name
Suggested paths are never applied to the output automatically.

OUTPUT NOTES
------------
  - .xlsx output: illegal control characters are stripped and cells over
    32,767 characters are truncated (reported on stderr). Use a .csv --out
    to avoid any truncation.
  - Numeric IDs stored as floats in Excel (3688.0) are normalized to 3688.

EXAMPLES
--------
  python attachment_matcher.py \\
      --main main_sheet.csv \\
      --attachments attachments.csv \\
      --root "/cygdrive/c/Users/me/Downloads/file transfer/opt/openproject/files/attachment/file" \\
      --out output.csv \\
      --prefix "file:///var/atlassian/application-data/shared-home/data/attachments/file/"

  # Plain relative paths (no prefix), xlsx in/out, no container_type filter
  python attachment_matcher.py --main main.xlsx --attachments attachments.xlsx \\
      --root /opt/openproject/files/attachment/file --out out.xlsx --container-type ''
"""

import argparse
import csv
import difflib
import os
import re
import sys
import unicodedata
from urllib.parse import quote, unquote

import pandas as pd

# Excel hard limits
EXCEL_MAX_CELL_CHARS = 32767
# Control characters openpyxl/Excel cannot store in a cell (keeps tab/newline/CR)
ILLEGAL_XLSX_CHARS_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)


def clean_id_str(val):
    """Normalize a value that should be a plain integer-like ID string.
    Fixes the common pandas/openpyxl gotcha where a whole number stored
    as a float in Excel (e.g. 3688) round-trips through dtype=str as
    "3688.0" instead of "3688"."""
    s = str(val).strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s


CYGDRIVE_RE = re.compile(r"^/cygdrive/([a-zA-Z])(/.*)?$")


def to_native_path(path):
    """If running under native Windows Python and given a Cygwin-style
    /cygdrive/<letter>/... path, convert it to a native Windows path
    (C:\\...) so os.path/os.scandir can actually resolve it. No-op on
    any other combination (Cygwin's own Python handles /cygdrive/ fine
    natively, and non-Windows platforms won't see this pattern)."""
    if os.name != "nt":
        return path
    m = CYGDRIVE_RE.match(path)
    if not m:
        return path
    drive = m.group(1).upper()
    rest = (m.group(2) or "").replace("/", "\\")
    converted = f"{drive}:{rest}" if rest else f"{drive}:\\"
    print(f"NOTE: converted Cygwin-style path '{path}' -> '{converted}' "
          f"(native Windows Python detected)", file=sys.stderr)
    return converted


# ---------------------------------------------------------------------------
# I/O helpers (CSV / XLSX interchangeable)
# ---------------------------------------------------------------------------

def sanitize_for_xlsx(df):
    """Strip characters Excel/openpyxl cannot store, and truncate any
    cell exceeding Excel's per-cell character limit. Returns the
    cleaned DataFrame and a list of (row, col, reason) notes for
    anything that was altered."""
    notes = []
    cleaned = df.copy()
    for col in cleaned.columns:
        for idx in cleaned.index:
            val = cleaned.at[idx, col]
            if not isinstance(val, str) or val == "":
                continue
            new_val = val
            if ILLEGAL_XLSX_CHARS_RE.search(new_val):
                new_val = ILLEGAL_XLSX_CHARS_RE.sub("", new_val)
                notes.append((idx, col, "removed illegal control character(s)"))
            if len(new_val) > EXCEL_MAX_CELL_CHARS:
                new_val = new_val[:EXCEL_MAX_CELL_CHARS]
                notes.append((idx, col, f"truncated to {EXCEL_MAX_CELL_CHARS} chars"))
            if new_val != val:
                cleaned.at[idx, col] = new_val
    return cleaned, notes

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
        cleaned, notes = sanitize_for_xlsx(df)
        if notes:
            print(
                f"\n{len(notes)} cell(s) had to be sanitized for Excel "
                f"compatibility (illegal characters and/or the 32,767-char "
                f"cell limit):",
                file=sys.stderr,
            )
            for row_idx, col, reason in notes[:20]:
                print(f"  - row {row_idx + 2}, column '{col}': {reason}", file=sys.stderr)
            if len(notes) > 20:
                print(f"  ...and {len(notes) - 20} more", file=sys.stderr)
        cleaned.to_excel(path, index=False)
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


def diagnose_missing_path(path):
    """Walk up from `path` to find the deepest ancestor that actually
    exists, and list what's really in it -- helps pinpoint exactly
    which path segment is wrong (hidden character, typo, wrong drive
    mapping, etc.) instead of a flat 'does not exist'."""
    p = os.path.normpath(path)
    drive, _ = os.path.splitdrive(p)
    current = p
    while current and current != drive and not os.path.isdir(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    print(f"  Full path requested : {path!r}", file=sys.stderr)
    if current and os.path.isdir(current):
        print(f"  Deepest existing dir: {current!r}", file=sys.stderr)
        try:
            entries = sorted(os.listdir(current))
        except OSError as e:
            print(f"  (could not list it: {e})", file=sys.stderr)
            return
        missing_next = path[len(current):].lstrip("/\\").split(os.sep, 1)
        wanted = missing_next[0] if missing_next and missing_next[0] else "(nothing further)"
        print(f"  Next segment wanted : {wanted!r}", file=sys.stderr)
        print(f"  Actually present ({len(entries)} entries, first 20):", file=sys.stderr)
        for e in entries[:20]:
            print(f"    - {e!r}", file=sys.stderr)
    else:
        print("  Not even the drive/root of this path could be found.", file=sys.stderr)


def build_disk_index(attachment_root):
    """Walk <root>/<id>/<filename>. Returns (index, folder_files):
      index        {(id_str, normalized_lower_filename): actual_relative_path}
      folder_files {id_str: [actual filenames in that subfolder]}
    """
    index = {}
    folder_files = {}
    if not os.path.isdir(attachment_root):
        print(f"WARNING: attachment root does not exist: {attachment_root}", file=sys.stderr)
        diagnose_missing_path(attachment_root)
        return index, folder_files

    for entry in os.scandir(attachment_root):
        if not entry.is_dir():
            continue
        subfolder = entry.name.strip()  # this is the "id"
        folder_files.setdefault(subfolder, [])
        for f in os.scandir(entry.path):
            if not f.is_file():
                continue
            folder_files[subfolder].append(f.name)
            fname_norm = normalize_name(f.name)
            key = (subfolder, fname_norm.lower())
            rel_path = f"{entry.name}/{f.name}"
            if key in index and index[key] != rel_path:
                print(
                    f"WARNING: case-insensitive collision on disk: "
                    f"'{index[key]}' vs '{rel_path}'",
                    file=sys.stderr,
                )
            index[key] = rel_path
    return index, folder_files


# ---------------------------------------------------------------------------
# Core matching logic
# ---------------------------------------------------------------------------

def load_attachment_lookup(att_df, container_type_filter=None):
    """Build container_id -> [(id, filename, disk_filename), ...] from the
    attachments table. Header match is case-insensitive. disk_filename is
    optional (used first when the export includes OpenProject's
    disk_filename column)."""
    col_map = {c.lower(): c for c in att_df.columns}
    required = ["id", "container_id", "filename"]
    missing = [r for r in required if r not in col_map]
    if missing:
        raise ValueError(f"attachments table missing required column(s): {missing}")

    has_type_col = "container_type" in col_map
    has_disk_col = "disk_filename" in col_map

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

        container_id = clean_id_str(container_id)
        att_id = clean_id_str(att_id)
        filename = str(filename).strip()
        disk_filename = str(row[col_map["disk_filename"]]).strip() if has_disk_col else ""
        lookup.setdefault(container_id, []).append((att_id, filename, disk_filename))
    return lookup


# OpenProject stores files via CarrierWave, which rewrites any character
# outside [word . - +] to "_" in the on-disk name (spaces, parentheses,
# brackets, commas, '&', '#', etc.). So "My Report (v2).pdf" is usually
# stored as "My_Report__v2_.pdf".
CARRIERWAVE_BAD_CHARS_RE = re.compile(r"[^\w.\-+]", re.UNICODE)


def carrierwave_sanitize(name):
    return CARRIERWAVE_BAD_CHARS_RE.sub("_", name)


def loose_key(name):
    """Compare names ignoring case, spacing, underscores, and all
    punctuation/dash variants (en/em dash, nbsp, doubled spaces, etc.)."""
    n = unicodedata.normalize("NFKC", str(name))
    return re.sub(r"[\W_]+", "", n, flags=re.UNICODE).lower()


def resolve_paths(ticket, pairs, disk_index, folder_files, unresolved_rows):
    """pairs: list of (id, filename, disk_filename). Returns verified
    relative paths that exist on disk. Anything unresolved is appended to
    unresolved_rows as a dict with a reason and a suggested fix."""
    resolved = []
    for att_id, raw_filename, disk_filename in pairs:
        candidates = []
        if disk_filename:
            candidates.append(("disk_filename column", disk_filename))
        candidates.append(("exact (normalized)", raw_filename))
        candidates.append(("url-decoded", normalize_name(raw_filename, from_url=True)))
        candidates.append(("special chars -> '_' (OpenProject/CarrierWave rename)",
                           carrierwave_sanitize(normalize_name(raw_filename))))

        hit = None
        for how, cand in candidates:
            key = (att_id, normalize_name(cand).lower())
            if key in disk_index:
                hit = (how, disk_index[key])
                break
        if hit:
            resolved.append(hit[1])
            if hit[0] not in ("exact (normalized)", "disk_filename column"):
                print(f"NOTE: ticket {ticket}: '{att_id}/{raw_filename}' matched via "
                      f"{hit[0]} -> {hit[1]}", file=sys.stderr)
            continue

        # ---- fallback: same name once spacing/punctuation differences are ignored ----
        if att_id in folder_files:
            want = loose_key(raw_filename)
            same = [a for a in folder_files[att_id] if loose_key(a) == want]
            if len(same) == 1:
                path = f"{att_id}/{same[0]}"
                resolved.append(path)
                print(f"NOTE: ticket {ticket}: '{att_id}/{raw_filename}' matched loosely "
                      f"(punctuation/spacing ignored) -> {path}", file=sys.stderr)
                continue

        # ---- unresolved: work out why and suggest what to change ----
        if att_id not in folder_files:
            reason = "SUBFOLDER_MISSING"
            detail = f"no folder named '{att_id}' under the attachment root"
            suggestion = ""
        else:
            actual = folder_files[att_id]
            if not actual:
                reason = "FOLDER_EMPTY"
                detail = f"folder '{att_id}' exists but contains no files"
                suggestion = ""
            else:
                target = carrierwave_sanitize(normalize_name(raw_filename)).lower()
                close = difflib.get_close_matches(
                    target, [a.lower() for a in actual], n=1, cutoff=0.6)
                if len(actual) == 1:
                    reason = "NAME_MISMATCH"
                    detail = f"folder has 1 file: '{actual[0]}' (sheet says '{raw_filename}')"
                    suggestion = f"{att_id}/{actual[0]}"
                elif close:
                    best = next(a for a in actual if a.lower() == close[0])
                    reason = "NAME_MISMATCH"
                    detail = f"closest file in folder: '{best}'"
                    suggestion = f"{att_id}/{best}"
                else:
                    reason = "FILE_MISSING"
                    detail = (f"folder '{att_id}' has {len(actual)} file(s), none resemble "
                              f"'{raw_filename}': {actual[:5]}")
                    suggestion = ""
        unresolved_rows.append({
            "ticket": ticket, "id": att_id, "filename_in_sheet": raw_filename,
            "filename_repr": ascii(raw_filename),
            "reason": reason, "detail": detail, "suggested_path": suggestion,
        })
    return resolved


def process(main_path, attachments_path, attachment_root, out_path, container_type,
            prefix="", encode=False):
    disk_index, folder_files = build_disk_index(attachment_root)
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

    unresolved_rows = []
    matched_tickets = 0
    max_needed = len(existing_attachment_cols)

    # First pass: figure out the max number of resolved attachments any
    # single row needs, so we can pre-create enough columns.
    per_row_resolved = {}
    for idx, row in main_df.iterrows():
        issue_key = clean_id_str(row[issue_col])
        if issue_key == "" or issue_key == "nan":
            continue
        pairs = attachment_lookup.get(issue_key, [])
        if not pairs:
            continue
        resolved = resolve_paths(issue_key, pairs, disk_index, folder_files, unresolved_rows)
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
            cell = quote(path, safe="/") if encode else path
            main_df.at[idx, existing_attachment_cols[i]] = f"{prefix}{cell}"

    write_table(main_df, out_path)
    print(f"Matched attachments for {matched_tickets} ticket(s). Wrote {out_path}")

    if unresolved_rows:
        report_path = os.path.splitext(out_path)[0] + "_unresolved.csv"
        fields = ["ticket", "id", "filename_in_sheet", "filename_repr", "reason", "detail", "suggested_path"]
        with open(report_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(unresolved_rows)

        counts = {}
        for r in unresolved_rows:
            counts[r["reason"]] = counts.get(r["reason"], 0) + 1
        print(f"\n{len(unresolved_rows)} attachment(s) could not be verified on disk under {attachment_root}")
        print(f"Full per-attachment report (with reasons + suggested paths): {report_path}")
        meaning = {
            "SUBFOLDER_MISSING": "the <id> folder isn't on disk (file never exported/copied, or wrong root)",
            "FOLDER_EMPTY": "folder exists but is empty (file missing from the copy)",
            "NAME_MISMATCH": "folder exists, name differs -> see suggested_path column",
            "FILE_MISSING": "folder has other files, none resemble the name",
        }
        for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {n:6d}  {reason}: {meaning.get(reason, '')}")
        print("\nFirst 10 examples:")
        for r in unresolved_rows[:10]:
            print(f"  ticket {r['ticket']} | {r['id']}/{r['filename_in_sheet']} | {r['reason']} | {r['detail']}")


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--main", required=True, help="Main migration sheet (.csv or .xlsx), col A = ticket number")
    parser.add_argument("--attachments", required=True, help="Attachments table (.csv or .xlsx) with id/container_id/container_type/filename columns")
    parser.add_argument("--root", required=True, help="Attachment root dir, laid out as <root>/<id>/<filename>")
    parser.add_argument("--out", required=True, help="Output path (.csv or .xlsx)")
    parser.add_argument("--container-type", default="WorkPackage", help="Filter attachments to this container_type (default: WorkPackage). Pass '' to disable filtering.")
    parser.add_argument("--prefix", default="", help="Text written before <id>/<filename> in each Attachment cell, e.g. file:///var/atlassian/application-data/shared-home/data/attachments/file/")
    parser.add_argument("--encode", action="store_true", help="Percent-encode the <id>/<filename> part (spaces -> %%20 etc.) for URL-style prefixes")
    args = parser.parse_args()

    args.main = to_native_path(args.main)
    args.attachments = to_native_path(args.attachments)
    args.root = to_native_path(args.root)
    args.out = to_native_path(args.out)

    container_type = args.container_type if args.container_type else None
    prefix = args.prefix
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    process(args.main, args.attachments, args.root, args.out, container_type,
            prefix=prefix, encode=args.encode)


if __name__ == "__main__":
    main()