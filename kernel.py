"""Sidecar for the podcast-debrief skill.

Turns a Claude Science project's saved artifacts into a fact-grounded,
two-voice podcast script plus a portable handoff package that Claude Code
renders into finished audio. Every spoken claim is traced to a source
artifact in a fact ledger, and a verification pass rejects any turn whose
numbers are not in the ledger.

Call order (see SKILL.md): find_fact_sources -> build_ledger ->
draft_podcast_script -> verify_script -> write_package.
The `host` singleton is a kernel global; functions reference it at call time.
"""

DEFAULT_SPEAKERS = (
    {"role": "HOST", "name": "Host", "voice_slot": "voice_a"},
    {"role": "GUEST", "name": "Claude", "voice_slot": "voice_b"},
)

LOUDNESS_TARGET_LUFS = -16.0
CROSSFADE_MS = 120
GAP_MS = 220


def find_fact_sources(search=None, content_types=None, limit=60):
    """Return candidate fact-bearing artifacts (JSON/markdown summaries).

    Ranked-fuzzy when `search` is given, else newest-first. Prioritizes
    machine-readable *facts.json / *_report.md style artifacts that carry the
    real numbers. Returns a list of {filename, version_id, content_type}.
    """
    if content_types is None:
        content_types = ("application/json", "text/markdown")
    kw = {"limit": limit}
    if search:
        kw["search"] = search
    res = host.artifacts(**kw)
    out = []
    for a in res.get("artifacts", []):
        ct = a.get("content_type", "")
        if content_types and ct not in content_types:
            continue
        out.append({"filename": a["filename"],
                    "version_id": a["latest_version_id"],
                    "content_type": ct})
    return out


def flatten_json(obj, prefix=""):
    rows = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            rows.extend(flatten_json(v, p))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            rows.extend(flatten_json(v, f"{prefix}[{i}]"))
    else:
        rows.append((prefix, obj))
    return rows


def build_ledger(sources, extra_facts=None):
    """Build a fact ledger from source artifacts + optional manual facts.

    `sources`: list of {filename, version_id, ...} (from find_fact_sources) or
    bare version_id strings. JSON sources are flattened to scalar leaves;
    markdown sources are recorded whole for provenance (not auto-parsed).
    `extra_facts`: optional list of {claim_id, value, source} to append by hand.

    Returns a list of ledger rows: {claim_id, value, source, version_id}.
    """
    import json
    ledger = []
    for s in (sources or []):
        vid = s["version_id"] if isinstance(s, dict) else s
        fname = s.get("filename", vid) if isinstance(s, dict) else vid
        path = host.artifact_path(vid)
        is_json = fname.endswith(".json") or (
            isinstance(s, dict) and s.get("content_type") == "application/json")
        if is_json:
            try:
                data = json.load(open(path))
            except Exception as e:
                ledger.append({"claim_id": fname, "value": f"<unparseable: {e}>",
                               "source": fname, "version_id": vid})
                continue
            for key, val in flatten_json(data):
                if isinstance(val, str) and len(val) > 240:
                    val = val[:240] + "..."
                ledger.append({"claim_id": key, "value": val,
                               "source": fname, "version_id": vid})
        else:
            ledger.append({"claim_id": fname,
                           "value": "<markdown source; cite verbatim>",
                           "source": fname, "version_id": vid})
    for ef in (extra_facts or []):
        ledger.append({"claim_id": ef["claim_id"], "value": ef["value"],
                       "source": ef.get("source", "manual"),
                       "version_id": ef.get("version_id", "")})
    return ledger


def ledger_digest(ledger, max_rows=2000):
    # Cap high enough to include a full multi-source ledger. A low cap silently
    # drops rows, which makes verify_script false-flag real facts that live past
    # the cutoff — pass the WHOLE ledger to draft and verify.
    lines = []
    for r in ledger[:max_rows]:
        v = r["value"]
        if isinstance(v, float):
            v = f"{v:g}"
        lines.append(f"{r['claim_id']} = {v}  [src: {r['source']}]")
    return "\n".join(lines)


def draft_podcast_script(ledger, speakers=None, target_minutes=2.0,
                         topic=None, style=None, model=None):
    """Generate a two-voice dialogue grounded ONLY in the ledger.

    Returns a list of turns: {speaker, name, voice_slot, text}. Numbers spoken
    must come from the ledger; the model is told not to invent figures.
    """
    import json
    if speakers is None:
        speakers = [dict(s) for s in DEFAULT_SPEAKERS]
    if model is None:
        model = host.reasoning_model()
    words = int(target_minutes * 150)  # ~150 wpm natural podcast pace
    roles = ", ".join(f"{s['role']} ({s['name']})" for s in speakers)
    digest = ledger_digest(ledger)
    sys = ("You script short, natural two-person science podcasts. You NEVER "
           "state a number, percentage, gene name, or quantitative claim that "
           "is not present in the provided FACT LEDGER. Spell numbers as a "
           "narrator would say them. Output STRICT JSON only.")
    prompt = (
        f"Write a ~{target_minutes:.1f}-minute podcast (~{words} words total) "
        f"between {roles}.\n"
        f"TOPIC: {topic or 'a project progress debrief and where the work goes next'}.\n"
        f"STYLE: {style or 'warm, concrete, curious; host asks, guest explains; no hype'}.\n\n"
        "RULES:\n"
        "- Ground every quantitative claim in the FACT LEDGER below. Do not invent figures.\n"
        "- Open with a one-line hook, close with a forward-looking beat.\n"
        "- Alternate speakers naturally; the guest carries the detail.\n\n"
        "FACT LEDGER (claim = value [source]):\n"
        f"{digest}\n\n"
        "Return JSON: a list of turns, each "
        '{"role": "HOST|GUEST|...", "text": "..."}. No prose outside JSON.'
    )
    r = host.llm(prompt, system=sys, model=model, max_tokens=4000)
    txt = r["text"].strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1]
        if txt.lstrip().startswith("json"):
            txt = txt.lstrip()[4:]
    turns = json.loads(txt)
    by_role = {s["role"]: s for s in speakers}
    default = speakers[0]
    out = []
    for t in turns:
        role = t.get("role", default["role"]).upper()
        sp = by_role.get(role, default)
        out.append({"speaker": role, "name": sp["name"],
                    "voice_slot": sp["voice_slot"], "text": t["text"].strip()})
    return out


def verify_script(script, ledger, model=None):
    """Audit each turn: flag quantitative claims not supported by the ledger.

    Returns {ok, n_turns, n_flagged, findings:[{turn, text, unsupported:[...]}]}.
    Run before shipping; hand findings back into a redraft if not ok.
    """
    import json
    if model is None:
        model = host.reasoning_model()
    digest = ledger_digest(ledger)
    sys = ("You are a fact-checker. Given a FACT LEDGER and a podcast turn, list "
           "ONLY the quantitative or named-entity claims in the turn that are NOT "
           "supported by the ledger (allowing spelled-out numbers, rounding, and "
           "'over/about' phrasing). Output STRICT JSON.")
    findings = []
    reqs = []
    for i, turn in enumerate(script):
        reqs.append({"prompt":
                     f"FACT LEDGER:\n{digest}\n\nTURN #{i}: \"{turn['text']}\"\n\n"
                     'Return JSON {"unsupported": ["claim", ...]} — empty list if all supported.',
                     "system": sys, "model": model, "max_tokens": 500})
    results = host.llm(reqs, max_concurrency=6)
    for i, (turn, res) in enumerate(zip(script, results)):
        if isinstance(res, dict) and "error" in res:
            findings.append({"turn": i, "text": turn["text"],
                             "unsupported": [f"<check-error: {res['error']}>"]})
            continue
        txt = res["text"].strip()
        if txt.startswith("```"):
            txt = txt.split("```", 2)[1]
            if txt.lstrip().startswith("json"):
                txt = txt.lstrip()[4:]
        try:
            parsed = json.loads(txt)
            uns = parsed.get("unsupported", [])
        except Exception:
            uns = []
        if uns:
            findings.append({"turn": i, "text": turn["text"], "unsupported": uns})
    return {"ok": len(findings) == 0, "n_turns": len(script),
            "n_flagged": len(findings), "findings": findings}


def render_brief_text(script, speakers, out_dir, audio_name, provider):
    slots = sorted({t["voice_slot"] for t in script})
    slot_lines = "\n".join(f"- `{s}` -> <assign a {provider} voice id>" for s in slots)
    total_words = sum(len(t["text"].split()) for t in script)
    est_min = round(total_words / 150, 1)
    return f"""# Render brief: {audio_name}

Hand this folder to Claude Code (local machine, real TTS + ffmpeg) to produce
finished audio. Claude Science produced the grounded script; Code does the render.

## Inputs
- `script.json` — ordered turns: {{speaker, name, voice_slot, text}}
- `fact_ledger.csv` — provenance for every quantitative claim (audit trail)
- `transcript.md` — human-readable

## Voices ({len(slots)} slots, {provider} suggested)
{slot_lines}

Recommended providers: ElevenLabs (most natural conversational voices) or
OpenAI `tts-1-hd`. Pick two clearly distinct voices; keep the same voice per
slot across all turns.

## Render steps
1. For each turn in `script.json`, synthesize `text` with the voice mapped to
   its `voice_slot`. Save `seg_{{i:03d}}.wav` (24 kHz mono is fine).
2. Concatenate in order with ~{GAP_MS} ms of silence between turns (or a
   ~{CROSSFADE_MS} ms crossfade for a smoother feel).
3. Loudness-normalize the mix to {LOUDNESS_TARGET_LUFS:g} LUFS integrated
   (podcast standard) and peak-limit to about -1.5 dBTP.
4. Export MP3 (e.g. 128 kbps) as `{audio_name}`. Optional: low intro/outro bed.

Example ffmpeg concat + loudnorm (after per-turn wavs + a silence.wav exist):
```
# build concat list interleaving segments with silence, then:
ffmpeg -f concat -safe 0 -i list.txt -af loudnorm=I={LOUDNESS_TARGET_LUFS:g}:TP=-1.5:LRA=11 -b:a 128k {audio_name}
```

## Target
~{est_min} min ({total_words} words). If a hard 2:00 is required, trim one
exchange rather than speeding the voices past a natural pace.
"""


def write_package(script, ledger, out_dir="podcast_package", speakers=None,
                  audio_name=None, provider="ElevenLabs", title=None):
    """Write the portable handoff package for Claude Code.

    Emits script.json, fact_ledger.csv, transcript.md, render_brief.md into
    `out_dir`. Returns the list of written file paths.
    """
    import os, json, csv
    if speakers is None:
        speakers = [dict(s) for s in DEFAULT_SPEAKERS]
    if audio_name is None:
        audio_name = "podcast.mp3"
    os.makedirs(out_dir, exist_ok=True)
    written = []

    p = os.path.join(out_dir, "script.json")
    json.dump({"title": title or "Project debrief podcast",
               "speakers": speakers, "turns": script},
              open(p, "w"), indent=2)
    written.append(p)

    p = os.path.join(out_dir, "fact_ledger.csv")
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["claim_id", "value", "source", "version_id"])
        w.writeheader()
        for row in ledger:
            w.writerow({k: row.get(k, "") for k in
                        ["claim_id", "value", "source", "version_id"]})
    written.append(p)

    p = os.path.join(out_dir, "transcript.md")
    lines = [f"# {title or 'Project debrief podcast'}", ""]
    for t in script:
        lines.append(f"**{t['name']}:** {t['text']}")
        lines.append("")
    open(p, "w").write("\n".join(lines))
    written.append(p)

    p = os.path.join(out_dir, "render_brief.md")
    open(p, "w").write(render_brief_text(script, speakers, out_dir, audio_name, provider))
    written.append(p)

    # Bundle the self-contained local renderer if it ships alongside this skill.
    import sys, shutil
    here = os.path.dirname(sys._getframe().f_code.co_filename)
    if here:
        src_render = os.path.join(here, "render.py")
        if os.path.isfile(src_render):
            dst = os.path.join(out_dir, "render.py")
            shutil.copyfile(src_render, dst)
            written.append(dst)

    return written


def load_script(out_dir="podcast_package"):
    """Load the saved script.json back from disk.

    Returns (turns, meta) where turns is the list of turn dicts and meta is
    {title, speakers}. ALWAYS reconstruct the review text from THIS return
    value — never from memory — so what the user marks up is byte-identical to
    what will be rendered.
    """
    import os, json
    data = json.load(open(os.path.join(out_dir, "script.json")))
    return data["turns"], {"title": data.get("title"),
                           "speakers": data.get("speakers")}


def numbered_transcript(turns):
    """Return a per-turn-numbered markdown string for review.

    Feed it the turns from load_script() so the numbering the user references
    matches script.json exactly. Present THIS verbatim; do not paraphrase turns
    into chat — a paraphrase desyncs turn numbers from the saved file.
    """
    out = []
    for i, t in enumerate(turns):
        out.append(f"**[{i}] {t['name']}:** {t['text']}")
    return "\n\n".join(out)


def edit_turn(out_dir, index, new_text, ledger, verify=True, model=None):
    """Replace turn `index`'s text in the saved script.json, then re-verify it.

    Writes the change straight back to disk (so the artifact and the audio stay
    in sync with what the user approved) and, by default, runs verify_script on
    just the edited turn against the ledger. Returns
    {index, new_text, ok, unsupported, n_words}. If `ok` is False, the fact in
    new_text isn't in the ledger — add it via build_ledger(extra_facts=...) if
    it's real and citable, or revise the wording.
    """
    import os, json
    path = os.path.join(out_dir, "script.json")
    data = json.load(open(path))
    data["turns"][index]["text"] = new_text.strip()
    json.dump(data, open(path, "w"), indent=2)
    result = {"index": index, "new_text": new_text.strip(),
              "n_words": sum(len(t["text"].split()) for t in data["turns"])}
    if verify:
        rep = verify_script([data["turns"][index]], ledger, model=model)
        result["ok"] = rep["ok"]
        result["unsupported"] = (rep["findings"][0]["unsupported"]
                                 if rep["findings"] else [])
    return result
