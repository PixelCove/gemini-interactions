# /// script
# requires-python = ">=3.10"
# dependencies = ["google-genai"]
# ///
"""
gemini_tts.py — text-to-speech via Google's Gemini **Interactions API**
(single- or multi-speaker), for voiceovers/narration. Outputs a WAV that the
HyperFrames video pipeline (or anything) can consume.

Key: GEMINI_API_KEY env var (open-source default); falls back to 1Password
(via `op read $GEMINI_OP_REF`) if `op` is available and GEMINI_OP_REF is set.

  uv run gemini_tts.py --text "Say warmly: Welcome to the show." --voice Kore --out vo.wav
  uv run gemini_tts.py --speaker "Host=Kore" --speaker "Guest=Puck" \
     --text "Host: Welcome.\nGuest: Glad to be here." --out podcast.wav
"""
import argparse, base64, os, subprocess, sys, wave

DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"
OP_REF = os.environ.get("GEMINI_OP_REF", "")


def resolve_key() -> str:
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    if OP_REF:
        try:
            r = subprocess.run(["op", "read", OP_REF], capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    sys.exit("ERROR: set GEMINI_API_KEY (or set GEMINI_OP_REF so `op` can read the key).")


def write_wav(path: str, pcm: bytes, rate: int = 24000):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(rate)
        wf.writeframes(pcm)


def main():
    ap = argparse.ArgumentParser(description="Gemini Interactions API TTS → WAV")
    ap.add_argument("--text", required=True, help="text to speak (use 'Name: line' for multi-speaker)")
    ap.add_argument("--voice", default="Kore", help="prebuilt voice (single-speaker)")
    ap.add_argument("--speaker", action="append", default=[], help="multi-speaker map 'Name=Voice' (repeatable)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default="tts.wav")
    args = ap.parse_args()

    try:
        from google import genai
    except ImportError:
        sys.exit("ERROR: google-genai not available. Run via `uv run`.")
    client = genai.Client(api_key=resolve_key())

    if args.speaker:
        if not all("=" in s for s in args.speaker):
            sys.exit("ERROR: --speaker must be 'Name=Voice' (e.g. --speaker Host=Kore).")
        if len(args.speaker) > 2:
            sys.exit("ERROR: multi-speaker TTS supports at most 2 speakers.")
        # Interactions API multi-speaker: flat list of {speaker, voice} (same container as single-speaker)
        speech_config = [{"speaker": s.split("=", 1)[0], "voice": s.split("=", 1)[1]} for s in args.speaker]
    else:
        speech_config = [{"voice": args.voice}]

    try:
        it = client.interactions.create(
            model=args.model,
            input=args.text.replace("\\n", "\n"),
            response_format={"type": "audio"},
            generation_config={"speech_config": speech_config},
        )
    except Exception as e:
        sys.exit(f"ERROR: TTS call failed: {e}")

    audio = getattr(it, "output_audio", None)
    if audio is None or not getattr(audio, "data", None):
        sys.exit("ERROR: no audio returned.")
    write_wav(args.out, base64.b64decode(audio.data))
    print(f"wrote {os.path.abspath(args.out)} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
