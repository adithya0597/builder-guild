"""GT-1: the golden-set SCHEMA + storage + null/temporal templates.

The golden set is the human-validated answer key M3 calibrates against (CONTEXT_EVALS §4). This
module defines ONLY the contract + templates + IO + a round-trip demo — it does NOT draft questions
(that is GT-2) and does NOT contain validated answers (that is the GT-5 human gate).
Two-level labels per §1/§4: the support-fact set (retrieval correctness) is stored
SEPARATELY from the correct_answer (generation correctness).

Why a schema module first: every downstream harness (eRAG, judge sweep) reads
this format, so the contract is the dependency the code is built against — the human labels fill it
in later. `validated=False` on every item until a human signs off (no self-grading, §0).
"""
import json
import os
import sys

ROLES = ["engineering", "finance", "operations", "product", "market", "governance", "shared"]
HOP_TYPES = ["single", "multi_abstract", "multi_specific"]   # RAGAS 50/25/25 distribution (§4.1)
# normal Q / abstain-probe / as-of / temporal-abstain (as-of w/ no temporal evidence -> must abstain)
KINDS = ["normal", "null", "temporal", "temporal_null"]
DECISIONS = ["pass", "partial", "abstain", "escalate"]
ABSTAIN_KINDS = ("null", "temporal_null")                    # kinds that must expect 'abstain'

# The golden-item contract. (key -> (python_type, required)). support_facts + correct_answer are the
# TWO LEVELS; forbidden_namespaces guards null/leakage probes; as_of drives temporal as-of checks.
GOLDEN_SCHEMA = {
    "id":                   (str,         True),
    "role":                 (str,         True),
    "question":             (str,         True),
    "hop_type":             (str,         True),
    "kind":                 (str,         True),
    "correct_answer":       ((str, list), True),  # str OR list (multi_abstract answers); "" pre-validation
    "support_facts":        (list,        True),  # node keys ("issue:SPI-1") and/or edge triples [s,rel,o]
    "expected_decision":    (str,         True),  # what serve() SHOULD do (null -> "abstain")
    "forbidden_namespaces": (list,        True),  # namespaces that must NOT surface (leakage probe)
    "as_of":                (str,         False), # ISO ts for temporal items; absent otherwise
    "validated":            (bool,        True),  # False until a human signs off
    "draft_source":         (str,         True),  # provenance of the draft (states eRAG GT source, §4.6)
    # human-validation provenance (added when a human signs off at GT-5):
    "validation_basis":     (str,         False), # how the human validated (e.g. paperclip_ai_native_org_model)
    "reason":               (str,         False), # the human's justification for the correct_answer
    "support_required":     (list,        False), # temporal: edges/conditions the answer REQUIRES to hold
}


def validate_item(item):
    """Structural validation against GOLDEN_SCHEMA. Returns (ok, errors)."""
    errs = []
    for key, (typ, required) in GOLDEN_SCHEMA.items():
        if key not in item:
            if required:
                errs.append(f"missing required key: {key}")
            continue
        if not isinstance(item[key], typ):
            errs.append(f"{key}: expected {typ.__name__}, got {type(item[key]).__name__}")
    if item.get("role") not in ROLES:
        errs.append(f"role {item.get('role')!r} not in ROLES")
    if item.get("hop_type") not in HOP_TYPES:
        errs.append(f"hop_type {item.get('hop_type')!r} not in HOP_TYPES")
    if item.get("kind") not in KINDS:
        errs.append(f"kind {item.get('kind')!r} not in KINDS")
    if item.get("expected_decision") not in DECISIONS:
        errs.append(f"expected_decision {item.get('expected_decision')!r} not in DECISIONS")
    # two-level rule: a normal/temporal item must carry a support-fact set (the retrieval label);
    # null / temporal_null deliberately have none (no answer / no temporal evidence) and must abstain.
    if item.get("kind") in ("normal", "temporal") and not item.get("support_facts"):
        errs.append("normal/temporal item needs a non-empty support_facts set (two-level label)")
    if item.get("kind") in ABSTAIN_KINDS and item.get("expected_decision") != "abstain":
        errs.append(f"{item.get('kind')} item must expect 'abstain'")
    return (not errs, errs)


def normal_item(id_, role, question, hop_type, support_facts, draft_source, correct_answer=""):
    """A standard Q grounded in real graph facts. correct_answer stays "" until human-validated."""
    return {"id": id_, "role": role, "question": question, "hop_type": hop_type, "kind": "normal",
            "correct_answer": correct_answer, "support_facts": support_facts,
            "expected_decision": "pass", "forbidden_namespaces": [], "validated": False,
            "draft_source": draft_source}


def null_item(id_, role, question, forbidden_namespaces, draft_source):
    """Answer-not-in-KB / cross-role leakage probe (§4.4). Must abstain; must not surface a
    forbidden namespace. No support_facts by construction (nothing legitimately supports it)."""
    return {"id": id_, "role": role, "question": question, "hop_type": "single", "kind": "null",
            "correct_answer": "", "support_facts": [], "expected_decision": "abstain",
            "forbidden_namespaces": forbidden_namespaces, "validated": False, "draft_source": draft_source}


def temporal_item(id_, role, question, as_of, support_facts, draft_source, correct_answer=""):
    """As-of correctness over a supersession chain (§4.5): the fact valid AT as_of, not the latest."""
    it = normal_item(id_, role, question, "multi_specific", support_facts, draft_source, correct_answer)
    it.update({"kind": "temporal", "as_of": as_of})
    return it


def write_golden(items, path):
    with open(path, "w") as f:
        for it in items:
            f.write(json.dumps(it, sort_keys=True) + "\n")
    return path


def read_golden(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def demo():
    fail = []
    items = [
        normal_item("eng-1", "engineering", "Who is issue SPI-1 assigned to?", "single",
                    ["issue:SPI-1", ["issue:SPI-1", "ASSIGNED_TO", "agent:cto"]], "GT-1 template demo"),
        normal_item("eng-2", "engineering", "What does SPI-2 block, and who owns that blocked issue?",
                    "multi_specific", ["issue:SPI-2", ["issue:SPI-2", "BLOCKS", "issue:SPI-3"],
                                       ["issue:SPI-3", "ASSIGNED_TO", "agent:cto"]], "GT-1 template demo"),
        null_item("null-1", "engineering", "What is the Q3 finance inference budget cap?",
                  ["finance"], "GT-1 template demo"),   # eng role must NOT surface finance -> abstain
        temporal_item("tmp-1", "finance", "Who owned SPI-4 as of 2026-05-01?", "2026-05-01T00:00:00",
                      ["issue:SPI-4", ["issue:SPI-4", "ASSIGNED_TO", "agent:cfo"]], "GT-1 template demo"),
    ]

    # 1) every template item is structurally valid
    for it in items:
        ok, errs = validate_item(it)
        print(f"[valid]   {it['id']:8} kind={it['kind']:8} hop={it['hop_type']:14} -> {ok}{'' if ok else ' '+str(errs)}")
        fail += [] if ok else [f"{it['id']} invalid: {errs}"]

    # 2) a deliberately broken item is REJECTED (validator actually validates)
    bad = dict(items[0]); bad["expected_decision"] = "frobnicate"; bad.pop("support_facts")
    ok_bad, errs_bad = validate_item(bad)
    print(f"[reject]  broken item -> valid={ok_bad} errs={len(errs_bad)} (expect valid=False)")
    fail += [] if (not ok_bad and errs_bad) else ["validator passed a broken item"]

    # 3) two-level separation: support_facts (retrieval) is independent of correct_answer (generation)
    two_level = all(("support_facts" in it and "correct_answer" in it) for it in items)
    unfilled = all(it["correct_answer"] == "" and it["validated"] is False for it in items)
    print(f"[2level]  support_facts ⟂ correct_answer present={two_level} | answers unfilled+unvalidated={unfilled}")
    fail += [] if (two_level and unfilled) else ["two-level/unvalidated invariant broken"]

    # 4) JSONL round-trip is lossless
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_schema_demo.jsonl")
    write_golden(items, path)
    back = read_golden(path)
    rt = back == items
    print(f"[io]      round-trip {len(back)} items lossless={rt} -> {os.path.basename(path)}")
    fail += [] if rt else ["JSONL round-trip lost data"]
    os.remove(path)

    if fail:
        print("GOLDEN_FAIL:", fail); sys.exit(1)
    print("GOLDEN_OK")


if __name__ == "__main__":
    demo()
