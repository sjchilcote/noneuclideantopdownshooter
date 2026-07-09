"""tools/artgen/gen.py

Reusable OpenRouter image-generation helper for PERIHELION's generated-art
pipeline: prompt -> PNG, with API key loading from `.openrouter_key` at the
repo root (falls back to the OPENROUTER_API_KEY env var), retry-with-backoff,
and a running cost log persisted to tools/artgen/cost_log.json so repeated
invocations across a session share one running total.

The API key is read at call time and never printed, logged, or written
anywhere by this module -- only usage/cost numbers are recorded.

CLI:
    uv run python tools/artgen/gen.py --prompt "..." --out path.png [--model ...]
    uv run python tools/artgen/gen.py --process src.png --out dst.png [--w 480 --h 270]
    uv run python tools/artgen/gen.py --report      # print running spend/call count
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageEnhance

REPO_ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = REPO_ROOT / ".openrouter_key"
COST_LOG = Path(__file__).resolve().parent / "cost_log.json"

# "Nano Banana 2" -- Google's latest Gemini image-gen/edit model, best
# available quality-per-dollar on OpenRouter as of writing. Good for both
# texture-like and full-scene work per the art director's brief.
DEFAULT_MODEL = "google/gemini-3.1-flash-image"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_RETRIES = 3
RETRY_BACKOFF_S = 5.0


def _load_key() -> str:
    if KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
        if key:
            return key
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    raise RuntimeError(
        f"No OpenRouter API key found: {KEY_FILE} missing/empty and "
        "OPENROUTER_API_KEY not set."
    )


def _read_cost_log() -> dict:
    if COST_LOG.exists():
        try:
            return json.loads(COST_LOG.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"total_cost": 0.0, "calls": []}


def _write_cost_log(log: dict) -> None:
    COST_LOG.write_text(json.dumps(log, indent=2))


def total_spend() -> float:
    return _read_cost_log().get("total_cost", 0.0)


def call_count() -> int:
    return len(_read_cost_log().get("calls", []))


def generate_image(
    prompt: str,
    out_path: str | Path,
    *,
    model: str = DEFAULT_MODEL,
    negative: str | None = None,
    max_retries: int = MAX_RETRIES,
    reference_images: list[str | Path] | None = None,
) -> dict:
    """Generate one image from `prompt`, save the model's raw output as a
    PNG to `out_path`. Returns {path, size, cost, model, total_spend}.

    `reference_images`, if given, are attached as input images (base64 data
    URLs) alongside the text prompt -- image-edit / continuity mode, e.g.
    "same corridor as this reference but with X changed". Nano Banana-family
    models accept prior images this way in a single-turn user message.

    Raises RuntimeError on repeated failure or refusal -- never fabricates
    a placeholder image.
    """
    key = _load_key()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    full_prompt = prompt
    if negative:
        full_prompt += f"\n\nAvoid entirely: {negative}"

    if reference_images:
        content: list[dict] = [{"type": "text", "text": full_prompt}]
        for ref in reference_images:
            ref_bytes = Path(ref).read_bytes()
            ref_b64 = base64.b64encode(ref_bytes).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{ref_b64}"},
            })
        user_content: object = content
    else:
        user_content = full_prompt

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "modalities": ["image", "text"],
    }
    body = json.dumps(payload).encode()

    data = None
    last_err = None
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            API_URL, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = str(e)
        if attempt < max_retries:
            time.sleep(RETRY_BACKOFF_S * attempt)
    if data is None:
        raise RuntimeError(f"generate_image failed after {max_retries} attempts: {last_err}")

    msg = data["choices"][0]["message"]
    images = msg.get("images") or []
    if not images:
        refusal = msg.get("refusal")
        raise RuntimeError(
            f"model returned no image (refusal={refusal!r}); content={msg.get('content')!r}"
        )
    url = images[0]["image_url"]["url"]
    if not url.startswith("data:"):
        raise RuntimeError(f"unexpected image_url scheme: {url[:40]}")
    b64 = url.split(",", 1)[1]
    raw = base64.b64decode(b64)
    im = Image.open(io.BytesIO(raw))
    im.load()
    im.convert("RGB").save(out_path)

    usage = data.get("usage", {})
    cost = float(usage.get("cost", 0.0))

    log = _read_cost_log()
    log["total_cost"] = log.get("total_cost", 0.0) + cost
    log.setdefault("calls", []).append({
        "model": model,
        "out": str(out_path),
        "cost": cost,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "ts": time.time(),
    })
    _write_cost_log(log)

    return {
        "path": str(out_path),
        "size": im.size,
        "cost": cost,
        "model": model,
        "total_spend": log["total_cost"],
        "calls_so_far": len(log["calls"]),
    }


# ---------------------------------------------------------------------------
# post-processing
# ---------------------------------------------------------------------------

def downscale_to(im: Image.Image, w: int, h: int) -> Image.Image:
    """Center-crop to the target aspect ratio (if needed), then resize to
    exactly w x h with LANCZOS."""
    src_w, src_h = im.size
    target_ratio = w / h
    src_ratio = src_w / src_h
    if abs(src_ratio - target_ratio) > 1e-3:
        if src_ratio > target_ratio:
            new_w = int(round(src_h * target_ratio))
            x0 = (src_w - new_w) // 2
            im = im.crop((x0, 0, x0 + new_w, src_h))
        else:
            new_h = int(round(src_w / target_ratio))
            y0 = (src_h - new_h) // 2
            im = im.crop((0, y0, src_w, y0 + new_h))
    return im.resize((w, h), Image.LANCZOS)


def quantize_colors(im: Image.Image, n_colors: int = 64) -> Image.Image:
    q = im.quantize(colors=n_colors, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG)
    return q.convert("RGB")


def top_region_luminance(im: Image.Image, frac: float = 2 / 3) -> float:
    """Mean luminance (0..255) of the top `frac` of the image."""
    w, h = im.size
    top = im.crop((0, 0, w, max(1, int(h * frac)))).convert("L")
    hist = top.histogram()
    total = sum(hist)
    return sum(i * c for i, c in enumerate(hist)) / total if total else 0.0


def darken_multiply(im: Image.Image, factor: float) -> Image.Image:
    """Multiply all pixel values by `factor` (0..1), i.e. a multiply blend
    against black -- darkens without touching hue/contrast shape."""
    return ImageEnhance.Brightness(im).enhance(factor)


def ensure_text_safe(im: Image.Image, max_luma: float = 60.0, frac: float = 2 / 3) -> Image.Image:
    """Iteratively multiply-darken until the top `frac` of the image has
    mean luminance <= max_luma. No-op if already safe."""
    cur = im
    for _ in range(8):
        luma = top_region_luminance(cur, frac)
        if luma <= max_luma:
            return cur
        factor = max(0.5, min(0.95, (max_luma / max(luma, 1.0)) ** 0.8))
        cur = darken_multiply(cur, factor)
    return cur


def process_asset(
    src_path: str | Path,
    out_path: str | Path,
    w: int = 480,
    h: int = 270,
    quantize: int | None = 64,
    max_luma: float = 60.0,
    luma_frac: float = 2 / 3,
) -> dict:
    """Full post-process pipeline: downscale -> darken-for-text-safety ->
    optional quantize. Writes out_path, returns a verification dict."""
    im = Image.open(src_path).convert("RGB")
    im = downscale_to(im, w, h)
    im = ensure_text_safe(im, max_luma=max_luma, frac=luma_frac)
    if quantize:
        im = quantize_colors(im, quantize)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)

    final = Image.open(out_path).convert("RGB")
    return {
        "path": str(out_path),
        "size": final.size,
        "top_luma": top_region_luminance(final, luma_frac),
        "text_safe": top_region_luminance(final, luma_frac) <= max_luma + 1e-6,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", type=str, default=None)
    ap.add_argument("--negative", type=str, default=None)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--model", type=str, default=DEFAULT_MODEL)
    ap.add_argument("--ref", action="append", default=None,
                     help="reference image path for image-edit continuity (repeatable)")
    ap.add_argument("--process", type=str, default=None, help="post-process an existing src PNG")
    ap.add_argument("--w", type=int, default=480)
    ap.add_argument("--h", type=int, default=270)
    ap.add_argument("--quantize", type=int, default=64)
    ap.add_argument("--max-luma", type=float, default=60.0)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.report:
        log = _read_cost_log()
        print(f"total_spend=${log.get('total_cost', 0.0):.4f} calls={len(log.get('calls', []))}")
        return

    if args.process:
        if not args.out:
            raise SystemExit("--process requires --out")
        result = process_asset(
            args.process, args.out, w=args.w, h=args.h,
            quantize=args.quantize or None, max_luma=args.max_luma,
        )
        print(json.dumps(result, indent=2))
        return

    if not args.prompt or not args.out:
        raise SystemExit("--prompt and --out are required for generation")
    result = generate_image(args.prompt, args.out, model=args.model, negative=args.negative,
                             reference_images=args.ref)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()
