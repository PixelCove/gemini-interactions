---
name: gemini-interactions
description: "Generate images (Nano Banana 2/Pro), music (Lyria 3), speech/voiceovers (TTS), and grounded/Deep-Research reports (Maps + Search) via Google's Gemini Interactions API. Use when a task needs Gemini image/music/audio generation or Google-grounded research. Triggers: generate image, nano banana, lyria music, text to speech, voiceover, deep research, maps grounded, gemini interactions."
license: MIT
metadata:
  engine: "Gemini Interactions API (google-genai)"
  version: "0.2.0"
---

# gemini-interactions

One self-contained `uv`-run CLI for the Gemini Interactions API. Key from `GEMINI_API_KEY` (or `op read $GEMINI_OP_REF`). See [README.md](README.md) for full docs.

| Need | Run |
|------|-----|
| Image gen/edit | `uv run gemini.py image --prompt "…" --aspect-ratio 16:9 --image-size 1K --out img.png` |
| Voiceover / TTS | `uv run gemini.py tts --text "…" --voice Kore --out vo.wav` |
| Music (Lyria 3) | `uv run gemini.py music --prompt "…" --run --out beat.mp3` |
| Quick grounded research | `uv run gemini.py research --query "…" --lat L --lng L` |
| Deep cited report + chart | `uv run gemini.py research --deep --query "…" --out report.md` |

Each subcommand prints usage with `--help` (`uv run gemini.py <cmd> --help`). Models: image `gemini-3.1-flash-image` / `gemini-3-pro-image`; music `lyria-3-{clip,pro}-preview`; TTS `gemini-3.1-flash-tts-preview`; research `gemini-3.5-flash` + `deep-research-*` agents. Image/music need a billing-enabled key.
