"""Feynman configuration — every personal path/value comes from the
environment with sensible defaults, so the repo ships no private data.

FEYNMAN_DATA   root for the brain db, dossiers, diary, skills, todo
FEYNMAN_GCP_PROJECT   Vertex AI project id (required for voice + nightly)
FEYNMAN_MODEL   live model id (default gemini-live-2.5-flash-native-audio)
FEYNMAN_VOICE   voice name (default Puck)
FEYNMAN_ZCODE_DOOR / _TOKEN   optional ZCode app-task adapter sockets
"""
import os

DATA_DIR = os.path.abspath(os.environ.get(
    "FEYNMAN_DATA", os.path.expanduser("~/coding/PROJECTS/FEYNMAN")))
BRAIN_DIR = os.path.join(DATA_DIR, "brain")
DB_PATH = os.path.join(BRAIN_DIR, "memory.db")
SEED_PATH = os.path.join(BRAIN_DIR, "seed_notes.json")
DOSSIER_DIR = BRAIN_DIR          # dossiers live beside the db

SKILLS_DIR = os.path.join(DATA_DIR, "skills")
OUT_DIR = os.path.join(BRAIN_DIR, "out")
TODO_PATH = os.path.join(OUT_DIR, "todo.md")
JOURNAL_PATH = os.path.join(OUT_DIR, "journal.md")

GCP_PROJECT = os.environ.get("FEYNMAN_GCP_PROJECT", "")
if not GCP_PROJECT:
    print("[feynman] set FEYNMAN_GCP_PROJECT=<your-gcp-project> "
          "(see docs/SETUP.md)")
GCP_REGION = os.environ.get("FEYNMAN_GCP_REGION", "us-central1")
MODEL = os.environ.get("FEYNMAN_MODEL", "gemini-live-2.5-flash-native-audio")
VOICE = os.environ.get("FEYNMAN_VOICE", "Puck")

LIVE_URL = (f"wss://{GCP_REGION}-aiplatform.googleapis.com/ws/"
            f"google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent")
GENERATE_URL = (f"https://{GCP_REGION}-aiplatform.googleapis.com/v1/projects/"
                f"{GCP_PROJECT}/locations/{GCP_REGION}/publishers/google/"
                f"models/gemini-2.5-flash:generateContent")

# optional ZCode app-task adapter (private deployment; not part of the OSS core)
ZCODE_DOOR = os.environ.get("FEYNMAN_ZCODE_DOOR",
                            os.path.expanduser("~/.zcode/cli/task-run.sock"))
ZCODE_TOKEN = os.environ.get("FEYNMAN_ZCODE_TOKEN",
                             os.path.expanduser("~/.zcode/cli/task-run.token"))

for d in (SKILLS_DIR, OUT_DIR):
    os.makedirs(d, exist_ok=True)
