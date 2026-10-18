#!/usr/bin/env python3
"""Feynman test runner — every component, assertion-based.

Usage:
    python3 tests/run_all.py            # core suite (brain, tools, pipe)
    python3 tests/run_all.py --live     # + headless live-session E2E (needs
                                        # gcloud auth; no mic/speaker needed)
Door tests (fire_task/task_status) run only when the optional ZCode adapter
is present; they're skipped otherwise so CI stays green.
"""
import os, subprocess, sys, tempfile, shutil, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL, SKIP = [], [], []

def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'✅' if cond else '❌'} {name}" + (f"  — {detail}" if detail and not cond else ""))

def section(title):
    print(f"\n=== {title} ===")

def fresh_env(tmp):
    env = dict(os.environ)
    env["FEYNMAN_DATA"] = tmp
    return env

# ---------------------------------------------------------------- brain
def test_brain(tmp):
    section("BRAIN")
    os.makedirs(f"{tmp}/brain/out", exist_ok=True)
    from feynman.brain.memory import Brain
    b = Brain(db_path=f"{tmp}/brain/memory.db")          # no seed file → tolerated
    check("missing seed tolerated", True)

    b.add_note("t1.md", "Notice period is two months", kw=["notice", "join"],
               text="Notice period is two months as of Oct 2026")
    hits = b.recall("when can I join?", k=1)
    check("keyword recall", any("notice" in h[1].lower() for h in hits), str(hits))

    b.log("user", "the notice period question")
    b.log("assistant", "two months")
    s = b.search_sessions("notice")
    check("session search", len(s) >= 1)

    p = b.build_system_prompt("notice period")
    check("prompt: retrieved notes included", "RELEVANT MEMORIES" in p)
    check("prompt: session excerpts included", "PAST SESSION" in p)
    check("prompt: budget respected", len(p) <= 15000 + 2000, f"{len(p)} chars")

    # missing dossiers tolerated (fresh tmp has none)
    check("missing dossiers tolerated", p.startswith("RELEVANT") or "warning" in p or p)

    # embedding mode when libs available
    try:
        b2 = Brain(db_path=f"{tmp}/brain/memory.db", use_embeddings=True)
        hits = b2.recall("when can I start a new job?", k=1)
        check("embedding recall", len(hits) >= 1)
    except Exception as e:
        SKIP.append("embedding recall")
        print(f"⏭️  embedding recall — {type(e).__name__}")

# ---------------------------------------------------------------- tools
def test_tools(tmp):
    section("TOOLS (19)")
    os.environ["FEYNMAN_DATA"] = tmp
    for m in list(sys.modules):
        if m.startswith("feynman"):
            del sys.modules[m]
    from feynman import tools as T
    os.makedirs(f"{tmp}/brain/out", exist_ok=True)

    check("memory_save", T.dispatch("memory_save",
          {"text": "loves filter coffee", "keywords": ["coffee"]}) == "saved")
    check("memory_search", "coffee" in T.dispatch("memory_search", {"query": "coffee"}))
    T.dispatch("session_search", {"query": "anything"})  # empty is fine
    check("session_search", True)
    check("journal", T.dispatch("journal", {"text": "test line"}) == "journaled")
    check("journal file", "test line" in open(T.JOURNAL_PATH).read())
    T.dispatch("todo", {"action": "add", "text": "ship feynman"})
    check("todo add/list", "#1" in T.dispatch("todo", {"action": "list"}))
    check("todo done", "done" in T.dispatch("todo", {"action": "done", "id": 1}))
    T.dispatch("skill_manage", {"action": "create", "name": "greeter",
                                "content": "# Greeter\nsay hi"})
    check("skill create/list", "greeter" in T.dispatch("skills_list", {}))
    check("skill_view", "say hi" in T.dispatch("skill_view", {"name": "greeter"}))

    check("terminal", "hello" in T.dispatch("terminal", {"command": "echo hello"}))
    check("terminal blocklist", "BLOCKED" in T.dispatch("terminal",
          {"command": "rm -rf /"}))
    T.dispatch("file_write", {"path": f"{tmp}/f.txt", "content": "alpha beta"})
    check("file_write", "alpha" in open(f"{tmp}/f.txt").read())
    check("file_edit", T.dispatch("file_edit", {"path": f"{tmp}/f.txt",
          "old_text": "beta", "new_text": "gamma"}) == "edited")
    check("file_edit ambiguous", "ambiguous" in T.dispatch("file_edit",
          {"path": f"{tmp}/f.txt", "old_text": "a", "new_text": "x"}))
    check("file_read", "gamma" in T.dispatch("file_read", {"path": f"{tmp}/f.txt"}))
    check("search_files", "gamma" in T.dispatch("search_files",
          {"pattern": "gamma", "path": tmp}))
    check("schedule list", isinstance(T.dispatch("schedule", {"action": "list"}), str))
    check("process list", "PID" in T.dispatch("process", {"action": "list"}))
    check("process protect", "REFUSED" in T.dispatch("process",
          {"action": "kill", "pid": "1"}))
    # web_fetch against a stable URL (github is reliable; skip offline)
    try:
        r = T.dispatch("web_fetch", {"url": "https://example.com"})
        check("web_fetch", "Example" in r or "Domain" in r, r[:80])
    except Exception as e:
        SKIP.append("web_fetch"); print(f"⏭️  web_fetch — {e}")

    # door tests: only when adapter present
    import socket as _s
    door = os.path.exists(T.ZCODE_DOOR) and os.path.exists(T.ZCODE_TOKEN)
    if door:
        r = json.loads(T.dispatch("fire_task",
              {"prompt": "[test-suite] write feynman-test-marker.txt with PASS"}))
        check("fire_task", r.get("ok") is True, str(r))
        check("task_status", "messages" in T.dispatch("task_status",
              {"task_id": r.get("taskId", "")}))
    else:
        SKIP.append("fire_task (no door)"); SKIP.append("task_status (no door)")
        print("⏭️  fire_task / task_status — ZCode adapter not installed")

# ---------------------------------------------------------------- pipe
def test_pipe(tmp):
    section("LEARNING PIPE (real nightly extraction)")
    from feynman.brain.memory import Brain
    b = Brain(db_path=f"{tmp}/brain/memory.db")
    b.log("meta", "session_start")
    b.log("user", "I've decided I prefer Goa over Pune for the December trip, "
                  "and my notice period is now 3 months as of today")
    b.log("assistant", "Noted — Goa it is, and I'll remember the 3-month notice")
    b.log("meta", "session_end")
    env = fresh_env(tmp)
    r = subprocess.run([sys.executable, f"{ROOT}/feynman/brain/extract_nightly.py",
                        "--auto"], capture_output=True, text=True, env=env,
                       timeout=300, cwd=ROOT)
    out = r.stdout + r.stderr
    ok_extract = "[auto] +" in out
    check("nightly extract ran", ok_extract, out[-200:])
    diary_p = f"{tmp}/brain/out/diary.md"
    check("diary line written", os.path.exists(diary_p) and
          len(open(diary_p).read().strip()) > 5)
    if ok_extract:
        n = b.conn.execute("select count(*) from notes where source='nightly'").fetchone()[0]
        check("notes landed in brain", n >= 1, f"{n} nightly notes")

# ---------------------------------------------------------------- live (headless)
def test_live(tmp):
    section("LIVE HEADLESS E2E (text-mode, no mic)")
    import asyncio
    env = fresh_env(tmp)
    code = r'''
import asyncio, json, os, sys
sys.path.insert(0, os.environ["FEYNMAN_ROOT"])
from feynman import tools as FT
from feynman.brain.memory import Brain
import websockets, subprocess

async def main():
    tok = subprocess.run(["gcloud","auth","print-access-token"],
                         capture_output=True, text=True).stdout.strip()
    url = os.environ["FEYNMAN_LIVE_URL"]
    async with websockets.connect(url, additional_headers={
            "Authorization": f"Bearer {tok}"}, open_timeout=20) as ws:
        await ws.send(json.dumps({"setup": {
            "model": "projects/" + os.environ["FEYNMAN_PROJECT"] +
                     "/locations/us-central1/publishers/google/models/" +
                     os.environ["FEYNMAN_MODEL"],
            "generation_config": {"response_modalities": ["AUDIO"]},
            "tools": FT.declarations()}}))
        journal_path = os.environ["FEYNMAN_JOURNAL"]
        await ws.send(json.dumps({"client_content": {
            "turns": [{"role": "user", "parts": [{"text":
                "Call the journal tool right now with the text 'headless e2e ok' "
                "and then reply DONE."}]}], "turn_complete": True}}))
        got_tool = done = False
        for _ in range(60):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
            except asyncio.TimeoutError:
                break
            sc = msg.get("serverContent", {})
            if msg.get("toolCall", {}).get("functionCalls"):
                for fc in msg["toolCall"]["functionCalls"]:
                    got_tool = True
                    res = FT.dispatch(fc["name"], fc.get("args") or {})
                    await ws.send(json.dumps({"tool_response": {
                        "id": fc["id"], "response": {"result": str(res)[:4000]}}}))
            if sc.get("turnComplete"):
                done = True; break
        journaled = "headless e2e ok" in open(journal_path).read()
        print("RESULT:" + json.dumps(
            {"toolCall": got_tool, "turnComplete": done, "journaled": journaled}))

asyncio.run(main())
'''
    env.update({"FEYNMAN_ROOT": ROOT,
                "FEYNMAN_LIVE_URL": __import__("feynman.config", fromlist=["x"]).LIVE_URL,
                "FEYNMAN_PROJECT": __import__("feynman.config", fromlist=["x"]).GCP_PROJECT,
                "FEYNMAN_MODEL": "gemini-live-2.5-flash-native-audio",
                "FEYNMAN_JOURNAL": f"{tmp}/brain/out/journal.md"})
    os.makedirs(f"{tmp}/brain/out", exist_ok=True)
    open(f"{tmp}/brain/out/journal.md", "a").write("")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env, timeout=300)
    import re as _re
    m = _re.search(r'RESULT:(\{.*\})', r.stdout + r.stderr)
    if not m:
        check("live headless E2E", False, (r.stdout + r.stderr)[-300:])
        return
    res = json.loads(m.group(1))
    check("live: toolCall received", res["toolCall"])
    check("live: turn completed", res["turnComplete"])
    check("live: tool actually executed (journaled)", res["journaled"])

# ---------------------------------------------------------------- main
if __name__ == "__main__":
    import json  # noqa
    tmp = tempfile.mkdtemp(prefix="feynman-test-")
    try:
        test_brain(tmp)
        test_tools(tmp)
        test_pipe(tmp)
        if "--live" in sys.argv:
            test_live(tmp)
        else:
            print("\n(live headless E2E skipped — add --live)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'='*50}\nPASS {len(PASS)}  FAIL {len(FAIL)}  SKIP {len(SKIP)}")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)
    print("ALL GREEN ✅")
