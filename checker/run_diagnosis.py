"""
run_diagnosis.py
-----------------
Sends every case in cases.csv through the AI (Google Gemini API, free tier)
using the diagnose_prompt.md template, and saves each raw response as its
own JSON file under runs/ai_responses/.

Setup (one-time, all free -- no credit card needed):
    1. Go to https://aistudio.google.com, sign in with a Google account.
    2. Click "Get API key" -> "Create API key". Copy it.
    3. pip install google-generativeai
    4. Set it as an environment variable (never paste it into code you push to git):
       Mac/Linux:   export GOOGLE_API_KEY="your-key-here"
       Windows:     setx GOOGLE_API_KEY "your-key-here"   (then reopen your terminal)

Usage:
    python run_diagnosis.py
    python run_diagnosis.py --limit 5      # test on just the first 5 cases first
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import google.generativeai as genai

MODEL = "gemini-2.5-flash"  # free tier, no credit card required

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


def diagnose_case(model, case):
    response = model.generate_content(
        build_user_message(case),
        generation_config={
            "response_mime_type": "application/json",  # asks Gemini to force valid JSON
            "max_output_tokens": 1000,
        },
    )
    return response.text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="cases/cases.csv")
    parser.add_argument("--out", default="runs/ai_responses")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N cases (useful for testing)")
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY environment variable is not set.")
        print("Set it first -- see the setup instructions at the top of this file.")
        sys.exit(1)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)

    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, case in enumerate(cases, 1):
        case_id = case["case_id"]
        print(f"[{i}/{len(cases)}] Diagnosing {case_id}...", end=" ", flush=True)

        try:
            raw_text = diagnose_case(model, case)
        except Exception as e:
            print(f"FAILED ({e})")
            continue

        try:
            parsed = json.loads(raw_text)
            parse_ok = True
        except json.JSONDecodeError:
            parsed = None
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

        status = "OK" if parse_ok else "WARNING: response was not valid JSON"
        print(status)

        time.sleep(1)  # stay comfortably under the free tier's per-minute rate limit

    print(f"\nDone. Responses saved to {out_dir}/")


if __name__ == "__main__":
    main()
