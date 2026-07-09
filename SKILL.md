---
name: podcast-debrief
description: Turn a Claude Science project's saved artifacts into a fact-grounded, two-voice podcast script plus a portable handoff package (script.json, fact_ledger.csv, transcript.md, render_brief.md) that Claude Code renders into finished audio with real TTS and ffmpeg. Use when the user wants a podcast, audio debrief, spoken summary, or "episode" about what a project has done and where it goes next. Splits content generation (here, grounded in artifacts) from audio production (Claude Code, local machine).
---

# podcast-debrief

Produce a **grounded two-voice podcast script** from a project's own artifacts,
then hand rendering off to Claude Code. This skill owns the *content* and its
*provenance*; Claude Code owns the *audio render* (premium TTS + ffmpeg) on the
user's machine, where the network allowlist and offline-only voices don't apply.

**Why the split:** the sandbox can't reach premium TTS APIs, and its offline
voice is flat. Claude Code has the user's keys, real ffmpeg, and no allowlist —
so it makes genuinely good audio. Meanwhile artifact mining, fact-checking, and
scripting are exactly what Claude Science does well. The interface between them
is the `podcast_package/` folder.

## When to use
User asks for a podcast / audio debrief / spoken recap / "episode" about the
project's progress and next steps. Also good for a stakeholder update or a
demo voiceover grounded in real results.

## Helper functions (auto-loaded from kernel.py)
- `find_fact_sources(search=None, content_types=None, limit=60)` — list
  fact-bearing artifacts (JSON/markdown summaries) in the project.
- `build_ledger(sources, extra_facts=None)` — flatten JSON sources into a
  claim→value→source **fact ledger**; append manual facts if needed.
- `draft_podcast_script(ledger, speakers=None, target_minutes=2.0, topic=None, style=None, model=None)`
  — generate a two-voice dialogue grounded ONLY in the ledger.
- `verify_script(script, ledger, model=None)` — audit every turn; flags any
  quantitative/named claim not supported by the ledger.
- `write_package(script, ledger, out_dir="podcast_package", speakers=None, audio_name=None, provider="ElevenLabs", title=None)`
  — write the handoff package; returns the file paths.
- `load_script(out_dir="podcast_package")` — reload the saved script.json;
  returns `(turns, meta)`. Use before showing or editing so you work from disk.
- `numbered_transcript(turns)` — per-turn-numbered markdown for review. Present
  its output **verbatim**; never paraphrase turns into chat.
- `edit_turn(out_dir, index, new_text, ledger, verify=True)` — replace a turn's
  text on disk and re-verify just that turn. Returns `{ok, unsupported, ...}`.

## Workflow
1. **Find the facts.** `srcs = find_fact_sources(search="summary facts report")`
   — or pass no `search` to get the newest JSON/markdown artifacts. Prefer
   machine-readable `*facts.json` / `*_report.md` artifacts that carry real
   numbers. Inspect and keep the ones that actually anchor the story.
2. **Build the ledger.** `ledger = build_ledger(srcs)`. This is the substrate
   the whole skill trusts — every spoken number must trace to a row. Add
   `extra_facts=[{"claim_id","value","source"}]` for anything not in a JSON.
3. **Draft the script.** `script = draft_podcast_script(ledger, target_minutes=2)`.
   Customize `speakers` to set names/voice slots, `topic`/`style` to taste.
   Speakers default to HOST + GUEST(Claude) mapped to `voice_a`/`voice_b`.
4. **Verify.** `report = verify_script(script, ledger)`. If `report["ok"]` is
   False, either redraft (facts drifted) or add the missing fact to the ledger
   if it's real and you can cite it. Do NOT ship with unresolved findings —
   this is the step that prevents confidently-wrong audio.
5. **Write the package.** `paths = write_package(script, ledger, title=...,
   provider="ElevenLabs")`, then `save_artifacts(paths, language="python")`.
6. **Show for review — VERBATIM.** `turns, _ = load_script()` then present
   `numbered_transcript(turns)` exactly. NEVER retype or paraphrase the script
   from memory into chat: a paraphrase desyncs the turn numbers the user marks
   up from the saved `script.json` that actually gets rendered. The words on
   screen must be byte-identical to the words on disk.
7. **Apply feedback with the edit loop.** For each change, call
   `edit_turn(out_dir, index, new_text, ledger)` — it writes to disk AND
   re-verifies that turn. If `ok` is False, the new wording states a fact not in
   the ledger: add it via `build_ledger(extra_facts=[...])` if it's real and
   citable, else revise. Re-save the package artifacts (`version_of=`) after
   edits so the rendered audio matches the approved text.
8. **Hand off.** The package includes `render.py` — a self-contained local
   renderer (OpenAI or ElevenLabs TTS + ffmpeg). Tell the user to open the
   folder in Claude Code, set one API key, map the two `voice_slot`s to real
   voice ids at the top of `render.py`, and run it. Confirm which provider they
   have a key for so `render_brief.md` names the right one.

## The handoff contract (podcast_package/)
- `script.json` — `{title, speakers, turns:[{speaker,name,voice_slot,text}]}`
- `fact_ledger.csv` — `claim_id,value,source,version_id` (audit trail)
- `transcript.md` — human-readable
- `render_brief.md` — provider, voice-slot mapping, ffmpeg concat +
  loudness-normalize to -16 LUFS, MP3 export, length guidance

## Voice slots
The script assigns a `voice_slot` (e.g. `voice_a`, `voice_b`) per speaker, not a
concrete voice id — the skill stays provider-agnostic. `render_brief.md` maps
each slot to a real voice id on the Code side. To make the host match the user,
set `speakers` names/genders when you draft.

## Notes
- Keep the ledger honest: markdown sources are recorded for provenance but not
  auto-parsed, so cite their numbers verbatim (add them via `extra_facts`).
- For a hard time budget, trim exchanges rather than speeding voices unnaturally.
- The skill produces text + a plan; it does not synthesize audio itself.
