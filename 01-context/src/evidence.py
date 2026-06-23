"""EVIDENCE (serve-join): the canonical EvidenceItem — ONE shape for graph facts, vector hits,
and PageIndex sections — so the serve path can normalize → epist-merge → freshness-stamp → gate a
single homogeneous set. See SERVE_JOIN_DESIGN.md §1-§3.

SHARED CONTRACT: this module is byte-identical in the private spine and the public mirror. The
serve-join consumes it in BOTH trees; only the PageIndex ADAPTER differs (private = the real
deep-retrieval worker; public = a stubbed interface). Do NOT diverge this file between trees.

v1 is NARROW by decision (founder, 2026-06-17): exactly 11 fields, every one populated by a real
producer. `evidence_id` and the :Episodic provenance link are NAMED FOR LATER, not v1 fields —
the runtime object must not look more complete than it is.

Hard boundary (SERVE_JOIN_DESIGN §3): this module decides evidence SHAPE only. epist decides
authority/conflict; abstain/gate decides actionability. `is_actionable()` here is a freshness
parity helper for the gate — it is NOT a gate.
"""
from dataclasses import dataclass, fields
from typing import Optional

# ── FROZEN trigger constant (SERVE_JOIN_DESIGN §2.1) ──────────────────────────────────────────
# LABELED-ESTIMATE: uncalibrated; pending PageIndex pilot scoring + a coverage-vs-deep-benefit
# sweep. BOTH trees import THIS constant so the deep-rung escalation policy cannot drift.
DEEP_COVERAGE_TAU = 0.5

# Fixed epistemic role per retrieval method (HYBRID_RETRIEVAL_ARCHITECTURE PART 4). A stable HINT,
# never a weight — role-dependent numeric weights stay in epist.weights_for(role). Unknown method
# -> "recall" (lowest authority, fail-safe).
_AUTHORITY_HINT = {"keyword": "fact", "graph": "fact", "pageindex": "prose", "vector": "recall"}

# v1 field set — the contract demo asserts EvidenceItem matches this EXACTLY (drift = test fail).
_V1_FIELDS = {"retrieval_method", "node_id", "text", "namespace", "retrieval_score", "source_path",
              "section_id", "valid_at", "invalid_at", "freshness_state", "authority_hint"}


def authority_hint(method):
    return _AUTHORITY_HINT.get(method, "recall")


def freshness_state(validity="current", node_fresh="fresh"):
    """Collapse (edge validity, node freshness) into one freshness_state.
    Node-dirty DOMINATES (content edited, re-embed pending) -> "dirty"; else a superseded edge
    -> "superseded"; else "current". Mirrors stamp.action_gate (acts only on current+fresh) so
    is_actionable() agrees with the gate by construction."""
    if node_fresh == "stale":
        return "dirty"
    if validity == "historical":
        return "superseded"
    return "current"


def is_actionable(fs):
    """Freshness parity with stamp.action_gate: only 'current' may feed an autonomous action.
    A dirty/superseded/historical item is presentable but NOT actionable. NOT a gate — the gate
    (abstain.stage_a_decision) is the sole actionability authority; this only exposes the
    freshness axis so the gate can refuse to ACT on a stale PageIndex section."""
    return fs == "current"


@dataclass(frozen=True)
class EvidenceItem:
    retrieval_method: str            # "keyword" | "graph" | "vector" | "pageindex"
    node_id: str                     # entity key (pageindex: the host long-doc node key)
    text: str                        # graph: fact str | vector: long_context excerpt | pageindex: section text
    namespace: str                   # role-scope (isolation already enforced upstream)
    retrieval_score: Optional[float]  # vector cosine | graph: None (a structural MATCH is not a similarity score) | pageindex nav score | None
    source_path: Optional[str]       # pageindex: source doc path; graph/vector: None (facts have no path)
    section_id: Optional[str]        # pageindex: selected node_id(s); else None
    valid_at: Optional[str]          # graph facts when the producer has it; else None
    invalid_at: Optional[str]        # graph facts when the producer has it; else None
    freshness_state: str             # "current" | "historical" | "superseded" | "dirty"
    authority_hint: str              # "fact" | "prose" | "recall" — derived from retrieval_method


def from_graph(fact, namespace, node_id, validity="current", node_fresh="fresh",
               valid_at=None, invalid_at=None, method="graph"):
    """A stamped graph/keyword fact string ('ASSIGNED_TO -> agent:cto') -> EvidenceItem.
    retrieval_score is None on purpose: an exact structural MATCH is certain-by-construction,
    not a similarity score — do NOT fabricate a number (serve labels confidence separately)."""
    return EvidenceItem(method, node_id, fact, namespace, None, None, None,
                        valid_at, invalid_at, freshness_state(validity, node_fresh),
                        authority_hint(method))


def from_vector(node_id, namespace, score, text, node_fresh="fresh"):
    """A vector recall hit + its long_context excerpt -> EvidenceItem. authority = recall."""
    return EvidenceItem("vector", node_id, text, namespace, score, None, None, None, None,
                        freshness_state("current", node_fresh), authority_hint("vector"))


def from_pageindex(host_node_id, namespace, text, source_path, section_id,
                   score=None, node_fresh="fresh", validity="current"):
    """A PageIndex section -> EvidenceItem. freshness_state PROPAGATES from the HOST node
    (node_fresh/validity passed by serve off the host node's stamp): a section from a dirty or
    superseded long-doc node is non-actionable, so the gate refuses to ACT on stale prose
    (SERVE_JOIN_DESIGN freshness contract). authority = prose."""
    return EvidenceItem("pageindex", host_node_id, text, namespace, score, source_path,
                        section_id, None, None, freshness_state(validity, node_fresh),
                        authority_hint("pageindex"))


def demo():
    """Contract self-test (house *_OK idiom). LOCKS the v1 shape, authority map, freshness
    mapping, and the freshness-propagation safety case. A drifting subagent fails this."""
    import sys
    fail = []

    # authority hints fixed per method (incl. unknown -> recall, fail-safe)
    fail += [] if (authority_hint("graph") == "fact" and authority_hint("keyword") == "fact"
                   and authority_hint("pageindex") == "prose" and authority_hint("vector") == "recall"
                   and authority_hint("mystery") == "recall") else ["authority_hint map wrong"]

    # freshness mapping (node-dirty dominates) + actionability parity with stamp.action_gate
    fail += [] if (freshness_state("current", "fresh") == "current"
                   and freshness_state("historical", "fresh") == "superseded"
                   and freshness_state("current", "stale") == "dirty"
                   and freshness_state("historical", "stale") == "dirty") else ["freshness_state map wrong"]
    fail += [] if (is_actionable("current") and not is_actionable("dirty")
                   and not is_actionable("superseded") and not is_actionable("historical")) \
        else ["is_actionable parity wrong"]

    # graph fact normalizer: text=fact, no path, no score, fact authority
    g = from_graph("ASSIGNED_TO -> agent:cto", "engineering", "issue:SPI-1")
    fail += [] if (g.retrieval_method == "graph" and g.authority_hint == "fact"
                   and g.text.startswith("ASSIGNED_TO") and g.source_path is None
                   and g.retrieval_score is None and g.freshness_state == "current") else ["from_graph wrong"]

    # vector normalizer: carries cosine, recall authority, no section
    v = from_vector("issue:SPI-2", "engineering", 0.87, "backoff for the inference client")
    fail += [] if (v.retrieval_method == "vector" and v.authority_hint == "recall"
                   and v.retrieval_score == 0.87 and v.section_id is None) else ["from_vector wrong"]

    # pageindex normalizer: prose authority, carries doc path + section, current host -> actionable
    p_fresh = from_pageindex("doc:arch", "engineering", "the eval layer is not a relevance gate",
                             "/docs/HYBRID.md", "0001", node_fresh="fresh")
    fail += [] if (p_fresh.retrieval_method == "pageindex" and p_fresh.authority_hint == "prose"
                   and p_fresh.source_path == "/docs/HYBRID.md" and p_fresh.section_id == "0001"
                   and p_fresh.freshness_state == "current" and is_actionable(p_fresh.freshness_state)) \
        else ["from_pageindex(fresh) wrong"]

    # THE safety case: a section from a DIRTY host node must be non-actionable (freshness propagation)
    p_dirty = from_pageindex("doc:arch", "engineering", "stale prose", "/docs/HYBRID.md", "0001",
                             node_fresh="stale")
    fail += [] if (p_dirty.freshness_state == "dirty" and not is_actionable(p_dirty.freshness_state)) \
        else ["freshness propagation: dirty-host section must be non-actionable"]
    # and a superseded host doc -> non-actionable too
    p_super = from_pageindex("doc:arch", "engineering", "old prose", "/docs/HYBRID.md", "0007",
                             validity="historical")
    fail += [] if (p_super.freshness_state == "superseded" and not is_actionable(p_super.freshness_state)) \
        else ["freshness propagation: superseded-host section must be non-actionable"]

    # v1 NARROWNESS: EvidenceItem fields == the frozen set exactly; evidence_id absent
    names = {f.name for f in fields(EvidenceItem)}
    fail += [] if names == _V1_FIELDS else [f"EvidenceItem drifted from v1: {names ^ _V1_FIELDS}"]
    fail += [] if "evidence_id" not in names else ["evidence_id must NOT be a v1 runtime field"]

    # frozen trigger constant intact
    fail += [] if DEEP_COVERAGE_TAU == 0.5 else ["DEEP_COVERAGE_TAU changed"]

    if fail:
        print("EVIDENCE_FAIL:", fail)
        sys.exit(1)
    print("EVIDENCE_OK")


if __name__ == "__main__":
    demo()
