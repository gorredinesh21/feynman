# Tool Reference (19 native tools)

| Tool | Purpose | Safety |
|---|---|---|
| `memory_save` | durable fact/preference to long-term memory | — |
| `memory_search` | search memory notes (keyword + embeddings) | — |
| `session_search` | search raw transcripts of past conversations | — |
| `journal` | timestamped line to the shared journal (mood, moments) | — |
| `todo` | the companion's own promise tracker (add/list/done/remove) | — |
| `skills_list` / `skill_view` / `skill_manage` | procedural memory — learnable procedures stored as SKILL.md files | — |
| `terminal` | run a shell command | destructive-pattern blocklist (rm -rf /, mkfs, dd to device, fork bombs, shutdown) |
| `file_read` | read with line numbers, paginated | — |
| `file_write` | write/replace a file | — |
| `file_edit` | surgical single-occurrence string replacement; refuses ambiguous matches | — |
| `search_files` | ripgrep content search / filename find | — |
| `web_fetch` | fetch a URL, return readable text | — |
| `fire_task` | fire a full agent task into the ZCode app (appears in its task list, full access) | optional adapter; token-gated door |
| `task_followup` | send a follow-up message into a running task | same door |
| `task_status` | task state + last output | read-only |
| `schedule` | cron items (tagged `# FEYNMAN`) | — |
| `process` | list processes / kill by pid | refuses protected names (zcode, systemd, Xorg, audio) |

Free abilities via the Live API (no tool code): web search (Google
grounding), vision (camera/screen stream), emotional voice output.

Schema + dispatch live in `feynman/tools.py` (`SCHEMAS`, `declarations()`,
`dispatch()`).
