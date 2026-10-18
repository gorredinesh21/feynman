# Setup

## Prerequisites
- Python 3.10+
- A GCP project with Vertex AI enabled (`aiplatform.googleapis.com`)
- `gcloud` CLI authenticated: `gcloud auth application-default login`
- Linux with a mic + headset (headset strongly recommended — without echo
  cancellation the mic hears the model's voice and interrupts itself)

## Install
```bash
pip install -r requirements.txt   # websockets, sounddevice, fastembed, sqlite-vec (optional)
export FEYNMAN_GCP_PROJECT=your-project
export FEYNMAN_DATA=~/.feynman    # brain home
mkdir -p $FEYNMAN_DATA/brain
cp -r feynman/brain/dossiers_example $FEYNMAN_DATA/brain/dossiers
```

## Dossiers (the personality + the owner)
Edit the five markdown files in `$FEYNMAN_DATA/brain/dossiers/`:
`feynman_self` (who the companion is), `personal_profile`, `skill_profile`,
`voice` (real writing samples beat adjectives), `principles` (decision
rules). Keep each ≤ ~600 words. These are always injected — they are the
identity layer, and by design only *you* edit them.

## Run
```bash
python3 -m feynman.live
```
Speak. Interrupt it mid-sentence. `Ctrl+C` to quit. Every complete
utterance is already in the raw log.

## Nightly learning (sleep)
```bash
crontab -e
# 30 4 * * * cd /path/to/feynman && FEYNMAN_DATA=$FEYNMAN_DATA /usr/bin/python3 -c "from feynman.brain.extract_nightly import main" --auto >> $FEYNMAN_DATA/brain/out/nightly.log 2>&1
```
(or invoke `python3 feynman/brain/extract_nightly.py --auto` with the env set)

## Configuration (env)
| Var | Default | Meaning |
|---|---|---|
| `FEYNMAN_DATA` | `~/coding/PROJECTS/FEYNMAN` | brain home (db, dossiers, diary, skills) |
| `FEYNMAN_GCP_PROJECT` | — (must set) | Vertex project |
| `FEYNMAN_GCP_REGION` | `us-central1` | region |
| `FEYNMAN_MODEL` | `gemini-live-2.5-flash-native-audio` | live model |
| `FEYNMAN_VOICE` | `Puck` | Puck/Charon/Kore/Fenrir/Aoede |
| `FEYNMAN_ZCODE_DOOR` / `FEYNMAN_ZCODE_TOKEN` | `~/.zcode/cli/...` | optional app-task adapter |

## Optional: app-task adapter
`fire_task` / `task_followup` / `task_status` speak to a local token-gated
unix socket exposed by a patched coding-agent desktop app (private
integration; not part of this repo). Without it, those three tools report
"door not installed" and everything else works.
