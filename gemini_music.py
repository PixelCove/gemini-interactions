#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["google-genai"]
# ///
"""Generate Lyria 3 music via Google's Gemini **Interactions API** (google-genai SDK).

Migrated 2026-06-22 off Vertex AI (aiplatform.googleapis.com + gcloud access token) to the
Gemini Developer API with an API key resolved from 1Password at runtime (no token at rest,
no gcloud dependency — which kept expiring). Models: lyria-3-pro-preview (full song) /
lyria-3-clip-preview (30s). Defaults to --dry-run.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_PROJECT = "gemini-developer-api"   # metadata label only (no Vertex project now)
DEFAULT_MODEL = "lyria-3-pro-preview"
DEFAULT_OP_REF = os.environ.get("GEMINI_OP_REF", "")
ROOT = Path(__file__).resolve().parents[1]


def resolve_key(op_ref: str) -> str:
    """Env var wins; else resolve from 1Password at runtime. Never written to disk."""
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    r = subprocess.run(["op", "read", op_ref], capture_output=True, text=True, timeout=20)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    raise RuntimeError(f"No Gemini API key: set GEMINI_API_KEY or ensure `op` can read {op_ref}")


def load_prompts(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Prompt file must be a JSON list")
    prompts = []
    for idx, item in enumerate(data, 1):
        if isinstance(item, str):
            prompts.append({"id": f"track-{idx:03d}", "prompt": item})
        else:
            prompts.append(dict(item))
    return prompts


def post_lyria(client, model: str, prompt: str) -> dict:
    """Call the Interactions API; normalize to the {outputs:[...]} shape write_outputs expects."""
    interaction = client.interactions.create(model=model, input=prompt)
    outputs = []
    audio = getattr(interaction, "output_audio", None)
    if audio is not None and getattr(audio, "data", None):
        outputs.append({"type": "audio", "data": audio.data,
                        "mime_type": getattr(audio, "mime_type", "audio/mpeg")})
    text = getattr(interaction, "output_text", None)
    if text:
        outputs.append({"type": "text", "text": text})
    return {"outputs": outputs, "status": getattr(interaction, "status", "completed")}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe(path: Path) -> dict[str, Any]:
    if shutil.which("ffprobe") is None:
        return {"available": False, "error": "ffprobe not found"}
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-print_format",
        "json",
        str(path),
    ]
    try:
        raw = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - CLI diagnostic tool
        return {"available": True, "error": str(exc)}
    audio_streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    fmt = data.get("format", {})
    return {
        "available": True,
        "duration_sec": round(float(fmt.get("duration", 0) or 0), 2),
        "bit_rate": int(float(fmt.get("bit_rate", 0) or 0)),
        "format_name": fmt.get("format_name"),
        "audio_streams": [
            {
                "codec": s.get("codec_name"),
                "sample_rate": int(s.get("sample_rate", 0) or 0),
                "channels": s.get("channels"),
                "channel_layout": s.get("channel_layout"),
            }
            for s in audio_streams
        ],
    }


def write_qa_stub(path: Path, item: dict[str, Any]) -> None:
    probe = item.get("audio_probe") or {}
    duration = probe.get("duration_sec", "")
    text = (
        "# Track QA\n\n"
        f"- Artist: {item.get('artist', '')}\n"
        "- Track title: TODO\n"
        f"- Source file: {item.get('source_file', '')}\n"
        f"- Generator/tool: {item.get('source', '')}\n"
        f"- Prompt/source notes: {item.get('prompt', '')}\n"
        f"- Date generated: {time.strftime('%Y-%m-%d')}\n"
        f"- Duration: {duration}\n\n"
        "Scores 1-5:\n"
        "- Prompt adherence:\n"
        "- Mix quality:\n"
        "- Artifact rate:\n"
        "- No-vocal compliance:\n"
        "- Hook/listenability:\n"
        "- Distinctiveness:\n"
        "- Release readiness:\n\n"
        "Decision: reject / revise / candidate / release-ready\n\n"
        "Notes:\n\n"
        "Red flags:\n"
        "- [ ] Artist imitation\n"
        "- [ ] Copyright/sample concern\n"
        "- [ ] Fake real-person voice/likeness concern\n"
        "- [ ] Metadata/title issue\n"
        "- [ ] Bad ending/transition/artifact\n"
    )
    path.write_text(text, encoding="utf-8")


def _relpath(p: Path) -> str:
    """Path relative to the project root, or absolute if the outdir lives outside it."""
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p.resolve())


def write_outputs(outdir: Path, item: dict[str, Any], response: dict, project: str, model: str) -> dict[str, Any]:
    track_id = item["id"]
    prompt = item["prompt"]
    tdir = outdir / track_id
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "prompt.txt").write_text(prompt)
    (tdir / "response.json").write_text(json.dumps(response, indent=2))

    notes = [f"# {track_id} Lyria Notes\n", "## Prompt\n", prompt + "\n"]
    audio_files = []
    for i, output in enumerate(response.get("outputs", []) or []):
        typ = output.get("type")
        if typ == "audio" and output.get("data"):
            mime = output.get("mime_type", "")
            ext = "mp3" if mime == "audio/mpeg" else "audio"
            audio_path = tdir / f"track.{ext}"
            audio_path.write_bytes(base64.b64decode(output["data"]))
            audio_files.append(audio_path)
            notes.append(f"\n## Audio {i}\n- MIME: {mime}\n- File: `{audio_path.name}`\n- Bytes: {audio_path.stat().st_size}\n")
        elif typ == "text":
            notes.append(f"\n## Text output {i}\n\n{output.get('text', '')}\n")
    (tdir / "notes.md").write_text("\n".join(notes))

    primary_audio = audio_files[0] if audio_files else None
    item = {
        "id": track_id,
        "source": "lyria",
        "source_file": _relpath(primary_audio) if primary_audio else "",
        "sha256": sha256_file(primary_audio) if primary_audio else "",
        "artist": item.get("artist", "TBD"),
        "niche": item.get("niche", "TBD"),
        "artist_id": item.get("artist_id", ""),
        "project": project,
        "model": model,
        "prompt": prompt,
        "response_status": response.get("status"),
        "audio_probe": ffprobe(primary_audio) if primary_audio else {},
        "status": "needs_qa" if primary_audio else "no_audio_output",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (tdir / "candidate.json").write_text(json.dumps(item, indent=2) + "\n", encoding="utf-8")
    write_qa_stub(tdir / "qa.md", item)
    return item


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--run", action="store_true", help="Actually call Google Cloud Lyria and incur generation costs")
    args = parser.parse_args()

    prompts = load_prompts(args.prompts)
    if args.limit:
        prompts = prompts[: args.limit]

    print(f"project={args.project} model={args.model} prompts={len(prompts)} outdir={args.outdir}")
    for item in prompts:
        print(f"- {item['id']}: {item['prompt'][:110]}")

    if not args.run or args.dry_run:
        print("DRY_RUN: pass --run to generate audio")
        return 0

    from google import genai
    client = genai.Client(api_key=resolve_key(DEFAULT_OP_REF))
    args.outdir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for item in prompts:
        started = time.time()
        print(f"generating {item['id']}...", flush=True)
        response = post_lyria(client, args.model, item["prompt"])
        candidate = write_outputs(args.outdir, item, response, args.project, args.model)
        manifest.append({"id": item["id"], "status": response.get("status"), "candidate_status": candidate.get("status"), "elapsed_sec": round(time.time() - started, 2)})
        print(f"done {item['id']} status={response.get('status')}")
    (args.outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
