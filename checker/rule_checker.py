"""
rule_checker.py
----------------
Deterministic, rule-based network fault checker. NO AI involved -- every
check here is plain pattern matching against known signatures of common
network problems. This exists as an independent "second opinion" alongside
the AI diagnosis: if the AI hallucinates or misses something obvious, this
script should still catch it (and vice versa -- it won't catch everything
the AI can reason about).

Usage:
    python rule_checker.py                    # runs against ../cases/cases.csv
    python rule_checker.py path/to/other.csv   # runs against a different file
"""

import csv
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Individual rule checks
# ---------------------------------------------------------------------------
# Each rule is a small, independent function. It takes the case's combined
# evidence text (symptom + topology_note + show_output, all lowercased) and
# returns either None (rule did not fire) or a short string describing what
# it found. Keeping each rule separate makes it easy to add more later
# without touching the others.

def check_duplicate_ip(text):
    if "ip address conflict" in text or ("conflict" in text and "ip" in text):
        return "Possible duplicate/conflicting IP address detected."
    return None


def check_interface_down_or_errdisabled(text):
    if "err-disabled" in text or "errdisabled" in text:
        return "Interface is error-disabled (often port security or loop-related)."
    if "administratively down" in text or re.search(r"\binterface\b.*\bdown\b", text):
        return "An interface appears to be down."
    return None


def check_duplex_mismatch(text):
    if "half-duplex" in text and (
        "full-duplex" in text or "collision" in text or "late collisions" in text
    ):
        return "Possible duplex mismatch (half-duplex reported alongside full-duplex/collision evidence)."
    return None


def check_subnet_mask_issue(text):
    if re.search(r"(incorrect|wrong|mismatched)\s+(subnet\s+)?mask", text):
        return "Subnet mask misconfiguration detected."
    masks = re.findall(r"255(?:\.\d{1,3}){3}", text)
    if len(masks) >= 2 and len(set(masks)) > 1:
        return f"Multiple differing subnet masks found in evidence: {sorted(set(masks))}."
    return None


def check_gateway_mismatch(text):
    if re.search(
        r"(gateway\s+mismatch|wrong\s+gateway|incorrect\s+default[- ]gateway|wrong\s+default[- ]gateway)",
        text,
    ):
        return "Default gateway misconfiguration/mismatch detected."
    return None


def check_native_vlan_mismatch(text):
    natives = re.findall(r"native vlan[:\s]+(\d+)", text)
    if len(natives) >= 2 and len(set(natives)) > 1:
        return f"Native VLAN mismatch detected across trunk ends: {sorted(set(natives))}."
    return None


def check_mtu_mismatch(text):
    mtus = re.findall(r"mtu[:\s]+(\d{3,4})", text)
    if len(mtus) >= 2 and len(set(mtus)) > 1:
        return f"MTU mismatch detected between interfaces: {sorted(set(mtus))}."
    return None


def check_vtp_revision_overwrite(text):
    if "revision number" in text and ("higher" in text or "overwrit" in text):
        return "Possible VTP revision number overwrite (VLAN database may have been wiped)."
    return None


def check_dhcp_relay_missing(text):
    # Kept strict: only fires on evidence specifically about ip helper-address,
    # not on generic "DHCP failed" symptoms (see check_dhcp_no_address_received
    # below). Previously this also fired on any APIPA/169.254 mention, which
    # over-triggered on unrelated DHCP failures like scope exhaustion (C021).
    if "helper-address" in text and (
        "no ip helper" in text or "does not" in text or "missing" in text
    ):
        return "DHCP relay (ip helper-address) appears to be missing on this VLAN interface."
    return None


def check_dhcp_no_address_received(text):
    # Generic signal that DHCP failed for *some* reason -- doesn't say why.
    # Meant to be read alongside other DHCP-related rule hits, not alone.
    if "apipa" in text or "169.254" in text:
        return "Device has an APIPA address -- DHCP failed for some reason (see other DHCP rule hits for cause)."
    return None


def check_dhcp_scope_exhaustion(text):
    match = re.search(r"addresses in use[:\s]+(\d+)\s*/\s*(\d+)", text)
    if match and match.group(1) == match.group(2):
        return "DHCP scope appears fully exhausted (in-use count equals total)."
    if "dhcpnak" in text or "no addresses available" in text:
        return "DHCP server reported no addresses available."
    return None


def check_nat_exhaustion(text):
    if "near limit" in text or "translations near limit" in text:
        return "NAT/PAT translation table is near or at its limit."
    return None


def check_missing_vlan(text):
    # Tightened from a plain "both keywords exist anywhere" check, which
    # produced a false positive on C002 (matched "VLAN 30" ... "preempt not
    # configured" as if they were related, when they weren't).  Now requires
    # "vlan <number>" and "not configured" to appear close together, in that
    # order, describing the same thing.
    if "does not list vlan" in text:
        return "A referenced VLAN does not appear to be configured on this switch."
    if re.search(r"vlan\s+\d+[^.]{0,40}not configured", text):
        return "A referenced VLAN does not appear to be configured on this switch."
    return None


def check_missing_route(text):
    # Tightened after adding C035: the generic "no entry for" phrase also
    # matched unrelated ARP-table evidence ("no entry for 10.10.6.99" on a
    # gateway-mismatch case), which has nothing to do with a missing route.
    # Now "no entry for" only counts if the word "rout" (route/router/
    # routing) appears nearby, tying it back to an actual routing context.
    if "no directly connected route" in text or re.search(r"\bno\s+route\b", text):
        return "Routing table appears to be missing an expected route."
    if re.search(r"no\s+entry for[^.]{0,60}\brout", text):
        return "Routing table appears to be missing an expected route."
    return None


def check_acl_order_risk(text):
    # Rewritten: the original version compared the position of the FIRST
    # "permit" anywhere in the text against the first "deny", which missed
    # cases with several earlier, unrelated permits (e.g. C016, where permit
    # icmp/80/443 appear before the problem deny, hiding it from that check).
    # What actually matters is whether a specific deny sits before the
    # catch-all "permit ip any any" at the end of the ACL -- that's the
    # pattern that silently blocks traffic the catch-all was meant to allow.
    catchall = re.search(r"permit\s+ip\s+any\s+any", text)
    if not catchall:
        return None
    denies_before = [
        m.group(0) for m in re.finditer(r"deny\s+\w+[^,]{0,30}", text)
        if m.start() < catchall.start()
    ]
    if denies_before:
        return (
            "Specific deny rule(s) found before the general/catch-all permit "
            f"-- verify these are intentional: {denies_before}."
        )
    return None


def check_ospf_neighbor_stuck(text):
    if re.search(r"\b(exstart|exchange)\b", text) and "full" not in text:
        return "OSPF neighbor appears stuck before reaching FULL state."
    return None


def check_eigrp_as_mismatch(text):
    as_numbers = re.findall(r"eigrp\s+(\d+)", text)
    if len(as_numbers) >= 2 and len(set(as_numbers)) > 1:
        return f"EIGRP AS number mismatch detected: {sorted(set(as_numbers))}."
    return None


def check_radius_timeout(text):
    if "radius" in text and "timeout" in text:
        return "RADIUS server timeout detected -- may cause repeated wireless re-authentication."
    return None


def check_rogue_ap(text):
    if "unrecognized ssid" in text or "rogue" in text:
        return "Unrecognized/rogue wireless access point detected nearby."
    return None


# Registry of all checks. Add new rule functions here to include them in a run.
RULES = [
    check_duplicate_ip,
    check_subnet_mask_issue,
    check_gateway_mismatch,
    check_interface_down_or_errdisabled,
    check_duplex_mismatch,
    check_native_vlan_mismatch,
    check_mtu_mismatch,
    check_vtp_revision_overwrite,
    check_dhcp_relay_missing,
    check_dhcp_no_address_received,
    check_dhcp_scope_exhaustion,
    check_nat_exhaustion,
    check_missing_vlan,
    check_missing_route,
    check_acl_order_risk,
    check_ospf_neighbor_stuck,
    check_eigrp_as_mismatch,
    check_radius_timeout,
    check_rogue_ap,
]


# ---------------------------------------------------------------------------
# Running the rules against a case
# ---------------------------------------------------------------------------

def build_evidence_text(case):
    """Combine every field we have evidence in, lowercased, into one blob."""
    fields = [
        case.get("symptom", ""),
        case.get("topology_note", ""),
        case.get("show_output", ""),
    ]
    return " ".join(fields).lower()


def check_case(case):
    """Run every rule against one case dict. Returns a list of finding strings."""
    text = build_evidence_text(case)
    findings = []
    for rule in RULES:
        result = rule(text)
        if result:
            findings.append(f"[{rule.__name__}] {result}")
    return findings


# ---------------------------------------------------------------------------
# Loading cases and producing a report
# ---------------------------------------------------------------------------

def load_cases(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def run_report(csv_path):
    cases = load_cases(csv_path)
    lines = []
    fired_count = 0
    for case in cases:
        findings = check_case(case)
        case_id = case.get("case_id", "UNKNOWN")
        expected = case.get("expected_fault", "")
        lines.append(f"=== {case_id} ===")
        lines.append(f"Expected fault (ground truth): {expected}")
        if findings:
            fired_count += 1
            for f_ in findings:
                lines.append(f"  RULE HIT: {f_}")
        else:
            lines.append("  No deterministic rule fired for this case.")
        lines.append("")
    lines.append(f"Summary: {fired_count}/{len(cases)} cases triggered at least one rule.")
    return "\n".join(lines)


if __name__ == "__main__":
    default_path = Path(__file__).resolve().parent.parent / "cases" / "cases.csv"
    csv_path = sys.argv[1] if len(sys.argv) > 1 else default_path
    print(run_report(csv_path))
