"""F3-scope: 2-D scoping = role-axis (CXO namespace slice) x query-axis, with a
per-role token budget and a T-cap (top-K results, start 3). This is the isolation boundary the
serve orchestrator applies before any retrieval — a role can only ever see its own namespace
slice + 'shared'. Deterministic; no LLM.
"""
import sys

# role-axis: each CXO role maps to the namespace slice it may read. 'shared' = cross-cutting
# reference data (e.g. status values). NO role's slice includes another role's namespace.
ROLE_NAMESPACES = {
    "engineering": ["engineering", "shared"],
    "finance":     ["finance", "shared"],
    "operations":  ["operations", "shared"],
    "product":     ["product", "shared"],
    "market":      ["market", "shared"],
    # governance/audit is the one cross-cutting reader (Dragon Judge) — it may read ALL slices
    # to audit, but that is an EXPLICIT, named exception, not a default.
    "governance":  ["engineering", "finance", "operations", "product", "market", "governance", "shared"],
}

T_CAP = 3   # query-axis: max results returned per source (tune; not proven)

# per-role token budget for the assembled context (query-axis cap on card size)
TOKEN_BUDGET = {r: 2000 for r in ROLE_NAMESPACES}
TOKEN_BUDGET["governance"] = 6000   # auditor assembles across slices -> larger budget


def allowed_namespaces(role):
    """role-axis -> the namespace slice this role may read. Unknown role -> 'shared' only (deny-by-default)."""
    return ROLE_NAMESPACES.get(role, ["shared"])


def scope(role, query_type="default"):
    """Return the full 2-D scope descriptor the serve pipeline applies."""
    return {
        "role": role,
        "allowed": allowed_namespaces(role),
        "t_cap": T_CAP,
        "token_budget": TOKEN_BUDGET.get(role, 1000),
        "query_type": query_type,
    }


def in_scope(role, namespace):
    """The isolation predicate: may `role` read a fact in `namespace`?"""
    return namespace in allowed_namespaces(role)


def demo():
    fail = []
    # role-axis: each non-governance role maps to its own slice + shared, nothing else
    eng = scope("engineering")
    print(f"[role]    engineering -> allowed={eng['allowed']} t_cap={eng['t_cap']} budget={eng['token_budget']}")
    fail += [] if eng["allowed"] == ["engineering", "shared"] else ["engineering scope wrong"]

    # cross-role isolation: engineering CANNOT read finance; finance CANNOT read engineering
    print(f"[isolate] eng can read finance? {in_scope('engineering','finance')} "
          f"| finance can read engineering? {in_scope('finance','engineering')}")
    fail += [] if (not in_scope("engineering", "finance")
                   and not in_scope("finance", "engineering")) else ["cross-role isolation breached"]

    # governance is the named cross-cutting auditor — may read every slice
    gov = allowed_namespaces("governance")
    print(f"[audit]   governance reads all slices: finance={in_scope('governance','finance')} "
          f"engineering={in_scope('governance','engineering')} ({len(gov)} namespaces)")
    fail += [] if (in_scope("governance", "finance") and in_scope("governance", "engineering")) \
        else ["governance audit scope wrong"]

    # deny-by-default: an unknown role sees only 'shared'
    print(f"[default] unknown role 'intern' -> {allowed_namespaces('intern')}")
    fail += [] if allowed_namespaces("intern") == ["shared"] else ["unknown role not deny-by-default"]

    # T-cap + token budget present
    fail += [] if (eng["t_cap"] == 3 and eng["token_budget"] == 2000) else ["t_cap/budget missing"]

    if fail:
        print("F3_SCOPE_FAIL:", fail); sys.exit(1)
    print("F3_SCOPE_OK")


if __name__ == "__main__":
    demo()
