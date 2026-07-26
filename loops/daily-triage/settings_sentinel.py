#!/usr/bin/env python3
"""Settings-tamper sentinel for the daily-triage loop: live GitHub settings vs committed intent.

A no-bypass ruleset protects *merges*, not its own on/off switch — an admin can disable the
`loop-merge-gates` ruleset, merge, and re-enable it, and nothing in the loop notices (DA teardown +
codex rev-security P3). The key insight: an attacker can toggle a LIVE setting out-of-band, but
cannot silently re-baseline a COMMITTED intent file without a visible commit — so live-vs-committed-
intent is the meaningful tamper signal. This tool detects that OUT-OF-BAND drift.

  check       PURE, gh-free, deterministic core: compare a live settings snapshot (`--actual`) against
              the committed minimum-secure posture (`--expected`) on the watched security keys; print
              one `DRIFT:` line per weakening, exit 1 if any drift, exit 0 if actual MEETS expected.
              Fully self-testable offline (caller supplies both JSONs; no gh, no network).
  fetch-live  best-effort `gh api` dump of live rulesets + main branch protection, normalized into the
              same shape as expected.json. Fail-safe: ANY gh failure/absence prints an
              {"gh":"unavailable","reason":...} sentinel to stdout + a note to stderr and exits 0 —
              it NEVER crashes the loop (unverifiable => the loop routes to Watch, not silent-pass).

Read-only DETECTOR: never modifies a live setting; remediation is human-gated. Pure stdlib.

Watched keys (the intended-secure posture, a MINIMUM the actual must MEET): ruleset `loop-merge-gates`
present + enforcement `active` + `bypass_actors` empty + required_status_checks ⊇
{smoke, graph, publish-gate, pr-classified} + pull_request `required_approving_review_count` == 0; and
main branch-protection NOT re-imposing `required_approving_review_count` >= 1 (the theatrical trap).
"""
import argparse
import json
import subprocess
import sys

RULESET = "loop-merge-gates"  # the one ruleset this loop's merge posture depends on
_GH_TIMEOUT = 30              # seconds per gh call; TimeoutExpired => unavailable sentinel (fail-safe)


def _load_json(path):
    with open(path) as f:  # OSError (missing/unreadable) + json.JSONDecodeError propagate to caller
        return json.load(f)


def _rulesets_named(doc, name):
    """ALL rulesets with this name — NOT last-wins. GitHub applies every ruleset, so a check that
    inspects only one (e.g. a dict keyed by name) has a parser/validator differential: an attacker
    can disable the real loop-merge-gates and add a passing duplicate (or vice-versa) and the check
    sees only one. We validate every same-named ruleset instead."""
    return [r for r in doc.get("rulesets", []) if isinstance(r, dict) and r.get("name") == name]


def _check(expected, actual):
    """PURE comparison. Return a list of `DRIFT: ...` strings (empty == no drift).

    Data-driven off `expected`: for each ruleset named in expected, the same-named ruleset in actual
    must MEET it (enforcement active, bypass empty, required checks a superset, approvals not raised).
    Comparison DIRECTION per key lives here (code); the VALUES live in settings-expected.json (data).
    """
    drifts = []
    for exp_rs in expected.get("rulesets", []):
        name = exp_rs.get("name")
        matches = _rulesets_named(actual, name)
        if not matches:
            drifts.append(f"DRIFT: ruleset {name} missing (expected present + active)")
            continue
        # Validate EVERY same-named ruleset (not last-wins): a disabled/weakened duplicate is drift
        # even if a passing one also exists, and vice-versa (parser/validator differential fix).
        for a in matches:
            tag = name if len(matches) == 1 else f"{name}#{matches.index(a)}"
            exp_enf = exp_rs.get("enforcement", "active")
            if a.get("enforcement") != exp_enf:
                drifts.append(
                    f"DRIFT: ruleset {tag} enforcement expected {exp_enf} got {a.get('enforcement')}")
            # Targeting: an active ruleset retargeted off main applies to NOTHING while looking intact.
            if a.get("target", "branch") != "branch":
                drifts.append(f"DRIFT: ruleset {tag} target expected branch got {a.get('target')}")
            have_refs = set(a.get("ref_name_include", []))
            for ref in exp_rs.get("target_includes", []):
                if ref not in have_refs:
                    drifts.append(
                        f"DRIFT: ruleset {tag} no longer targets '{ref}' (retargeted off main — gate disabled)")
            # Exclude: include=[main] + exclude=[main-matching] => targets main then removes it. The
            # parser read only include; a non-empty exclude on the loop-merge-gates ruleset is drift.
            excl = a.get("ref_name_exclude", [])
            if excl:
                drifts.append(
                    f"DRIFT: ruleset {tag} ref_name.exclude non-empty ({excl}) — may carve main out of scope")
            # Rule-TYPE presence: deleting a whole rule (pull_request / deletion / non_fast_forward) can
            # normalize to a coincidentally-meets-expected value, silently dropping the protection.
            have_types = set(a.get("rule_types", []))
            for rt in exp_rs.get("required_rule_types", []):
                if rt not in have_types:
                    drifts.append(f"DRIFT: ruleset {tag} missing required rule type '{rt}' (protection deleted)")
            bypass = a.get("bypass_actors", [])
            if bypass:
                drifts.append(
                    f"DRIFT: ruleset {tag} bypass_actors expected empty got {len(bypass)} actor(s)")
            want = set(exp_rs.get("required_status_checks", []))
            have = set(a.get("required_status_checks", []))
            for c in sorted(want - have):
                drifts.append(f"DRIFT: ruleset {tag} required_status_checks missing '{c}'")
            exp_appr = exp_rs.get("required_approving_review_count", 0)
            act_appr = a.get("required_approving_review_count", 0)
            if act_appr > exp_appr:  # approvals RE-RAISED — the loop merges autonomously, 0 is intent
                drifts.append(
                    f"DRIFT: ruleset {tag} required_approving_review_count expected <={exp_appr} "
                    f"got {act_appr}")
    # main branch-protection re-imposing classic approvals (the theatrical trap)
    exp_bp = expected.get("branch_protection", {}).get("max_required_approvals", 0)
    act_bp = actual.get("branch_protection", {}).get("max_required_approvals", 0)
    if act_bp > exp_bp:
        drifts.append(
            f"DRIFT: branch_protection required_approving_review_count expected <={exp_bp} got {act_bp}")
    return drifts


def cmd_check(args):
    try:
        expected = _load_json(args.expected)
        actual = _load_json(args.actual)
    except OSError as e:
        print(f"ERROR: cannot read settings file: {e}", file=sys.stderr)
        return 2
    except ValueError as e:  # json.JSONDecodeError is a ValueError subclass
        print(f"ERROR: malformed JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        print("ERROR: expected and actual must both be JSON objects", file=sys.stderr)
        return 2
    if actual.get("gh") == "unavailable":
        # Fail-safe: a gh-unavailable snapshot is NOT drift. Reading it as "all rulesets missing"
        # would be a FALSE tamper alarm; upstream must route this to Watch, not High-Priority.
        print(f"ERROR: actual is a gh-unavailable sentinel ({actual.get('reason', '?')}); "
              "cannot verify live settings — treat as Watch, not drift", file=sys.stderr)
        return 2
    drifts = _check(expected, actual)
    for line in drifts:
        print(line)
    return 1 if drifts else 0


def _gh_json(api_path):
    """Run `gh api <path>`, return parsed JSON. Raise on any failure (caller fails safe)."""
    proc = subprocess.run(
        ["gh", "api", api_path], capture_output=True, text=True, timeout=_GH_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"gh api {api_path} exited {proc.returncode}")
    return json.loads(proc.stdout)


def _normalize_ruleset(detail):
    """gh ruleset-detail JSON -> normalized watched-keys dict the pure `_check` reads."""
    approvals = 0
    checks = []
    rule_types = []
    for rule in detail.get("rules", []):
        rtype = rule.get("type")
        rule_types.append(rtype)
        params = rule.get("parameters", {}) or {}
        if rtype == "pull_request":
            approvals = params.get("required_approving_review_count", 0)
        elif rtype == "required_status_checks":
            checks = [c.get("context") for c in params.get("required_status_checks", [])]
    ref = (detail.get("conditions", {}) or {}).get("ref_name", {}) or {}
    return {
        "name": detail.get("name"),
        "enforcement": detail.get("enforcement"),
        "bypass_actors": detail.get("bypass_actors", []),
        "required_status_checks": checks,
        "required_approving_review_count": approvals,
        "rule_types": rule_types,               # every rule type present (for delete-a-rule detection)
        "target": detail.get("target"),         # "branch" — a retarget to something else disables it
        "ref_name_include": ref.get("include", []),  # must still include refs/heads/main
        "ref_name_exclude": ref.get("exclude", []),  # a main-matching exclude carves the gate off main
    }


def _branch_protection_approvals(base):
    """Classic main branch-protection required approvals; 0 if no protection (HTTP 404).

    404 is a definite "no classic protection" => 0 approvals. Any OTHER error raises, so the whole
    fetch fails safe to unavailable rather than silently reading 0 (which would hide a re-imposed
    approval — a false negative on the theatrical trap)."""
    proc = subprocess.run(
        ["gh", "api", f"{base}/branches/main/protection"],
        capture_output=True, text=True, timeout=_GH_TIMEOUT)
    if proc.returncode != 0:
        if "HTTP 404" in proc.stderr:  # exact "no classic protection"; a stray "404" substring in some
            return 0                   # other error must NOT mask a re-imposed approval (fail safe -> raise)
        raise RuntimeError(proc.stderr.strip() or "branch protection fetch failed")
    data = json.loads(proc.stdout)
    return data.get("required_pull_request_reviews", {}).get("required_approving_review_count", 0)


def _fetch_and_normalize(repo):
    # gh substitutes {owner}/{repo} from the current repo when --repo is not given.
    base = f"repos/{repo}" if repo else "repos/{owner}/{repo}"
    # per_page=100 so loop-merge-gates can't sit beyond a default 30-item page and read as "missing"
    # (a false DRIFT). One page of 100 covers any real repo; avoids --paginate's array-merge quirk.
    rulesets = [_normalize_ruleset(_gh_json(f"{base}/rulesets/{rs['id']}"))
                for rs in _gh_json(f"{base}/rulesets?per_page=100")]
    return {
        "rulesets": rulesets,
        "branch_protection": {"max_required_approvals": _branch_protection_approvals(base)},
    }


def cmd_fetch_live(args):
    try:
        snapshot = _fetch_and_normalize(args.repo)
    except Exception as e:  # fail-safe: ANY gh/parse failure => unavailable sentinel, never crash loop
        print(json.dumps({"gh": "unavailable", "reason": str(e)}))
        print(f"note: could not fetch live settings ({args.repo or 'current repo'}): {e}",
              file=sys.stderr)
        return 0
    print(json.dumps(snapshot, indent=2))
    return 0


def _selftest(args=None):
    import copy
    import os
    import tempfile

    # Committed intent (expected-shape, mirrors settings-expected.json): the MINIMUM secure posture.
    expected_intent = {
        "rulesets": [{
            "name": RULESET, "enforcement": "active", "bypass_actors": [],
            "required_status_checks": ["smoke", "graph", "publish-gate", "pr-classified"],
            "required_approving_review_count": 0,
            "required_rule_types": ["pull_request", "required_status_checks", "deletion", "non_fast_forward"],
            "target_includes": ["refs/heads/main"],
        }],
        "branch_protection": {"max_required_approvals": 0},
    }
    # A live snapshot (actual-shape, as fetch-live normalizes) that MEETS the intent.
    actual_secure = {
        "rulesets": [{
            "name": RULESET, "enforcement": "active", "bypass_actors": [],
            "required_status_checks": ["smoke", "graph", "publish-gate", "pr-classified"],
            "required_approving_review_count": 0,
            "rule_types": ["pull_request", "required_status_checks", "deletion", "non_fast_forward"],
            "target": "branch", "ref_name_include": ["refs/heads/main"], "ref_name_exclude": [],
        }],
        "branch_protection": {"max_required_approvals": 0},
    }

    with tempfile.TemporaryDirectory() as d:
        exp_path = os.path.join(d, "expected.json")
        with open(exp_path, "w") as f:
            json.dump(expected_intent, f)

        def check_actual(actual):
            """Write `actual` to a tempfile and run the REAL cmd_check — rc IS the exit contract."""
            ap = os.path.join(d, "actual.json")
            with open(ap, "w") as f:
                json.dump(actual, f)
            return cmd_check(argparse.Namespace(expected=exp_path, actual=ap))

        def drift(edit, label):
            """Deep-copy the secure snapshot, apply `edit`, assert the REAL check flags DRIFT (exit 1)."""
            m = copy.deepcopy(actual_secure)
            edit(m["rulesets"][0], m)
            rc = check_actual(m)
            assert rc == 1, f"{label} should DRIFT, got exit {rc}"
            print(f"  {label}: DRIFT exit 1  OK")

        # (a) actual MEETS the intent -> no drift
        rc = check_actual(actual_secure)
        assert rc == 0, f"(a) secure posture should pass, got exit {rc}"
        print("  (a) actual meets intent: exit 0  OK")

        # VALUE weakenings
        drift(lambda rs, m: rs.update(enforcement="disabled"), "(b) enforcement active->disabled")
        drift(lambda rs, m: rs.update(bypass_actors=[{"actor_id": 1, "actor_type": "Team"}]), "(c) bypass_actors non-empty")
        drift(lambda rs, m: rs.update(required_status_checks=["smoke", "graph", "publish-gate"]), "(d) required check dropped")
        drift(lambda rs, m: rs.update(required_approving_review_count=1), "(e) ruleset approvals 0->1")
        drift(lambda rs, m: m["branch_protection"].update(max_required_approvals=1), "(e2) branch-protection re-imposes 1 approval")
        drift(lambda rs, m: m.update(rulesets=[]), "(f) ruleset loop-merge-gates missing")
        # DELETION/TARGET weakenings that normalize to a coincidentally-meets-expected value (codex P1 fixes)
        drift(lambda rs, m: rs.update(rule_types=["required_status_checks", "deletion", "non_fast_forward"]), "(i) pull_request rule deleted (no PR required)")
        drift(lambda rs, m: rs.update(rule_types=["pull_request", "required_status_checks"]), "(j) deletion+non_fast_forward rules deleted")
        drift(lambda rs, m: rs.update(ref_name_include=["refs/heads/nonexistent"]), "(k) ruleset retargeted off main")
        drift(lambda rs, m: rs.update(target="tag"), "(k2) ruleset target changed off branch")
        # (l) duplicate-name shadow: disable the real ruleset + add a passing same-named duplicate.
        #     last-wins would MATCH; validating ALL same-named catches the disabled one.
        def _dup_shadow(rs, m):
            disabled = copy.deepcopy(rs); disabled["enforcement"] = "disabled"
            m["rulesets"] = [disabled, copy.deepcopy(rs)]  # [disabled-real, active-dup]
        drift(_dup_shadow, "(l) disabled real + passing duplicate (last-wins shadow)")
        # (m) ref_name.exclude carves main out of scope while include still lists main
        drift(lambda rs, m: rs.update(ref_name_exclude=["refs/heads/main"]), "(m) ref_name.exclude removes main")

        # (g) robustness: malformed actual JSON -> clean exit 2, NOT a traceback
        bad = os.path.join(d, "bad.json")
        with open(bad, "w") as f:
            f.write("{not valid json")
        rc = cmd_check(argparse.Namespace(expected=exp_path, actual=bad))
        assert rc == 2, f"(g) malformed actual should be clean exit 2, got exit {rc}"
        print("  (g) malformed actual JSON: clean exit 2 (no traceback)  OK")

        # (h) fail-safe: a gh-unavailable sentinel as actual -> exit 2, NOT a false DRIFT(1)/match(0)
        sent = os.path.join(d, "sentinel.json")
        with open(sent, "w") as f:
            json.dump({"gh": "unavailable", "reason": "gh not found"}, f)
        rc = cmd_check(argparse.Namespace(expected=exp_path, actual=sent))
        assert rc == 2, f"(h) gh-unavailable sentinel should be exit 2 (not drift), got exit {rc}"
        print("  (h) gh-unavailable sentinel actual: exit 2, not false DRIFT  OK")

    print("SENTINEL_OK")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Settings-tamper sentinel: live GitHub settings vs committed intent (read-only)")
    p.add_argument("--self-test", action="store_true",
                   help="run the self-test demo, print SENTINEL_OK, exit 0")
    sub = p.add_subparsers(dest="cmd")

    pc = sub.add_parser("check", help="compare expected(min secure posture) vs actual; exit 1 on drift")
    pc.add_argument("--expected", required=True)
    pc.add_argument("--actual", required=True)
    pc.set_defaults(func=cmd_check)

    pf = sub.add_parser(
        "fetch-live", help="best-effort gh dump of live rulesets + main branch protection, normalized")
    pf.add_argument("--repo", default=None,
                    help="owner/repo; default = current repo via gh {owner}/{repo} placeholders")
    pf.set_defaults(func=cmd_fetch_live)

    pt = sub.add_parser("test", help="alias for --self-test")
    pt.set_defaults(func=_selftest)

    args = p.parse_args(argv)
    if args.self_test:
        return _selftest(args)
    if not getattr(args, "func", None):
        p.print_help(sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
