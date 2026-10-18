#!/usr/bin/env python3
"""
FEYNMAN brain — retrieval eval (stage 7 of the build plan).

21 questions with known answers. For each, we build the system prompt the
model would receive and check that the answer text is actually present in
the injected context. Deterministic — no LLM call needed: it tests the
memory layer, not the model's eloquence.

Each required item is either a string (must appear) or a tuple of
alternatives (any one must appear).

    python3 brain/eval.py                    # keyword mode (instant, offline)
    FEYNMAN_EMBED=1 python3 brain/eval.py    # embedding mode

Pass bar: >= 90% hit-rate.
"""
import os
import sys

BRAIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BRAIN_DIR))
from brain.memory import Brain  # noqa: E402

EVAL = [
    ("What is my notice period?", ["2 month"]),
    ("What salary should I expect or negotiate for?", ["16 LPA"]),
    ("Where did I study? What's my college?", ["ISM Dhanbad"]),
    ("Which company do I currently work at?", ["Reliance"]),
    ("Where was my internship and what stack was it?", ["Pepsales", "Flask"]),
    ("What's my mother's name?", ["Lalitha"]),
    ("What language does my family speak at home?", ["Telugu"]),
    ("How many orders per day does Homaatri do?", [("40-50", "40–50")]),
    ("What is Homaatri's headline feature?", ["WhatsApp"]),
    ("What's my Codeforces rating?", ["1600"]),
    ("How many LeetCode problems have I solved?", ["500"]),
    ("What cloud platform are my services deployed on?", ["Cloud Run"]),
    ("What are my two big goals?", ["funding"]),
    ("Who are my referrers at InfoCepts?", ["Atharv", "Arya"]),
    ("How many projects go on my resume?", ["exactly 2"]),
    ("What is Wingman AI?", ["Tinder"]),
    ("What did I build for the Swiggy application?", ["OrderPilot", "MenuMind"]),
    ("How many startups are in the Startup Intel corpus?", ["175"]),
    ("Can we schedule a call at 9 AM tomorrow?", ["11 AM"]),
    ("What are my resume style rules?", ["buzzword"]),
    ("How much RAM does my laptop have?", ["7.5"]),
]


def _present(item, text_low):
    alts = item if isinstance(item, tuple) else (item,)
    return any(a.lower() in text_low for a in alts)


def main():
    brain = Brain()
    mode = "embeddings" if brain.use_embeddings else "keyword-hooks"
    passed, failures = 0, []
    for i, (q, required) in enumerate(EVAL, 1):
        prompt = brain.build_system_prompt(q)
        low = prompt.lower()
        missing = [item for item in required if not _present(item, low)]
        if not missing:
            passed += 1
            print(f"  PASS  {i:2d}. {q}")
        else:
            failures.append((q, missing))
            print(f"  FAIL  {i:2d}. {q}  missing={missing}")

    rate = passed / len(EVAL) * 100
    verdict = "PASS" if rate >= 90 else "BELOW BAR — fix hooks or add notes"
    print(f"\n[eval] mode={mode}  hit-rate {passed}/{len(EVAL)} = {rate:.0f}%  {verdict}")
    return 0 if rate >= 90 else 1


if __name__ == "__main__":
    sys.exit(main())
