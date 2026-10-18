#!/usr/bin/env python3
"""
FEYNMAN brain — nightly extraction loop (stage 4 of the build plan).

Reads yesterday's session messages, asks an LLM to pull out durable facts,
and writes them to learned_notes.md + the notes table for Dinesh's review.

Review gate by design: extraction APPENDS learned notes; it never edits the
four hand-written dossiers without Dinesh approving the diff.

Usage:
    python3 brain/extract_nightly.py              # last 24h
    python3 brain/extract_nightly.py --all        # everything unprocessed
    python3 brain/extract_nightly.py --apply      # apply reviewed facts from learned_notes.md

LLM: uses Gemini if GEMINI_API_KEY / GOOGLE_API_KEY is set
     (pip install google-generativeai). Without a key, writes the ready-to-paste
     prompt to brain/out/extraction_prompt.txt — visible, not silent.
"""
import datetime
import json
import os
import sys

BRAIN_DIR = os.path.dirname(os.path.abspath(__file__))
try:                                   # package layout (repo) — honors FEYNMAN_DATA
    from .memory import Brain, _now
except ImportError:                    # standalone (legacy)
    sys.path.insert(0, os.path.dirname(BRAIN_DIR))
    from brain.memory import Brain, _now, BRAIN_DIR  # noqa: E402

OUT_DIR = os.path.join(BRAIN_DIR, "out")
os.makedirs(OUT_DIR, exist_ok=True)

EXTRACTION_PROMPT = """You maintain the long-term memory of a personal AI assistant.
Below is a conversation log between Dinesh and his assistant from the last day.
Extract ONLY durable facts worth remembering long-term: decisions, preferences,
new/changed facts (supersede old ones), people, deadlines, project states.

Rules:
- NO ephemeral content (one-off questions, intermediate debugging).
- If a fact CONTRADICTS existing memory (e.g. notice period 30d -> 2 months),
  mark it "supersedes: <old value>".
- Return ONLY a JSON array, one object per fact:
  {{"file": "short-name.md", "desc": "one-line fact, self-contained",
    "kw": ["3-8", "retrieval", "keywords"], "evidence": "quote from the log"}}

Conversation log:
{log}
"""


def fetch_unprocessed(brain, since_hours=24, all_time=False):
    if all_time:
        return brain.conn.execute(
            "SELECT ts, role, text FROM messages ORDER BY id").fetchall()
    cutoff = (datetime.datetime.now()
              - datetime.timedelta(hours=since_hours)).isoformat(timespec="seconds")
    return brain.conn.execute(
        "SELECT ts, role, text FROM messages WHERE ts >= ? ORDER BY id",
        (cutoff,)).fetchall()


def call_gemini(prompt):
    """Vertex REST client (same as the corpus pipeline). No API key needed."""
    import subprocess as sp, time as _t, urllib.request, urllib.error
    proj = os.environ.get("FEYNMAN_GCP_PROJECT", "")
    URL = ("https://us-central1-aiplatform.googleapis.com/v1/projects/"
           f"{proj}/locations/us-central1/publishers/google/"
           "models/gemini-2.5-flash:generateContent")
    tok = sp.run(["gcloud", "auth", "print-access-token"],
                 capture_output=True, text=True).stdout.strip()
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.2,
                                            "thinkingConfig": {"thinkingBudget": 0}}
                       }).encode()
    for attempt in range(4):
        req = urllib.request.Request(URL, data=body, method="POST")
        req.add_header("Authorization", "Bearer " + tok)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
                return "".join(p.get("text", "") for p in
                               d["candidates"][0]["content"]["parts"])
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503):
                _t.sleep(20 * (attempt + 1)); continue
            raise
    raise RuntimeError("vertex retries exhausted")


def parse_facts(text):
    if not text:
        return []
    m = text[text.find("["):text.rfind("]") + 1]
    try:
        return json.loads(m)
    except json.JSONDecodeError:
        return []


def main():
    all_time = "--all" in sys.argv
    apply_mode = "--apply" in sys.argv
    brain = Brain()

    if apply_mode:
        # apply reviewed facts from out/learned_facts.json (Dinesh-approved)
        path = os.path.join(OUT_DIR, "learned_facts.json")
        with open(path) as f:
            facts = json.load(f)
        for fact in facts:
            brain.add_note(fact["file"], fact["desc"], fact.get("kw"))
        print(f"[extract] applied {len(facts)} reviewed facts to notes")
        return

    rows = fetch_unprocessed(brain, all_time=all_time)
    if not rows:
        print("[extract] no messages in window — nothing to do")
        return

    log_text = "\n".join(f"[{r['ts']}] {r['role']}: {r['text']}" for r in rows)
    prompt = EXTRACTION_PROMPT.format(log=log_text[:60000])

    raw = call_gemini(prompt)
    if raw is None:
        path = os.path.join(OUT_DIR, "extraction_prompt.txt")
        with open(path, "w") as f:
            f.write(prompt)
        print(f"[extract] no GEMINI_API_KEY set — prompt written to {path}")
        print("[extract] paste it into any LLM, save the JSON array as "
              "brain/out/learned_facts.json, then run: python3 brain/extract_nightly.py --apply")
        return

    facts = parse_facts(raw)
    path = os.path.join(OUT_DIR, "learned_facts.json")
    with open(path, "w") as f:
        json.dump(facts, f, indent=2)
    print(f"[extract] {len(facts)} candidate facts -> {path}")
    print("[extract] REVIEW them, delete junk, then: "
          "python3 brain/extract_nightly.py --apply")
    for fct in facts[:10]:
        print(f"  - [{fct.get('file')}] {fct.get('desc')}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------- v2 (Oct 18)
# Wire 1 auto mode: extract -> auto-apply -> one diary line per day.
# Auto-apply was Dinesh's explicit choice (weekly digest ritual covers review).

def auto_run():
    import re as _re
    brain = Brain()
    rows = fetch_unprocessed(brain, since_hours=24)
    msgs = [(r["ts"], r["role"], r["text"]) for r in rows
            if r["role"] in ("user", "assistant")]
    if not msgs:
        print("[auto] no conversations in the last 24h")
        return
    log = "\n".join(f"[{t} {r}] {x[:800]}" for t, r, x in msgs)
    print(f"[auto] extracting from {len(msgs)} messages ...")
    raw = call_gemini(EXTRACTION_PROMPT.format(log=log))
    m = _re.search(r"\[.*\]", raw, _re.S)
    facts = json.loads(m.group(0)) if m else []
    added = 0
    for f in facts:
        brain.add_note(f.get("file", "learned.md"), f.get("desc", ""),
                       kw=f.get("kw", []), text=f.get("desc", ""), source="nightly")
        added += 1
    # diary line (Wire 2 rides along)
    diary_prompt = ("One diary line for this AI companion's owner, from today's "
                    "conversations. Format strictly: 'TOPICS; his apparent mood'. "
                    "Max 25 words. Conversations:\n" + log[:20000])
    line = call_gemini(diary_prompt).strip().strip('"')
    today = datetime.date.today().isoformat()
    with open(os.path.join(OUT_DIR, "diary.md"), "a") as f:
        f.write(f"- {today}: {line}\n")
    print(f"[auto] +{added} notes, diary line: {line}")

if "--auto" in sys.argv:
    auto_run()
