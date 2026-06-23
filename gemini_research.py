# /// script
# requires-python = ">=3.10"
# dependencies = ["google-genai"]
# ///
"""
seo-local-research engine — Google Gemini **Interactions API**, grounded in
**Google Maps + Google Search**, for local-SEO competitive research.

Two modes:
  default : one grounded model call (fast, cheap) — gemini-3.5-flash + google_maps
            (+ google_search). Returns a cited report with Maps place citations.
  --deep  : fires the Deep Research *agent* (deep-research-preview-04-2026) with
            background execution and polls to completion — heavyweight multi-step report.

Maps grounding gives competitor names, ratings, review counts, categories, hours —
data Claude can't reach natively — which is the point for local SEO / GEO.

Run (deps auto-managed by uv):
  uv run scripts/research.py --query "top personal-injury lawyers near downtown Providence RI: ratings, review counts, gaps" --lat 41.8240 --lng -71.4128
"""
import argparse, base64, json, os, subprocess, sys, time

DEFAULT_OP_REF = os.environ.get("GEMINI_OP_REF", "")
FALLBACK_OP_REF = os.environ.get("GEMINI_OP_REF_FALLBACK", "")


def resolve_key(op_ref: str) -> str:
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


def render_grounded(interaction) -> tuple[str, list[dict]]:
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
    # fallback to convenience property if steps were empty
    if not text_parts and getattr(interaction, "output_text", None):
        text_parts.append(interaction.output_text)
    seen, deduped = set(), []
    for s in sources:
        if s.get("url") and s["url"] not in seen:
            seen.add(s["url"]); deduped.append(s)
    return "\n".join(text_parts).strip(), deduped


def main():
    ap = argparse.ArgumentParser(description="Maps+Search-grounded local-SEO research via Gemini Interactions API")
    ap.add_argument("--query", required=True, help="research question (include the locale)")
    ap.add_argument("--lat", type=float, default=None, help="latitude for 'near me' grounding")
    ap.add_argument("--lng", type=float, default=None, help="longitude for 'near me' grounding")
    ap.add_argument("--model", default="gemini-3.5-flash")
    ap.add_argument("--mode", choices=["maps", "search", "both"], default="maps",
                    help="grounding source: maps (default — local/competitor data), search, "
                         "or both (two passes merged; they can't share one request)")
    ap.add_argument("--deep", action="store_true", help="use the Deep Research agent (background, slow)")
    ap.add_argument("--deep-max", action="store_true", help="Deep Research Max (most comprehensive)")
    ap.add_argument("--out", default=None, help="save the report markdown to this path")
    ap.add_argument("--op-ref", default=DEFAULT_OP_REF)
    args = ap.parse_args()

    try:
        from google import genai
    except ImportError:
        sys.exit("ERROR: google-genai not available. Run via `uv run` or `pip install google-genai`.")
    client = genai.Client(api_key=resolve_key(args.op_ref))

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
        # report = every text block across model_output steps; sources = URLCitation
        # annotations (deduped); the agent also emits ImageContent charts (no .text) — skipped here.
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
            return render_grounded(it)

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
            seen, sources = set(), []  # dedupe across the two passes by url (fallback name)
            for s in s1 + s2:
                k = s.get("url") or s.get("name")
                if k and k not in seen:
                    seen.add(k)
                    sources.append(s)

    if not report:
        sys.exit("ERROR: empty report returned.")

    # save the Deep Research native chart next to the report, if present (decode before writing)
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

    md = f"# Local-SEO research\n\n**Query:** {args.query}\n\n{report}\n"
    if chart_path:
        md += f"\n## Chart\n\n![Deep Research chart]({os.path.basename(chart_path)})\n"
    if sources:
        md += "\n## Sources\n" + "".join(f"{i}. [{s['name']}]({s['url']})\n" for i, s in enumerate(sources, 1) if s.get("url"))
    if args.out:
        with open(args.out, "w") as f:
            f.write(md)

    print(json.dumps({
        "mode": "deep" if (args.deep or args.deep_max) else "grounded",
        "model": (None if (args.deep or args.deep_max) else args.model),
        "report_chars": len(report),
        "source_count": len(sources),
        "out": os.path.abspath(args.out) if args.out else None,
        "chart": os.path.abspath(chart_path) if chart_path else None,
    }, indent=2))
    print("\n----- REPORT -----\n" + md)


if __name__ == "__main__":
    main()
