# Responsible AI Log

Document at least 5 cases where the AI's diagnosis was wrong and a human
corrected it. For each: what the AI said, what was actually true, and why
the AI likely got it wrong.

This log reflects the second full review pass, run after `cases.csv` was
rewritten so `show_output` fields contain realistic Cisco CLI-style
evidence instead of narrated English conclusions (see project history).
The first review pass (against the old, narrated evidence) found only
3 real failures + 2 borderline cases out of 35, a ~91% accuracy rate that
turned out to be inflated because the evidence was effectively spelling
out the answer. This review, run against harder evidence and checked at
the level of individual evidence claims (not just final conclusions),
found 4 outright wrong diagnoses and 7 correct-but-partially-unsupported
diagnoses out of 35 -- 24 clean Accepts (~69%), 7 Edited (~20%), 4 Rejected
(~11%).

---

## Case 1 — C001 (STP / bridging loop)
- **AI said:** A physical layer issue or speed/duplex mismatch on link
  Fa0/2 is causing excessive collisions and link instability, which
  repeatedly triggers Spanning Tree Topology Change Notifications (TCNs).
- **Actual root cause:** A redundant link between two switches was added
  without EtherChannel, creating a genuine Layer 2 loop; STP is
  reacting correctly to a real loop, not to a flaky physical link.
- **Why AI was wrong:** Both explanations produce the same visible
  symptom (frequent STP topology changes), so the AI pattern-matched to
  the more common textbook cause (duplex mismatch) rather than checking
  for a second/redundant physical path between the same two switches,
  which the evidence actually pointed to. This is a case where two
  different-layer problems share one symptom, and the AI picked the
  wrong one.

## Case 2 — C002 (HSRP failover)
- **AI said:** R1 is load-sharing (ECMP) default route traffic between
  its own WAN link and R2, or R2 is still advertising a default route
  despite its WAN link being down.
- **Actual root cause:** HSRP failover to the backup router (R2) never
  happened as designed, because R2's HSRP configuration is missing
  `preempt`. Traffic that lands on R2 (whose own WAN link is down) has
  nowhere to go and is silently dropped.
- **Why AI was wrong:** The AI reasoned about routing-table mechanics
  (ECMP, route advertisement) instead of first-hop redundancy protocol
  behavior (HSRP state and preempt config), even though the evidence
  was framed around a first-hop redundancy scenario. It missed the more
  specific, protocol-level cause in favor of a more generic routing
  explanation.

## Case 3 — C006 (Routing instability)
- **AI said:** The router is load-balancing traffic to 172.16.0.0/24
  across two different next hops because both a static route and an
  OSPF route are concurrently installed in the routing table.
- **Actual root cause:** Instability is caused by two competing paths
  with equal or near-equal preference (equal-cost or misconfigured
  administrative distance), producing route flapping and asymmetric
  routing.
- **Why AI was wrong:** The AI's answer has the right general shape
  ("two competing paths causing instability") but asserted a specific
  and different mechanism (static route vs. OSPF route coexisting)
  than what the evidence actually supports. This was judged too
  different from the ground truth to count as a match, despite the
  surface-level similarity -- a good example of why root-cause
  diagnoses need to be checked for the *specific* mechanism, not just
  the general category of problem.

## Case 4 — C011 (IPv6 gateway / SLAAC)
- **AI said:** Interface Vlan50 lacks a properly configured IPv6
  address, preventing a connected IPv6 route from entering the routing
  table and preventing Router Advertisements from being generated.
- **Actual root cause:** Router Advertisements are being suppressed
  (e.g. `ipv6 nd ra suppress` on the interface) or IPv6 forwarding is
  misconfigured, so SLAAC-based hosts never learn a working default
  gateway -- the interface itself is very likely correctly addressed.
- **Why AI was wrong:** The AI inferred a plausible-sounding but
  incorrect prerequisite failure (no interface address) rather than
  the actual, more specific cause (RA suppression). Both would produce
  "hosts have no usable default gateway via SLAAC," so the AI picked a
  cause that fits the symptom but isn't what the evidence supports.

## Case 5 — C033 (Multi-fault: NAT exhaustion + overly broad ACL) — Edited, not Rejected
- **AI said:** The branch router's NAT overload translation table
  filled up during a traffic spike, and a recently added overly broad
  ACL is blocking legitimate return traffic for users. Evidence claim:
  NAT statistics show translations "near limit," and the ACL matches
  10.0.0.0/8 "instead of the intended /32 address."
- **Actual root cause:** Same two-fault diagnosis is correct (NAT
  exhaustion during a spike, plus an overly broad ACL blocking return
  traffic for some users even after NAT load drops).
- **Why this needed correction, not just acceptance:** The root cause
  itself is right, but the AI stated two details as if directly
  observed that aren't actually in the evidence: (1) it said
  translations were "near limit," but the evidence only gives a raw
  count (4088) with no stated maximum to compare against; (2) it
  described the ACL as written for an "intended /32 address," which
  assumes knowledge of the ACL author's original intent that was never
  shown in the evidence. This is a useful example for the log because
  it's not a wrong diagnosis -- it's the AI filling in plausible
  supporting detail that reads as observed fact rather than inference,
  which is a subtler and arguably more dangerous failure mode than an
  outright wrong answer, since a reviewer skimming quickly is more
  likely to miss it.

## Case 6 — C005 (DNS internal zone)
- **AI said:** Root cause correct (missing internal DNS zone file). Evidence
  claim: "nslookup for internal hostnames times out."
- **Actual evidence:** The nslookup evidence shows "Non-existent domain"
  (NXDOMAIN) — a different failure type than a timeout. A timeout means no
  response at all; NXDOMAIN means the server actively responded that the
  name doesn't exist.
- **Why AI was wrong:** The AI likely defaulted to the more common/textbook
  DNS failure mode ("times out") rather than reading the specific error
  string given in the evidence.

## Case 7 — C009 (ACL implicit deny)
- **AI said:** Root cause correct (ACL only permits ICMP, so HTTP/HTTPS
  falls to the implicit deny). Evidence claim described the ACL as a
  permit-icmp entry followed directly by the implicit deny.
- **Actual evidence:** The real ACL has three lines: a permit for ICMP,
  a separate permit for TCP port 22 (SSH), then the implicit deny. The AI's
  evidence description silently dropped the SSH line, describing a simpler
  2-line ACL than what was actually shown.
- **Why AI was wrong:** Likely summarized the ACL down to only the lines
  relevant to its stated conclusion, omitting a line that didn't affect the
  diagnosis but was still part of the real evidence.

## Case 8 — C010 (VTP revision overwrite)
- **AI said:** Root cause correct. Evidence claim included "the loss of all
  custom VLANs domain-wide" and "a blank VLAN database (only VLAN 1)."
- **Actual evidence:** The show_output only contains two `show vtp status`
  outputs with differing configuration revision numbers (47 vs 12). No
  `show vlan brief` confirming an actual, observed VLAN wipe was given.
- **Why AI was wrong:** The AI correctly knows the real-world consequence of
  a VTP revision overwrite (it does wipe the VLAN database) and stated that
  known consequence as if it were part of the observed evidence, rather
  than flagging it as an expected outcome still to be confirmed.

## Case 9 — C015 (DNS stale forwarder)
- **AI said:** Root cause correct. Evidence claim added that the secondary
  DNS server was "decommissioned last month."
- **Actual evidence:** No timeframe for the decommissioning appears
  anywhere in symptom, topology_note, or show_output.
- **Why AI was wrong:** A small, cosmetic embellishment that doesn't affect
  the diagnosis, but is still a fabricated specific detail stated as if it
  were given information.

## Case 10 — C023 (Wi-Fi stale password)
- **AI said:** Root cause: "the employee's device is using an outdated
  Wi-Fi password that was rotated last week."
- **Actual evidence:** Evidence only shows repeated PSK-mismatch
  authentication failures for one specific device, while all others succeed.
  It never confirms *why* the PSK is mismatched — a stale saved password is
  the most likely explanation, but the evidence doesn't rule out a typo, a
  wrong network selected, or another cause.
- **Why AI was wrong:** The AI presented its most-likely inference as a
  confirmed fact rather than flagging it as the leading hypothesis pending
  the obvious next check (asking the user to re-enter/verify the password).

## Case 11 — C030 (Subnet mask too narrow)
- **AI said:** Root cause and math correct. Evidence claim included "the PC
  can only successfully communicate with devices in the immediate
  10.10.4.48-10.10.4.63 range."
- **Actual evidence:** Only one failed ping outside that range is shown.
  No successful ping inside the range was captured as evidence.
- **Why AI was wrong:** The AI correctly computed the consequence of the
  subnet mask and stated it as an observed fact, when only half of that
  comparison (the failure) was actually shown.

---

## Note on review methodology
An earlier, faster read of all 35 AI responses (comparing only the final
root_cause sentence against the expected_fault) found just Cases 1-4 above
and judged the rest "clean." A slower, evidence-by-evidence pass — checking
whether each AI evidence claim actually matches what the `show_output`
field contains, not just whether the final conclusion is right — surfaced
six more cases (5-10 above, plus Case 5/C033 in the original pass) where
the AI's final conclusion was correct but it stated a detail as observed
fact that wasn't actually present in the evidence given to it.

All seven of these were reclassified from Accepted to Edited on a second
look. None of them would have been caught by only checking "is the final
diagnosis right?" — they required checking each individual claim in the
`evidence` field against the actual `show_output` text, line by line. This
is arguably the most useful finding in this log: it's not that the AI got
things wrong 20% of the time, but that in a project explicitly about
"evidence-backed" diagnosis, roughly 1 in 5 of its diagnoses contained at
least one claim that wasn't actually backed by the evidence it was given,
even when the final conclusion happened to be correct. That distinction —
"right answer, partially fabricated justification" — is a real and
under-discussed AI reliability issue, separate from just "wrong answer,"
and worth calling out explicitly in a responsible-AI report.
