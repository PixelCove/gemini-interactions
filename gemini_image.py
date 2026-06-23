# /// script
# requires-python = ">=3.10"
# dependencies = ["google-genai"]
# ///
"""
seo-image-gen engine — Google Gemini **Interactions API** + **Nano Banana 2/Pro**.

Replaces the old nanobanana-mcp dependency. Self-contained: resolves the Gemini key
from 1Password (no secret at rest), calls client.interactions.create(...), writes PNG(s).

Models:
  gemini-3.1-flash-image  -> Nano Banana 2   (default; fast, high-volume, adds 512px)
  gemini-3-pro-image      -> Nano Banana Pro  (advanced reasoning + high-fidelity text)

Run (deps auto-managed by uv):
  uv run scripts/generate.py --prompt "..." --aspect-ratio 16:9 --image-size 1K --out og.png
"""
import argparse, base64, json, os, subprocess, sys, time

DEFAULT_OP_REF = os.environ.get("GEMINI_OP_REF", "")
FALLBACK_OP_REF = os.environ.get("GEMINI_OP_REF_FALLBACK", "")
VALID_SIZES = {"512", "1K", "2K", "4K"}


def resolve_key(op_ref: str) -> str:
    """Env var wins; otherwise resolve from 1Password at runtime. Never written to disk."""
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    for ref in (op_ref, FALLBACK_OP_REF):
        if not ref:
            continue
        try:
            r = subprocess.run(["op", "read", ref], capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            break
    sys.exit("ERROR: no Gemini API key. Set GEMINI_API_KEY (or set GEMINI_OP_REF so `op` can read it).")


def build_input(prompt: str, image_paths: list[str]):
    if not image_paths:
        return prompt
    parts = [{"type": "text", "text": prompt}]
    for p in image_paths:
        with open(p, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        mime = "image/png" if p.lower().endswith(".png") else "image/jpeg"
        parts.append({"type": "image", "data": data, "mime_type": mime})
    return parts


def extract_image_b64(interaction) -> str | None:
    """interaction.output_image.data is base64 per the Interactions API docs."""
    img = getattr(interaction, "output_image", None)
    if img is None:
        return None
    data = getattr(img, "data", None) or (img.get("data") if isinstance(img, dict) else None)
    return data


def main():
    ap = argparse.ArgumentParser(description="SEO image generation via Gemini Interactions API")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--aspect-ratio", default="16:9")
    ap.add_argument("--image-size", default="1K", help="512 | 1K | 2K | 4K (uppercase K)")
    ap.add_argument("--model", default="gemini-3.1-flash-image",
                    help="gemini-3.1-flash-image (NB2) | gemini-3-pro-image (NB Pro)")
    ap.add_argument("--thinking", default=None, choices=["low", "medium", "high"],
                    help="thinking_level (NB Pro only; high = best text rendering)")
    ap.add_argument("--input-image", action="append", default=[],
                    help="reference/edit image path (repeatable, up to model limit)")
    ap.add_argument("--count", type=int, default=1, help="number of variations")
    ap.add_argument("--out", default=None, help="output path (.png); batch appends -N")
    ap.add_argument("--op-ref", default=DEFAULT_OP_REF)
    args = ap.parse_args()

    size = args.image_size.replace("k", "K")
    if size not in VALID_SIZES:
        sys.exit(f"ERROR: --image-size must be one of {sorted(VALID_SIZES)} (got {args.image_size})")
    if size == "512" and args.model != "gemini-3.1-flash-image":
        sys.exit("ERROR: 512px is only available on gemini-3.1-flash-image (Nano Banana 2).")

    try:
        from google import genai
    except ImportError:
        sys.exit("ERROR: google-genai not available. Run via `uv run` or `pip install google-genai`.")

    client = genai.Client(api_key=resolve_key(args.op_ref))
    payload = build_input(args.prompt, args.input_image)
    response_format = {"type": "image", "aspect_ratio": args.aspect_ratio, "image_size": size}

    base = args.out or f"seo-image-{int(time.time())}.png"
    if not base.lower().endswith(".png"):
        base += ".png"

    saved = []
    for i in range(max(1, args.count)):
        kwargs = dict(model=args.model, input=payload, response_format=response_format)
        if args.thinking:
            kwargs["generation_config"] = {"thinking_level": args.thinking}
        try:
            interaction = client.interactions.create(**kwargs)
        except Exception as e:  # surface clean API errors to the skill
            sys.exit(f"ERROR: Interactions API call failed: {e}")

        b64 = extract_image_b64(interaction)
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

    print(json.dumps({
        "images": saved,
        "model": args.model,
        "aspect_ratio": args.aspect_ratio,
        "image_size": size,
        "count": len(saved),
        "prompt": args.prompt,
    }, indent=2))


if __name__ == "__main__":
    main()
