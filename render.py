#!/usr/bin/env python3
"""Render podcast_package/script.json into a finished MP3.

Runs on your local machine (real TTS + ffmpeg). Reads script.json, synthesizes
one clip per turn with the voice mapped to its voice_slot, stitches with short
gaps, loudness-normalizes to the -16 LUFS podcast standard, and writes the MP3.

Providers: OpenAI (default) or ElevenLabs. Pick via --provider.
"""
import argparse, json, os, subprocess, sys, tempfile, wave

# --- Map each script voice_slot -> a concrete provider voice --------------
# OpenAI voices: alloy ash ballad coral echo fable onyx nova sage shimmer verse marin cedar
OPENAI_VOICES = {"voice_a": "coral", "voice_b": "sage"}   # a: US female host, b: guest
# ElevenLabs: paste voice IDs from your Voice Lab (elevenlabs.io -> Voices)
ELEVEN_VOICES = {"voice_a": "PASTE_FEMALE_VOICE_ID", "voice_b": "PASTE_SECOND_VOICE_ID"}

GAP_MS = 220            # silence between turns
LUFS = -16.0           # integrated loudness target (podcast standard)


def synth_openai(text, voice, out_wav):
    from openai import OpenAI
    client = OpenAI()  # reads OPENAI_API_KEY from env
    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts", voice=voice, input=text,
        instructions="Warm, natural podcast delivery; conversational, unhurried.",
        response_format="wav",
    ) as resp:
        resp.stream_to_file(out_wav)


def synth_eleven(text, voice_id, out_wav):
    from elevenlabs.client import ElevenLabs
    client = ElevenLabs()  # reads ELEVENLABS_API_KEY from env
    audio = client.text_to_speech.convert(
        text=text, voice_id=voice_id, model_id="eleven_v3",
        output_format="pcm_24000",  # raw PCM -> wrap into a wav below
    )
    pcm = b"".join(audio)
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(pcm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default="script.json")
    ap.add_argument("--provider", choices=["openai", "eleven"], default="openai")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    data = json.load(open(args.script))
    turns = data["turns"]
    out_name = args.out or "podcast.mp3"
    voices = OPENAI_VOICES if args.provider == "openai" else ELEVEN_VOICES
    synth = synth_openai if args.provider == "openai" else synth_eleven

    work = tempfile.mkdtemp(prefix="podcast_")
    seg_paths = []
    for i, t in enumerate(turns):
        slot = t.get("voice_slot", "voice_a")
        voice = voices.get(slot)
        if not voice or "PASTE" in str(voice):
            sys.exit(f"No voice set for slot {slot!r} — edit the *_VOICES map at top of render.py")
        seg = os.path.join(work, f"seg_{i:03d}.wav")
        print(f"[{i+1}/{len(turns)}] {t['name']} ({slot}) -> {voice}")
        synth(t["text"], voice, seg)
        seg_paths.append(seg)

    # silence clip matching the first segment's format
    with wave.open(seg_paths[0]) as w0:
        fr, ch, sw = w0.getframerate(), w0.getnchannels(), w0.getsampwidth()
    sil = os.path.join(work, "silence.wav")
    with wave.open(sil, "wb") as s:
        s.setnchannels(ch); s.setsampwidth(sw); s.setframerate(fr)
        s.writeframes(b"\x00" * int(fr * ch * sw * GAP_MS / 1000))

    # concat list: seg, silence, seg, silence, ...
    lst = os.path.join(work, "list.txt")
    with open(lst, "w") as f:
        for i, seg in enumerate(seg_paths):
            f.write(f"file '{seg}'\n")
            if i < len(seg_paths) - 1:
                f.write(f"file '{sil}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
        "-af", f"loudnorm=I={LUFS}:TP=-1.5:LRA=11", "-b:a", "128k", out_name
    ], check=True)
    print(f"\nWrote {out_name}")


if __name__ == "__main__":
    main()
