# Testing

## Run
```bash
python3 tests/run_all.py          # core: brain (8) + tools (22) + pipe (3) = 33
python3 tests/run_all.py --live   # + headless live E2E (3) = 36
```

## What each suite covers
- **Brain**: missing-seed tolerance, keyword recall, session log + search,
  prompt assembly (tiers, injection, budget), embedding recall when
  fastembed/sqlite-vec are installed.
- **Tools**: all 19 tools against an isolated `FEYNMAN_DATA` temp dir —
  including the terminal blocklist, ambiguous-edit refusal, and
  protected-process kill refusal. Door tools (`fire_task`, `task_status`)
  run live when the optional adapter is present, skip otherwise.
- **Learning pipe**: simulated utterances → nightly `--auto` extraction
  (one real Gemini call) → asserts notes landed in the brain + diary line
  written.
- **Headless live E2E**: opens a REAL Live session in text mode with all 19
  tools declared; the model is instructed to call `journal`; the suite
  asserts the `toolCall` arrived, the tool executed (file on disk), the
  `tool_response` was accepted, and the turn completed. No mic/speaker
  required — the same loop voice uses, minus audio.

## Bugs this suite caught (kept for honesty)
1. Five dossiers exceeded the 15k prompt budget → the trim order silently
   dropped *retrieved memories* while keeping static dossiers. Fixed:
   budget 24k; tiered trim now leaves room for what was learned.
2. Standalone script invocation ignored `FEYNMAN_DATA` → nightly extraction
   read the wrong brain. Fixed: env-aware path resolution in both import
   modes.
