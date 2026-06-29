"""eval_ocr.py — acceptance tests for G2 Multimodal RAG, OCR-first (G2).

Tests:
    T1  real OCR:         generate fixture PNG, run tesseract via ocr_adapter, assert planted text recovered.
    T2  $0-or-STOP:       inject _run returning an auth/payment string -> assert RuntimeError raised.
    T3  env-at-call-time: set OCR_CMD after import -> assert it takes effect (no import-time capture).
    T4  serve() demo:     OCR fixture -> ingest_ocr_doc() into a REAL role namespace -> serve() through
                          the genuine scope->ladder path retrieves it; serve()'s own isolation is clean;
                          a DIFFERENT role's serve() does NOT surface it. Gated on neo4j AND a locally-
                          cached embed model ($0/offline fail-closed — never downloads).
    A/B smoke:            NOT a valid comparison. OCR side = planted-token recovery smoke; vision side
                          (CLIP) only if a model is already cached locally (local_files_only=True, never
                          downloads). No winner is implied.

Prints OCR_OK iff T1-T4 all PASS. If T4 is SKIPPED on a missing dependency (neo4j down or
embed model not cached), prints OCR_PARTIAL (exit 3) — NOT a full pass. OCR_FAIL (exit 1) if any
test that ran failed. A/B is always reported, never gates.

Fixture note: OCR operates on rasterised page images (what a scanned PDF becomes). The fixture
is a page-image PNG so this eval stays $0 without a PDF rasteriser (poppler/pdf2image is a
documented add-on for born-digital PDFs).
"""
import os

# $0/offline fail-closed: force HuggingFace into offline mode BEFORE any import that could
# load a model (sentence_transformers / embed). With these set, a cached model loads from
# disk but a missing one raises instead of hitting the network — no metadata call, no download.
# setdefault so an explicit operator override still wins.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import sys
import tempfile

# Make 01-context/src importable (mirrors eval_corrective.py convention)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "01-context", "src"))

import ocr_adapter as _ocr_mod


# ---------------------------------------------------------------------------
# Fixture generation — NOT checked in; generated at runtime via Pillow
# ---------------------------------------------------------------------------

# ACME-scrubbed planted fact: issue SPI-42 is ASSIGNED_TO agent:cto.
# The fixture renders the fact as "issue SPI-42 is ASSIGNED TO agent cto" (spaces,
# no colon/underscore) because tesseract's default bitmap font mangled punctuation
# in initial testing. The OCR assertion checks key tokens — not the raw relation
# syntax — to stay honest about what tesseract actually recovers from rasterised text.
PLANTED_TEXT = "issue SPI-42 is ASSIGNED TO agent cto"
# Key tokens that MUST appear in OCR output (all case-insensitive)
PLANTED_TOKENS = ["SPI-42", "ASSIGNED", "agent", "cto"]
# T4 ingests into a REAL role namespace ("engineering") that scope.py recognizes, so the
# full scope -> ladder -> serve() path retrieves it (not a bypassing manual vector query).
# A unique key keeps it distinct from the seeded ACME nodes; cleanup runs in finally.
FIXTURE_ROLE = "engineering"
FIXTURE_NAMESPACE = "engineering"
OTHER_ROLE = "finance"        # a different role's serve() must NOT surface the OCR node
FIXTURE_KEY = "doc:ocr-spi-42-scan"
# Local embed model (must be cached for the $0/offline T4 demo). Mirrors embed.MODEL.
EMBED_MODEL = "google/embeddinggemma-300m"


def _make_fixture_png(path):
    """Render a page-image PNG with planted text + a simple diagram shape.

    Uses only Pillow — no external fonts required (uses default bitmap font).
    The shape (filled rectangle) stands in for a diagram region, representing
    what a scanned technical page might contain alongside prose.
    """
    from PIL import Image, ImageDraw, ImageFont

    # Simple 800×400 white canvas — tesseract works well at this size with Pillow's
    # default bitmap font. We avoid scale/resize chains: empirically the "Empty page!!"
    # warning appears when Lanczos downsampling turns anti-aliased bitmap-font pixels
    # into grey blobs that fall below tesseract's binarisation threshold.
    img = Image.new("RGB", (800, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Body text containing the planted retrievable fact.
    # Use ASCII-safe tokens (spaces, no colons or underscores) so tesseract's default
    # bitmap font doesn't merge adjacent tokens.
    body_lines = [
        "Company Knowledge Base  Engineering Domain",
        "",
        "Document OCR test fixture",
        "",
        # Planted fact: key tokens SPI-42, ASSIGNED, agent, cto
        "issue SPI-42 is ASSIGNED TO agent cto",
        "",
        "This document describes the current assignment state of tracked issues.",
        "Issue SPI-42 was escalated to the CTO track on 2026-06-01.",
        "See also issue SPI-43.",
        "",
    ]
    # Draw each line separately so newlines are handled portably
    y = 30
    for line in body_lines:
        draw.text((40, y), line, fill=(0, 0, 0))
        y += 20

    # Simple diagram: a labelled rectangle (represents a diagram region on the page)
    draw.rectangle([500, 250, 720, 350], outline=(0, 0, 0), width=2)
    draw.text((520, 290), "Process Diagram", fill=(80, 80, 80))

    img.save(path, format="PNG")


# ---------------------------------------------------------------------------
# Shared _run_test helper (mirrors eval_corrective.py)
# ---------------------------------------------------------------------------

def _run_test(name, fn):
    """Run a test function; return (ok, error_str)."""
    try:
        fn()
        return True, None
    except AssertionError as e:
        return False, f"AssertionError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# T1: real OCR — fixture PNG -> tesseract CLI -> planted text recovered
# ---------------------------------------------------------------------------

def t1_real_ocr():
    """Generate fixture PNG, run the REAL tesseract CLI, assert key planted tokens recovered.

    Checks that all tokens in PLANTED_TOKENS are present (case-insensitive) in the OCR
    output. Exact substring match is too brittle against bitmap-font noise (colons,
    underscores, merged spaces); token presence is the honest recovery bar.
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        png_path = tf.name
    try:
        _make_fixture_png(png_path)
        text = _ocr_mod.extract(png_path)
        text_lower = text.lower()
        missing = [tok for tok in PLANTED_TOKENS if tok.lower() not in text_lower]
        assert not missing, (
            f"T1: planted tokens {missing!r} not found in OCR output.\n"
            f"OCR output (first 500 chars): {text[:500]!r}"
        )
        print(f"  T1 real OCR: all {len(PLANTED_TOKENS)} planted tokens found "
              f"in output ({len(text)} chars total)")
    finally:
        os.unlink(png_path)


# ---------------------------------------------------------------------------
# T2: $0-or-STOP — inject _run returning auth/payment string -> RuntimeError
# ---------------------------------------------------------------------------

def t2_stop_on_payment():
    """Inject _run returning a payment/auth string; assert extract() raises RuntimeError."""
    class _FakeProc:
        def __init__(self, out):
            self.stdout, self.stderr = out, ""

    stop_phrases = [
        "payment required",
        "api key required",
        "billing issue",
        "quota exceeded",
        "authentication required",
    ]
    for phrase in stop_phrases:
        caught = None
        try:
            _ocr_mod.extract("/any/path.png", _run=lambda *a, _p=phrase, **k: _FakeProc(_p))
        except RuntimeError as e:
            caught = e
        assert caught is not None, f"T2: no RuntimeError for stop phrase {phrase!r}"
        assert "STOP" in str(caught) or "AUTH" in str(caught).upper(), (
            f"T2: RuntimeError for {phrase!r} is not the $0-or-STOP guard: {caught}"
        )
    print(f"  T2 $0-or-STOP: all {len(stop_phrases)} stop-phrase variants raised RuntimeError")


# ---------------------------------------------------------------------------
# T3: env-at-call-time — set OCR_CMD AFTER import, assert it takes effect
# ---------------------------------------------------------------------------

def t3_env_at_call_time():
    """Prove OCR_CMD is read at call time, not captured at import.

    Strategy: clear OCR_CMD, import (already done), then set OCR_CMD to a fake
    command. The injected _run captures the cmd list so we can inspect which binary
    was used without shelling out.
    """
    class _FakeProc:
        stdout = "fake ocr text"
        stderr = ""

    captured_cmd = []

    def _fake_run(cmd, **kw):
        captured_cmd[:] = list(cmd)
        return _FakeProc()

    # Remove OCR_CMD to start clean
    os.environ.pop("OCR_CMD", None)

    # Set AFTER import — this is the proof point
    os.environ["OCR_CMD"] = "/fake/tesseract-bin"
    try:
        _ocr_mod.extract("/any/path.png", _run=_fake_run)
    finally:
        os.environ.pop("OCR_CMD", None)

    assert captured_cmd and captured_cmd[0] == "/fake/tesseract-bin", (
        f"T3: OCR_CMD set after import was not picked up; cmd[0]={captured_cmd[0] if captured_cmd else 'none'!r}"
    )
    print(f"  T3 env-at-call-time: OCR_CMD set after import -> cmd[0]={captured_cmd[0]!r} (correct)")


# ---------------------------------------------------------------------------
# Neo4j connectivity gate (mirrors eval_corrective._check_neo4j)
# ---------------------------------------------------------------------------

def _check_neo4j():
    try:
        from neo4j import GraphDatabase
        drv = GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://localhost:7688"), auth=("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain")))
        drv.verify_connectivity()
        drv.close()
        return True
    except Exception as e:
        print(f"DEPENDENCY: Neo4j unreachable at bolt://localhost:7688 ({type(e).__name__}: {e}).")
        print("  T4 (neo4j demo) requires the live graph. T1-T3 are standalone.")
        return False


def _embed_model_cached():
    """$0/offline fail-closed guard for the embed model used by T4.

    T4's serve() path embeds the OCR'd node via embed.embed_node (EmbeddingGemma-300M).
    If that model is NOT already cached locally, embedding it would trigger a download —
    violating the $0/offline constraint. So we probe the HF hub cache WITHOUT loading the
    model. Returns True only when an ACTUAL weight file is present in a snapshot (not just
    a refs/ shell or a metadata-only partial cache). Does NOT modify embed.py and does NOT
    download anything.
    """
    import os as _os
    import glob as _glob
    hf_hub = _os.path.join(_os.path.expanduser("~"), ".cache", "huggingface", "hub")
    model_dir = _os.path.join(hf_hub, "models--" + EMBED_MODEL.replace("/", "--"))
    if not _os.path.isdir(model_dir):
        return False
    # Require a REAL weight file under snapshots/*/ — model.safetensors OR pytorch_model.bin.
    # "any file" was too loose (a partial/metadata-only cache would falsely pass and then
    # trigger a weight download at load). HF stores the actual tensors as a symlink into
    # blobs/; glob follows the link to confirm the target exists.
    for weight in ("model.safetensors", "pytorch_model.bin"):
        if _glob.glob(_os.path.join(model_dir, "snapshots", "*", weight)):
            return True
    return False


# ---------------------------------------------------------------------------
# T4: neo4j-gated demo — OCR -> ingest_ocr_doc -> serve() -> assert retrieval
# ---------------------------------------------------------------------------

def _retrieved_keys(result):
    """All node keys a serve() result touched at retrieval: keyword + graph + vector rungs,
    plus the chosen primary. This is what the real scope->ladder->serve path surfaced."""
    rt = result.get("trace", {}).get("retrieve", {})
    keys = set()
    for rung in ("keyword", "graph", "vector"):
        keys.update(rt.get(rung, []) or [])
    if result.get("primary"):
        keys.add(result["primary"])
    return keys


def t4_neo4j_demo():
    """OCR fixture -> ingest_ocr_doc() into a REAL role namespace -> serve() retrieves it.

    This is the genuine end-to-end + isolation proof (NOT a bypassing manual vector query):
    the node is ingested into the "engineering" namespace that scope.py recognizes, then the
    REAL serve(query, "engineering") path (scope -> ladder keyword/graph/vector -> fuse ->
    gate) runs against it.

    Asserts:
    (a) the OCR'd node is in serve("engineering")'s retrieved keys (real path, not a manual query),
    (b) serve("engineering")'s trace["isolation"]["clean"] is True,
    (c) serve("finance") — a DIFFERENT role — does NOT surface the OCR node (cross-role isolation).

    $0/offline: gated on _embed_model_cached() by the caller; embedding the node uses the
    locally-cached EmbeddingGemma — no download. Cleanup removes the test node in finally.
    """
    from neo4j import GraphDatabase
    import etl
    from serve import serve

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        png_path = tf.name
    URI, AUTH = os.environ.get("NEO4J_URI", "bolt://localhost:7688"), ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))

    def _cleanup(drv):
        with drv.session() as s:
            s.execute_write(lambda tx: tx.run(
                "MATCH (n:Entity {key:$k}) DETACH DELETE n", k=FIXTURE_KEY))
            s.execute_write(lambda tx: tx.run(
                "MATCH (e:Episodic {uuid:$u}) DETACH DELETE e", u=f"ocr:{FIXTURE_KEY}"))

    try:
        _make_fixture_png(png_path)
        with GraphDatabase.driver(URI, auth=AUTH) as drv:
            _cleanup(drv)  # remove any stale prior test node before ingest

            # 1. INGEST via the OCR path into the REAL engineering namespace.
            with drv.session() as s:
                ocr_text = etl.ingest_ocr_doc(s, png_path, FIXTURE_NAMESPACE, FIXTURE_KEY)
            missing4 = [tok for tok in PLANTED_TOKENS if tok.lower() not in ocr_text.lower()]
            assert not missing4, (
                f"T4: planted tokens {missing4!r} not in OCR output: {ocr_text[:300]!r}"
            )

            # 2. EMBED the new node (locally-cached EmbeddingGemma) so the vector rung sees it.
            from embed import embed_node
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with drv.session() as s:
                s.execute_write(lambda tx: embed_node(tx, FIXTURE_KEY, ocr_text, "prose", now_iso))

            # 3. SERVE through the REAL path for the owning role. The query phrasing matches the
            #    OCR'd content so the vector rung surfaces it.
            query = "SPI-42 assigned to the CTO agent"
            eng_result = serve(query, FIXTURE_ROLE)
            eng_keys = _retrieved_keys(eng_result)

            # (a) the OCR node is retrieved through serve()'s own ladder
            assert FIXTURE_KEY in eng_keys, (
                f"T4(a): OCR node {FIXTURE_KEY!r} NOT retrieved by serve({FIXTURE_ROLE!r}). "
                f"retrieve trace={eng_result.get('trace', {}).get('retrieve')}"
            )
            # (b) serve()'s own isolation self-check is clean
            iso = eng_result.get("trace", {}).get("isolation", {})
            assert iso.get("clean") is True, (
                f"T4(b): serve({FIXTURE_ROLE!r}) isolation not clean: {iso!r}"
            )

            # (c) a DIFFERENT role's serve() must NOT surface the OCR node (cross-role isolation)
            fin_result = serve(query, OTHER_ROLE)
            fin_keys = _retrieved_keys(fin_result)
            assert FIXTURE_KEY not in fin_keys, (
                f"T4(c): isolation LEAK — OCR node {FIXTURE_KEY!r} surfaced for role "
                f"{OTHER_ROLE!r}. retrieve trace={fin_result.get('trace', {}).get('retrieve')}"
            )
            fin_iso = fin_result.get("trace", {}).get("isolation", {})
            assert fin_iso.get("clean") is True, (
                f"T4(c): serve({OTHER_ROLE!r}) isolation not clean: {fin_iso!r}"
            )

            print(f"  T4 neo4j demo: OCR text ingested ({len(ocr_text)} chars) into "
                  f"{FIXTURE_NAMESPACE!r}; serve({FIXTURE_ROLE!r}) retrieved {FIXTURE_KEY!r} "
                  f"via its own ladder (keys={sorted(eng_keys)}), isolation clean=True; "
                  f"serve({OTHER_ROLE!r}) did NOT surface it (cross-role isolation holds)")
    finally:
        # Always clean the graph + temp file, even on assertion failure.
        try:
            with GraphDatabase.driver(URI, auth=AUTH) as drv:
                _cleanup(drv)
        except Exception:
            pass
        os.unlink(png_path)


# ---------------------------------------------------------------------------
# A/B: OCR coverage vs vision baseline (CLIP, best-effort, honest)
# ---------------------------------------------------------------------------

def ab_smoke():
    """A/B is NOT a valid comparison as-run — report it honestly as a SMOKE CHECK.

    Two reasons it is not a real eRAG A/B:
      1. The OCR side is a planted-token RECOVERY smoke check (same signal as T1), not a
         downstream-utility eRAG score.
      2. The vision side (CLIP cosine of image vs text) is a different metric on a different
         scale — not comparable to token recovery, so it cannot establish "OCR wins".

    A true eRAG A/B requires a cached vision model AND the SAME downstream utility metric on
    both paths (e.g. both feeding serve() and scoring eRAG coverage). That is out of scope for
    a $0/offline run with no cached vision model. So: report the OCR recovery smoke value, and
    run the vision side ONLY if a CLIP model is already cached locally (with local_files_only=
    True so it can never download); never imply a winner.
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        png_path = tf.name
    try:
        _make_fixture_png(png_path)

        # OCR side: planted-token recovery (a SMOKE value, not an eRAG utility score).
        ocr_text = _ocr_mod.extract(png_path)
        ocr_lower = ocr_text.lower()
        hits = sum(1 for tok in PLANTED_TOKENS if tok.lower() in ocr_lower)
        ocr_recovery = round(hits / len(PLANTED_TOKENS), 3)
        print(f"  A/B: NOT a valid comparison as-run — OCR side is a recovery smoke check, "
              f"vision side (if run) is a non-comparable metric.")
        print(f"  A/B OCR smoke: planted-token recovery={ocr_recovery} "
              f"({hits}/{len(PLANTED_TOKENS)} tokens) — recovery only, NOT a downstream eRAG utility.")

        # Vision baseline — run ONLY if a CLIP model is already cached locally; never download.
        vision_ran = False
        try:
            import os as _os
            cache_root = _os.path.join(_os.path.expanduser("~"), ".cache", "torch", "sentence_transformers")
            hf_cache = _os.path.join(_os.path.expanduser("~"), ".cache", "huggingface", "hub")
            clip_candidates = ["clip-ViT-B-32", "openai/clip-vit-base-patch32"]

            found_model = None
            for cand in clip_candidates:
                st_path = _os.path.join(cache_root, cand.replace("/", "_").replace("-", "_"))
                hf_path = _os.path.join(hf_cache, "models--" + cand.replace("/", "--"))
                if _os.path.isdir(st_path) or _os.path.isdir(hf_path):
                    found_model = cand
                    break

            if found_model:
                from sentence_transformers import SentenceTransformer
                from PIL import Image
                import numpy as np
                # local_files_only=True → fail-closed: raise (caught below) rather than download.
                clip = SentenceTransformer(found_model, cache_folder=cache_root,
                                           local_files_only=True)
                img = Image.open(png_path).convert("RGB")
                img_emb = clip.encode(img, normalize_embeddings=True)
                txt_emb = clip.encode(PLANTED_TEXT, normalize_embeddings=True)
                cosine_sim = round(float(np.dot(img_emb, txt_emb)), 4)
                vision_ran = True
                print(f"  A/B vision smoke ({found_model}): CLIP cosine(image, planted_fact)="
                      f"{cosine_sim}. NOT comparable to the OCR token-recovery number above "
                      f"(different metric + scale); NO winner is implied.")
        except Exception as ve:
            print(f"  A/B vision: not run (local load failed or unavailable: "
                  f"{type(ve).__name__}); $0/offline preserved.")

        if not vision_ran:
            print("  A/B: vision baseline NOT run (no local vision model; $0/offline "
                  "constraint) — OCR side reported as a standalone smoke check only.")

    finally:
        os.unlink(png_path)


# ---------------------------------------------------------------------------
# Main runner (mirrors eval_corrective.py structure)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    neo4j_up = _check_neo4j()

    tests = [
        ("T1", "real OCR: fixture PNG -> tesseract -> planted text recovered", t1_real_ocr),
        ("T2", "$0-or-STOP: payment/auth string in CLI output -> RuntimeError", t2_stop_on_payment),
        ("T3", "env-at-call-time: OCR_CMD set after import takes effect at call", t3_env_at_call_time),
    ]

    results = []
    for tid, desc, fn in tests:
        print(f"\n[{tid}] {desc}")
        ok, err = _run_test(tid, fn)
        results.append((tid, ok, err, False))  # 4th field = skipped
        if not ok:
            print(f"  FAIL: {err}")

    # T4 gated on BOTH neo4j AND the embed model being locally cached ($0/offline fail-closed).
    print(f"\n[T4] neo4j demo: OCR -> ingest_ocr_doc -> serve() -> assert retrieval + cross-role isolation")
    embed_cached = _embed_model_cached()
    if not neo4j_up:
        ok4, err4, skipped4 = False, "Neo4j not reachable — T4 skipped", True
        print(f"  SKIP: {err4}")
    elif not embed_cached:
        # Honest fail-closed skip (like _check_neo4j): never risk a download.
        ok4, err4, skipped4 = False, None, True
        print(f"  DEPENDENCY: embed model {EMBED_MODEL!r} not cached locally; $0/offline — "
              f"skipping live retrieval demo.")
    else:
        ok4, err4 = _run_test("T4", t4_neo4j_demo)
        skipped4 = False
    results.append(("T4", ok4, err4, skipped4))
    if not ok4 and not skipped4:
        print(f"  FAIL: {err4}")

    # A/B — honest SMOKE CHECK, not a comparison; never gated, never implies a winner.
    print(f"\n[A/B] smoke check (NOT a valid comparison): OCR token-recovery; vision only if cached")
    _, ab_err = _run_test("A/B", ab_smoke)
    if ab_err:
        print(f"  A/B error: {ab_err}")

    print("\n--- Summary ---")
    # T1-T3 always counted; T4 counts as PASS unless it RAN and failed (a dependency SKIP
    # does not fail the suite — but it also does NOT silently claim OCR_OK as a full pass).
    all_pass = True
    t4_skipped = False
    for rec in results:
        tid, ok, err = rec[0], rec[1], rec[2]
        skipped = rec[3] if len(rec) > 3 else False
        if skipped:
            status = "SKIP"
            if tid == "T4":
                t4_skipped = True
        else:
            status = "PASS" if ok else "FAIL"
        print(f"  {tid}: {status}" + (f" — {err}" if err else ""))
        if not ok and not skipped:
            all_pass = False

    if all_pass and not t4_skipped:
        print("\nOCR_OK")
    elif all_pass and t4_skipped:
        # T1-T3 passed but the live serve()+isolation demo could not run — be explicit,
        # do NOT print the full-pass token.
        print("\nOCR_PARTIAL: T1-T3 passed; T4 (live serve+isolation) SKIPPED on a missing "
              "dependency (neo4j or cached embed model). Not a full pass.")
        sys.exit(3)
    else:
        print("\nOCR_FAIL")
        sys.exit(1)
