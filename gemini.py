#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["google-genai"]
# ///
"""
gemini — one CLI for Google's **Gemini Interactions API** (GA June 2026), the unified
front door to Gemini's generative surface. Four subcommands, one shared key resolution:

  gemini image     Image gen/edit (Nano Banana 2 / Pro)
  gemini music     Music gen (Lyria 3) — clips + full songs
  gemini tts       Text-to-speech, single- or multi-speaker → WAV
  gemini research  Maps/Search-grounded research + the Deep Research agent

Self-contained: deps auto-managed by `uv`, key from one env var. Run any subcommand
with `--help` for its flags.

  uv run gemini.py image --prompt "a minimal green leaf icon on white" --image-size 512 --out leaf.png
  uv run gemini.py tts   --text "Welcome to the show." --voice Kore --out vo.wav
  uv run gemini.py music --prompt "lofi hip hop, mellow, rainy night" --run --out beat.mp3
  uv run gemini.py research --query "top dentists near downtown Austin: ratings, gaps" --lat 30.27 --lng -97.74

Key resolution (in order): GEMINI_API_KEY / GOOGLE_API_KEY / GOOGLE_GENAI_API_KEY env,
then `op read $GEMINI_OP_REF` (and $GEMINI_OP_REF_FALLBACK) if 1Password's `op` is present.
Image/music need a billing-enabled key; grounding/Deep Research may need those features
enabled on the key's Cloud project. Image outputs carry Google's SynthID watermark.
"""
import argparse, base64, json, os, subprocess, sys, time

AUDIO_EXT = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav",
             "audio/x-wav": "wav", "audio/wave": "wav"}


# --------------------------------------------------------------------------- shared

def resolve_key(op_ref: str = "") -> str:
    """Env var wins; otherwise resolve from 1Password at runtime. Never written to disk."""
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    refs = [op_ref or os.environ.get("GEMINI_OP_REF", ""), os.environ.get("GEMINI_OP_REF_FALLBACK", "")]
    for ref in refs:
        if not ref:
            continue
        try:
            r = subprocess.run(["op", "read", ref], capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            break
    sys.exit("ERROR: no Gemini API key. Set GEMINI_API_KEY (or set GEMINI_OP_REF so `op` can read it).")


def get_client(args):
    try:
        from google import genai
    except ImportError:
        sys.exit("ERROR: google-genai not available. Run via `uv run gemini.py …` or `pip install google-genai`.")
    return genai.Client(api_key=resolve_key(getattr(args, "op_ref", "")))


# --------------------------------------------------------------------------- image

def _build_image_input(prompt: str, image_paths: list):
    if not image_paths:
        return prompt
    parts = [{"type": "text", "text": prompt}]
    for p in image_paths:
        with open(p, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        mime = "image/png" if p.lower().endswith(".png") else "image/jpeg"
        parts.append({"type": "image", "data": data, "mime_type": mime})
    return parts


def cmd_image(args):
    VALID_SIZES = {"512", "1K", "2K", "4K"}
    size = args.image_size.replace("k", "K")
    if size not in VALID_SIZES:
        sys.exit(f"ERROR: --image-size must be one of {sorted(VALID_SIZES)} (got {args.image_size})")
    if size == "512" and args.model != "gemini-3.1-flash-image":
        sys.exit("ERROR: 512px is only available on gemini-3.1-flash-image (Nano Banana 2).")

    client = get_client(args)
    payload = _build_image_input(args.prompt, args.input_image)
    response_format = {"type": "image", "aspect_ratio": args.aspect_ratio, "image_size": size}

    base = args.out or f"gemini-image-{int(time.time())}.png"
    if not base.lower().endswith(".png"):
        base += ".png"

    saved = []
    for i in range(max(1, args.count)):
        kwargs = dict(model=args.model, input=payload, response_format=response_format)
        if args.thinking:
            kwargs["generation_config"] = {"thinking_level": args.thinking}
        try:
            interaction = client.interactions.create(**kwargs)
        except Exception as e:
            sys.exit(f"ERROR: Interactions API call failed: {e}")

        img = getattr(interaction, "output_image", None)
        b64 = getattr(img, "data", None) if img is not None else None
        if not b64:
            sys.exit("ERROR: no image returned (likely a safety block — rephrase the prompt).")
        try:
            img_bytes = base64.b64decode(b64, validate=True)
        except Exception as e:
            sys.exit(f"ERROR: returned image data was not valid base64: {e}")
        out_path = base if args.count == 1 else base[:-4] + f"-{i + 1}.png"
        with open(out_path, "wb") as f:  # decode first, so a bad response can't truncate an existing file
            f.write(img_bytes)
        saved.append(os.path.abspath(out_path))

    print(json.dumps({"images": saved, "model": args.model, "aspect_ratio": args.aspect_ratio,
                      "image_size": size, "count": len(saved), "prompt": args.prompt}, indent=2))


def add_image(sub, common):
    p = sub.add_parser("image", parents=[common], help="image generation/editing (Nano Banana 2/Pro)")
    p.add_argument("--prompt", required=True)
    p.add_argument("--aspect-ratio", default="16:9")
    p.add_argument("--image-size", default="1K", help="512 | 1K | 2K | 4K (uppercase K)")
    p.add_argument("--model", default="gemini-3.1-flash-image",
                   help="gemini-3.1-flash-image (NB2) | gemini-3-pro-image (NB Pro)")
    p.add_argument("--thinking", default=None, choices=["low", "medium", "high"],
                   help="thinking_level (NB Pro only; high = best text rendering)")
    p.add_argument("--input-image", action="append", default=[],
                   help="reference/edit image path (repeatable, up to model limit)")
    p.add_argument("--count", type=int, default=1, help="number of variations")
    p.add_argument("--out", default=None, help="output path (.png); batch appends -N")
    p.set_defaults(func=cmd_image)


# --------------------------------------------------------------------------- music

def _load_music_prompts(args):
    """One --prompt, or a --prompts JSON file (list of strings or {id, prompt} objects)."""
    if args.prompt:
        return [{"id": "track", "prompt": args.prompt}]
    data = json.loads(open(args.prompts).read())
    if not isinstance(data, list):
        sys.exit("ERROR: --prompts file must be a JSON list (of strings or {id, prompt} objects).")
    out = []
    for i, item in enumerate(data, 1):
        if isinstance(item, str):
            out.append({"id": f"track-{i:03d}", "prompt": item})
        else:
            out.append({"id": item.get("id", f"track-{i:03d}"), "prompt": item["prompt"]})
    return out


def cmd_music(args):
    if bool(args.prompt) == bool(args.prompts):
        sys.exit("ERROR: pass exactly one of --prompt (single) or --prompts FILE (batch).")
    prompts = _load_music_prompts(args)
    if args.limit:
        prompts = prompts[: args.limit]

    print(f"model={args.model} prompts={len(prompts)}")
    for it in prompts:
        print(f"- {it['id']}: {it['prompt'][:110]}")
    if not args.run:
        print("DRY_RUN: pass --run to generate audio (this incurs Lyria generation cost).")
        return

    client = get_client(args)
    single = bool(args.prompt)
    outdir = None
    if not single:
        outdir = args.outdir or "."
        os.makedirs(outdir, exist_ok=True)

    written = []
    for it in prompts:
        print(f"generating {it['id']}…", flush=True)
        try:
            interaction = client.interactions.create(model=args.model, input=it["prompt"])
        except Exception as e:
            sys.exit(f"ERROR: Lyria call failed: {e}")
        audio = getattr(interaction, "output_audio", None)
        if audio is None or not getattr(audio, "data", None):
            sys.exit(f"ERROR: no audio returned for {it['id']} (status: {getattr(interaction, 'status', '?')}).")
        ext = AUDIO_EXT.get(getattr(audio, "mime_type", ""), "mp3")

        if single:
            audio_path = args.out or f"track.{ext}"
            if "." not in os.path.basename(audio_path):
                audio_path += f".{ext}"
        else:
            audio_path = os.path.join(outdir, f"{it['id']}.{ext}")
        with open(audio_path, "wb") as f:
            f.write(base64.b64decode(audio.data))

        lyrics = getattr(interaction, "output_text", None)
        lyrics_path = None
        if lyrics:
            lyrics_path = os.path.splitext(audio_path)[0] + ".lyrics.txt"
            with open(lyrics_path, "w") as f:
                f.write(lyrics)
        written.append({"id": it["id"], "audio": os.path.abspath(audio_path),
                        "lyrics": os.path.abspath(lyrics_path) if lyrics_path else None})
        print(f"  wrote {audio_path}")

    print(json.dumps({"model": args.model, "tracks": written}, indent=2))


def add_music(sub, common):
    p = sub.add_parser("music", parents=[common], help="music generation (Lyria 3)")
    p.add_argument("--prompt", default=None, help="single music prompt")
    p.add_argument("--prompts", default=None, help="JSON file: list of prompts (strings or {id, prompt})")
    p.add_argument("--model", default="lyria-3-pro-preview",
                   help="lyria-3-pro-preview (full song) | lyria-3-clip-preview (30s)")
    p.add_argument("--out", default=None, help="output audio path (single-prompt mode)")
    p.add_argument("--outdir", default=None, help="output dir (batch mode; default .)")
    p.add_argument("--limit", type=int, default=None, help="cap number of tracks (batch)")
    p.add_argument("--run", action="store_true", help="actually generate (incurs cost); omit for a dry run")
    p.set_defaults(func=cmd_music)


# --------------------------------------------------------------------------- tts

def _write_wav(path: str, pcm: bytes, rate: int = 24000):
    import wave
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(rate)
        wf.writeframes(pcm)


def cmd_tts(args):
    if args.speaker:
        if not all("=" in s for s in args.speaker):
            sys.exit("ERROR: --speaker must be 'Name=Voice' (e.g. --speaker Host=Kore).")
        if len(args.speaker) > 2:
            sys.exit("ERROR: multi-speaker TTS supports at most 2 speakers.")
        speech_config = [{"speaker": s.split("=", 1)[0], "voice": s.split("=", 1)[1]} for s in args.speaker]
    else:
        speech_config = [{"voice": args.voice}]

    client = get_client(args)
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
    _write_wav(args.out, base64.b64decode(audio.data))
    print(f"wrote {os.path.abspath(args.out)} ({os.path.getsize(args.out)} bytes)")


def add_tts(sub, common):
    p = sub.add_parser("tts", parents=[common], help="text-to-speech → WAV (single/multi-speaker)")
    p.add_argument("--text", required=True, help="text to speak (use 'Name: line' for multi-speaker)")
    p.add_argument("--voice", default="Kore", help="prebuilt voice (single-speaker)")
    p.add_argument("--speaker", action="append", default=[], help="multi-speaker map 'Name=Voice' (repeatable, max 2)")
    p.add_argument("--model", default="gemini-3.1-flash-tts-preview")
    p.add_argument("--out", default="tts.wav")
    p.set_defaults(func=cmd_tts)


# --------------------------------------------------------------------------- research

def _render_grounded(interaction):
    """Walk the steps schema → assembled text + place/search citations."""
    text_parts, sources = [], []
    for step in getattr(interaction, "steps", []) or []:
        if getattr(step, "type", None) != "model_output":
            continue
        for block in getattr(step, "content", []) or []:
            if getattr(block, "type", None) != "text":
                continue
            text_parts.append(block.text)
            for ann in (getattr(block, "annotations", None) or []):
                if getattr(ann, "type", None) in ("place_citation", "web_citation", "url_citation"):
                    sources.append({"name": getattr(ann, "name", None) or getattr(ann, "title", ""),
                                    "url": getattr(ann, "url", "")})
    if not text_parts and getattr(interaction, "output_text", None):
        text_parts.append(interaction.output_text)
    seen, deduped = set(), []
    for s in sources:
        if s.get("url") and s["url"] not in seen:
            seen.add(s["url"]); deduped.append(s)
    return "\n".join(text_parts).strip(), deduped


def cmd_research(args):
    client = get_client(args)
    chart = None  # (base64, mime) of the Deep Research native infographic, if any

    if args.deep or args.deep_max:
        agent = "deep-research-max-preview-04-2026" if args.deep_max else "deep-research-preview-04-2026"
        try:
            it = client.interactions.create(input=args.query, agent=agent, background=True)
        except Exception as e:
            sys.exit(f"ERROR: Deep Research start failed: {e}")
        sys.stderr.write(f"Deep Research started ({it.id}); polling…\n")
        deadline = time.monotonic() + 1800  # 30-min cap so a stuck/cancelled run can't poll forever
        while True:
            it = client.interactions.get(it.id)
            status = getattr(it, "status", None)
            if status == "completed":
                break
            if status in ("failed", "cancelled", "canceled", "expired", "error"):
                sys.exit(f"ERROR: Deep Research {status}: {getattr(it, 'error', None)}")
            if time.monotonic() > deadline:
                sys.exit(f"ERROR: Deep Research timed out after 30 min (last status: {status}, id: {it.id}).")
            time.sleep(10)
        parts, sources, seen = [], [], set()
        for st in (getattr(it, "steps", []) or []):
            if getattr(st, "type", None) != "model_output":
                continue
            for b in (getattr(st, "content", []) or []):
                t = getattr(b, "text", None)
                if t:
                    parts.append(t)
                for ann in (getattr(b, "annotations", None) or []):
                    url = getattr(ann, "url", None)
                    if url and url not in seen:
                        seen.add(url)
                        sources.append({"name": getattr(ann, "title", None) or url, "url": url})
        report = "\n\n".join(parts) or (getattr(it, "output_text", "") or "")
        img = getattr(it, "output_image", None)
        if img is not None and getattr(img, "data", None):
            chart = (img.data, getattr(img, "mime_type", "image/png"))
    else:
        def grounded(tool):
            try:
                it = client.interactions.create(model=args.model, input=args.query, tools=[tool])
            except Exception as e:
                sys.exit(f"ERROR: grounded call failed: {e}\n"
                         "(If this mentions Maps/grounding, enable 'Grounding with Google Maps' on the key's Cloud project.)")
            return _render_grounded(it)

        maps_tool = {"type": "google_maps"}
        if args.lat is not None and args.lng is not None:
            maps_tool |= {"latitude": args.lat, "longitude": args.lng}
        search_tool = {"type": "google_search"}

        if args.mode == "maps":
            report, sources = grounded(maps_tool)
        elif args.mode == "search":
            report, sources = grounded(search_tool)
        else:  # both — Maps and Search can't share a request, so run two passes and merge
            r1, s1 = grounded(maps_tool)
            r2, s2 = grounded(search_tool)
            report = f"### Maps-grounded\n\n{r1}\n\n### Search-grounded\n\n{r2}"
            seen, sources = set(), []
            for s in s1 + s2:
                k = s.get("url") or s.get("name")
                if k and k not in seen:
                    seen.add(k)
                    sources.append(s)

    if not report:
        sys.exit("ERROR: empty report returned.")

    chart_path = None
    if chart and args.out:
        try:
            chart_bytes = base64.b64decode(chart[0], validate=True)
        except Exception:
            chart_bytes = None
        if chart_bytes:
            mime = chart[1] or "image/png"
            ext = "png" if "png" in mime else ("jpg" if "jpeg" in mime else "img")
            chart_path = os.path.splitext(args.out)[0] + "-chart." + ext
            with open(chart_path, "wb") as f:
                f.write(chart_bytes)

    md = f"# Research\n\n**Query:** {args.query}\n\n{report}\n"
    if chart_path:
        md += f"\n## Chart\n\n![Deep Research chart]({os.path.basename(chart_path)})\n"
    if sources:
        md += "\n## Sources\n" + "".join(f"{i}. [{s['name']}]({s['url']})\n"
                                          for i, s in enumerate(sources, 1) if s.get("url"))
    if args.out:
        with open(args.out, "w") as f:
            f.write(md)

    print(json.dumps({
        "mode": "deep" if (args.deep or args.deep_max) else "grounded",
        "model": (None if (args.deep or args.deep_max) else args.model),
        "report_chars": len(report), "source_count": len(sources),
        "out": os.path.abspath(args.out) if args.out else None,
        "chart": os.path.abspath(chart_path) if chart_path else None,
    }, indent=2))
    print("\n----- REPORT -----\n" + md)


def add_research(sub, common):
    p = sub.add_parser("research", parents=[common], help="Maps/Search-grounded + Deep Research")
    p.add_argument("--query", required=True, help="research question (include the locale)")
    p.add_argument("--lat", type=float, default=None, help="latitude for 'near me' grounding")
    p.add_argument("--lng", type=float, default=None, help="longitude for 'near me' grounding")
    p.add_argument("--model", default="gemini-3.5-flash")
    p.add_argument("--mode", choices=["maps", "search", "both"], default="maps",
                   help="grounding source: maps (default), search, or both (two passes merged)")
    p.add_argument("--deep", action="store_true", help="use the Deep Research agent (background, slow)")
    p.add_argument("--deep-max", action="store_true", help="Deep Research Max (most comprehensive)")
    p.add_argument("--out", default=None, help="save the report markdown to this path")
    p.set_defaults(func=cmd_research)


# --------------------------------------------------------------------------- entry

def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--op-ref", default=os.environ.get("GEMINI_OP_REF", ""),
                        help="1Password secret ref for the key (used only if no env var is set)")

    ap = argparse.ArgumentParser(
        prog="gemini",
        description="One CLI for Google's Gemini Interactions API — image, music, speech, research.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add_image(sub, common)
    add_music(sub, common)
    add_tts(sub, common)
    add_research(sub, common)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
