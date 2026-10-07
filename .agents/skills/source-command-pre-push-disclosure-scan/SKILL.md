---
name: "source-command-pre-push-disclosure-scan"
description: "Gate a commit/push on a leak scan of the exact push surface (git status), classify each hit as boundary/breach/already-public, prove any scrub edit inert, then allow commit wording."
---

# source-command-pre-push-disclosure-scan

Use this skill when the user asks to run the migrated source command `pre-push-disclosure-scan`.

## Command Template

Run the pre-push disclosure scan before staging a commit that publishes to a public or shared mirror. Invariant: `grep(push_surface, breach_terms) == ∅` before `git add`.

Steps:
1. **Identify the exact push surface** — `git status --porcelain`; the surface = the files you will stage (`M`/`A`/`??` you intend to `git add`). Untracked files in scope; tracked-unchanged files are already-public-not-this-push. Write the file list down.
2. **Grep ONLY that surface** for the project's private-provenance terms (NOT the whole tree, NOT generic strings): `grep -niE '<terms>' <surface files>; echo "grep_exit=$?"`.
3. **Classify each hit**: boundary-matching (should be public — leave) / breach (private grant term — genericize or remove before staging) / already-public-not-this-push (in HEAD already — flag for a separate pass, don't block this commit).
4. **Rerun the smallest inertness proof** after any scrub edit (module demo / cheapest `*_OK` / `ast.parse`) to prove the edit changed disclosure only, not behavior.
5. **Only then write commit wording** — a "scrub-clean" claim is licensed only by step 2's re-grep returning ∅ on breach terms. Verify dependency completeness (untracked imports must be staged). Commit/push stay human-owned unless explicitly authorized.

Full contract + classification rules + per-project breach-term list + gotchas: `~/Projects/.Codex/skills/pre-push-disclosure-scan/SKILL.md`.
