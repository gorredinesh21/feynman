# Feynman

**A personal AI companion harness you own.** Feynman talks with you live by
voice, remembers your shared life permanently, carries a personality, and
commands a small army of tools — running on *your* infrastructure, learning
from *your* actual history, owned by no one but you.

> Named for Richard Feynman: explain simply, reason from first principles,
> be honest — especially when it's uncomfortable.

---

## Why

Every chatbot you've used starts each conversation with amnesia. Your history
sits in someone else's cloud, your "memory" is a session long, and your
assistant's personality is a marketing decision. Feynman is the opposite bet:

- **Live voice, full-duplex** — talk naturally, interrupt mid-word, it yields.
- **A memory that compounds** — nightly sleep consolidates each day's
  conversations into long-term memory notes. It remembers what you said
  Tuesday, and the debate you never finished.
- **A self, not a settings page** — five always-injected dossiers define who
  it is, who you are, and how it thinks. Identity changes only by your
  consent, never silently.
- **Tools it actually owns** — 19 native tools (memory, terminal, files,
  search, scheduling, and an agent-task firing system) declared to the model
  and dispatched by your local code.
- **Yours** — SQLite brain on your disk, voice on your GCP project, MIT code.

## How it works (60 seconds)

```
        ┌──────────────── you (voice / text) ────────────────┐
        ▼                                                    │
  Gemini Live API  ◄── websocket, never closes ──►  feynman/live.py
  (native audio: hears speech, speaks speech,             │
   VAD barge-in, tool calls mid-session)                  ▼
                                               feynman/tools.py (19 tools)
                                                        │
                          feynman/brain — 3-tier memory ▼
                          dossiers → notes (2,178 seeded from my real
                          6-month chat corpus) → raw session log
                          + nightly extraction (sleep) + diary (working memory)
```

The model exists only inside turns; the orchestrator and the pipe provide the
continuity. Full theory in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quickstart

```bash
git clone https://github.com/gorredinesh21/feynman && cd feynman
pip install -r requirements.txt

# 1) auth (Vertex AI voice + nightly learning)
gcloud auth application-default login
export FEYNMAN_GCP_PROJECT=your-project-id

# 2) a brain home + dossiers (templates included)
export FEYNMAN_DATA=~/.feynman
cp -r feynman/brain/dossiers_example $FEYNMAN_DATA/brain/dossiers
# edit the five .md dossiers — they define you and your companion

# 3) talk
python3 -m feynman.live
```

Everything is env-configurable — see [docs/SETUP.md](docs/SETUP.md).
Tool reference: [docs/TOOLS.md](docs/TOOLS.md).

## The tool belt (19)

`memory_save` · `memory_search` · `session_search` · `journal` · `todo` ·
`skills_list` · `skill_view` · `skill_manage` · `terminal` · `file_read` ·
`file_write` · `file_edit` · `search_files` · `web_fetch` · `fire_task` ·
`task_followup` · `task_status` · `schedule` · `process`

Plus free abilities from the Live API: web search (grounding), vision
(camera/screen stream), emotional voice. An optional adapter lets Feynman
fire full agent tasks into a local coding-agent app — see
[docs/SETUP.md](docs/SETUP.md#optional-app-task-adapter).

## Learning loop

1. You talk → complete utterances logged to the raw session log (crash-safe)
2. Nightly (cron, 4:30 AM) → Gemini distills yesterday into durable notes +
   one diary line
3. Next session → dossiers + last-week diary + retrieved notes build the
   system prompt
4. Weekly digest ritual → *"here's what I learned this week — anything wrong?"*

## Testing

```bash
python3 tests/run_all.py         # 33 checks: brain, 19 tools, learning pipe
python3 tests/run_all.py --live  # + headless live E2E (36 total)
```

The headless E2E is the interesting one: it opens a real Live session in
text mode, the model decides to call a tool, the tool executes, and the
round-trip completes — no mic or speaker needed. Details in
[docs/TESTING.md](docs/TESTING.md).

## Status & roadmap

- [x] Live voice loop with barge-in (Gemini Live API on Vertex)
- [x] 3-tier memory + corpus bootstrap (11.5k messages → 2,178 notes, 100% eval)
- [x] 19 native tools, 36-check test suite
- [x] Nightly learning + diary (auto) · self dossier with life story
- [ ] Proactive rituals (morning briefing) · open-debates board
- [ ] Wake-word hands-free · personality drift guard
- [ ] MCP attach (browser, messaging)

## License

MIT — see [LICENSE](LICENSE). Your data is yours: the repo ships zero
personal data, and `.gitignore` keeps your brain, dossiers, and tokens out.
