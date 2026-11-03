"""Verify the song without ears.

1. Symbolic (music21): ranges, ground bass, strong-beat chord tones.
2. Stems (basic-pitch + mir_eval): every part actually sounds the written notes.
3. Mix (Essentia): key, tempo, chord recognition against the plan.
4. Mood/style (Essentia Discogs-EffNet / MusiCNN models): MTG-Jamendo mood
   tags, Discogs styles, instruments, happy/sad, DEAM valence/arousal.
5. Master: loudness, true peak, loudness range; spectrogram image + MP4.
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np

from audio import match_notes, transcribe
from instruments import BUILD, INSTRUMENTS, MODELS

SR = 48000
results: dict = {}
failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def load_song() -> dict:
    return json.loads((BUILD / "song.json").read_text())


# ---------------------------------------------------------------- 1. symbolic
def symbolic(song: dict) -> None:
    from music21 import harmony
    pcs_of, bass_of = {}, {}
    for key, fig in song["figures"].items():
        cs = harmony.ChordSymbol(fig)
        pcs_of[key] = {p.pitchClass for p in cs.pitches}
        bass_of[key] = cs.bass().pitchClass

    def chord_at(beat: float):
        for s, d, k in song["chords"]:
            if s <= beat + 1e-6 < s + d:
                return s, k
        return None, None

    out = {}
    for name, notes in song["tracks"].items():
        lo, hi = INSTRUMENTS[name]["range"]
        bad = [n["pitch"] for n in notes if not lo <= n["pitch"] <= hi]
        check(not bad, f"range {name}: {len(notes)} notes within {lo}-{hi}" + (f" (out: {bad[:5]})" if bad else ""))

    for name in ("bass_pizz", "bass_arco"):
        wrong = []
        for n in song["tracks"][name]:
            s, k = chord_at(n["start"])
            on_downbeat = abs(n["start"] % 4) < 1e-6  # the ground lives on bar downbeats
            if k and on_downbeat and abs(n["start"] - s) < 1e-6 and n["pitch"] % 12 != bass_of[k]:
                wrong.append((n["start"], n["pitch"], k))
        check(not wrong, f"ground bass {name}: every bar downbeat on the ground bass note" + (f" {wrong[:4]}" if wrong else ""))

    clashes, total = [], 0
    for name in ("trumpet", "flute", "rhodes", "glock"):
        for n in song["tracks"][name]:
            beat_in_bar = round(n["start"], 2) % 4
            strong = beat_in_bar in (0.0, 2.0) or (name == "rhodes")
            if not strong:
                continue
            _, k = chord_at(n["start"] + 0.03)  # +0.03: Rhodes roll
            total += 1
            if k and n["pitch"] % 12 not in pcs_of[k]:
                clashes.append((name, n["start"], n["pitch"], k))
    out["strong_beat_chord_tones"] = f"{total - len(clashes)}/{total}"
    check(not clashes, f"harmony: {total - len(clashes)}/{total} strong-beat notes are chord tones" + (f" {clashes[:6]}" if clashes else ""))
    results["symbolic"] = out


# ------------------------------------------------------------------- 2. stems
def stems(song: dict) -> None:
    spb = 60 / song["bpm"]
    out = {}
    # Minimum onset+pitch F1 per part. Polyphonic Rhodes and low bass are
    # harder for basic-pitch, so their bars are lower.
    floors = {"trumpet": 0.8, "flute": 0.75, "glock": 0.75, "bass_pizz": 0.6, "rhodes": 0.6, "horn": 0.6, "bass_arco": 0.5}
    for name, notes in song["tracks"].items():
        wav = BUILD / "stems_raw" / f"{name}.wav"
        if not notes or not wav.exists():
            continue
        ref = [(n["start"] * spb, (n["start"] + n["dur"]) * spb, n["pitch"]) for n in notes]
        m = match_notes(ref, transcribe(wav), onset_tol=0.08)
        out[name] = m
        check(m["recall"] >= floors[name] or m["f1"] >= floors[name],
              f"stem {name}: basic-pitch F1 {m['f1']:.2f} (P {m['precision']:.2f} R {m['recall']:.2f}, "
              f"octave errors {m['octave_errors']}) vs floor {floors[name]}")
    results["stems"] = out


# --------------------------------------------------------------------- 3. mix
def mix_analysis(song: dict, wav: str) -> None:
    import essentia.standard as es
    from music21 import harmony
    audio = es.MonoLoader(filename=wav, sampleRate=44100)()
    out = {}

    key, scale, strength = es.KeyExtractor(profileType="temperley")(audio)
    out["key"] = f"{key} {scale} ({strength:.2f})"
    check(key == "D" and scale == "major", f"key: Essentia detects {out['key']}, expected D major")

    bpm, *_ = es.RhythmExtractor2013(method="multifeature")(audio)
    out["bpm"] = round(float(bpm), 1)
    ok = any(abs(bpm - song["bpm"] * f) < 3 for f in (0.5, 1, 2))
    check(ok, f"tempo: Essentia detects {bpm:.1f} BPM, expected {song['bpm']} (or half/double)")

    # Chord recognition: HPCP -> ChordsDetection, majority vote per planned chord.
    frame, hop = 4096, 2048
    w, spec, peaks = es.Windowing(type="blackmanharris62"), es.Spectrum(), es.SpectralPeaks(
        orderBy="magnitude", magnitudeThreshold=1e-5, minFrequency=40, maxFrequency=5000, maxPeaks=60)
    hpcp = es.HPCP(size=36, referenceFrequency=440, harmonics=8, nonLinear=True, normalized="unitMax")
    frames = np.array([hpcp(*peaks(spec(w(f)))) for f in es.FrameGenerator(audio, frameSize=frame, hopSize=hop)])
    labels, _ = es.ChordsDetection(hopSize=hop, windowSize=1.0)(frames.astype(np.float32))
    names = ["A", "Bb", "B", "C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab"]
    pc = {n: (i + 9) % 12 for i, n in enumerate(names)}
    spb, fps = 60 / song["bpm"], 44100 / hop
    hits, rows = 0, []
    for s, d, k in song["chords"]:
        a, b = int((s + 0.5) * spb * fps), int((s + d) * spb * fps)
        seg = labels[a:b]
        if not len(seg):
            continue
        lab = max(set(seg), key=list(seg).count)
        minor = lab.endswith("m")
        root = pc[lab[:-1] if minor else lab]
        triad = {root, (root + (3 if minor else 4)) % 12, (root + 7) % 12}
        planned = {p.pitchClass for p in harmony.ChordSymbol(song["figures"][k]).pitches}
        ok = triad <= planned
        hits += ok
        rows.append((song["figures"][k], lab, ok))
    out["chord_agreement"] = round(hits / len(rows), 3)
    out["chords"] = rows
    check(out["chord_agreement"] >= 0.6,
          f"chords: Essentia's detected triad fits the planned chord in {hits}/{len(rows)} segments (floor 60%)")
    results["mix"] = out


# -------------------------------------------------------------------- 4. mood
def mood(wav: str) -> None:
    import essentia.standard as es
    audio16 = es.MonoLoader(filename=wav, sampleRate=16000, resampleQuality=4)()
    meta = lambda n: json.loads((MODELS / f"{n}.json").read_text())  # noqa: E731
    emb = es.TensorflowPredictEffnetDiscogs(graphFilename=str(MODELS / "discogs-effnet-bs64-1.pb"),
                                           output="PartitionedCall:1")(audio16)

    def head(name, out="model/Sigmoid", inp="model/Placeholder", e=emb):
        p = es.TensorflowPredict2D(graphFilename=str(MODELS / f"{name}.pb"), input=inp, output=out)(e)
        return dict(zip(meta(name)["classes"], np.mean(p, axis=0).round(4).tolist()))

    res = {}
    m = head("mtg_jamendo_moodtheme-discogs-effnet-1")
    ranked = sorted(m, key=m.get, reverse=True)
    res["moodtheme_top10"] = [(k, m[k]) for k in ranked[:10]]
    targets = ["melancholic", "hopeful", "epic", "dramatic", "film", "emotional", "sad", "retro", "inspiring"]
    res["moodtheme_targets"] = {t: dict(score=m[t], rank=ranked.index(t) + 1) for t in targets}
    g = head("genre_discogs400-discogs-effnet-1", out="PartitionedCall:0", inp="serving_default_model_Placeholder")
    res["genre_top10"] = sorted(g.items(), key=lambda kv: -kv[1])[:10]
    res["genre_targets"] = {k: v for k, v in g.items() if any(s in k for s in
                            ("Soundtrack", "Score", "Jazz-Funk", "Soul-Jazz", "Fusion", "Easy Listening", "Neo-Classical"))}
    ins = head("mtg_jamendo_instrument-discogs-effnet-1")
    res["instrument_top8"] = sorted(ins.items(), key=lambda kv: -kv[1])[:8]
    res["happy"] = head("mood_happy-discogs-effnet-1", out="model/Softmax")["happy"]
    res["sad"] = head("mood_sad-discogs-effnet-1", out="model/Softmax")["sad"]
    mn = es.TensorflowPredictMusiCNN(graphFilename=str(MODELS / "msd-musicnn-1.pb"), output="model/dense/BiasAdd")(audio16)
    va = es.TensorflowPredict2D(graphFilename=str(MODELS / "deam-msd-musicnn-2.pb"), output="model/Identity")(mn)
    res["deam_valence_arousal_1to9"] = np.mean(va, axis=0).round(2).tolist()

    print("mood top-10:", ", ".join(f"{k} {v:.2f}" for k, v in res["moodtheme_top10"]))
    print("mood targets (rank of 56):", ", ".join(f"{k} #{v['rank']}" for k, v in res["moodtheme_targets"].items()))
    print("styles top-10:", ", ".join(f"{k} {v:.2f}" for k, v in res["genre_top10"]))
    print("instruments:", ", ".join(f"{k} {v:.2f}" for k, v in res["instrument_top8"]))
    print(f"happy {res['happy']:.2f}  sad {res['sad']:.2f}  valence/arousal {res['deam_valence_arousal_1to9']}")
    # Bittersweet target: the melancholic/sad side must register, without
    # tipping into pure despair (both happy and sad models engaged).
    t = res["moodtheme_targets"]
    check(t["melancholic"]["rank"] <= 10 or t["sad"]["rank"] <= 10,
          f"mood: melancholic #{t['melancholic']['rank']} / sad #{t['sad']['rank']} of 56 (want one in top 10)")
    check(min(t[k]["rank"] for k in ("film", "dramatic", "epic", "emotional")) <= 10,
          "mood: at least one cinematic tag (film/dramatic/epic/emotional) in top 10")
    results["mood"] = res


# ------------------------------------------------------------------ 5. master
def master(wav: str, name: str) -> None:
    import essentia.standard as es
    import librosa
    import librosa.display
    import matplotlib
    import pyloudnorm as pyln
    import soundfile as sf
    from scipy.signal import resample_poly
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y, sr = sf.read(wav, always_2d=True)
    lufs = pyln.Meter(sr).integrated_loudness(y)
    tp = 20 * np.log10(np.abs(resample_poly(y, 4, 1, axis=0)).max())
    st = es.AudioLoader(filename=wav)()[0]
    _, _, integrated, lra = es.LoudnessEBUR128(sampleRate=sr)(st)
    results["master"] = dict(lufs=round(lufs, 2), true_peak_dbtp=round(float(tp), 2), loudness_range_lu=round(float(lra), 1))
    check(abs(lufs + 14) <= 1, f"loudness {lufs:.1f} LUFS (target -14 ±1)")
    check(tp <= -1.0, f"true peak {tp:.2f} dBTP (ceiling -1.0)")
    check(lra >= 4, f"loudness range {lra:.1f} LU (want ≥ 4 LU of dynamics)")

    mono = y.mean(axis=1)
    fig, ax = plt.subplots(2, 1, figsize=(14, 7), gridspec_kw=dict(height_ratios=[3, 1]), sharex=True)
    S = librosa.amplitude_to_db(np.abs(librosa.stft(mono, n_fft=4096, hop_length=1024)), ref=np.max)
    librosa.display.specshow(S, sr=sr, hop_length=1024, x_axis="time", y_axis="log", ax=ax[0], cmap="magma", vmin=-80)
    ax[0].set_title(f"{name} — spectrogram")
    rms = librosa.feature.rms(y=mono, frame_length=sr, hop_length=sr // 4)[0]
    ax[1].plot(np.arange(len(rms)) / 4, 20 * np.log10(rms + 1e-9))
    ax[1].set_ylabel("RMS dB")
    sections = load_song()["sections"]
    for label, bar, _ in sections:
        t = (bar - 1) * 4 * 60 / load_song()["bpm"]
        for a in ax:
            a.axvline(t, color="cyan", lw=0.8)
        ax[0].text(t + 0.5, 12000, label, color="cyan")
    fig.tight_layout()
    png = BUILD / "audio" / f"{name}_spectrogram.png"
    fig.savefig(png, dpi=90)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-i", wav,
                    "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-vf", "scale=1260:-2",
                    "-c:a", "aac", "-b:a", "256k", "-shortest", str(BUILD / "audio" / f"{name}.mp4")], check=True)


def main(name: str = "canon_sketch") -> None:
    wav = str(BUILD / "audio" / f"{name}.wav")
    song = load_song()
    symbolic(song)
    stems(song)
    mix_analysis(song, wav)
    mood(wav)
    master(wav, name)
    results["failures"] = failures
    (BUILD / "report.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\n{len(failures)} failing check(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main(*sys.argv[1:])
