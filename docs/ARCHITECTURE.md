# Feynman Architecture

## The one-line theory

A language model exists only during forward passes. A "live companion" is an
orchestrator that keeps a websocket warm, wakes the model on events, and
injects the right memory into every wake. Feynman is that orchestrator plus
a brain.

## Three actors

1. **The orchestrator** (`feynman/live.py`) — the only always-running thing.
   Streams mic audio up, plays model audio down, dispatches tools, logs
   utterances.
2. **The session** — one websocket to the Gemini Live API
   (`LlmBidiService/BidiGenerateContent`). Audio chunks up (~100ms), events
   down: `modelTurn`, `interrupted`, `turnComplete`, `toolCall`.
3. **The model** — invoked per turn (utterance-end, tool result, injection).
   Between turns it does not exist; the warm pipe + KV cache make it feel
   continuous.

## Barge-in (interruption)

The server's VAD detects user speech during a model turn → sends
`serverContent.interrupted` → the client flushes unplayed audio (one line)
and the server truncates the model's unspoken output from context. The next
turn knows it was cut off.

## Tool binding

Declared twice, meeting in the middle:

- **To the model** (session setup): name + description + JSON schema per
  tool (`tools.declarations()`).
- **In our code**: the `SCHEMAS` registry maps names to Python functions
  (`tools.dispatch`).

Flow: model emits `toolCall {name, args}` → orchestrator dispatches
off-thread (audio never blocks) → result returns as `tool_response` → model
continues the turn. The model never executes anything; all power stays local
behind blocklists (destructive shell patterns, protected-process refusals).

## Memory: three tiers

| Tier | What | When injected |
|---|---|---|
| 1. Dossiers | 5 markdown files: self, personal, skill, voice, principles | every prompt, verbatim |
| 1.5 Diary | one line per day, written nightly | last 7 lines every prompt |
| 2. Notes | durable facts (SQLite `notes`; keyword + 384d embedding recall) | top-k per message |
| 3. Raw log | every utterance ever (`messages`) | LIKE-searched fallback |

Budget: 24k chars; overflow drops tier-3, then tier-2 — never the dossiers.

## The learning loop (sleep)

`live.py` logs complete utterances (on transcription `finished` +
`turnComplete`) → cron at 4:30 AM runs `extract_nightly.py --auto` →
Gemini distills yesterday into notes (auto-applied, source=`nightly`) +
one diary line. A weekly digest ritual surfaces everything learned for
review.

## Corpus bootstrap

Long-term memory can be seeded from real chat history: export → preprocess →
distill (batched Gemini) → consolidate. The author's brain was seeded from
11,469 messages across three AI tools → 2,178 notes, retrieval eval 21/21
in both keyword and embedding modes.

## Deployment shape

Code (this repo) is separate from data (`FEYNMAN_DATA`): brain db, dossiers,
diary, skills, todo. Nothing personal ships in the repo.
