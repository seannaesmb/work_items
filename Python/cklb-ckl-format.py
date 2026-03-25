#!/usr/bin/env python3
"""
cklb_to_ckl.py - Convert STIG Viewer 3.x .cklb (JSON) files to .ckl (XML) format

Usage:
    python cklb_to_ckl.py input.cklb
    python cklb_to_ckl.py input.cklb -o output.ckl
    python cklb_to_ckl.py *.cklb
    python cklb_to_ckl.py /path/to/folder/
    python cklb_to_ckl.py /path/to/folder/ -d /path/to/output/
"""

import json
import argparse
import sys
import os
import glob
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


# ---------------------------------------------------------------------------
# Status mapping  (cklb -> ckl)
# ---------------------------------------------------------------------------
STATUS_MAP = {
    "not_a_finding":  "NotAFinding",
    "notafinding":    "NotAFinding",
    "open":           "Open",
    "fail":           "Open",
    "not_applicable": "Not_Applicable",
    "not_reviewed":   "Not_Reviewed",
    "pass":           "NotAFinding",
    # Already-correct ckl values passed through unchanged
    "NotAFinding":    "NotAFinding",
    "Open":           "Open",
    "Not_Applicable": "Not_Applicable",
    "Not_Reviewed":   "Not_Reviewed",
}

def map_status(value):
    if not value:
        return "Not_Reviewed"
    return STATUS_MAP.get(str(value).strip(), "Not_Reviewed")


def s(value, default=""):
    """Safe string conversion."""
    if value is None:
        return default
    return str(value)


# ---------------------------------------------------------------------------
# ASSET block
# ---------------------------------------------------------------------------
def build_asset(root, target):
    asset = SubElement(root, "ASSET")

    def ae(tag, text):
        e = SubElement(asset, tag)
        e.text = text

    ae("ROLE",            s(target.get("role", "None")))
    ae("ASSET_TYPE",      s(target.get("asset_type", s(target.get("type", "Computing")))))
    ae("HOST_NAME",       s(target.get("host_name", "")))
    ae("HOST_IP",         s(target.get("host_ip", "")))
    ae("HOST_MAC",        s(target.get("host_mac", "")))
    ae("HOST_FQDN",       s(target.get("host_fqdn", "")))
    ae("TECH_AREA",       s(target.get("tech_area", "")))
    ae("TARGET_KEY",      s(target.get("target_key", "")))
    # cklb uses is_web_database; older versions used web_or_database
    web = target.get("is_web_database", target.get("web_or_database", False))
    ae("WEB_OR_DATABASE", "true" if web else "false")
    ae("WEB_DB_SITE",     s(target.get("web_db_site", "")))
    ae("WEB_DB_INSTANCE", s(target.get("web_db_instance", "")))


# ---------------------------------------------------------------------------
# STIG_INFO block
# ---------------------------------------------------------------------------
def build_stig_info(istig_el, stig):
    """
    cklb stores stig metadata as flat fields on the stig object.
    ckl wraps each in <SI_DATA><SID_NAME>...<SID_DATA>...
    """
    stig_info_el = SubElement(istig_el, "STIG_INFO")

    def si(sid_name, value):
        e = SubElement(stig_info_el, "SI_DATA")
        n = SubElement(e, "SID_NAME")
        n.text = sid_name
        d = SubElement(e, "SID_DATA")
        d.text = s(value)

    # Parse version out of release_info if a standalone version field is absent
    release_info = s(stig.get("release_info", ""))
    version = s(stig.get("version", ""))
    if not version and "Version:" in release_info:
        try:
            version = release_info.split("Version:")[1].split()[0]
        except Exception:
            version = ""

    si("version",        version)
    si("classification", stig.get("classification", "Unclassified"))
    si("customname",     stig.get("customname", stig.get("display_name", "")))
    si("stigid",         stig.get("stig_id", ""))
    si("description",    stig.get("description", ""))
    si("filename",       stig.get("filename", stig.get("stig_name", "")))
    si("releaseinfo",    release_info)
    si("title",          stig.get("title", stig.get("display_name", stig.get("stig_name", ""))))
    si("uuid",           stig.get("uuid", ""))
    si("notice",         stig.get("notice", ""))
    si("source",         stig.get("source", ""))


# ---------------------------------------------------------------------------
# VULN block
# ---------------------------------------------------------------------------
def build_vuln(istig_el, rule):
    vuln_el = SubElement(istig_el, "VULN")

    def sd(attr, value):
        """Add a STIG_DATA child."""
        e = SubElement(vuln_el, "STIG_DATA")
        va = SubElement(e, "VULN_ATTRIBUTE")
        va.text = attr
        ad = SubElement(e, "ATTRIBUTE_DATA")
        ad.text = s(value)

    # --- Vuln_Num: rule_id (bare ID, e.g. SV9900340r879522) ---
    sd("Vuln_Num",    rule.get("rule_id", ""))

    # --- Severity ---
    sd("Severity",    rule.get("severity", ""))

    # --- Group_Title ---
    # group_tree is a list; fall back to group_title string
    group_tree = rule.get("group_tree", [])
    if group_tree and isinstance(group_tree, list):
        group_title = group_tree[0].get("title", "") if group_tree else ""
    else:
        group_title = s(rule.get("group_title", ""))
    # Prefer explicit group_title field if present
    group_title = s(rule.get("group_title", group_title))
    sd("Group_Title", group_title)

    # --- Rule_ID: rule_id_src (full rule ID with _rule suffix) ---
    sd("Rule_ID",     rule.get("rule_id_src", s(rule.get("rule_id", "")) + "_rule"))

    # --- Rule_Ver: rule_version (STIG rule version / STIG ref) ---
    sd("Rule_Ver",    rule.get("rule_version", rule.get("rule_ver", "")))

    # --- Rule_Title ---
    sd("Rule_Title",  rule.get("rule_title", rule.get("title", "")))

    # --- Vuln_Discuss ---
    sd("Vuln_Discuss", rule.get("vuln_discuss", rule.get("discussion", "")))

    # --- IA_Controls ---
    sd("IA_Controls", rule.get("ia_controls", ""))

    # --- Check_Content ---
    sd("Check_Content", rule.get("check_content", rule.get("check", "")))

    # --- Fix_Text ---
    sd("Fix_Text",    rule.get("fix_text", rule.get("fix", "")))

    # --- Misc STIG_DATA fields ---
    sd("False_Positives",   rule.get("false_positives", ""))
    sd("False_Negatives",   rule.get("false_negatives", ""))
    sd("Documentable",      s(rule.get("documentable", "false")) or "false")
    sd("Mitigations",       rule.get("mitigations", ""))
    sd("Potential_Impact",  rule.get("potential_impact", ""))
    sd("Third_Party_Tools", rule.get("third_party_tools", ""))
    sd("Mitigation_Control", rule.get("mitigation_control", ""))
    sd("Responsibility",    rule.get("responsibility", ""))
    sd("Security_Override_Guidance", rule.get("security_override_guidance", ""))
    sd("Check_Content_Ref", rule.get("check_content_ref", ""))
    sd("Weight",            s(rule.get("weight", "")))
    sd("Class",             rule.get("classification", "Unclassified"))
    sd("STIGRef",           rule.get("stig_ref", ""))
    sd("TargetKey",         rule.get("target_key", ""))
    sd("STIG_UUID",         rule.get("stig_uuid", ""))

    # LEGACY_ID and CCI_REF may be lists or strings
    legacy = rule.get("legacy_ids", rule.get("legacy_id", ""))
    if isinstance(legacy, list):
        legacy = ", ".join(legacy)
    sd("LEGACY_ID", legacy)

    cci = rule.get("cci_ref", rule.get("cci", ""))
    if isinstance(cci, list):
        cci = ", ".join(cci)
    sd("CCI_REF", cci)

    # --- Finding fields ---
    # Handle severity_override from overrides dict or direct field
    overrides = rule.get("overrides", {})
    sev_override = ""
    sev_just = ""
    if isinstance(overrides, dict) and overrides:
        # overrides may contain {old_severity: new_severity} or similar
        sev_override = s(overrides.get("severity_override",
                         overrides.get("new_severity", "")))
        sev_just = s(overrides.get("severity_justification",
                     overrides.get("justification", "")))
    else:
        sev_override = s(rule.get("severity_override", ""))
        sev_just = s(rule.get("severity_justification", ""))

    status_el = SubElement(vuln_el, "STATUS")
    status_el.text = map_status(rule.get("status"))

    fd_el = SubElement(vuln_el, "FINDING_DETAILS")
    fd_el.text = s(rule.get("finding_details", ""))

    cm_el = SubElement(vuln_el, "COMMENTS")
    cm_el.text = s(rule.get("comments", ""))

    so_el = SubElement(vuln_el, "SEVERITY_OVERRIDE")
    so_el.text = sev_override

    sj_el = SubElement(vuln_el, "SEVERITY_JUSTIFICATION")
    sj_el.text = sev_just


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------
def cklb_to_ckl(cklb_path, ckl_path):
    with open(cklb_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    root = Element("CHECKLIST")

    # ASSET
    target = data.get("target_data", {})
    build_asset(root, target)

    # STIGS
    stigs_el = SubElement(root, "STIGS")
    for stig in data.get("stigs", []):
        istig = SubElement(stigs_el, "iSTIG")
        build_stig_info(istig, stig)
        for rule in stig.get("rules", []):
            build_vuln(istig, rule)

    # Serialize
    raw_xml = tostring(root, encoding="unicode")
    pretty = minidom.parseString(raw_xml).toprettyxml(indent="  ")

    # Strip the extra XML declaration minidom prepends
    lines = pretty.splitlines()
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]

    with open(ckl_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("<!--DISA STIG Viewer :: 2.x-->\n")
        f.write("\n".join(lines))

    print(f"  [OK]  {cklb_path}  ->  {ckl_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def resolve_inputs(inputs):
    files = []
    for pattern in inputs:
        if os.path.isdir(pattern):
            found = glob.glob(os.path.join(pattern, "**", "*.cklb"), recursive=True)
            if not found:
                print(f"  [WARN] No .cklb files found in: {pattern}")
            files.extend(found)
        else:
            expanded = glob.glob(pattern)
            if not expanded:
                print(f"  [WARN] No files matched: {pattern}")
            files.extend(expanded)
    return sorted(set(files))


def main():
    parser = argparse.ArgumentParser(
        description="Convert STIG Viewer 3.x .cklb (JSON) files to .ckl (XML)."
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT",
                        help=".cklb file(s), glob(s), or folder(s)")
    parser.add_argument("-o", "--output", metavar="FILE",
                        help="Output .ckl path (single-file mode only)")
    parser.add_argument("-d", "--outdir", metavar="DIR",
                        help="Directory for output files (default: same as input)")
    args = parser.parse_args()

    input_files = resolve_inputs(args.inputs)
    if not input_files:
        print("No .cklb files found. Nothing to convert.")
        sys.exit(1)

    if args.output and len(input_files) > 1:
        print("Error: -o/--output can only be used with a single input file.")
        sys.exit(1)

    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)

    print(f"Converting {len(input_files)} file(s)...\n")
    errors = []

    for cklb_path in input_files:
        try:
            if args.output:
                ckl_path = args.output
            else:
                base = os.path.splitext(cklb_path)[0]
                if args.outdir:
                    base = os.path.join(args.outdir, os.path.basename(base))
                ckl_path = base + ".ckl"
            cklb_to_ckl(cklb_path, ckl_path)
        except json.JSONDecodeError as e:
            msg = f"  [ERROR] {cklb_path}: Invalid JSON — {e}"
            print(msg); errors.append(msg)
        except Exception as e:
            msg = f"  [ERROR] {cklb_path}: {e}"
            print(msg); errors.append(msg)

    print(f"\nDone. {len(input_files) - len(errors)} succeeded, {len(errors)} failed.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()