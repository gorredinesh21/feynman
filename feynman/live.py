#!/usr/bin/env python3
"""
Gemini Live — native-audio voice agent (Phase 1)
===============================================
Talk to gemini-live-2.5-flash-native-audio on YOUR GCP project.
Audio in -> model -> audio out. No STT, no TTS, one websocket.

THE MAP (theory report -> code):
  Actor 1: this orchestrator (the only thing always running)
  Actor 2: the websocket (never closes while we talk)
  Actor 3: the model (exists only inside turns — see receiver loop)
  Barge-in: serverContent.interrupted -> flush speaker buffer (1 line)

Wiring:
  mic --(100ms PCM chunks)--> websocket --> [model]
  [model] --> websocket --(audio chunks)--> speaker
  your voice during its speech -> server VAD -> interrupted -> we stop playback

TIP: use a HEADSET. Without echo-cancellation the mic hears the model's
voice from your speakers and interrupts itself.
"""
import asyncio, base64, json, queue, subprocess, sys, threading
import sounddevice as sd
try:
    from .brain.memory import Brain
    from . import tools as FT, config
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from feynman.brain.memory import Brain
    from feynman import tools as FT, config
import os
BRAIN = Brain()                       # Wire 1: the learning pipe

# ---------------------------------------------------------------- CONFIG (env-driven; see config.py)
PROJECT = config.GCP_PROJECT
MODEL   = config.MODEL
VOICE   = config.VOICE               # Puck | Charon | Kore | Fenrir | Aoede
SYSTEM  = ("You are Dinesh's voice assistant. Warm, brief, technically sharp. "
           "He is an AI engineer — talk to him like a smart friend, not a chatbot.")
IN_RATE  = 16000                      # mic: 16kHz mono int16 (what the model wants)
OUT_RATE = 24000                      # model speech: 24kHz mono int16
URL = config.LIVE_URL

def token():
    return subprocess.run(["gcloud", "auth", "print-access-token"],
                          capture_output=True, text=True).stdout.strip()

# ------------------------------------------------------- SPEAKER (Actor 1)
class Speaker(threading.Thread):
    """Plays model audio chunks. flush() = the barge-in kill-switch."""
    def __init__(self):
        super().__init__(daemon=True)
        self.buf = queue.Queue()
        self.lock = threading.Lock()
        self.stream = sd.RawOutputStream(
            samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=4800)
        self.stream.start()

    def play(self, pcm: bytes):
        with self.lock:
            self.buf.put(pcm)

    def flush(self):                       # <- interruption: drop everything not yet played
        with self.lock:
            drained = 0
            while True:
                try: self.buf.get_nowait(); drained += 1
                except queue.Empty: break
        if drained: print(f"\n     [cut — dropped {drained} unplayed chunk(s)]")

    def run(self):
        while True:
            pcm = self.buf.get()
            self.stream.write(pcm)

# ------------------------------------------------- SETUP MESSAGE (the session)
def setup_message():
    return {"setup": {
        "model": f"projects/{PROJECT}/locations/us-central1/publishers/google/models/{MODEL}",
        "generation_config": {
            "response_modalities": ["AUDIO"],
            "speech_config": {"voice_config": {
                "prebuilt_voice_config": {"voice_name": VOICE}}},
        },
        "system_instruction": {"parts": [{"text": BRAIN.build_system_prompt()}]},
        # endpointing dials (theory report §4): how much silence = "he's done talking"
        "realtime_input_config": {"automatic_activity_detection": {
            "silence_duration_ms": 600,          # snappier than the 2000ms default
            "prefix_padding_ms": 500,
        }},
        # live transcripts of BOTH sides — proof the model does its own STT
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        # the tool belt (Wire: tools bound here, dispatched on toolCall)
        "tools": FT.declarations(),
    }}

# ------------------------------------------------------------ TOOL DISPATCH
async def run_tool(fc):
    """Execute a model-requested tool off-thread and answer into the session."""
    name, args = fc.get("name"), fc.get("args") or {}
    print(f"\n🔧 tool: {name} {str(args)[:120]}")
    try:
        result = await asyncio.to_thread(FT.dispatch, name, args)
    except Exception as e:
        result = f"tool crashed: {e}"
    print(f"🔧 result: {str(result)[:140]}")
    await ws.send(json.dumps({"tool_response": {"id": fc.get("id"),
                                                "response": {"result": result}}}))

# ---------------------------------------------------------------- MAIN LOOP
async def run():
    import websockets
    global ws
    print(f"connecting to {MODEL} on {PROJECT} ...")
    ws = await websockets.connect(
        URL, additional_headers={"Authorization": f"Bearer {token()}"},
        open_timeout=15, max_size=2**22)
    await ws.send(json.dumps(setup_message()))
    print("connected. Ctrl+C to quit.\n")

    speaker = Speaker(); speaker.start()
    mic_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    # Wire 1: turn streams into complete utterances, log them to the brain
    in_buf, out_buf = [], []
    BRAIN.log("meta", "session_start")
    def flush_user():
        global _unused
        if in_buf:
            BRAIN.log("user", "".join(in_buf).strip()); in_buf.clear()
    def flush_assistant():
        if out_buf:
            BRAIN.log("assistant", "".join(out_buf).strip()); out_buf.clear()

    # ---- MIC -> WEBSOCKET (your mouth; chunk up to ~100ms of PCM)
    def on_mic(indata, frames, time_info, status):
        loop.call_soon_threadsafe(mic_q.put_nowait, bytes(indata))
    mic = sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16",
                            blocksize=1600, callback=on_mic)   # 1600 frames = 100ms
    mic.start()

    async def sender():
        while True:
            chunk = await mic_q.get()
            await ws.send(json.dumps({"realtime_input": {"media_chunks": [{
                "mime_type": f"audio/pcm;rate={IN_RATE}",
                "data": base64.b64encode(chunk).decode()}]}}))

    async def receiver():
        async for raw in ws:
            msg = json.loads(raw)
            sc = msg.get("serverContent", {})

            if msg.get("setupComplete"):
                print(f"[session {msg['setupComplete'].get('sessionId','')[:8]} — speak now]")

            elif sc.get("interrupted"):                 # BARGE-IN (theory §5)
                speaker.flush()

            elif sc.get("modelTurn", {}).get("parts"):
                for part in sc["modelTurn"]["parts"]:
                    inline = part.get("inlineData")
                    if inline:
                        speaker.play(base64.b64decode(inline["data"]))

            elif sc.get("inputTranscription", {}).get("text"):
                t = sc["inputTranscription"]
                print(f"\r you: {t['text']}", end="", flush=True)
                in_buf.append(t["text"])
                if t.get("finished"):
                    flush_user()

            elif sc.get("outputTranscription", {}).get("text"):
                t = sc["outputTranscription"]
                print(f"\r  ai: {t['text']}", end="", flush=True)
                out_buf.append(t["text"])
                if t.get("finished"):
                    flush_assistant()

            elif msg.get("toolCall", {}).get("functionCalls"):
                for fc in msg["toolCall"]["functionCalls"]:
                    asyncio.create_task(run_tool(fc))

            elif sc.get("turnComplete"):
                flush_user(); flush_assistant()
                print()                                  # tidy line after each turn

            if msg.get("error"):
                print("\n[server error]", json.dumps(msg["error"])[:300]); break

    try:
        await asyncio.gather(sender(), receiver())
    finally:
        mic.stop(); mic.close(); speaker.stream.stop(); speaker.stream.close()
        await ws.close()
        flush_user(); flush_assistant()
        BRAIN.log("meta", "session_end")

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nbye.")
