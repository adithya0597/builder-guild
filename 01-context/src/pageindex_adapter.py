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

INJECTION PATTERN (for tests and the demo):
    Call _inject(fn) before calling serve() or drill() directly. A test that wants to
    exercise the positive path (resolved_at == "pageindex") injects a fake that returns
    a canned payload — zero external calls. Restore with _inject(None) when done.
    NOTE: _inject sets module-global state; intended for single-threaded tests only.
"""
import sys

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


def drill(allowed, query_text, t_cap):
    """Run the PageIndex drill for the given scope + query.

    In the public mirror this is ALWAYS stubbed — returns _GATED_RESPONSE, zero external calls.
    A test or demo may inject a fake via _inject(fn) to exercise the resolved_at=="pageindex"
    positive path without touching any real resource.

    Args:
        allowed:     list of namespace strings (role-scoped, already enforced upstream).
        query_text:  the natural-language query to navigate the PageIndex tree for.
        t_cap:       max sections to retrieve (role T-cap from scope).

    Returns:
        dict matching the DRILL INTERFACE CONTRACT above.
    """
    if _injected is not None:
        return _injected(allowed, query_text, t_cap)
    # Public stub: zero external calls, always gated.
    return dict(_GATED_RESPONSE)


def demo():
    """Contract self-test (house *_OK idiom). Proves interface shape + zero external calls.

    Three cases:
      (1) Stub (default): resolved_at=="gated", no external call, answer/doc/sections defined.
      (2) Injected fake (positive path): resolved_at=="pageindex", sections populated.
      (3) Restored stub after injection: gated again, injection cleaned up.
    """
    fail = []

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

    if fail:
        print("PAGEINDEX_ADAPTER_FAIL:", fail)
        sys.exit(1)
    print("PAGEINDEX_ADAPTER_OK")


if __name__ == "__main__":
    demo()
