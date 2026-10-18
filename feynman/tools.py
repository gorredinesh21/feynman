#!/usr/bin/env python3
"""
FEYNMAN tools — the native tool set + Live API binding.

Every tool = (name, description, JSON schema) declared to the Live API at
session start + a Python implementation in TOOLS below. The model emits
toolCall(name, args); dispatch() runs the implementation and returns the
result the model sees. All power lives here, not in the model.

Safety philosophy: Dinesh's machine, companion-grade trust with hard
blocklists for the catastrophic stuff (never for targeted annoyance).
"""
import asyncio, datetime, json, os, re, socket, subprocess, uuid

from . import config
HOME = os.path.expanduser("~")
FEYNMAN = config.DATA_DIR
SKILLS_DIR = config.SKILLS_DIR
TODO_PATH = config.TODO_PATH
JOURNAL_PATH = config.JOURNAL_PATH
ZCODE_DOOR = config.ZCODE_DOOR
ZCODE_TOKEN = config.ZCODE_TOKEN
RG = os.environ.get("FEYNMAN_RG", "/opt/ZCode/resources/tools/ripgrep/rg")

os.makedirs(SKILLS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(TODO_PATH), exist_ok=True)

# brain attaches lazily (import path set by live.py; standalone for tests)
BRAIN = None
def _brain():
    global BRAIN
    if BRAIN is None:
        try:
            from .brain.memory import Brain
        except ImportError:
            import sys; sys.path.insert(0, FEYNMAN)
            from brain.memory import Brain
        BRAIN = Brain()
    return BRAIN

DESTRUCTIVE = re.compile(
    r"rm\s+-rf\s+[/~]|mkfs|dd\s+if=.*of=/dev/|:\(\)\{.*\};:|shutdown|reboot",
    re.I)

def _cap(s, n=8000):
    s = s if isinstance(s, str) else str(s)
    return s if len(s) <= n else s[:n] + f"\n...[truncated {len(s)-n} chars]"

# ============================================================ implementations

def memory_save(text, keywords=None, type="fact"):
    kw = keywords or []
    _brain().add_note(f"live-{uuid.uuid4().hex[:6]}.md", text.strip()[:500],
                      kw=[k.lower() for k in kw][:10], text=text.strip()[:2000],
                      source="live")
    return "saved"

def memory_search(query):
    hits = _brain().recall(query, k=5)
    return _cap("\n".join(f"- [{f}] {d}" for f, d, _ in hits) or "no matches")

def session_search(query):
    hits = _brain().search_sessions(query, k=4)
    return _cap("\n".join(f"- ({r['ts'][:16]} {r['role']}) {r['text'][:150]}"
                          for r in hits) or "no past conversations matched")

def journal(text):
    line = f"- {datetime.datetime.now().isoformat(timespec='minutes')}: {text.strip()}"
    with open(JOURNAL_PATH, "a") as f:
        f.write(line + "\n")
    return "journaled"

def _todo_lines():
    if not os.path.exists(TODO_PATH):
        return []
    return [l.rstrip("\n") for l in open(TODO_PATH) if l.strip()]

def todo(action, text=None, id=None):
    lines = _todo_lines()
    if action == "list":
        return _cap("\n".join(lines) or "todo list is empty")
    if action == "add":
        entry = f"[ ] #{len(lines)+1} {text.strip()}"
        with open(TODO_PATH, "a") as f:
            f.write(entry + "\n")
        return f"added #{len(lines)+1}"
    if action == "done":
        out, hit = [], False
        for l in lines:
            if id and f"#{id}" in l and l.startswith("[ ]"):
                out.append(l.replace("[ ]", "[x]", 1)); hit = True
            else:
                out.append(l)
        open(TODO_PATH, "w").write("\n".join(out) + ("\n" if out else ""))
        return "marked done" if hit else f"#{id} not found/open"
    if action == "remove":
        keep = [l for l in lines if not (id and f"#{id}" in l)]
        open(TODO_PATH, "w").write("\n".join(keep) + ("\n" if keep else ""))
        return "removed"
    return "action must be add|list|done|remove"

def skills_list():
    out = []
    for d in sorted(os.listdir(SKILLS_DIR)):
        p = f"{SKILLS_DIR}/{d}/SKILL.md"
        if os.path.exists(p):
            first = next((l.lstrip("# ") for l in open(p) if l.startswith("#")), d)
            out.append(f"- {d}: {first[:80]}")
    return _cap("\n".join(out) or "no skills learned yet")

def skill_view(name):
    p = f"{SKILLS_DIR}/{re.sub(r'[^a-z0-9-]', '', name.lower())}/SKILL.md"
    if not os.path.exists(p):
        return "no such skill"
    return _cap(open(p).read())

def skill_manage(action, name, content=None):
    d = f"{SKILLS_DIR}/{re.sub(r'[^a-z0-9-]', '', name.lower())}"
    p = f"{d}/SKILL.md"
    if action == "create" or action == "update":
        os.makedirs(d, exist_ok=True)
        open(p, "w").write(content)
        return f"skill '{os.path.basename(d)}' saved"
    if action == "delete":
        if os.path.exists(p):
            os.remove(p); return "deleted"
        return "no such skill"
    return "action must be create|update|delete"

def terminal(command, timeout=60):
    if DESTRUCTIVE.search(command):
        return "BLOCKED: command matches the destructive blocklist"
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True,
                           timeout=min(int(timeout), 300), cwd=HOME)
        out = (r.stdout or "") + (("\nSTDERR: " + r.stderr) if r.stderr else "")
        return _cap(f"exit={r.returncode}\n{out.strip() or '(no output)'}")
    except subprocess.TimeoutExpired:
        return f"timed out after {timeout}s"

def file_read(path, offset=0, limit=400):
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(p):
        return "no such file"
    lines = open(p, encoding="utf-8", errors="replace").readlines()
    chunk = lines[int(offset):int(offset) + int(limit)]
    return _cap("".join(f"{i+int(offset)+1}\t{l}" for i, l in enumerate(chunk))
                or "(empty range)")

def file_write(path, content):
    p = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(content)
    return f"wrote {len(content)} chars to {p}"

def file_edit(path, old_text, new_text):
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(p):
        return "no such file"
    src = open(p, encoding="utf-8", errors="replace").read()
    n = src.count(old_text)
    if n == 0:
        return "old_text not found"
    if n > 1:
        return f"old_text found {n} times — refusing ambiguous edit"
    open(p, "w", encoding="utf-8").write(src.replace(old_text, new_text, 1))
    return "edited"

def search_files(pattern, path=None, mode="content"):
    root = os.path.abspath(os.path.expanduser(path or HOME))
    if mode == "filename":
        cmd = f"find '{root}' -iname '*{pattern}*' -not -path '*/.*' 2>/dev/null | head -50"
    else:
        grep = f"'{RG}'" if os.path.exists(RG) else "grep -rn"
        cmd = (f"{grep} '{pattern}' '{root}' --max-count 3 2>/dev/null | head -60"
               if os.path.exists(RG)
               else f"{grep} '{pattern}' '{root}' 2>/dev/null | head -60")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return _cap(r.stdout.strip() or "no matches")

def web_fetch(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Feynman"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read(2_000_000).decode("utf-8", "replace")
    except Exception as e:
        return f"fetch failed: {e}"
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "nav", "footer"]):
            t.decompose()
        text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n"))
    except ImportError:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s{2,}", " ", text)
    return _cap(text.strip()[:10000], 10000)

# ------------------------------------------------ ZCode door (fire/follow/status)

def _door(request):
    if not (os.path.exists(ZCODE_DOOR) and os.path.exists(ZCODE_TOKEN)):
        return {"ok": False, "error": "door not installed/running (needs patched ZCode app)"}
    tok = open(ZCODE_TOKEN).read().strip()
    request.update({"id": str(uuid.uuid4()), "token": tok})
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(300)
    try:
        s.connect(ZCODE_DOOR)
        s.sendall((json.dumps(request) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            c = s.recv(65536)
            if not c:
                break
            buf += c
        return json.loads(buf.split(b"\n")[0])
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        s.close()

DEFAULT_TASK_WS = os.environ.get(
    "FEYNMAN_TASK_WORKSPACE",
    os.path.expanduser("~/coding/PROJECTS/zcode-agent-tasks"))

def fire_task(prompt, workspace=None):
    workspace = workspace or DEFAULT_TASK_WS
    r = _door({"op": "run", "prompt": prompt, "workspacePath": workspace,
               "mode": "yolo"})
    return _cap(json.dumps(r))

def task_followup(task_id, prompt):
    r = _door({"op": "followup", "taskId": task_id, "prompt": prompt})
    return _cap(json.dumps(r))

def task_status(task_id):
    db = f"{HOME}/.zcode/cli/db/db.sqlite"
    if not task_id.startswith("sess_"):
        task_id = "sess_" + task_id.lstrip("s")
    try:
        import sqlite3
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        last = c.execute(
            "select json_extract(data,'$.finish') from message "
            "where session_id=? order by rowid desc limit 1",
            (task_id,)).fetchone()
        n = c.execute("select count(*) from message where session_id=?",
                      (task_id,)).fetchone()[0]
        snippet = ""
        for (pdata,) in c.execute(
                "select p.data from part p join message m on m.id=p.message_id "
                "where m.session_id=? and json_extract(p.data,'$.type')='text' "
                "order by p.rowid desc limit 1", (task_id,)).fetchall():
            snippet = json.loads(pdata).get("text", "")[:200]
        fin = (last or [None])[0]
        state = {"stop": "done", "tool-calls": "working (mid-step)",
                 None: "no messages yet"} .get(fin, f"state: {fin}")
        return f"{state} | {n} messages | last: {snippet or '(none)'}"
    except Exception as e:
        return f"status failed: {e}"

# ------------------------------------------------ schedule + process

def schedule(action, when=None, command=None, note=None, id=None):
    tag = "# FEYNMAN"
    cur = subprocess.run("crontab -l", shell=True, capture_output=True,
                         text=True).stdout.splitlines()
    mine = [l for l in cur if tag in l]
    if action == "list":
        return _cap("\n".join(mine) or "no scheduled items")
    if action == "add":
        if not (when and command):
            return "need cron expression + command"
        line = f"{when} {command} {tag}"
        subprocess.run("crontab -", shell=True, input="\n".join(cur + [line]) + "\n",
                       text=True)
        return f"scheduled: {line}" + (f"  ({note})" if note else "")
    if action == "remove":
        keep = [l for l in cur if not (id and id in l)]
        subprocess.run("crontab -", shell=True, input="\n".join(keep) + "\n", text=True)
        return "removed"
    return "action must be add|list|remove"

PROTECT = re.compile(r"zcode|ZCode|systemd|Xorg|gnome|pulseaudio|pipewire", re.I)

def process(action, pattern=None, pid=None):
    if action == "list":
        r = subprocess.run("ps -eo pid,pcpu,pmem,comm --sort=-pcpu | head -25",
                           shell=True, capture_output=True, text=True)
        return _cap(r.stdout)
    if action == "kill":
        if not pid:
            return "need pid"
        r = subprocess.run(f"ps -p {pid} -o comm=", shell=True,
                           capture_output=True, text=True)
        name = (r.stdout or "").strip()
        if not name:
            return f"no process {pid}"
        if PROTECT.search(name):
            return f"REFUSED: '{name}' is protected"
        subprocess.run(f"kill {pid}", shell=True)
        return f"sent SIGTERM to {pid} ({name})"
    return "action must be list|kill"

# ============================================================ registry + schemas

SCHEMAS = {
    "memory_save": (memory_save,
        "Save a durable fact/preference to long-term memory. Use when Dinesh says something worth remembering forever.",
        {"text": "the fact to remember, self-contained",
         "keywords": "list of 3-8 recall keywords", "type": "fact|preference|project|people|goal"}),
    "memory_search": (memory_search,
        "Search long-term memory notes for relevant knowledge.",
        {"query": "what to look for"}),
    "session_search": (session_search,
        "Search raw transcripts of past conversations ('remember when...').",
        {"query": "topic or words from the past conversation"}),
    "journal": (journal,
        "Append a timestamped line to the shared journal (mood notes, moments worth keeping).",
        {"text": "one line, may include his apparent mood"}),
    "todo": (todo,
        "Feynman's own promise tracker — things I said I'd do for Dinesh.",
        {"action": "add|list|done|remove", "text": "the item (for add)",
         "id": "item number (for done/remove)"}),
    "skills_list": (skills_list, "List my learned skills (procedural memory).", {}),
    "skill_view": (skill_view, "Read a skill's full instructions.",
                   {"name": "skill name"}),
    "skill_manage": (skill_manage,
        "Create/update/delete a skill — how I learn new procedures permanently.",
        {"action": "create|update|delete", "name": "skill name (kebab-case)",
         "content": "full SKILL.md content (markdown)"}),
    "terminal": (terminal,
        "Run a shell command on Dinesh's laptop (Linux). Destructive patterns are blocked.",
        {"command": "the command", "timeout": "seconds, default 60"}),
    "file_read": (file_read, "Read a text file with line numbers.",
                  {"path": "absolute path", "offset": "line to start from",
                   "limit": "max lines (default 400)"}),
    "file_write": (file_write, "Write/replace a file entirely.",
                   {"path": "absolute path", "content": "full new content"}),
    "file_edit": (file_edit,
        "Surgical edit: replace one exact string occurrence in a file.",
        {"path": "file", "old_text": "exact existing text",
         "new_text": "replacement"}),
    "search_files": (search_files,
        "Search file contents (ripgrep) or filenames under a path.",
        {"pattern": "text/regex to find", "path": "directory (default home)",
         "mode": "content|filename"}),
    "web_fetch": (web_fetch, "Fetch a web page and return readable text.",
                  {"url": "http(s) URL"}),
    "fire_task": (fire_task,
        "Fire a real agent task into Dinesh's ZCode app (full-access mode, appears in his task list, can use his browser).",
        {"prompt": "complete task instructions", "workspace": "absolute workspace path (default his agent-tasks folder)"}),
    "task_followup": (task_followup,
        "Send a follow-up message into a running/completed ZCode task.",
        {"task_id": "sess_ id from fire_task", "prompt": "the message"}),
    "task_status": (task_status,
        "Check a ZCode task's state (done/working) and last output.",
        {"task_id": "session id"}),
    "schedule": (schedule,
        "Manage scheduled items (cron). Format: 'm h * * *'.",
        {"action": "add|list|remove", "when": "cron expression",
         "command": "shell command", "note": "what it's for", "id": "substring to remove"}),
    "process": (process,
        "List processes or kill by pid (protected system apps refused).",
        {"action": "list|kill", "pattern": "filter", "pid": "process id"}),
}

def declarations():
    """Live API functionDeclarations block for session setup."""
    out = []
    for name, (fn, desc, params) in SCHEMAS.items():
        props = {k: {"type": "string"} for k in params}
        required = [k for k in list(params)[:2] if k in ("query", "text",
                    "command", "path", "prompt", "url", "action", "name")]
        out.append({"name": name, "description": desc,
                    "parameters": {"type": "object", "properties": props,
                                   "required": required}})
    return {"functionDeclarations": out}

def dispatch(name, args):
    """Run a tool by name; always returns a string result."""
    if name not in SCHEMAS:
        return f"unknown tool: {name}"
    fn, _, params = SCHEMAS[name]
    call = {k: args.get(k) for k in params if args.get(k) is not None}
    # coerce numeric-ish strings the model may send
    for k in ("timeout", "offset", "limit", "pid", "id"):
        if k in call:
            try:
                call[k] = int(float(str(call[k])))
            except (TypeError, ValueError):
                pass
    try:
        return fn(**call)
    except Exception as e:
        return f"tool error: {type(e).__name__}: {e}"

# ============================================================ smoke test
if __name__ == "__main__":
    print(f"{len(SCHEMAS)} tools registered\n")
    tests = [
        ("memory_save", {"text": "[smoke] wire test", "keywords": ["smoke"]}),
        ("memory_search", {"query": "smoke test"}),
        ("session_search", {"query": "notice period"}),
        ("journal", {"text": "[smoke] pipeline check"}),
        ("todo", {"action": "add", "text": "[smoke] verify todo"}),
        ("todo", {"action": "list"}),
        ("skills_manage" if "skills_manage" in SCHEMAS else "skill_manage",
         {"action": "create", "name": "smoke-test",
          "content": "# Smoke Test\nverify skill storage\n"}),
        ("skills_list", {}),
        ("terminal", {"command": "echo hello from feynman tools"}),
        ("file_write", {"path": "/tmp/feynman_smoke.txt", "content": "alpha beta\n"}),
        ("file_edit", {"path": "/tmp/feynman_smoke.txt",
                       "old_text": "beta", "new_text": "gamma"}),
        ("file_read", {"path": "/tmp/feynman_smoke.txt"}),
        ("search_files", {"pattern": "gamma", "path": "/tmp"}),
        ("schedule", {"action": "list"}),
        ("process", {"action": "list"}),
        ("task_status", {"task_id": "sess_f10ad5fc-18e4-463f-bf90-9684899067b7"}),
        ("fire_task", {"prompt": "[smoke] write smoke-tools.txt saying TOOLS OK"}),
    ]
    for name, args in tests:
        r = dispatch(name, args)
        print(f"{name:16s} -> {str(r)[:110]}")
    # cleanup smoke artifacts
    import brain.memory  # noqa
    dispatch("skill_manage", {"action": "delete", "name": "smoke-test"})
    subprocess.run("rm -f /tmp/feynman_smoke.txt", shell=True)
    c = _brain().conn
    c.execute("delete from notes where desc like '[smoke]%' or desc like '%smoke test%'")
    c.execute("delete from messages where text like '[smoke]%'")
    c.commit()
    lines = [l for l in _todo_lines() if "[smoke]" not in l]
    open(TODO_PATH, "w").write("\n".join(lines) + ("\n" if lines else ""))
    print("\nsmoke artifacts cleaned")
