# Governance

## Today: one maintainer decides

Builder Guild is solo-maintained by [@adithya0597](https://github.com/adithya0597). Every issue
and PR is decided by that one person, today. No committee, no vote, no legal entity behind the
project — see [SECURITY.md](SECURITY.md) for the same solo-maintainer reality on the security side.

## Decision rule

Issues and PRs are triaged and decided by the maintainer, on the weekly cadence described in the
README. The three invariants in
[`CONTRIBUTING.md`](CONTRIBUTING.md#ground-rules-the-invariants-that-make-this-work) — no LLM ever
writes a fact, namespace on node *and* edge, bi-temporal by default — are not up for vote. They're
the product: the deterministic-write invariant is enforced by `tools/check_write_gateway.py` in CI,
namespace isolation by the namespace/decoy self-test in `01-context/src/serve.py`, bi-temporal
correctness by the invariant sweeps, and the staging gate by its own CI selftest. None of that is a
preference to be argued with. Everything else — API shape, roadmap priority, what merges — is the
maintainer's call.

## Path to maintainers

No formal application exists yet. The realistic path: sustained, high-quality contributions earn
**triage rights** (labeling, duplicate-closing, review) first, then **merge rights** on non-security
paths. Security-sensitive paths — the write gateway, staging gate, `SECURITY.md`, this file — already
require code-owner review on `main`: branch protection enforces [`CODEOWNERS`](.github/CODEOWNERS)
review today, no matter who else earns merge rights elsewhere.

When Builder Guild grows past one maintainer, contributor trust is meant to work the way the product
treats agent autonomy: extended deliberately, scoped to a role, revocable, and never granted by
default — earned against evidence rather than assumed. A vouch-style ladder, where already-trusted
contributors vouch in new ones, is the intended future shape of that on the contributor side,
mirroring the leased-autonomy model on the agent side.

None of this is wired up yet, and no tiers exist today — this names the intended direction, not an
installed mechanism or a promised timeline.

## Succession

Worth naming plainly: if the maintainer goes quiet for an extended stretch (no commits, no issue
responses — 90+ days) the project doesn't just disappear. It's licensed [AGPL-3.0](LICENSE)
specifically so anyone can fork and continue it without asking anyone's permission. That guarantee
is why the license choice matters as much as the code does.

## Where this could go

At scale, foundation-style stewardship — multiple maintainers, a neutral home for the license —
is the long-term direction, the same shape other AI-era OSS projects have moved toward once they
outgrew one person. That's not happening now, and no date is attached to it.

Two things about that future shape are recorded now, before any committee exists, so they travel with
any move to foundation stewardship: no single employer would ever hold more than one-third of the
seats, and while routine decisions would stay simple-majority, any change to this governance document
itself will require a two-thirds supermajority once a committee exists. Recording these caps before
there's a committee to benefit from them is deliberate — they're meant to bind whoever inherits the
project, not to be negotiated once the seats are filled.
