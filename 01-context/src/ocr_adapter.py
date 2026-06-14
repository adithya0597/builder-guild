"""OCR adapter — G2 Multimodal RAG, OCR-first (G2).

Wraps the system tesseract CLI as a pure-local $0 OCR path. Zero Python OCR wrappers
(no pytesseract, no easyocr) — subprocess only, mirroring judge_adapter._call.

Design choice (Most et al., arXiv 2505.05666 "Lost in OCR Translation?"): OCR-based
retrieval GENERALIZES BETTER to unseen / varying-quality documents, while vision-native
(ColPali) does well on in-domain / fine-tuned documents — so default to OCR-first for
general document ingestion. We use tesseract-via-subprocess so the path stays $0/offline
with no model downloads. (Abstract-level reading; full results table not walked.)

Environment (read at CALL TIME — never at import):
    OCR_MODE   "local" (default) — declares the intent that OCR_CMD is a local binary.
    OCR_CMD    tesseract binary path. Default: "tesseract".
    OCR_ARGS   extra args. Default: "stdout" (produces text on stdout).

$0-or-STOP guard: OCR_CMD defaults to a LOCAL binary (tesseract), so the primary $0
guarantee is the local-by-default invocation, NOT the regex. The auth/payment/quota
regex (same pattern as web_fallback_adapter._AUTH_RE) is a BACKSTOP for the case where
an operator points OCR_CMD at a hosted OCR CLI — if its output signals auth/payment,
raise RuntimeError rather than silently fall back to a paid path.

_run is injectable so tests don't shell out (same pattern as judge_adapter).
"""
import os
import re
import subprocess

# Backstop regex — same broadened pattern as web_fallback_adapter._AUTH_RE. NOT the
# primary $0 guard (that is OCR_MODE=local + a local OCR_CMD); this catches a hosted
# CLI that an operator wired in by setting OCR_CMD to something non-local.
_AUTH_RE = re.compile(r"auth|api[ _-]?key|payment|billing|quota", re.I)


def extract(image_path, *, _run=None):
    """Run OCR on *image_path* and return the extracted text as a str.

    Args:
        image_path: path to a rasterized page image (PNG, TIFF, JPEG, …).
        _run:       injectable callable replacing subprocess.run in tests.

    Returns:
        Extracted text string (non-empty).

    Raises:
        RuntimeError: on any of —
            * auth/payment/quota signal in the CLI output ($0-or-STOP backstop),
            * the OCR binary not being found (FileNotFoundError),
            * the CLI timing out,
            * a non-zero exit code,
            * empty OCR output (so an empty long_context is never ingested).
    """
    # Read env AT CALL TIME — no import-time capture (mirrors web_fallback_adapter design note).
    # OCR_MODE is the explicit local-by-default declaration; only "local" is honored today.
    ocr_mode = os.environ.get("OCR_MODE", "local")
    ocr_cmd = os.environ.get("OCR_CMD", "tesseract")
    # Default args: <image> stdout  → tesseract writes recognised text to stdout
    ocr_args_env = os.environ.get("OCR_ARGS", "")
    extra = ocr_args_env.split() if ocr_args_env else ["stdout"]

    cmd = [ocr_cmd, image_path] + extra
    runner = _run if _run is not None else subprocess.run

    try:
        p = runner(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"OCR binary {ocr_cmd!r} not found (OCR_MODE={ocr_mode!r}). "
            f"Install tesseract or set OCR_CMD to a valid local binary: {e}"
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"OCR CLI {ocr_cmd!r} timed out after 60s: {e}")

    out = (p.stdout or "") + (p.stderr or "")

    # $0-or-STOP backstop: any auth/payment signal → hard stop, never continue to a paid path.
    if _AUTH_RE.search(out):
        raise RuntimeError(
            f"AUTH/PAYMENT prompt from OCR CLI — STOP, do not fall back to paid path: "
            f"{out[:300]}"
        )

    # Non-zero exit → fail loud (don't ingest partial/garbage). Some injected fakes won't set
    # returncode; treat a missing attribute as 0 (the fake explicitly models success).
    rc = getattr(p, "returncode", 0)
    if rc not in (0, None):
        raise RuntimeError(
            f"OCR CLI {ocr_cmd!r} exited with code {rc}: {(p.stderr or '')[:300]}"
        )

    text = p.stdout or ""
    # Reject empty OCR output so ingest_ocr_doc never writes an empty long_context.
    if not text.strip():
        raise RuntimeError(
            f"OCR produced no text for {image_path!r} (stderr: {(p.stderr or '')[:200]!r}). "
            f"Refusing to ingest empty content."
        )
    return text
