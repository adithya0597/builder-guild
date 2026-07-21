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


def _index_by_name(doc):
    return {r.get("name"): r for r in doc.get("rulesets", []) if isinstance(r, dict)}


def _check(expected, actual):
    """PURE comparison. Return a list of `DRIFT: ...` strings (empty == no drift).

    Data-driven off `expected`: for each ruleset named in expected, the same-named ruleset in actual
    must MEET it (enforcement active, bypass empty, required checks a superset, approvals not raised).
    Comparison DIRECTION per key lives here (code); the VALUES live in settings-expected.json (data).
    """
    drifts = []
    act = _index_by_name(actual)
    for exp_rs in expected.get("rulesets", []):
        name = exp_rs.get("name")
        a = act.get(name)
        if a is None:
            drifts.append(f"DRIFT: ruleset {name} missing (expected present + active)")
            continue
        exp_enf = exp_rs.get("enforcement", "active")
        if a.get("enforcement") != exp_enf:
            drifts.append(
                f"DRIFT: ruleset {name} enforcement expected {exp_enf} got {a.get('enforcement')}")
        bypass = a.get("bypass_actors", [])
        if bypass:
            drifts.append(
                f"DRIFT: ruleset {name} bypass_actors expected empty got {len(bypass)} actor(s)")
        want = set(exp_rs.get("required_status_checks", []))
        have = set(a.get("required_status_checks", []))
        for c in sorted(want - have):
            drifts.append(f"DRIFT: ruleset {name} required_status_checks missing '{c}'")
        exp_appr = exp_rs.get("required_approving_review_count", 0)
        act_appr = a.get("required_approving_review_count", 0)
        if act_appr > exp_appr:  # approvals RE-RAISED — the loop merges autonomously, 0 is intent
            drifts.append(
                f"DRIFT: ruleset {name} required_approving_review_count expected <={exp_appr} "
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
    """gh ruleset-detail JSON -> normalized watched-keys dict (same shape as expected.json)."""
    approvals = 0
    checks = []
    for rule in detail.get("rules", []):
        params = rule.get("parameters", {}) or {}
        if rule.get("type") == "pull_request":
            approvals = params.get("required_approving_review_count", 0)
        elif rule.get("type") == "required_status_checks":
            checks = [c.get("context") for c in params.get("required_status_checks", [])]
    return {
        "name": detail.get("name"),
        "enforcement": detail.get("enforcement"),
        "bypass_actors": detail.get("bypass_actors", []),
        "required_status_checks": checks,
        "required_approving_review_count": approvals,
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
        if "404" in proc.stderr:
            return 0
        raise RuntimeError(proc.stderr.strip() or "branch protection fetch failed")
    data = json.loads(proc.stdout)
    return data.get("required_pull_request_reviews", {}).get("required_approving_review_count", 0)


def _fetch_and_normalize(repo):
    # gh substitutes {owner}/{repo} from the current repo when --repo is not given.
    base = f"repos/{repo}" if repo else "repos/{owner}/{repo}"
    rulesets = [_normalize_ruleset(_gh_json(f"{base}/rulesets/{rs['id']}"))
                for rs in _gh_json(f"{base}/rulesets")]
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

    # The committed minimum-secure posture (mirrors settings-expected.json / loop-merge-gates.json).
    secure = {
        "rulesets": [{
            "name": RULESET,
            "enforcement": "active",
            "bypass_actors": [],
            "required_status_checks": ["smoke", "graph", "publish-gate", "pr-classified"],
            "required_approving_review_count": 0,
        }],
        "branch_protection": {"max_required_approvals": 0},
    }

    with tempfile.TemporaryDirectory() as d:
        exp_path = os.path.join(d, "expected.json")
        with open(exp_path, "w") as f:
            json.dump(secure, f)

        def check_actual(actual):
            """Write `actual` to a tempfile and run the REAL cmd_check — rc IS the exit contract."""
            ap = os.path.join(d, "actual.json")
            with open(ap, "w") as f:
                json.dump(actual, f)
            return cmd_check(argparse.Namespace(expected=exp_path, actual=ap))

        # (a) actual == expected secure posture -> no drift, exit 0
        rc = check_actual(secure)
        assert rc == 0, f"(a) identical secure posture should pass, got exit {rc}"
        print("  (a) actual == expected secure posture: exit 0  OK")

        # (b) ruleset enforcement flipped active -> disabled  (the deliberate-change DETECTION)
        m = copy.deepcopy(secure); m["rulesets"][0]["enforcement"] = "disabled"
        rc = check_actual(m)
        assert rc == 1, f"(b) disabled enforcement should DRIFT, got exit {rc}"
        print("  (b) enforcement active->disabled: DRIFT exit 1  OK")

        # (c) bypass_actors non-empty
        m = copy.deepcopy(secure)
        m["rulesets"][0]["bypass_actors"] = [{"actor_id": 1, "actor_type": "Team"}]
        rc = check_actual(m)
        assert rc == 1, f"(c) non-empty bypass should DRIFT, got exit {rc}"
        print("  (c) bypass_actors non-empty: DRIFT exit 1  OK")

        # (d) a required status check dropped
        m = copy.deepcopy(secure)
        m["rulesets"][0]["required_status_checks"] = ["smoke", "graph", "publish-gate"]  # -pr-classified
        rc = check_actual(m)
        assert rc == 1, f"(d) dropped required check should DRIFT, got exit {rc}"
        print("  (d) required check dropped (pr-classified): DRIFT exit 1  OK")

        # (e) pull_request approvals re-raised 0 -> 1 (in the ruleset)
        m = copy.deepcopy(secure); m["rulesets"][0]["required_approving_review_count"] = 1
        rc = check_actual(m)
        assert rc == 1, f"(e) ruleset approvals re-raised should DRIFT, got exit {rc}"
        print("  (e) approvals re-raised 0->1 (ruleset): DRIFT exit 1  OK")

        # (e2) main branch-protection re-imposing 1 approval (the theatrical trap — distinct key)
        m = copy.deepcopy(secure); m["branch_protection"]["max_required_approvals"] = 1
        rc = check_actual(m)
        assert rc == 1, f"(e2) branch-protection approvals should DRIFT, got exit {rc}"
        print("  (e2) branch-protection re-imposes 1 approval: DRIFT exit 1  OK")

        # (f) ruleset missing entirely
        m = copy.deepcopy(secure); m["rulesets"] = []
        rc = check_actual(m)
        assert rc == 1, f"(f) missing ruleset should DRIFT, got exit {rc}"
        print("  (f) ruleset loop-merge-gates missing: DRIFT exit 1  OK")

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
