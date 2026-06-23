# gemini-interactions

A small toolkit of single-file CLIs for Google's **Gemini Interactions API** — the unified API (GA June 2026) for image, music, speech, and agentic research. Each tool is a self-contained `uv`-run script: no install, deps auto-managed, key from one env var.

> The Interactions API is one front door to Gemini's generative surface. These wrap the highest-value pieces so you can script them in a line.

## Tools

| Tool | What it does | Model(s) |
|------|--------------|----------|
| `gemini_image.py` | Image generation + editing (Nano Banana 2 / Pro) — aspect ratio, resolution, reference images | `gemini-3.1-flash-image`, `gemini-3-pro-image` |
| `gemini_music.py` | Music generation (Lyria 3) — clips + full songs, 44.1 kHz stereo | `lyria-3-clip-preview`, `lyria-3-pro-preview` |
| `gemini_tts.py` | Text-to-speech, single- or multi-speaker (voiceovers, podcasts) → WAV | `gemini-3.1-flash-tts-preview` |
| `gemini_research.py` | Grounded research — Google **Maps**/Search grounding + the **Deep Research** agent (cited reports + native charts) | `gemini-3.5-flash`, `deep-research-*` |

## Setup

```bash
# one dependency: uv  (https://docs.astral.sh/uv/)
export GEMINI_API_KEY="your-key"      # from https://aistudio.google.com/apikey
```

Image/music need a **billing-enabled** key. Deep Research and grounding may require those features enabled on the key's Cloud project. (Optional: set `GEMINI_OP_REF` to resolve the key from 1Password via `op` instead.)

## Examples

```bash
# Image (Nano Banana 2)
uv run gemini_image.py --prompt "a minimal green leaf icon on white" --aspect-ratio 1:1 --image-size 512 --out leaf.png

# Voiceover (TTS) — drops straight into a video pipeline as a 24 kHz WAV
uv run gemini_tts.py --text "Say warmly: Welcome to the show." --voice Kore --out vo.wav
# multi-speaker podcast
uv run gemini_tts.py --speaker "Host=Kore" --speaker "Guest=Puck" --text "Host: Welcome.\nGuest: Glad to be here." --out podcast.wav

# Music (Lyria 3 clip)
uv run gemini_music.py --prompts prompts.json --outdir out --model lyria-3-clip-preview --run

# Grounded research — quick (Maps) and deep (cited report + chart)
uv run gemini_research.py --query "top dentists near downtown Austin: ratings, gaps" --lat 30.27 --lng -97.74
uv run gemini_research.py --deep --query "2026 local SEO best practices, cited" --out report.md   # also writes report-chart.png
```

## HyperFrames hookup (TTS → video)

`gemini_tts.py` emits a 24 kHz WAV that a [HyperFrames](https://github.com) composition consumes as a narration track:

```html
<audio src="vo.wav" data-start="0" data-duration="8.4" data-track-index="2"></audio>
```

Generate the voiceover, drop the `<audio>` element into the composition, then `hyperframes transcribe` for synced captions and `hyperframes render`.

## Notes
- Each script resolves the key as: `GEMINI_API_KEY` env → (optional) `op read $GEMINI_OP_REF`.
- Outputs carry Google's SynthID watermark (images) and grounding metadata (research).
- MIT licensed. Built on the `google-genai` SDK.
