"""
run_diagnosis.py
-----------------
Sends every case in cases.csv through the AI (Google Gemini API, free tier)
using the diagnose_prompt.md template, and saves each raw response as its
own JSON file under runs/ai_responses/.

SETUP (see the step-by-step guide for full detail):
    1. Get a free API key at https://aistudio.google.com/apikey
    2. Create a file called "api_key.txt" in this same folder, paste ONLY
       the key into it, and save.
    3. Install the required package:  python -m pip install google-genai
       (NOT google-generativeai -- that package is deprecated)

USAGE (run from a terminal, inside this folder):
    python run_diagnosis.py                 # runs all cases
    python run_diagnosis.py --limit 5        # test on just the first 5 cases first
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types

MODEL = "gemini-3.5-flash-lite"  # free tier -- current stable lite model as of this run

SYSTEM_PROMPT = """You are a network troubleshooting assistant for Cisco/Packet Tracer style
lab networks. You will be given a symptom report, a short topology note,
and evidence from show commands. Your job is to diagnose the most likely
root cause.

Rules you must follow:
1. Base your diagnosis ONLY on the evidence given. Do not invent commands,
   error messages, or device behavior that wasn't stated.
2. If the evidence is genuinely insufficient to be confident, say so in
   "confidence" and suggest what to check next in "next_command" -- do not
   guess with false confidence.
3. Respond with ONLY a single valid JSON object. No preamble, no markdown
   formatting, no text before or after the JSON.

Respond in exactly this JSON schema:
{
  "root_cause": "<one or two sentence diagnosis of what's actually wrong>",
  "confidence": <integer 0-100>,
  "evidence": "<which specific piece(s) of the given evidence support this diagnosis>",
  "next_command": "<the single most useful next show/debug command to confirm or narrow this down>",
  "fix_steps": ["<step 1>", "<step 2>", "..."]
}

Here are two worked examples showing the expected format and reasoning style.

Example 1 -- a confident diagnosis:
Input:
Symptom: New laptops on VLAN 60 never get an IP address and fall back to APIPA; VLAN 10 on the same building works fine.
Topology note: DHCP server is centralized on VLAN 10; VLAN 60 is a newly added VLAN trunked back to the router.
Evidence: show ip interface brief on the router shows no ip helper-address configured on the VLAN 60 SVI, while VLAN 10's SVI has one pointing to the DHCP server.
Output:
{
  "root_cause": "VLAN 60's router interface is missing the ip helper-address (DHCP relay) configuration, so DHCP broadcast requests from VLAN 60 never reach the centralized DHCP server on VLAN 10.",
  "confidence": 90,
  "evidence": "VLAN 10's SVI has an ip helper-address configured pointing to the DHCP server, while VLAN 60's SVI does not -- and DHCP broadcasts can't cross VLANs without a relay.",
  "next_command": "show running-config interface vlan60",
  "fix_steps": ["Enter interface configuration mode for VLAN 60's SVI on the router.", "Add 'ip helper-address <DHCP server IP>' to relay DHCP requests.", "Verify a test device on VLAN 60 receives a valid IP address after the change."]
}

Example 2 -- low confidence when evidence is genuinely ambiguous:
Input:
Symptom: A branch office's connection to HQ is inconsistent -- sometimes fast, sometimes times out.
Topology note: Branch router has both a static route and an OSPF-learned route to the HQ subnet.
Evidence: show ip route shows two routes to the HQ subnet with different next hops; no administrative distance values were captured.
Output:
{
  "root_cause": "Likely route instability caused by two competing paths to the HQ subnet, but the exact mechanism (AD misconfiguration vs. genuine link flapping) can't be confirmed from the evidence given.",
  "confidence": 40,
  "evidence": "Two different routes to the same destination with different next hops were observed, which is consistent with route flapping, but administrative distance values weren't captured so the actual cause of the instability is unclear.",
  "next_command": "show ip route 172.16.0.0 (or the specific HQ subnet, to see AD values and which route is currently active)",
  "fix_steps": ["Run the suggested next_command to see the administrative distance of each competing route.", "If AD values are tied or misconfigured, adjust so only one preferred path is used.", "If AD values look correct, investigate the underlying link for flapping (interface errors, physical issues)."]
}"""


def build_user_message(case):
    return (
        f"Symptom: {case['symptom']}\n\n"
        f"Topology note: {case['topology_note']}\n\n"
        f"Evidence (show command output): {case['show_output']}\n\n"
        "Diagnose the root cause using the JSON schema you were given."
    )


def load_cases(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def try_parse_json(raw_text):
    """
    Attempts to parse the AI's response as JSON. Handles the common case
    where the model wraps valid JSON in markdown code fences (```json ... ```)
    or adds a little text before/after it, despite being told not to.
    Returns (parsed_dict_or_None, cleaned_text_that_was_parsed).
    """
    text = raw_text.strip()

    # Try as-is first.
    try:
        return json.loads(text), text
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
        try:
            return json.loads(text), text
        except json.JSONDecodeError:
            pass

    # Last resort: grab the substring between the first { and the last }.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate), candidate
        except json.JSONDecodeError:
            pass

    return None, text


def diagnose_case(client, case, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=build_user_message(case),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    max_output_tokens=4096,
                ),
            )
            return response.text
        except Exception as e:
            is_rate_limit = "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e)
            if is_rate_limit and attempt < max_retries - 1:
                wait_seconds = 65  # per-minute quotas reset well within this
                print(f"\n    Rate limited, waiting {wait_seconds}s before retry {attempt + 2}/{max_retries}...", end=" ", flush=True)
                time.sleep(wait_seconds)
                continue
            raise


def get_api_key():
    """
    Looks for the API key in two places, in order:
    1. A file called api_key.txt sitting next to this script (simplest option).
    2. The GOOGLE_API_KEY environment variable (for anyone who prefers that).
    """
    key_file = Path(__file__).resolve().parent / "api_key.txt"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    return os.environ.get("GOOGLE_API_KEY")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(Path(__file__).resolve().parent.parent / "cases" / "cases.csv"))
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "runs" / "ai_responses"))
    parser.add_argument("--limit", type=int, default=None, help="only run the first N cases (useful for testing)")
    parser.add_argument("--force", action="store_true", help="re-run cases even if a successful result already exists")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("ERROR: No API key found.")
        print("Create a file called api_key.txt in the same folder as this script,")
        print("and paste your Google AI Studio API key into it (just the key, nothing else).")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, case in enumerate(cases, 1):
        case_id = case["case_id"]

        # Skip cases that already succeeded on a previous run, so re-running
        # after a quota error doesn't waste requests re-doing finished work.
        existing_path = out_dir / f"{case_id}.json"
        if not args.force and existing_path.exists():
            try:
                with open(existing_path, encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("parsed_ok"):
                    print(f"[{i}/{len(cases)}] {case_id} already done -- skipping.")
                    continue
            except (json.JSONDecodeError, OSError):
                pass  # existing file is corrupt/unreadable, re-run it

        print(f"[{i}/{len(cases)}] Diagnosing {case_id}...", end=" ", flush=True)

        try:
            raw_text = diagnose_case(client, case)
        except Exception as e:
            print(f"FAILED ({e})")
            continue

        try:
            parsed, cleaned_text = try_parse_json(raw_text)
            parse_ok = parsed is not None
        except Exception:
            parsed, cleaned_text = None, raw_text
            parse_ok = False

        out_path = out_dir / f"{case_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "case_id": case_id,
                    "raw_response": raw_text,
                    "parsed_ok": parse_ok,
                    "parsed": parsed,
                },
                f,
                indent=2,
            )

        status = "OK" if parse_ok else "WARNING: response was not valid JSON even after cleanup -- check the raw_response field in the saved file"
        print(status)

        time.sleep(5)  # ~12 requests/min, comfortably under the 15/min free tier cap

    print(f"\nDone. Responses saved to {out_dir}/")


if __name__ == "__main__":
    main()
