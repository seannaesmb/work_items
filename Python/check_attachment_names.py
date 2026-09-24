import os
import re
import unicodedata
from collections import Counter, defaultdict
from urllib.parse import quote, quote_plus
import pandas as pd
# ---------------- settings ----------------

INPUT = "C:\\projects\\sbrown\\Python\\db_file_exports\\20260922\\attachments_non_ascii.xlsx"        # col A = ID, col C = filename
OUTPUT = "C:\\projects\\sbrown\\Python\\db_file_exports\\20260922\\attachment_adjustments.csv"
PREFIX = "opt/openproject/files/attachment/file"   # set to "" for just ID/name
BASE_DIR = None   # e.g. r"C:\path\to\unzipped" to also check files exist; None to skip
HEADER = 0         # 0 if row 1 is a header row, None if there is no header
ID_COL, NAME_COL = 0, 3   # column A and column D
# ------------------------------------------


INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
ODD_SPACES = re.compile("[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")
CONTROL = re.compile("[\x01-\x1f\x7f]")  # \x00 (NUL) handled separately as a hard error
SHELL_CHARS = set(" $`'\"&;|<>()!*?[]{}~#^")
PARTS = [p for p in PREFIX.split("/") if p]
 
 
def clean_name(raw):
    """Apply safe, reversible conversions; return (cleaned_name, list_of_conversions).
    Conversions prefixed 'ERROR:' or 'WARNING:' are NOT applied to the name -- they
    flag something the caller must handle explicitly rather than silently fix."""
    converted, name = [], raw
    hard_flags = []
 
    if "\x00" in name:
        hard_flags.append("ERROR: NUL byte in original filename")
 
    # Check for a '/' that isn't just a Windows-path leftover before we strip separators.
    # We treat backslash as a separator first; anything left with a '/' before the final
    # segment suggests a real embedded slash rather than a stray path prefix.
    normalized_seps = name.replace("\\", "/")
    if "/" in normalized_seps.rsplit("/", 1)[0] if "/" in normalized_seps else False:
        hard_flags.append("WARNING: '/' inside filename truncated a path segment -- check source data")
 
    def step(new, label):
        nonlocal name
        if new != name:
            converted.append(label)
            name = new
 
    step(INVISIBLE.sub("", name), "removed invisible characters")
    step(ODD_SPACES.sub(" ", name), "non-breaking/odd spaces -> space")
    step(CONTROL.sub(" ", name), "control characters/newlines -> space")
    step(name.replace("\\", "/").split("/")[-1], "path separators removed")
    step(unicodedata.normalize("NFC", name), "unicode normalized (NFC)")
    step(name.strip(), "trimmed leading/trailing spaces")
    return name, converted, hard_flags
 
 
def check_name(name):
    """Return (errors, flags). Errors will fail; flags are informational."""
    errors, flags = [], []
    if not name:
        return ["empty filename"], flags
    if name in (".", ".."):
        errors.append("reserved name")
    if len(name.encode("utf-8")) > 255:
        errors.append("over 255 bytes (Linux limit)")
    if name.startswith("."):
        flags.append("leading dot (hidden file)")
    if name.startswith("-"):
        flags.append("leading dash (looks like an option in shell)")
    if name.endswith("."):
        flags.append("trailing dot")
    ext = os.path.splitext(name)[1]
    if not ext:
        flags.append("no extension")
    elif ext != ext.lower():
        flags.append("uppercase extension")
    if "  " in name:
        flags.append("consecutive spaces")
    if any(c in SHELL_CHARS for c in name):
        flags.append("needs quoting in shell")
    if "," in name or '"' in name:
        flags.append("comma/quote: CSV field must be quoted")
    if quote(name, safe="") != name:
        flags.append("needs URL encoding")
    if "+" in name:
        flags.append("contains literal '+' (ambiguous if server decodes + as space)")
    if not name.isascii():
        flags.append("non-ASCII characters")
    return errors, flags
 
 
_listing_cache = {}
 
def listing(folder):
    if folder not in _listing_cache:
        _listing_cache[folder] = os.listdir(folder) if os.path.isdir(folder) else None
    return _listing_cache[folder]
 
 
def match_on_disk(id_, candidates):
    folder = os.path.join(BASE_DIR, *PARTS, id_)
    names = listing(folder)
    if names is None:
        return None, "folder missing"
    nameset = set(names)
    for c in candidates:
        if c in nameset:
            return c, "exact"
    norm = lambda s: unicodedata.normalize("NFC", s).strip()
    for c in candidates:
        for n in names:
            if norm(n) == norm(c):
                return n, "matched after unicode/whitespace normalization"
    for c in candidates:
        for n in names:
            if norm(n).casefold() == norm(c).casefold():
                return n, "matched case-insensitively"
    return None, "file not found"
 
 
df = pd.read_excel(INPUT, dtype=str, header=HEADER).fillna("")
if df.shape[1] <= max(ID_COL, NAME_COL):
    raise SystemExit("Sheet has fewer columns than expected")
if BASE_DIR and not os.path.isdir(BASE_DIR):
    raise SystemExit(f"BASE_DIR not found: {BASE_DIR}")
 
first_row = 2 if HEADER is not None else 1
rows = []
 
for i, r in df.iterrows():
    raw_id, raw_name = r.iloc[ID_COL], r.iloc[NAME_COL]
    if not raw_id.strip() and not raw_name.strip():
        continue  # fully blank row
 
    converted, errors = [], []
 
    # ---- ID checks ----
    id_ = raw_id.strip()
    if id_ != raw_id:
        converted.append("ID trimmed")
    m = re.fullmatch(r"(\d+)\.0+", id_)
    if m:
        id_ = m.group(1)
        converted.append("ID '.0' suffix removed")
    if not re.fullmatch(r"\d+", id_):
        errors.append("ID missing or not numeric")
 
    # ---- filename conversions ----
    final, conv, hard_flags = clean_name(raw_name)
    converted += conv
    errors += hard_flags  # NUL bytes / embedded slashes are errors, not silent fixes
 
    # ---- optional on-disk verification ----
    disk = ""
    if BASE_DIR and id_.isdigit() and final:
        found, disk = match_on_disk(id_, list(dict.fromkeys([raw_name, final])))
        if found is None:
            errors.append(disk)
        elif found != final:
            converted.append("using actual on-disk name")
            final = found
 
    name_errors, flags = check_name(final)
    errors += name_errors
 
    ok_path = bool(id_.isdigit() and final)
    unix_path = "/".join(PARTS + [id_, final]) if ok_path else ""
    if unix_path and len(unix_path.encode("utf-8")) > 4096:
        errors.append("total path over 4096 bytes")
 
    rows.append({
        "sheet_row": i + first_row,
        "id": id_,
        "cell_value": raw_name,
        "final_name": final,
        "unix_path": unix_path,
        "url_encoded_path": "/".join(PARTS + [id_, quote(final, safe="")]) if ok_path else "",
        "url_plus_path": "/".join(PARTS + [id_, quote_plus(final)]) if ok_path else "",
        "status": "ERROR" if errors else ("CONVERTED" if converted else "OK"),
        "errors": "; ".join(errors),
        "converted": "; ".join(converted),
        "flags": "; ".join(flags),
        "disk_match": disk,
    })
 
# ---- duplicate checks across rows ----
exact, folded = defaultdict(list), defaultdict(set)
for idx, row in enumerate(rows):
    if row["id"] and row["final_name"]:
        exact[(row["id"], row["final_name"])].append(idx)
        folded[(row["id"], row["final_name"].casefold())].add(row["final_name"])
 
def add_flag(row, text):
    row["flags"] = (row["flags"] + "; " if row["flags"] else "") + text
 
for idxs in exact.values():
    if len(idxs) > 1:
        for idx in idxs:
            add_flag(rows[idx], "duplicate row (same ID and filename)")
for (id_, _), variants in folded.items():
    if len(variants) > 1:
        for idx, row in enumerate(rows):
            if row["id"] == id_ and row["final_name"] in variants:
                add_flag(row, "case-only name collision in same folder")
 
out = pd.DataFrame(rows)
out.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
 
# ---- summary ----
print(f"{len(out)} rows written to {OUTPUT}")
print(out["status"].value_counts().to_string())
tally = Counter()
for col in ("errors", "converted", "flags"):
    for cell in out[col]:
        tally.update(x for x in cell.split("; ") if x)
print("\nIssue counts:")
for k, v in tally.most_common():
    print(f"  {v:6}  {k}")
 