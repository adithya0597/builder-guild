"""PageIndex adapter — the contract a real drill fulfills, and a STUB for the public mirror.

PUBLIC MIRROR STUB: the live PageIndex drill is a private grant (an authenticated retrieval call + private
pageindex_trees). This module ships the MECHANISM + INTERFACE so the public mirror can wire
and exercise the serve-join shape WITHOUT any external/LLM calls.

DRILL INTERFACE CONTRACT (SERVE_JOIN_DESIGN §2.3):
    drill(allowed, query_text, t_cap) -> {
        "resolved_at": "pageindex" | "gated",
        "answer": str,               # the prose answer from the selected sections
        "doc":    str,               # the host long-doc node key
        "sections": [str, ...],      # section node_id(s) selected
    }

    - "pageindex" : the drill resolved — answer + doc + sections are populated.
    - "gated"     : the drill could not resolve (no grant, no live tree, etc.) — answer
                    may be an explanation, doc/sections may be absent or empty.

A real adapter (private) makes one authenticated deep retrieval and maps
the result to this shape. This stub makes ZERO external/LLM calls.

OPT-IN LOCAL DRILL (env PAGEINDEX_LOCAL_DRILL=1, read live per call, default OFF): a REAL but
LOCAL drill — deterministic markdown-heading-tree navigation over an in-repo doc, token-overlap
section pick, zero LLM/network calls. This is the un-stubbed MECHANISM, honestly labeled via
"mechanism": "local_toc_deterministic" on its return dict. It is NOT vendor PageIndex LLM
tree-reasoning (that stays the private grant, excluded here) and NOT the measured
PAGEINDEX_PILOT.md pilot. Flag absent/falsy -> byte-identical to the gated stub, zero file I/O.

INJECTION PATTERN (for tests and the demo):
    Call _inject(fn) before calling serve() or drill() directly. A test that wants to
    exercise the positive path (resolved_at == "pageindex") injects a fake that returns
    a canned payload — zero external calls. Restore with _inject(None) when done.
    NOTE: _inject sets module-global state; intended for single-threaded tests only.
"""
import hashlib
import os
import re
import sys
from pathlib import Path

# The public-mirror stub response: always returns "gated" — no external call, no pageindex drill.
_GATED_RESPONSE = {
    "resolved_at": "gated",
    "reason": (
        "live PageIndex drill is a private grant; "
        "the public mirror ships the mechanism + interface only"
    ),
    "answer": "",
    "doc": None,
    "sections": [],
}

# Module-level injectable drill function. None = use the stub. Tests call _inject(fake_fn) to
# exercise the positive path (resolved_at=="pageindex") without any external/LLM calls.
_injected = None


def _inject(fn):
    """Replace the drill implementation for the duration of a test. Call _inject(None) to restore."""
    global _injected
    _injected = fn


# The real in-repo doc the opt-in local drill navigates (352 lines, #/##/### headings). Path is
# relative to this file, mirroring serve.py's own Path(__file__).parent.parent convention.
_DOC_PATH = Path(__file__).parent.parent / "HYBRID_RETRIEVAL_ARCHITECTURE.md"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")   # ``` / ~~~ code-fence delimiter (open or close)


def _doc_sha256(path=_DOC_PATH):
    """Real sha256 of the doc's bytes — computed, not hand-typed."""
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _build_tree(path=_DOC_PATH):
    """Parse the doc's markdown headings into a flat, document-order list of sections:
    {node_id, title, level, text}. node_id is a zero-padded sequential index (matches this
    file's own ["0001", "0007"] demo fixture below). Re-parsed per call — no checked-in cache;
    the doc is small enough that a live parse can never go stale the way a cached file could.
    Lines inside ``` / ~~~ fenced code blocks are never heading candidates (a `#` comment or
    `#!/bin/sh` in a fenced snippet is not a real heading). Missing doc -> empty tree (the
    caller degrades to gated, it does not crash)."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        print(f"[pageindex_adapter] doc not found at {path} — local drill degrades to gated",
              file=sys.stderr)
        return []
    headings = []
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2)))
    sections = []
    for idx, (line_no, level, title) in enumerate(headings):
        start = line_no + 1
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        sections.append({
            "node_id": f"{idx + 1:04d}",
            "title": title,
            "level": level,
            "text": "\n".join(lines[start:end]).strip(),
        })
    return sections


def _local_drill(query_text, t_cap):
    """Deterministic local ToC navigation: token-overlap section pick over the real doc tree.
    A bag-of-words match — NOT vendor PageIndex LLM tree-reasoning, honest about its ceiling.
    Zero overlap -> gated (never a fabricated pick on zero signal)."""
    if t_cap <= 0:      # degenerate T-cap: clamp to 1 rather than break the top-N slice contract
        t_cap = 1
    q_tokens = set(re.findall(r"[a-z0-9]+", (query_text or "").lower()))
    if not q_tokens:
        return dict(_GATED_RESPONSE)
    scored = []
    for sec in _build_tree():
        sec_tokens = set(re.findall(r"[a-z0-9]+", (sec["title"] + " " + sec["text"]).lower()))
        overlap = len(q_tokens & sec_tokens)
        if overlap > 0:
            scored.append((overlap, sec["node_id"], sec["text"]))
    if not scored:
        return dict(_GATED_RESPONSE)
    scored.sort(key=lambda row: (-row[0], row[1]))          # score desc, node_id asc tie-break
    picked = scored[:t_cap]
    return {
        "resolved_at": "pageindex",
        "answer": " ".join(text[:200] for _, _, text in picked),  # this repo's ctx[:200] excerpt convention
        # SAME graph node demo_seed.py stamps with the real pageindex_ref/pageindex_doc_sha — a
        # documented pairing-by-convention, not a live Neo4j join (see demo_seed.py's mirror comment).
        "doc": "extsrc:context-evals",
        "sections": [node_id for _, node_id, _ in picked],
        "mechanism": "local_toc_deterministic",
    }


def drill(allowed, query_text, t_cap):
    """Run the PageIndex drill for the given scope + query.

    Three paths, in priority order:
      1. _injected(fn) — test/demo override; exercises any path with zero external calls.
      2. PAGEINDEX_LOCAL_DRILL=1 (env, read live, default OFF) — the real local drill:
         deterministic token-overlap navigation over an in-repo doc, zero LLM/network.
         Honors `allowed`: the hardcoded host doc is namespace 'shared', so it only
         resolves when 'shared' is in allowed — otherwise gated, zero tree-building work.
      3. Public stub (default) — _GATED_RESPONSE, zero external calls, no file I/O.

    Args:
        allowed:     list of namespace strings (role-scoped, already enforced upstream).
        query_text:  the natural-language query to navigate the PageIndex tree for.
        t_cap:       max sections to retrieve (role T-cap from scope).

    Returns:
        dict matching the DRILL INTERFACE CONTRACT above. The local-drill path additionally
        sets "mechanism": "local_toc_deterministic" (absent on the stub and on injected fakes).
    """
    if _injected is not None:
        return _injected(allowed, query_text, t_cap)
    if os.environ.get("PAGEINDEX_LOCAL_DRILL") == "1":
        # Local drill honors the SAME allowed-scope contract serve.py enforces post-drill —
        # defense-in-depth on the isolation boundary. The hardcoded host doc is namespace
        # 'shared'; out-of-scope callers get the gated stub before any tree-building work.
        if "shared" not in allowed:
            return dict(_GATED_RESPONSE)
        return _local_drill(query_text, t_cap)
    # Public stub: zero external calls, always gated.
    return dict(_GATED_RESPONSE)


def demo():
    """Contract self-test (house *_OK idiom). Proves interface shape + zero external calls,
    plus the opt-in local drill's real (non-fabricated) positive path.

    Four cases:
      (1) Stub (default): resolved_at=="gated", no external call, answer/doc/sections defined.
      (2) Injected fake (positive path): resolved_at=="pageindex", sections populated.
      (3) Restored stub after injection: gated again, injection cleaned up.
      (4) PAGEINDEX_LOCAL_DRILL=1 (self-cleaning): real doc-tree navigation returns REAL
          sections (not the canned fake), then the env var is restored and the next call
          reverts to gated — proves no state leak.
    """
    fail = []

    # Hermetic against the selftest's OWN opt-in env var: if the caller's shell already has
    # PAGEINDEX_LOCAL_DRILL exported, cases (1)/(3) below (which assume the gated stub, since
    # nothing has called _inject yet) must still see it absent. Snapshot + pop here; restore
    # in finally so a user-exported flag survives the selftest untouched (still their choice
    # outside demo()).
    _env_snapshot = os.environ.pop("PAGEINDEX_LOCAL_DRILL", None)
    try:
        # (1) Stub: always gated, zero external calls, all keys present
        r = drill(["engineering", "shared"], "some query", 3)
        fail += [] if r["resolved_at"] == "gated" else ["stub must return resolved_at=gated"]
        fail += [] if "answer" in r and "doc" in r and "sections" in r \
            else ["stub response missing required keys (answer/doc/sections)"]
        fail += [] if not r["sections"] else ["stub sections must be empty (zero external calls)"]
        print(f"[stub]   resolved_at={r['resolved_at']!r} sections={r['sections']} "
              f"(zero external calls, always gated) OK")

        # (2) Injected fake: positive pageindex path, zero external calls
        _FAKE = {
            "resolved_at": "pageindex",
            "answer": "the sufficient-context paper finds abstention beats answering on low coverage",
            "doc": "extsrc:context-evals",
            "sections": ["0001", "0007"],
        }
        _inject(lambda allowed, q, t: dict(_FAKE))
        r2 = drill(["shared"], "sufficient context paper conclusions", 3)
        fail += [] if r2["resolved_at"] == "pageindex" else ["injected fake must return resolved_at=pageindex"]
        fail += [] if r2["sections"] == ["0001", "0007"] else ["injected sections mismatch"]
        fail += [] if r2["doc"] == "extsrc:context-evals" else ["injected doc mismatch"]
        print(f"[inject] resolved_at={r2['resolved_at']!r} doc={r2['doc']!r} "
              f"sections={r2['sections']} (injected fake, zero external calls) OK")

        # (3) Restored stub: gated again after _inject(None)
        _inject(None)
        r3 = drill(["shared"], "some query", 3)
        fail += [] if r3["resolved_at"] == "gated" else ["stub must be restored after _inject(None)"]
        print(f"[restore] resolved_at={r3['resolved_at']!r} (stub restored) OK")

        # (4) Opt-in local drill (self-cleaning): flag ON navigates the REAL doc tree — real
        # sections, not the canned case-(2) fake — then the flag is restored and the next call
        # reverts to gated. Mirrors this file's existing restore-after-_inject(None) idiom above.
        prior_flag = os.environ.get("PAGEINDEX_LOCAL_DRILL")
        os.environ["PAGEINDEX_LOCAL_DRILL"] = "1"
        try:
            r4 = drill(["shared"], "fusion rerank", 3)
            # Scope gate (defense-in-depth): the hardcoded host doc is namespace 'shared' —
            # an allowed list that does NOT include 'shared' must gate, not leak doc text,
            # even though the query itself would otherwise overlap real sections.
            r_empty_scope = drill([], "fusion rerank", 1)
            r_wrong_scope = drill(["engineering"], "fusion rerank", 1)
        finally:
            if prior_flag is None:
                os.environ.pop("PAGEINDEX_LOCAL_DRILL", None)
            else:
                os.environ["PAGEINDEX_LOCAL_DRILL"] = prior_flag
        fail += [] if r4["resolved_at"] == "pageindex" \
            else ["flag-on drill must return resolved_at=pageindex on real overlap"]
        fail += [] if r4["sections"] and r4["sections"] != ["0001", "0007"] \
            else ["flag-on drill must return REAL, non-fake sections"]
        fail += [] if r4.get("mechanism") == "local_toc_deterministic" \
            else ["flag-on drill must label mechanism=local_toc_deterministic"]
        print(f"[flag-on] resolved_at={r4['resolved_at']!r} sections={r4['sections']} "
              f"mechanism={r4.get('mechanism')!r} (real doc tree, zero LLM) OK")

        fail += [] if r_empty_scope["resolved_at"] == "gated" \
            else ["scope gate: allowed=[] must not resolve pageindex (out-of-scope doc leak)"]
        fail += [] if r_wrong_scope["resolved_at"] == "gated" \
            else ["scope gate: allowed=['engineering'] (no 'shared') must not resolve pageindex"]
        print(f"[scope]   allowed=[] -> resolved_at={r_empty_scope['resolved_at']!r}; "
              f"allowed=['engineering'] -> resolved_at={r_wrong_scope['resolved_at']!r} "
              f"(both gated, out-of-scope) OK")

        r5 = drill(["shared"], "fusion rerank", 3)
        fail += [] if r5["resolved_at"] == "gated" \
            else ["flag restore failed: drill still resolving after env cleanup"]
        print(f"[restore2] resolved_at={r5['resolved_at']!r} (flag cleaned up, reverted to gated) OK")
    finally:
        if _env_snapshot is None:
            os.environ.pop("PAGEINDEX_LOCAL_DRILL", None)
        else:
            os.environ["PAGEINDEX_LOCAL_DRILL"] = _env_snapshot

    if fail:
        print("PAGEINDEX_ADAPTER_FAIL:", fail)
        sys.exit(1)
    print("PAGEINDEX_ADAPTER_OK")


if __name__ == "__main__":
    demo()
