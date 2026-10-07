---
name: "source-command-notebooklm"
description: "Interact with Google NotebookLM — create notebooks, add sources, chat, generate content (podcast, video, quiz, slides, etc.), and download artifacts."
---

# source-command-notebooklm

Use this skill when the user asks to run the migrated source command `notebooklm`.

## Command Template

Programmatic access to Google NotebookLM for notebooks, sources, chat, and content generation.

Steps:
1. Verify CLI: `notebooklm --version || bash scripts/notebooklm-setup.sh`
2. Route by intent:
   - **Notebooks**: `notebooklm list`, `notebooklm create "Title"`, `notebooklm use <id>`
   - **Sources**: `notebooklm source add "<url-or-path>"` (URLs, PDFs, YouTube, Drive, text)
   - **Chat**: `notebooklm ask "question"` (modes: `--mode default|learning-guide|concise|detailed`)
   - **Generate**: `notebooklm generate <type> [description] [--wait] [--json]`
     Types: `audio`, `video`, `cinematic-video`, `slide-deck`, `quiz`, `flashcards`, `infographic`, `mind-map`, `report`, `data-table`
   - **Download**: `notebooklm download <type> ./generated/notebooklm/<filename>`
   - **Research**: `notebooklm source add-research "query"`
   - **Share**: `notebooklm share --public`
3. For long-running generation (audio/video): use `--json` to capture artifact ID, poll with `notebooklm artifact list`, download when complete
4. After downloads: verify with `ls -lh <output-path>`
5. For parallel work: use explicit `-n <notebook_id>` instead of `notebooklm use`
