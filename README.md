# NetSage AI

An AI-assisted troubleshooting helper for Cisco-style Packet Tracer lab networks.
The assistant reads symptoms and show-command output, suggests a likely root
cause, OSI layer, next command, and fix — but every diagnosis requires human
review before it's accepted.

## Project structure
- `cases/cases.csv` — 30+ troubleshooting cases (symptom, evidence, expected fault)
- `prompts/diagnose_prompt.md` — structured prompt template (forces JSON output)
- `checker/rule_checker.py` — deterministic Python checks (no AI)
- `runs/ai_responses/` — raw AI output per case
- `runs/review_log.csv` — human review verdicts (Accepted/Edited/Rejected)
- `responsible_ai_log.md` — documented cases where AI was corrected
- `dashboard/` — summary of issue types and AI vs human agreement
- `demo/` — demo video / link

## Status
Work in progress.
