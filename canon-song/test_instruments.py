"""Prove every pitched instrument sounds at the right pitch across its range.

Renders a D-major scale through each SFZ with sfizz, transcribes it back with
Spotify's basic-pitch and scores it with mir_eval. Also reports the dominant
pitch offset (octave mapping errors) and median onset lag (slow attacks),
which feed `transpose` and `latency` in instruments.py.
"""
import json
import sys
from collections import Counter

import numpy as np
import soundfile as sf

from audio import Note, match_notes, render, transcribe, write_midi
from instruments import BUILD, INSTRUMENTS

BPM = 84
D_MAJOR = {2, 4, 6, 7, 9, 11, 1}  # pitch classes
LEAD = 2.0  # beats before the first note


def main(only: list[str]) -> None:
    out = BUILD / "instrument_test"
    path = out / "report.json"
    report = json.loads(path.read_text()) if path.exists() else {}
    spb = 60 / BPM
    for name, cfg in INSTRUMENTS.items():
        if cfg.get("drums") or (only and name not in only):
            continue
        lo, hi = cfg["range"]
        pitches = [p for p in range(lo, hi + 1) if p % 12 in D_MAJOR]
        notes = [Note(LEAD + i * 1.0, 0.8, p, 80) for i, p in enumerate(pitches)]
        mid, wav = out / f"{name}.mid", out / f"{name}.wav"
        t = cfg.get("transpose", 0)
        lat = cfg.get("latency", 0.0)
        write_midi([Note(n.start, n.dur, n.pitch + t, n.vel) for n in notes], mid, BPM, tail_beats=4,
                   offsets_s=[-lat] * len(notes))
        render(cfg["sfz"], mid, wav)

        y, _ = sf.read(wav)
        mono = y.mean(axis=1) if y.ndim > 1 else y
        peak_db = 20 * np.log10(np.abs(mono).max() + 1e-12)
        ref = [(n.start * spb, (n.start + n.dur) * spb, n.pitch) for n in notes]
        est = transcribe(wav)
        m = match_notes(ref, est, onset_tol=0.1)
        diffs, lags = Counter(), []
        for s, _, p in ref:
            near = [(q, t0 - s) for t0, _, q in est if -0.1 <= t0 - s <= 0.35]
            diffs.update(q - p for q, _ in near)
            lags += [d for q, d in near if q == p]
        offset = diffs.most_common(1)[0][0] if diffs else None
        lag = float(np.median(lags)) if lags else None
        report[name] = dict(range=[lo, hi], n_notes=len(notes), peak_dbfs=round(float(peak_db), 1),
                            pitch_offset=offset, median_onset_lag_s=None if lag is None else round(lag, 3), **m)
        print(f"{name:14s} peak {peak_db:6.1f} dBFS  F1 {m['f1']:.2f} (P {m['precision']:.2f} R {m['recall']:.2f})  "
              f"offset {offset:+d}  lag {1000 * (lag or 0):4.0f} ms  octave_err {m['octave_errors']}", flush=True)
    path.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
