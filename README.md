# gemini-interactions

One small CLI for Google's **Gemini Interactions API** — the unified API (GA June 2026) for image, music, speech, and agentic research. A single self-contained `uv`-run script: no install, deps auto-managed, key from one env var.

> The Interactions API is one front door to Gemini's generative surface. This wraps the highest-value pieces so you can script them in a line.

## Subcommands

| Command | What it does | Model(s) |
|---------|--------------|----------|
| `gemini image` | Image generation + editing (Nano Banana 2 / Pro) — aspect ratio, resolution, reference images | `gemini-3.1-flash-image`, `gemini-3-pro-image` |
| `gemini music` | Music generation (Lyria 3) — clips + full songs, with lyrics | `lyria-3-pro-preview`, `lyria-3-clip-preview` |
| `gemini tts` | Text-to-speech, single- or multi-speaker (voiceovers, podcasts) → WAV | `gemini-3.1-flash-tts-preview` |
| `gemini research` | Grounded research — Google **Maps**/Search grounding + the **Deep Research** agent (cited reports + native charts) | `gemini-3.5-flash`, `deep-research-*` |

Run any subcommand with `--help` for its flags.

## Setup

```bash
# one dependency: uv  (https://docs.astral.sh/uv/)
export GEMINI_API_KEY="your-key"      # from https://aistudio.google.com/apikey
```

Image/music need a **billing-enabled** key. Deep Research and grounding may require those features enabled on the key's Cloud project. (Optional: set `GEMINI_OP_REF` to resolve the key from 1Password via `op` instead of an env var.)

## Examples

```bash
# Image (Nano Banana 2)
uv run gemini.py image --prompt "a minimal green leaf icon on white" --aspect-ratio 1:1 --image-size 512 --out leaf.png

# Voiceover (TTS) — drops straight into a video pipeline as a 24 kHz WAV
uv run gemini.py tts --text "Say warmly: Welcome to the show." --voice Kore --out vo.wav
# multi-speaker podcast
uv run gemini.py tts --speaker "Host=Kore" --speaker "Guest=Puck" --text "Host: Welcome.\nGuest: Glad to be here." --out podcast.wav

# Music (Lyria 3) — dry run by default; --run generates (and incurs cost)
uv run gemini.py music --prompt "lofi hip hop, mellow, rainy night" --run --out beat.mp3
uv run gemini.py music --prompts prompts.json --outdir out --model lyria-3-clip-preview --run   # batch

# Grounded research — quick (Maps) and deep (cited report + chart)
uv run gemini.py research --query "top dentists near downtown Austin: ratings, gaps" --lat 30.27 --lng -97.74
uv run gemini.py research --deep --query "2026 local SEO best practices, cited" --out report.md   # also writes report-chart.png
```

`gemini.py` is also directly executable (`./gemini.py image …`) via its `uv` shebang.

## HyperFrames hookup (TTS → video)

`gemini tts` emits a 24 kHz WAV that a [HyperFrames](https://github.com) composition consumes as a narration track:

```html
<audio src="vo.wav" data-start="0" data-duration="8.4" data-track-index="2"></audio>
```

Generate the voiceover, drop the `<audio>` element into the composition, then `hyperframes transcribe` for synced captions and `hyperframes render`.

## Notes
- Key resolution order: `GEMINI_API_KEY` / `GOOGLE_API_KEY` / `GOOGLE_GENAI_API_KEY` env → (optional) `op read $GEMINI_OP_REF` (and `$GEMINI_OP_REF_FALLBACK`).
- `research --mode both` runs two passes (Maps + Search can't share one request) and merges the sources.
- Outputs carry Google's SynthID watermark (images) and grounding metadata (research).
- MIT licensed. Built on the `google-genai` SDK.

## Disclaimer

Unofficial. This project is **not affiliated with, endorsed by, or sponsored by Google**. It is an independent, MIT-licensed wrapper around Google's publicly documented Gemini Interactions API. *Gemini*, *Nano Banana*, *Lyria*, and related names are trademarks of Google LLC, used here only descriptively to identify the API and models this tool integrates with. Use of those APIs is subject to Google's own terms.
