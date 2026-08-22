"""
Deterministic rule-based checker for common network config mistakes.
No AI involved -- pure Python logic.

Checks to implement:
- duplicate IPs
- wrong subnet mask
- gateway mismatch
- interface down
- missing VLAN
- missing route
"""

def check_case(case: dict) -> list:
    """Return a list of rule-violation findings for a given case."""
    findings = []
    # TODO: implement checks
    return findings


if __name__ == "__main__":
    pass
