#!/usr/bin/env python3
"""
cklb_to_ckl.py — Batch convert STIG .cklb (JSON) files to .ckl (XML) format.
Field mapping based on the official CKLB JSON schema (STIG Viewer 3).

Usage:
    python3 cklb_to_ckl.py <directory> [-r] [--dry-run]
"""

import argparse
import json
import os
import sys
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


def indent_xml(elem):
    raw = tostring(elem, encoding="unicode")
    reparsed = minidom.parseString(raw)
    return reparsed.toprettyxml(indent="    ", encoding=None)


def map_status(status: str) -> str:
    """Map CKLB status enum to CKL STATUS values."""
    return {
        "not_reviewed":   "Not_Reviewed",
        "not_applicable": "Not_Applicable",
        "open":           "Open",
        "not_a_finding":  "NotAFinding",
    }.get((status or "").lower(), "Not_Reviewed")


def get_severity_override(rule: dict) -> tuple[str, str]:
    """
    Extract severity override value and justification from the overrides block.
    overrides = { "severity": { "new_value": "high", "reason": "..." } }
    """
    overrides = rule.get("overrides") or {}
    sev_block = overrides.get("severity") or {}
    # the overridden value is any key that isn't 'reason'
    value = ""
    reason = sev_block.get("reason", "")
    for k, v in sev_block.items():
        if k != "reason":
            value = v
            break
    return value, reason


def build_ckl(data: dict) -> Element:
    checklist = Element("CHECKLIST")

    # ── ASSET ──────────────────────────────────────────────────────────────
    asset_node = SubElement(checklist, "ASSET")
    td = data.get("target_data") or {}

    def af(tag, value):
        el = SubElement(asset_node, tag)
        el.text = str(value) if value is not None else ""

    af("ROLE",            td.get("role", "None"))
    af("ASSET_TYPE",      td.get("target_type", "Computing"))
    af("HOST_NAME",       td.get("host_name", ""))
    af("HOST_IP",         td.get("ip_address", ""))
    af("HOST_MAC",        td.get("mac_address", ""))
    af("HOST_GUID",       "")
    af("HOST_FQDN",       td.get("fqdn", ""))
    af("TECH_AREA",       td.get("technology_area", ""))
    af("TARGET_KEY",      "")          # populated per-rule from rule.target_key
    af("WEB_OR_DATABASE", str(td.get("is_web_database", False)).lower())
    af("WEB_DB_SITE",     td.get("web_db_site", ""))
    af("WEB_DB_INSTANCE", td.get("web_db_instance", ""))

    # ── STIGS ──────────────────────────────────────────────────────────────
    stigs_node = SubElement(checklist, "STIGS")

    for stig in (data.get("stigs") or []):
        istig = SubElement(stigs_node, "iSTIG")

        # STIG_INFO — fields taken directly from stig-level schema properties
        stig_info = SubElement(istig, "STIG_INFO")

        def si(name, value):
            sid = SubElement(stig_info, "SI_DATA")
            SubElement(sid, "SID_NAME").text = name
            SubElement(sid, "SID_DATA").text = str(value) if value is not None else ""

        si("version",       "")         # not in cklb schema; left blank
        si("classification","UNCLASSIFIED")
        si("customname",    "")
        si("stigid",        stig.get("stig_id", ""))
        si("description",   "")         # not in cklb stig-level schema
        si("filename",      data.get("title", ""))
        si("releaseinfo",   stig.get("release_info", ""))
        si("title",         stig.get("stig_name", stig.get("display_name", "")))
        si("uuid",          stig.get("uuid", ""))
        si("notice",        "")
        si("source",        "")

        # VULN entries
        for rule in (stig.get("rules") or []):
            vuln = SubElement(istig, "VULN")

            def sd(attr, value):
                s = SubElement(vuln, "STIG_DATA")
                SubElement(s, "VULN_ATTRIBUTE").text = attr
                SubElement(s, "ATTRIBUTE_DATA").text = str(value) if value is not None else ""

            # Build STIGRef from stig-level fields (matches SV2 format)
            stig_ref = rule.get("stig_ref") or \
                       f"{stig.get('stig_name', '')} :: {stig.get('release_info', '')}"

            legacy_ids = rule.get("legacy_ids") or []
            ccis       = rule.get("ccis") or []

            sd("Vuln_Num",           rule.get("group_id", ""))
            sd("Severity",           rule.get("severity", "medium"))
            sd("Group_Title",        (rule.get("group_tree") or [{}])[0].get("title") or rule.get("group_title", ""))
            sd("Rule_ID",            rule.get("rule_id_src", rule.get("rule_id", "")))
            sd("Rule_Ver",           rule.get("rule_version", ""))
            sd("Rule_Title",         rule.get("rule_title", ""))
            sd("Vuln_Discuss",       rule.get("discussion", ""))
            sd("IA_Controls",        rule.get("ia_controls", ""))
            sd("Check_Content",      rule.get("check_content") or "")
            sd("Fix_Text",           rule.get("fix_text", ""))
            sd("False_Positives",    rule.get("false_positives", ""))
            sd("False_Negatives",    rule.get("false_negatives", ""))
            sd("Documentable",       rule.get("documentable", "false"))
            sd("Mitigations",        rule.get("mitigations", ""))
            sd("Potential_Impact",   rule.get("potential_impacts", ""))
            sd("Third_Party_Tools",  rule.get("third_party_tools", ""))
            sd("Mitigation_Control", rule.get("mitigation_control", ""))
            sd("Responsibility",     rule.get("responsibility", ""))
            sd("Security_Override_Guidance", rule.get("security_override_guidance", ""))

            ccr = rule.get("check_content_ref") or {}
            sd("Check_Content_Ref",  ccr.get("href", "") if isinstance(ccr, dict) else "")
            sd("Weight",             rule.get("weight", "10.0"))
            sd("Class",              rule.get("classification", "Unclass"))
            sd("STIGRef",            stig_ref)
            sd("TargetKey",          rule.get("reference_identifier") or rule.get("target_key") or stig.get("reference_identifier") or "")
            sd("STIG_UUID",          rule.get("stig_uuid", stig.get("uuid", "")))

            # LEGACY_ID — schema defines as array; CKL expects two STIG_DATA blocks
            sd("LEGACY_ID", legacy_ids[0] if len(legacy_ids) > 0 else "")
            sd("LEGACY_ID", legacy_ids[1] if len(legacy_ids) > 1 else "")

            # CCI_REF — one STIG_DATA block per CCI
            for cci in ccis:
                sd("CCI_REF", cci)

            # Severity override from overrides block
            sev_val, sev_reason = get_severity_override(rule)

            SubElement(vuln, "STATUS").text                  = map_status(rule.get("status"))
            SubElement(vuln, "FINDING_DETAILS").text         = rule.get("finding_details", "")
            SubElement(vuln, "COMMENTS").text                = rule.get("comments", "")
            SubElement(vuln, "SEVERITY_OVERRIDE").text       = sev_val
            SubElement(vuln, "SEVERITY_JUSTIFICATION").text  = sev_reason

    return checklist


def convert_file(src: str, dst: str) -> None:
    with open(src, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    root = build_ckl(data)
    xml_str = indent_xml(root)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(xml_str)


def main():
    parser = argparse.ArgumentParser(
        description="Batch-convert STIG .cklb (JSON) files to .ckl (XML) format."
    )
    parser.add_argument("directory", help="A .cklb file or a directory containing .cklb files")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Recurse into subdirectories")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be converted without writing files")
    args = parser.parse_args()

    target = args.directory  # may be a file or directory

    # ── Single file ────────────────────────────────────────────────────────
    if os.path.isfile(target):
        if not target.lower().endswith(".cklb"):
            print(f"ERROR: '{target}' is not a .cklb file.", file=sys.stderr)
            sys.exit(1)
        dst = os.path.splitext(target)[0] + ".ckl"
        if args.dry_run:
            print(f"[dry-run] {target}  →  {dst}")
            sys.exit(0)
        try:
            convert_file(target, dst)
            print(f"  OK  {target}  →  {dst}")
        except Exception as exc:
            print(f"  ERR {target}: {exc}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    # ── Directory ──────────────────────────────────────────────────────────
    if not os.path.isdir(target):
        print(f"ERROR: '{target}' is not a file or directory.", file=sys.stderr)
        sys.exit(1)

    if args.recursive:
        cklb_files = [
            os.path.join(dp, fn)
            for dp, _, files in os.walk(target)
            for fn in files if fn.lower().endswith(".cklb")
        ]
    else:
        cklb_files = [
            os.path.join(target, fn)
            for fn in os.listdir(target)
            if fn.lower().endswith(".cklb")
        ]

    if not cklb_files:
        print("No .cklb files found.")
        sys.exit(0)

    converted, errors = 0, 0

    for src in sorted(cklb_files):
        dst = os.path.splitext(src)[0] + ".ckl"
        if args.dry_run:
            print(f"[dry-run] {src}  →  {dst}")
            continue
        try:
            convert_file(src, dst)
            print(f"  OK  {src}  →  {dst}")
            converted += 1
        except Exception as exc:
            print(f"  ERR {src}: {exc}", file=sys.stderr)
            errors += 1

    if not args.dry_run:
        print(f"\nDone: {converted} converted, {errors} error(s).")


if __name__ == "__main__":
    main()