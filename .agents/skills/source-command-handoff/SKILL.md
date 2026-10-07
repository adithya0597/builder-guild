---
name: "source-command-handoff"
description: "Write or update a handoff document so the next agent with fresh context can continue this work."
---

# source-command-handoff

Use this skill when the user asks to run the migrated source command `handoff`.

## Command Template

Write or update a handoff document so the next agent with fresh context can continue this work.

Steps:
1. Check if HANDOFF.md already exists in the project root
2. If it exists, read it first to understand prior context before updating
3. Create or update the document with these sections:

   - **Goal**: What we're trying to accomplish
   - **Current Progress**: What's been done so far (with file paths)
   - **What Worked**: Approaches that succeeded
   - **What Didn't Work**: Approaches that failed (so they're not repeated)
   - **Key State**: Current state of any important systems, data, or workflows relevant to the task
   - **Next Steps**: Clear, numbered action items for continuing
   - **Open Questions**: Anything unresolved that needs user input

4. Save as HANDOFF.md in the project root
5. Tell the user the file path so they can start a fresh conversation with: `Codex -r` or reference the file directly
