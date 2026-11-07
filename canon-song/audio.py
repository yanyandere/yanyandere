"""MIDI writing, sfizz rendering and basic-pitch transcription helpers."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import mido
import numpy as np

PPQ = 480


@dataclass
class Note:
    start: float  # beats
    dur: float    # beats
    pitch: int
    vel: int
    tag: str = ""  # "app": appoggiatura (must resolve by step); "orn": ornament (gliss)


def write_midi(notes: list[Note], path: Path, bpm: float, cc: list[tuple[float, int, int]] = (),
               tail_beats: float = 8.0, offsets_s: list[float] | None = None) -> None:
    """One-track MIDI file. offsets_s: optional per-note timing offset in seconds (humanisation)."""
    spb = 60.0 / bpm
    ev = []
    for i, n in enumerate(notes):
        off = (offsets_s[i] / spb) if offsets_s else 0.0
        on = max(0.0, n.start + off)
        ev.append((on, 1, mido.Message("note_on", note=n.pitch, velocity=int(np.clip(n.vel, 1, 127)))))
        ev.append((on + max(0.05, n.dur), 0, mido.Message("note_off", note=n.pitch, velocity=0)))
    for beat, num, val in cc:
        ev.append((beat, 0, mido.Message("control_change", control=num, value=int(np.clip(val, 0, 127)))))
    ev.sort(key=lambda e: (e[0], e[1]))
    end = (max(e[0] for e in ev) if ev else 0.0) + tail_beats

    mf = mido.MidiFile(ticks_per_beat=PPQ)
    tr = mido.MidiTrack()
    mf.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)))
    last = 0
    for beat, _, msg in ev:
        t = int(round(beat * PPQ))
        tr.append(msg.copy(time=t - last))
        last = t
    tr.append(mido.MetaMessage("end_of_track", time=int(round(end * PPQ)) - last))
    path.parent.mkdir(parents=True, exist_ok=True)
    mf.save(path)


def render(sfz: Path, midi: Path, wav: Path, sr: int = 48000) -> None:
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["sfizz_render", "--sfz", str(sfz), "--midi", str(midi), "--wav", str(wav),
                    "-s", str(sr), "-q", "3", "-p", "256", "--use-eot"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def transcribe(wav: Path) -> list[tuple[float, float, int]]:
    """basic-pitch note events as (onset_s, offset_s, midi_pitch)."""
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict
    _, _, events = predict(str(wav), ICASSP_2022_MODEL_PATH)
    return sorted((float(s), float(e), int(p)) for s, e, p, *_ in events)


def match_notes(ref: list[tuple[float, float, int]], est: list[tuple[float, float, int]],
                onset_tol: float = 0.08) -> dict:
    """mir_eval onset+pitch F-measure (offsets ignored), plus octave-error diagnostics."""
    import mir_eval
    if not est:
        return dict(precision=0.0, recall=0.0, f1=0.0, octave_errors=0, n_ref=len(ref), n_est=0)
    ri = np.array([[s, max(e, s + 0.01)] for s, e, _ in ref])
    ei = np.array([[s, max(e, s + 0.01)] for s, e, _ in est])
    rp = mir_eval.util.midi_to_hz(np.array([p for *_, p in ref], float))
    ep = mir_eval.util.midi_to_hz(np.array([p for *_, p in est], float))
    p, r, f, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ri, rp, ei, ep, onset_tolerance=onset_tol, offset_ratio=None)
    octave = 0
    for s, _, pitch in ref:
        near = [q for (t, _, q) in est if abs(t - s) <= onset_tol]
        if near and pitch not in near and any(abs(q - pitch) in (12, 24) for q in near):
            octave += 1
    return dict(precision=round(p, 3), recall=round(r, 3), f1=round(f, 3), octave_errors=octave,
                n_ref=len(ref), n_est=len(est))
