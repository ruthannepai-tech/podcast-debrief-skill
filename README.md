# podcast-debrief

Turn a research project's saved artifacts into a **fact-grounded, two-voice
podcast script** plus a portable handoff package that a local machine renders
into finished audio with real TTS and ffmpeg.

Built as a [Claude Science](https://www.anthropic.com) skill. It splits the work
along the line each tool is best at:

- **Content generation** (grounded in your project's own data artifacts) —
  runs in the analysis environment, with programmatic access to the artifact
  store and an LLM for scripting and fact-checking.
- **Audio production** (premium TTS + ffmpeg) — runs on your local machine via
  Claude Code, where you have API keys, real ffmpeg, and no network sandbox.

The interface between the two is the `podcast_package/` folder.

## Why it exists

A debrief podcast is only worth listening to if the numbers in it are real. The
core of this skill is a **fact ledger**: every quantitative claim the script
makes — a gene count, a fold change, a p-value — is traced to the source
artifact it came from, and a verification pass rejects any spoken claim that
isn't in the ledger. The script you render is one that has been audited against
its own data.

## Pipeline

```
find_fact_sources  ->  build_ledger  ->  draft_podcast_script
                                              |
                                         verify_script   (reject unsupported claims)
                                              |
                                         write_package   ->  podcast_package/
                                                                script.json
                                                                fact_ledger.csv
                                                                transcript.md
                                                                render_brief.md
                                                                render.py
```

Then, locally:

```bash
cd podcast_package
python3 -m venv .venv && source .venv/bin/activate
pip install openai            # or: pip install elevenlabs
export OPENAI_API_KEY=...      # or ELEVENLABS_API_KEY
# edit the voice map at the top of render.py, then:
python render.py --provider openai --out episode.mp3
```

`render.py` synthesizes one clip per turn with the voice mapped to its
`voice_slot`, stitches them with short gaps, loudness-normalizes the mix to the
-16 LUFS podcast standard, and exports an MP3.

## Files

- `SKILL.md` — the skill definition and step-by-step workflow.
- `kernel.py` — helper functions, auto-loaded into the kernel when the skill loads.
- `render.py` — the self-contained local renderer (OpenAI or ElevenLabs + ffmpeg).

## Handoff contract (`podcast_package/`)

| file | purpose |
|------|---------|
| `script.json` | ordered turns: `{speaker, name, voice_slot, text}` |
| `fact_ledger.csv` | `claim_id,value,source,version_id` — provenance for every claim |
| `transcript.md` | human-readable transcript |
| `render_brief.md` | provider, voice-slot mapping, ffmpeg + loudness settings |
| `render.py` | run this to produce the audio |

## Notes

- The script assigns abstract `voice_slot`s, not concrete voices — the skill
  stays provider-agnostic; you map slots to real voice ids at render time.
- TTS providers require disclosure that a voice is AI-generated; label published
  audio accordingly.
- Verify before you ship: don't render a script with unresolved ledger findings.

## License

MIT — see [LICENSE](LICENSE).
