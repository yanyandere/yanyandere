"""Verify the song without ears.

1. Symbolic (music21): ranges, ground bass, chord tones on strong beats
   (appoggiaturas must resolve by step), canon voices are exact.
2. Stems (Spotify basic-pitch + mir_eval, librosa onsets): every part sounds
   its written notes.
3. Mix (Essentia): key per section, tempo, chord recognition.
4. Mood (Essentia Discogs-EffNet / MusiCNN models), whole song and per
   section: MTG-Jamendo mood tags, Discogs styles, happy/sad, DEAM arousal.
5. Text-audio (LAION-CLAP): style prompts and per-section narrative prompts.
6. Mix balance: lead lines audible over their accompaniment.
7. Master: loudness, true peak, loudness range, section dynamics arc;
   spectrogram image + MP4.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

from audio import match_notes, transcribe
from instruments import BUILD, INSTRUMENTS, MODELS, ROOT

results: dict = {}
failures: list[str] = []

SECTION_KEYS = {"intro": ("D", "major"), "theme": ("D", "major"), "canon": ("D", "major"),
                "tragedy": ("D", "minor"), "fight": ("E", "major"), "outro": ("D", "major")}
# (label, first bar, last bar, lead tracks)
LEADS = [("theme A", 9, 16, ["trumpet", "horn"]), ("theme B", 17, 24, ["trumpet", "horn", "flute"]),
         ("tragedy lament", 41, 48, ["oboe"]), ("tragedy big tune", 49, 56, ["violins", "cellos"]),
         ("fight theme", 61, 68, ["trumpet", "horn", "horns"]), ("fight B theme", 69, 76, ["violins", "flute"]),
         ("outro flute", 85, 88, ["flute"]), ("outro flugel", 89, 92, ["trumpet", "horn"])]
ONSET_TRACKS = {"trumpet": 0.8, "flute": 0.75, "oboe": 0.75, "glock": 0.7, "rhodes": 0.6, "horn": 0.6,
                "horns": 0.55, "trombones": 0.55, "bass_pizz": 0.55, "trumpets_stac": 0.6, "trombones_stac": 0.6,
                "harp": 0.55, "violins_spic": 0.5}
PRESENCE_TRACKS = {"violins": 0.75, "violas": 0.75, "cellos": 0.75, "bass_arco": 0.7}
# VSCO tremolo samples have weak fundamentals (2nd/3rd partial up to 48 dB
# louder), so basic-pitch reports octaves. Their mapping is confirmed by odd
# partials at 3f/5f; here we check each note's pitch class sounds (CQT chroma).
CHROMA_TRACKS = {"violins_trem": 0.75, "violas_trem": 0.75, "cellos_trem": 0.75}
ENERGY_TRACKS = {"bells": 0.95, "timpani": 0.95, "timp_roll": 0.95}  # basic-pitch misreads their partials


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def load_song() -> dict:
    return json.loads((BUILD / "song.json").read_text())


def bar_s(song, bar: float) -> float:
    return (bar - 1) * song["beats_per_bar"] * 60 / song["bpm"]


def section_spans(song) -> dict[str, tuple[float, float]]:
    return {name: (bar_s(song, first), bar_s(song, first + n)) for name, first, n in song["sections"]}


# ---------------------------------------------------------------- 1. symbolic
def symbolic(song: dict) -> None:
    from music21 import harmony
    from music21 import pitch as m21pitch
    figs = {f for _, _, f in song["chords"]}
    pcs_of = {f: {p.pitchClass for p in harmony.ChordSymbol(f).pitches} for f in figs}
    bass_of = {f: harmony.ChordSymbol(f).bass().pitchClass for f in figs}
    starts = [c[0] for c in song["chords"]]

    def chord_at(beat):
        i = int(np.searchsorted(starts, beat + 1e-6, side="right")) - 1
        return song["chords"][max(i, 0)][2]

    out = {}
    for name, notes in song["tracks"].items():
        lo, hi = INSTRUMENTS[name]["range"]
        bad = [n["pitch"] for n in notes if not lo <= n["pitch"] <= hi]
        if notes:
            check(not bad, f"range {name}: {len(notes)} notes within {lo}-{hi}" + (f" (out: {bad[:5]})" if bad else ""))

    for name in ("bass_pizz", "bass_arco"):
        wrong = [(n["start"], n["pitch"], chord_at(n["start"])) for n in song["tracks"][name]
                 if abs(n["start"] % 4) < 1e-6 and n["pitch"] % 12 != bass_of[chord_at(n["start"])]]
        check(not wrong, f"ground bass {name}: every bar downbeat on the chord's bass note" + (f" {wrong[:4]}" if wrong else ""))

    per_track, clashes, apps = {}, [], 0
    for name, notes in song["tracks"].items():
        if INSTRUMENTS[name].get("drums") or not notes:
            continue
        by_start = sorted(notes, key=lambda n: n["start"])
        ok = total = 0
        for n in by_start:
            pos = n["start"] % 2
            if not (pos < 0.12 or pos > 1.995) or n["dur"] < 0.2 or n["tag"] == "orn":
                continue
            fig = chord_at(n["start"] + 0.13 if pos < 0.12 else n["start"])
            total += 1
            if n["pitch"] % 12 in pcs_of[fig]:
                ok += 1
            elif n["tag"] == "app":
                nxt = [m for m in by_start if abs(m["start"] - (n["start"] + n["dur"])) < 0.05]
                if any(abs(m["pitch"] - n["pitch"]) <= 2 and m["pitch"] % 12 in pcs_of[chord_at(m["start"])] for m in nxt):
                    ok += 1
                    apps += 1
                else:
                    clashes.append((name, n["start"], n["pitch"], fig, "unresolved appoggiatura"))
            else:
                clashes.append((name, n["start"], n["pitch"], fig))
        per_track[name] = f"{ok}/{total}"
    total_ok = sum(int(v.split("/")[0]) for v in per_track.values())
    total_n = sum(int(v.split("/")[1]) for v in per_track.values())
    out["strong_beat_chord_tones"] = per_track
    check(not clashes, f"harmony: {total_ok}/{total_n} strong-beat notes are chord tones or resolved appoggiaturas "
                       f"({apps} appoggiaturas)" + (f" {clashes[:6]}" if clashes else ""))

    for canon in song["canons"]:
        subject = []
        t = 0.0
        for bar_i, text in enumerate(canon["subject"]):
            t = bar_i * 4
            for tok in text.split():
                name, dur = tok.split(":")
                d = float(dur.rstrip("!"))
                if name != "r":
                    subject.append((bar_i, t, d, m21pitch.Pitch(name).midi))
                t += d
        bad = []
        for track, start, transpose, n_bars in canon["voices"]:
            have = {(round(n["start"], 3), n["pitch"]): n["dur"] for n in song["tracks"][track]}
            for bar_i, t, d, p in subject:
                if bar_i >= n_bars:
                    continue
                key = (round(start + t, 3), p + transpose)
                if key not in have or abs(have[key] - d) > 0.01:
                    bad.append((track, start + t, p + transpose))
        check(not bad, f"{canon['name']}: {len(canon['voices'])} voices are exact transpositions of the subject"
                       + (f" (missing {bad[:3]})" if bad else ""))
    results["symbolic"] = out


# ------------------------------------------------------------------- 2. stems
def stems(song: dict) -> None:
    import librosa
    spb = 60 / song["bpm"]
    out = {}
    for name, notes in song["tracks"].items():
        wav = BUILD / "stems_raw" / f"{name}.wav"
        if not notes or not wav.exists():
            continue
        ref = [(n["start"] * spb, (n["start"] + n["dur"]) * spb, n["pitch"]) for n in notes]
        y, sr = sf.read(wav, always_2d=True)
        mono = y.mean(axis=1)
        if INSTRUMENTS[name].get("drums"):
            times = sorted({round(s, 2) for s, _, _ in [(n["start"] * spb, 0, 0) for n in notes if n["vel"] >= 60]})
            ref_t = [t for i, t in enumerate(times) if i == 0 or t - times[i - 1] > 0.03]
            on = librosa.onset.onset_detect(y=mono.astype(np.float32), sr=sr, units="time", backtrack=False)
            rec = float(np.mean([np.any(np.abs(on - t) < 0.05) for t in ref_t])) if ref_t else 1.0
            out[name] = dict(onset_recall=round(rec, 3), n_hits=len(ref_t))
            check(rec >= 0.7, f"stem {name}: {rec:.0%} of {len(ref_t)} hits found as audio onsets (floor 70%)")
            continue
        if name in ENERGY_TRACKS:
            hop = sr // 50
            rms = librosa.feature.rms(y=mono.astype(np.float32), frame_length=hop * 2, hop_length=hop)[0]
            db = 20 * np.log10(rms + 1e-9)
            top = db.max()
            heard = [db[int(s * 50):int(s * 50) + 25].max() > top - 40 for s, _, _ in ref]
            frac = float(np.mean(heard))
            out[name] = dict(energy_presence=round(frac, 3), n=len(ref))
            check(frac >= ENERGY_TRACKS[name], f"stem {name}: {frac:.0%} of {len(ref)} notes sound (energy within 40 dB of peak)")
            continue
        if name in CHROMA_TRACKS:
            y22 = librosa.resample(mono.astype(np.float32), orig_sr=sr, target_sr=22050)
            chroma = librosa.feature.chroma_cqt(y=y22, sr=22050, hop_length=512)
            fr = lambda t: int(t * 22050 / 512)  # noqa: E731
            long = [r for r in ref if r[1] - r[0] >= 0.3]
            heard = [chroma[:, fr(s0 + 0.1):fr(e0)].mean(1)[p % 12] >= 0.5 * chroma[:, fr(s0 + 0.1):fr(e0)].mean(1).max()
                     for s0, e0, p in long]
            frac = float(np.mean(heard))
            out[name] = dict(chroma_presence=round(frac, 3), n=len(long))
            check(frac >= CHROMA_TRACKS[name], f"stem {name}: {frac:.0%} of {len(long)} notes' pitch classes sound "
                                               f"(CQT chroma, floor {CHROMA_TRACKS[name]:.0%})")
            continue
        a, b = max(0.0, min(r[0] for r in ref) - 1.0), max(r[1] for r in ref) + 2.0
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            sf.write(tmp.name, y[int(a * sr):int(b * sr)], sr)
            est = [(s + a, e + a, p) for s, e, p in transcribe(tmp.name)]
        m = match_notes(ref, est, onset_tol=0.08)
        long = [r for r in ref if r[1] - r[0] >= 0.3]
        present = [any(q == p and min(e, ee) - max(s, ss) >= 0.25 * (e - s) for ss, ee, q in est) for s, e, p in long]
        m["presence_recall"] = round(float(np.mean(present)), 3) if present else None
        out[name] = m
        if name in PRESENCE_TRACKS:
            ok = (m["presence_recall"] or 0) >= PRESENCE_TRACKS[name]
            check(ok, f"stem {name}: {m['presence_recall']:.0%} of sustained notes sound at the written pitch "
                      f"(floor {PRESENCE_TRACKS[name]:.0%}; onset F1 {m['f1']:.2f})")
        else:
            floor = ONSET_TRACKS[name]
            check(m["f1"] >= floor or m["recall"] >= floor,
                  f"stem {name}: basic-pitch F1 {m['f1']:.2f} (P {m['precision']:.2f} R {m['recall']:.2f}, "
                  f"octave errors {m['octave_errors']}) vs floor {floor}")
    results["stems"] = out


# --------------------------------------------------------------------- 3. mix
def mix_analysis(song: dict, wav: str) -> None:
    import essentia.standard as es
    from music21 import harmony
    audio = es.MonoLoader(filename=wav, sampleRate=44100)()
    out = {"keys": {}}
    for name, (a, b) in section_spans(song).items():
        if name not in SECTION_KEYS:
            continue
        key, scale, strength = es.KeyExtractor(profileType="temperley")(audio[int(a * 44100):int(b * 44100)])
        out["keys"][name] = f"{key} {scale} ({strength:.2f})"
        want = SECTION_KEYS[name]
        check((key, scale) == want, f"key {name}: Essentia detects {key} {scale} ({strength:.2f}), expected {' '.join(want)}")

    bpm, *_ = es.RhythmExtractor2013(method="multifeature")(audio)
    out["bpm"] = round(float(bpm), 1)
    check(any(abs(bpm - song["bpm"] * f) < 3 for f in (0.5, 1, 2)),
          f"tempo: Essentia detects {bpm:.1f} BPM, expected {song['bpm']} (or half/double)")

    frame, hop = 4096, 2048
    w, spec = es.Windowing(type="blackmanharris62"), es.Spectrum()
    peaks = es.SpectralPeaks(orderBy="magnitude", magnitudeThreshold=1e-5, minFrequency=40, maxFrequency=5000, maxPeaks=60)
    hpcp = es.HPCP(size=36, referenceFrequency=440, harmonics=8, nonLinear=True, normalized="unitMax")
    frames = np.array([hpcp(*peaks(spec(w(f)))) for f in es.FrameGenerator(audio, frameSize=frame, hopSize=hop)])
    labels, _ = es.ChordsDetection(hopSize=hop, windowSize=1.0)(frames.astype(np.float32))
    names = ["A", "Bb", "B", "C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab"]
    pc = {n: (i + 9) % 12 for i, n in enumerate(names)}
    spb, fps = 60 / song["bpm"], 44100 / hop
    rows, per_section = [], {}
    bar_of = lambda beat: int(beat // 4) + 1  # noqa: E731
    for s, d, fig in song["chords"]:
        a, b = int((s + 0.5) * spb * fps), int((s + d) * spb * fps)
        seg = list(labels[a:b])
        if not seg:
            continue
        lab = max(set(seg), key=seg.count)
        minor = lab.endswith("m")
        root = pc[lab[:-1] if minor else lab]
        triad = {root, (root + (3 if minor else 4)) % 12, (root + 7) % 12}
        ok = triad <= {p.pitchClass for p in harmony.ChordSymbol(fig).pitches}
        rows.append((fig, lab, ok))
        sec = next(n for n, first, cnt in song["sections"] if first <= bar_of(s) < first + cnt)
        per_section.setdefault(sec, []).append(ok)
    out["chord_agreement"] = round(float(np.mean([r[2] for r in rows])), 3)
    out["chord_agreement_by_section"] = {k: round(float(np.mean(v)), 2) for k, v in per_section.items()}
    out["chords"] = rows
    check(out["chord_agreement"] >= 0.6, f"chords: Essentia's detected triad fits the planned chord in "
                                         f"{sum(r[2] for r in rows)}/{len(rows)} segments (floor 60%); by section "
                                         f"{out['chord_agreement_by_section']}")
    results["mix"] = out


# -------------------------------------------------------------------- 4. mood
def mood(song: dict, wav: str) -> None:
    import essentia.standard as es
    audio16 = es.MonoLoader(filename=wav, sampleRate=16000, resampleQuality=4)()
    meta = lambda n: json.loads((MODELS / f"{n}.json").read_text())  # noqa: E731
    emb = es.TensorflowPredictEffnetDiscogs(graphFilename=str(MODELS / "discogs-effnet-bs64-1.pb"),
                                           output="PartitionedCall:1")(audio16)
    mn = es.TensorflowPredictMusiCNN(graphFilename=str(MODELS / "msd-musicnn-1.pb"), output="model/dense/BiasAdd")(audio16)
    eff_hop, mn_hop = 62 * 256 / 16000, 93 * 256 / 16000

    def head(name, e, out="model/Sigmoid", inp="model/Placeholder"):
        return es.TensorflowPredict2D(graphFilename=str(MODELS / f"{name}.pb"), input=inp, output=out)(e)

    moods = head("mtg_jamendo_moodtheme-discogs-effnet-1", emb)
    happy = head("mood_happy-discogs-effnet-1", emb, out="model/Softmax")[:, 0]
    sad = head("mood_sad-discogs-effnet-1", emb, out="model/Softmax")[:, 1]
    genre = head("genre_discogs400-discogs-effnet-1", emb, out="PartitionedCall:0", inp="serving_default_model_Placeholder")
    inst = head("mtg_jamendo_instrument-discogs-effnet-1", emb)
    va = es.TensorflowPredict2D(graphFilename=str(MODELS / "deam-msd-musicnn-2.pb"), output="model/Identity")(mn)
    mood_cls, genre_cls, inst_cls = (meta(n)["classes"] for n in ("mtg_jamendo_moodtheme-discogs-effnet-1",
                                                                  "genre_discogs400-discogs-effnet-1",
                                                                  "mtg_jamendo_instrument-discogs-effnet-1"))
    labels = {"happy": "happy" in meta("mood_happy-discogs-effnet-1")["classes"][0],
              "sad": meta("mood_sad-discogs-effnet-1")["classes"][1] == "sad"}
    assert labels["happy"] and labels["sad"], "unexpected class order in mood_happy/mood_sad"

    def summarise(a, b):
        i, j = int(a / eff_hop), max(int(a / eff_hop) + 1, int((b - 2.048) / eff_hop))
        k, m = int(a / mn_hop), max(int(a / mn_hop) + 1, int((b - 3.0) / mn_hop))
        mv = moods[i:j].mean(0)
        ranked = [mood_cls[x] for x in np.argsort(mv)[::-1]]
        return dict(top5=[(c, round(float(mv[mood_cls.index(c)]), 3)) for c in ranked[:5]],
                    rank={c: ranked.index(c) + 1 for c in ("melancholic", "sad", "hopeful", "epic", "dramatic",
                                                           "film", "emotional", "dark", "action", "powerful")},
                    happy=round(float(happy[i:j].mean()), 3), sad=round(float(sad[i:j].mean()), 3),
                    valence_arousal=[round(float(x), 2) for x in va[k:m].mean(0)])

    total = len(audio16) / 16000
    res = {"song": summarise(0, total)}
    for name, (a, b) in section_spans(song).items():
        res[name] = summarise(a, b)
    g = genre.mean(0)
    res["genre_top10"] = [(genre_cls[x], round(float(g[x]), 3)) for x in np.argsort(g)[::-1][:10]]
    iv = inst.mean(0)
    res["instrument_top8"] = [(inst_cls[x], round(float(iv[x]), 3)) for x in np.argsort(iv)[::-1][:8]]

    for name in ["song"] + [n for n, *_ in song["sections"]]:
        r = res[name]
        print(f"  {name:8s} top5: {', '.join(f'{c} {v:.2f}' for c, v in r['top5'])} | happy {r['happy']:.2f} "
              f"sad {r['sad']:.2f} | valence/arousal {r['valence_arousal']}")
    print("  styles top-10:", ", ".join(f"{k} {v:.2f}" for k, v in res["genre_top10"]))
    print("  instruments:", ", ".join(f"{k} {v:.2f}" for k, v in res["instrument_top8"]))

    s, t, f = res["song"], res["tragedy"], res["fight"]
    check(min(s["rank"]["melancholic"], s["rank"]["sad"]) <= 10,
          f"mood song: melancholic #{s['rank']['melancholic']} / sad #{s['rank']['sad']} of 56 (want one in top 10)")
    check(min(s["rank"][k] for k in ("film", "dramatic", "epic", "emotional")) <= 10,
          "mood song: a cinematic tag (film/dramatic/epic/emotional) in the top 10")
    check(t["sad"] >= 0.7, f"mood tragedy: sad model {t['sad']:.2f} (want ≥ 0.70)")
    check(f["valence_arousal"][1] >= t["valence_arousal"][1] + 0.5,
          f"mood arc: fight arousal {f['valence_arousal'][1]:.2f} vs tragedy {t['valence_arousal'][1]:.2f} (want +0.5)")
    check(min(f["rank"][k] for k in ("epic", "dramatic", "action", "powerful")) < min(
          t["rank"][k] for k in ("epic", "dramatic", "action", "powerful")) or f["rank"]["epic"] <= 10,
          f"mood arc: fight ranks epic #{f['rank']['epic']}/action #{f['rank']['action']} above the tragedy's "
          f"(#{t['rank']['epic']}/#{t['rank']['action']})")
    results["mood"] = res


# -------------------------------------------------------------------- 5. CLAP
def clap(song: dict, wav: str) -> None:
    py = ROOT / ".venv-clap" / "bin" / "python"
    spans = {k: v for k, v in section_spans(song).items() if k != "rise"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(spans, f)
    proc = subprocess.run([str(py), str(ROOT / "clap_check.py"), wav, f.name], capture_output=True, text=True)
    if proc.returncode:
        check(False, f"CLAP failed: {proc.stderr.strip().splitlines()[-1] if proc.stderr else proc.returncode}")
        return
    r = json.loads(proc.stdout.strip().splitlines()[-1])
    results["clap"] = r
    print("  CLAP style:", ", ".join(f"{v:.3f} {k[:48]}" for k, v in sorted(r["style"].items(), key=lambda kv: -kv[1])[:5]))
    print("  CLAP narrative:", {k: max(v, key=v.get) for k, v in r["narrative"].items()})
    check(r["best_is_target"], f"CLAP: best-matching description is a target one: \"{r['best']}\"")
    check(r["mean_target"] > r["max_other"],
          f"CLAP: mean similarity to target descriptions {r['mean_target']:.3f} > best other {r['max_other']:.3f}")
    n = r["narrative"]
    check(n["tragedy"]["tragic"] > n["tragedy"]["battle"] and n["fight"]["battle"] > n["fight"]["tragic"],
          f"CLAP narrative: tragedy hears 'tragic' over 'battle' ({n['tragedy']['tragic']:.3f} vs {n['tragedy']['battle']:.3f}) "
          f"and fight the reverse ({n['fight']['battle']:.3f} vs {n['fight']['tragic']:.3f})")


# ----------------------------------------------------------- 6. mix balance
def balance(song: dict) -> None:
    import pyloudnorm as pyln
    stems_ = {p.stem: p for p in (BUILD / "stems").glob("*.wav")}
    data = {k: sf.read(v, always_2d=True)[0] for k, v in stems_.items()}
    sr = sf.info(next(iter(stems_.values()))).samplerate
    meter = pyln.Meter(sr)
    out = {}
    for label, first, last, leads in LEADS:
        a, b = int(bar_s(song, first) * sr), int(bar_s(song, last + 1) * sr)
        seg = lambda k: np.pad(data[k], ((0, max(0, b - len(data[k]))), (0, 0)))[a:b]  # noqa: E731
        lead = sum(seg(k) for k in leads if k in data)
        rest = sum(seg(k) for k in data if k not in leads)
        diff = meter.integrated_loudness(lead) - meter.integrated_loudness(rest)
        out[label] = round(float(diff), 1)
        check(diff >= -6, f"balance {label}: lead ({'+'.join(leads)}) is {diff:+.1f} LU vs the rest of the band (floor -6)")
    results["balance_lead_minus_rest_lu"] = out


# ------------------------------------------------------------------ 7. master
def master(song: dict, wav: str, name: str) -> None:
    import essentia.standard as es
    import librosa
    import librosa.display
    import matplotlib
    import pyloudnorm as pyln
    from scipy.signal import resample_poly
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y, sr = sf.read(wav, always_2d=True)
    meter = pyln.Meter(sr)
    lufs = meter.integrated_loudness(y)
    tp = 20 * np.log10(np.abs(resample_poly(y, 4, 1, axis=0)).max())
    _, _, _, lra = es.LoudnessEBUR128(sampleRate=sr)(es.AudioLoader(filename=wav)()[0])
    spans = section_spans(song)
    sec = {k: round(float(meter.integrated_loudness(y[int(a * sr):int(b * sr)])), 1) for k, (a, b) in spans.items()}
    trag1 = round(float(meter.integrated_loudness(y[int(bar_s(song, 41) * sr):int(bar_s(song, 49) * sr)])), 1)
    results["master"] = dict(lufs=round(lufs, 2), true_peak_dbtp=round(float(tp), 2), loudness_range_lu=round(float(lra), 1),
                             section_lufs=sec, tragedy_lament_lufs=trag1)
    check(abs(lufs + 14) <= 1, f"loudness {lufs:.1f} LUFS (target -14 ±1)")
    check(tp <= -1.0, f"true peak {tp:.2f} dBTP (ceiling -1.0)")
    check(lra >= 6, f"loudness range {lra:.1f} LU (want ≥ 6 LU of dynamics)")
    check(max(sec, key=sec.get) == "fight" and sec["fight"] - trag1 >= 6 and sec["fight"] - sec["intro"] >= 6,
          f"dynamics arc: section LUFS {sec}, tragedy lament {trag1}: fight loudest and ≥ 6 LU above intro and lament")

    mono = y.mean(axis=1)
    fig, ax = plt.subplots(2, 1, figsize=(16, 7), gridspec_kw=dict(height_ratios=[3, 1]), sharex=True)
    S = librosa.amplitude_to_db(np.abs(librosa.stft(mono, n_fft=4096, hop_length=1024)), ref=np.max)
    librosa.display.specshow(S, sr=sr, hop_length=1024, x_axis="time", y_axis="log", ax=ax[0], cmap="magma", vmin=-80)
    ax[0].set_title("Canon for a Dying World — spectrogram")
    rms = librosa.feature.rms(y=mono, frame_length=sr, hop_length=sr // 4)[0]
    ax[1].plot(np.arange(len(rms)) / 4, 20 * np.log10(rms + 1e-9))
    ax[1].set_ylabel("RMS dB")
    for label, (a, _) in spans.items():
        for x in ax:
            x.axvline(a, color="cyan", lw=0.8)
        ax[0].text(a + 0.5, 12000, label, color="cyan")
    fig.tight_layout()
    png = BUILD / "audio" / f"{name}_spectrogram.png"
    fig.savefig(png, dpi=80)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-i", wav,
                    "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-vf", "scale=1280:-2",
                    "-c:a", "aac", "-b:a", "256k", "-shortest", str(BUILD / "audio" / f"{name}.mp4")], check=True)


def main(name: str = "canon_for_a_dying_world", *only: str) -> None:
    wav = str(BUILD / "audio" / f"{name}.wav")
    song = load_song()
    steps = dict(symbolic=lambda: symbolic(song), stems=lambda: stems(song), mix=lambda: mix_analysis(song, wav),
                 mood=lambda: mood(song, wav), clap=lambda: clap(song, wav), balance=lambda: balance(song),
                 master=lambda: master(song, wav, name))
    for k, fn in steps.items():
        if not only or k in only:
            print(f"== {k}", flush=True)
            fn()
    results["failures"] = failures
    if not only:
        (BUILD / "report.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\n{len(failures)} failing check(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main(*sys.argv[1:])
