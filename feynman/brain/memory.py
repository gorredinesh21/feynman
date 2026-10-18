#!/usr/bin/env python3
"""
FEYNMAN brain — the memory layer.

Three tiers of memory:
  Tier 1  Dossiers (personal_profile / skill_profile / voice / principles)
          → ALWAYS injected, verbatim.
  Tier 2  Notes (seed corpus + everything learned later)
          → retrieved per query: embeddings if available, keyword hooks otherwise.
  Tier 3  Raw session log (every message Feynman ever exchanges)
          → LIKE-searched, used only when notes don't cover it.

Usage from feynman.py:

    from brain.memory import Brain
    brain = Brain()                       # loads db, bootstraps seed notes
    system = brain.build_system_prompt(question)
    reply = gemini_call(system_prompt=system, user_prompt=question)
    brain.log("user", question); brain.log("assistant", reply)

CLI:
    python3 brain/memory.py --stats       # memory statistics
    python3 brain/memory.py --selftest    # end-to-end check
    python3 brain/memory.py --embed       # force-enable embeddings and smoke-test
"""
import json
import os
import re
import sqlite3
import sys
import time
import datetime

try:                                   # package import (repo layout)
    from .. import config
    BRAIN_DIR = config.BRAIN_DIR
    DB_PATH = config.DB_PATH
    SEED_PATH = config.SEED_PATH
    DOSSIER_DIR = config.DOSSIER_DIR
except ImportError:                     # standalone (legacy layout) — still env-aware
    _data = os.environ.get("FEYNMAN_DATA")
    BRAIN_DIR = (os.path.join(os.path.abspath(_data), "brain") if _data
                 else os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(BRAIN_DIR, "memory.db")
    SEED_PATH = os.path.join(BRAIN_DIR, "seed_notes.json")
    DOSSIER_DIR = BRAIN_DIR
DOSSIERS = ["feynman_self", "personal_profile", "skill_profile", "voice", "principles"]
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIMS = 384
# keyword-injection threshold — a lone fuzzy prefix is weak evidence
# (lesson from the ai-memory-layer demo: "what" is a prefix of "whatsapp")
HIT_THRESHOLD = 1.0


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class Brain:
    def __init__(self, db_path=DB_PATH, use_embeddings=None):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._model = None
        self._embed_ready = False
        self._init_schema()
        self.bootstrap_seed()
        if use_embeddings is None:
            # embeddings on by default ONLY if explicitly enabled: model load can
            # hit the network on first use; keyword mode is instant and offline.
            use_embeddings = os.environ.get("FEYNMAN_EMBED", "0") == "1"
        self.use_embeddings = use_embeddings

    # ---------- schema ----------
    def _init_schema(self):
        c = self.conn
        c.execute(
            """CREATE TABLE IF NOT EXISTS messages(
                 id INTEGER PRIMARY KEY,
                 ts TEXT NOT NULL,
                 role TEXT NOT NULL,
                 text TEXT NOT NULL)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS notes(
                 id INTEGER PRIMARY KEY,
                 file TEXT NOT NULL,
                 type TEXT,
                 desc TEXT NOT NULL,
                 kw TEXT NOT NULL DEFAULT '[]',
                 text TEXT,
                 source TEXT DEFAULT 'seed',
                 ts TEXT NOT NULL)"""
        )
        c.commit()

    # ---------- embeddings (optional tier-2 upgrade) ----------
    def _load_embedder(self):
        if self._embed_ready:
            return True
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            print("[brain] sqlite-vec not installed — keyword retrieval active "
                  "(pip install sqlite-vec fastembed to enable embeddings)")
            return False
        try:
            import sqlite_vec
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            self.conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING "
                f"vec0(note_id INTEGER PRIMARY KEY, embedding float[{EMBED_DIMS}])"
            )
            self.conn.commit()
        except Exception as e:  # extension load failure → fall back cleanly
            print(f"[brain] sqlite-vec load failed ({e}) — keyword retrieval active")
            return False
        try:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(EMBED_MODEL)
        except Exception as e:
            print(f"[brain] fastembed load failed ({e}) — keyword retrieval active")
            return False
        self._embed_ready = True
        return True

    def _embed(self, texts):
        return [list(map(float, e)) for e in self._model.embed(texts)]

    def _sync_note_vectors(self):
        """Embed any notes that don't have a vector yet."""
        if not self._load_embedder():
            return
        rows = self.conn.execute(
            """SELECT n.id, n.desc, n.text FROM notes n
               LEFT JOIN vec_notes v ON v.note_id = n.id
               WHERE v.note_id IS NULL"""
        ).fetchall()
        if not rows:
            return
        vecs = self._embed([f"{r['desc']} {r['text'] or ''}" for r in rows])
        for r, v in zip(rows, vecs):
            self.conn.execute(
                "INSERT INTO vec_notes(note_id, embedding) VALUES (?, ?)",
                (r["id"], json.dumps(v)),
            )
        self.conn.commit()

    # ---------- tier 2: notes ----------
    def bootstrap_seed(self, force=False):
        n = self.conn.execute("SELECT COUNT(*) c FROM notes WHERE source='seed'").fetchone()["c"]
        if n and not force:
            return
        if force:
            self.conn.execute("DELETE FROM notes WHERE source='seed'")
        if not os.path.exists(SEED_PATH):
            print("[brain] no seed_notes.json — starting with an empty store")
            return
        with open(SEED_PATH) as f:
            seeds = json.load(f)
        for s in seeds:
            self.conn.execute(
                "INSERT INTO notes(file,type,desc,kw,text,source,ts) VALUES (?,?,?,?,?,? ,?)",
                (s["file"], s.get("type", "fact"), s["desc"],
                 json.dumps(s.get("kw", [])), s.get("desc"), "seed", _now()),
            )
        self.conn.commit()
        print(f"[brain] seeded {len(seeds)} notes from corpus")

    def add_note(self, file, desc, kw=None, text=None, source="learned"):
        self.conn.execute(
            "INSERT INTO notes(file,type,desc,kw,text,source,ts) VALUES (?,?,?,?,?,?,?)",
            (file, "fact", desc, json.dumps(kw or []), text or desc, source, _now()),
        )
        self.conn.commit()

    # ---------- retrieval ----------
    def _keyword_score(self, note_row, query):
        q = query.lower()
        words = [w for w in re.split(r"[^a-z0-9]+", q) if len(w) > 1]
        score = 0.0
        for k in json.loads(note_row["kw"] or "[]"):
            k = k.lower()
            if k in q:
                score += 2.0
            else:
                for w in words:
                    if len(w) >= 4 and (w.startswith(k) or k.startswith(w)):
                        score += 0.5
        # desc words count for a little
        for w in words:
            if len(w) >= 4 and w in note_row["desc"].lower():
                score += 0.25
        return score

    def recall(self, query, k=3):
        """Top-k relevant notes above threshold. Embeddings if enabled, keywords otherwise."""
        if self.use_embeddings and self._load_embedder():
            self._sync_note_vectors()
            qv = json.dumps(self._embed([query])[0])
            rows = self.conn.execute(
                """SELECT n.file, n.desc, n.text, v.distance
                   FROM (SELECT note_id, distance FROM vec_notes
                         WHERE embedding MATCH ? AND k = ?) v
                   JOIN notes n ON n.id = v.note_id
                   ORDER BY v.distance""",
                (qv, k),
            ).fetchall()
            return [(r["file"], r["desc"], r["text"]) for r in rows]
        rows = self.conn.execute("SELECT * FROM notes").fetchall()
        scored = sorted(
            ((self._keyword_score(r, query), r) for r in rows),
            key=lambda t: -t[0],
        )
        return [(r["file"], r["desc"], r["text"])
                for s, r in scored if s >= HIT_THRESHOLD][:k]

    # ---------- tier 3: raw session log ----------
    def log(self, role, text):
        self.conn.execute(
            "INSERT INTO messages(ts, role, text) VALUES (?,?,?)",
            (_now(), role, text),
        )
        self.conn.commit()

    def search_sessions(self, query, k=2):
        words = [w for w in re.split(r"[^a-zA-Z0-9]+", query) if len(w) >= 4]
        hits = []
        if words:
            like = " OR ".join("text LIKE ?" for _ in words)
            params = [f"%{w}%" for w in words] + [k]
            hits = self.conn.execute(
                f"SELECT ts, role, text FROM messages WHERE {like} "
                f"ORDER BY id DESC LIMIT ?", params
            ).fetchall()
        return hits

    # ---------- prompt assembly ----------
    def build_system_prompt(self, query=None, k_notes=3, k_sessions=2,
                            budget_chars=24000):
        parts = []
        for name in DOSSIERS:
            path = os.path.join(DOSSIER_DIR, f"{name}.md")
            if not os.path.exists(path):
                print(f"[brain] warning: dossier missing: {path}")
                continue
            with open(path) as f:
                parts.append(f.read().strip())

        notes = self.recall(query, k=k_notes) if query else []
        if notes:
            body = "\n".join(f"- [{f}] {d}" for f, d, _ in notes)
            parts.append(
                "RELEVANT MEMORIES (retrieved for this message):\n" + body
            )

        sessions = self.search_sessions(query, k=k_sessions) if query else []
        if sessions:
            body = "\n".join(f"- ({r['ts']}, {r['role']}) {r['text'][:160]}"
                             for r in sessions)
            parts.append("PAST SESSION EXCERPTS (raw log matches):\n" + body)

        prompt = "\n\n---\n\n".join(parts)
        if len(prompt) > budget_chars:
            # drop oldest tier first: raw excerpts, then notes
            while len(prompt) > budget_chars and parts:
                for i in range(len(parts) - 1, len(DOSSIERS) - 1, -1):
                    if parts[i].startswith(("PAST SESSION", "RELEVANT")):
                        parts.pop(i)
                        break
                else:
                    break
                prompt = "\n\n---\n\n".join(parts)
        return prompt

    # ---------- maintenance ----------
    def stats(self):
        return {
            "notes_total": self.conn.execute("SELECT COUNT(*) c FROM notes").fetchone()["c"],
            "notes_learned": self.conn.execute(
                "SELECT COUNT(*) c FROM notes WHERE source='learned'").fetchone()["c"],
            "messages": self.conn.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"],
            "embeddings": self.use_embeddings and self._load_embedder()
                          and self.conn.execute("SELECT COUNT(*) c FROM vec_notes").fetchone()["c"],
            "db_path": self.db_path,
        }


def selftest():
    print("[brain] selftest start")
    b = Brain()
    b.log("user", "selftest: what is my notice period?")
    b.log("assistant", "selftest: 2 months, superseding the 30-day figure")

    hits = b.recall("when can I join a new job?", k=3)
    assert any("notice" in f for f, _, _ in hits), f"recall missed notice-period: {hits}"
    print(f"[brain] recall OK -> {[(f, s[:40]) for f, s, _ in hits]}")

    sess = b.search_sessions("notice period")
    assert sess, "session search failed"
    print(f"[brain] session search OK -> {len(sess)} hits")

    prompt = b.build_system_prompt("how should I answer the notice period question?")
    for must in ("PERSONAL PROFILE", "SKILL PROFILE", "VOICE", "PRINCIPLES",
                 "notice", "2 MONTHS"):
        assert must.lower() in prompt.lower(), f"prompt missing {must}"
    print(f"[brain] system prompt OK -> {len(prompt)} chars, all sections present")
    print(f"[brain] stats -> {b.stats()}")
    print("[brain] selftest PASSED")


if __name__ == "__main__":
    if "--embed" in sys.argv:
        os.environ["FEYNMAN_EMBED"] = "1"
        b = Brain(use_embeddings=True)
        t0 = time.time()
        b._sync_note_vectors()
        hits = b.recall("how should my resume be written?", k=3)
        dt = time.time() - t0
        print(f"[brain] embedding smoke-test: {len(hits)} hits in {dt:.1f}s -> "
              f"{[f for f, _, _ in hits]}")
    elif "--selftest" in sys.argv:
        selftest()
    else:
        print(json.dumps(Brain().stats(), indent=2, default=str))
