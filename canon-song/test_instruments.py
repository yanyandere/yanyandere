"""Milestone 1: prove every instrument sounds, at the right pitch, across its range.

Renders a D-major scale through each SFZ with sfizz, then transcribes it back
with Spotify's basic-pitch and scores it with mir_eval.
"""
import json

import numpy as np
import soundfile as sf

from audio import Note, match_notes, render, transcribe, write_midi
from instruments import BUILD, INSTRUMENTS

BPM = 84
D_MAJOR = {2, 4, 6, 7, 9, 11, 1}  # pitch classes


def main() -> None:
    out = BUILD / "instrument_test"
    report = {}
    for name, cfg in INSTRUMENTS.items():
        lo, hi = cfg["range"]
        pitches = [p for p in range(lo, hi + 1) if p % 12 in D_MAJOR]
        notes = [Note(start=i * 1.0, dur=0.8, pitch=p, vel=80) for i, p in enumerate(pitches)]
        mid, wav = out / f"{name}.mid", out / f"{name}.wav"
        t = cfg.get("transpose", 0)
        write_midi([Note(n.start, n.dur, n.pitch + t, n.vel) for n in notes], mid, BPM, tail_beats=4)
        render(cfg["sfz"], mid, wav)

        y, sr = sf.read(wav)
        mono = y.mean(axis=1) if y.ndim > 1 else y
        peak_db = 20 * np.log10(np.abs(mono).max() + 1e-12)
        spb = 60 / BPM
        ref = [(n.start * spb, (n.start + n.dur) * spb, n.pitch) for n in notes]
        est = transcribe(wav)
        m = match_notes(ref, est, onset_tol=0.1)
        report[name] = dict(range=[lo, hi], n_notes=len(notes), peak_dbfs=round(float(peak_db), 1), **m)
        print(f"{name:10s} peak {peak_db:6.1f} dBFS  F1 {m['f1']:.2f}  "
              f"(P {m['precision']:.2f} R {m['recall']:.2f})  octave_err {m['octave_errors']}")
    (out / "report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
