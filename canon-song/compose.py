"""The song as data: Pachelbel's ground bass under a 70s jazz reharmonisation.

`python compose.py` writes per-track MIDI (humanised, for rendering), a
combined MIDI, and a MusicXML score into build/.
Currently implements the sketch: Intro (8) + Theme (16) + 2-bar coda.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict

from music21 import pitch as m21pitch

from audio import Note, write_midi
from instruments import BUILD, INSTRUMENTS

BPM = 84
BEATS = 4
LEAD_IN = 2.0  # beats of silence before bar 1; sfizz drops notes at tick 0. render.py trims it.


def P(name: str) -> int:
    return m21pitch.Pitch(name).midi


# Pachelbel's ground, one chord per bar.
GROUND = ["D2", "C#2", "B1", "A1", "G1", "F#1", "G1", "A1"]

# (music21 figure, rhodes voicing). Figures fully spell each voicing so the
# harmony check can be strict.
CHORD = {
    "DM9":      ["F#3", "A3", "C#4", "E4"],
    "A/C#":     ["E3", "A3", "C#4", "E4"],
    "Bm9":      ["A3", "C#4", "D4", "F#4"],
    "F#m7/A":   ["A3", "C#4", "E4", "F#4"],
    "GM9":      ["A3", "B3", "D4", "F#4"],
    "Dadd9/F#": ["A3", "D4", "E4", "F#4"],
    "GM9b":     ["B3", "D4", "F#4", "A4"],   # GM9, higher voicing
    "A9sus4":   ["G3", "B3", "D4", "E4"],
    "A9":       ["G3", "B3", "C#4", "E4"],
    "F#7b13":   ["E3", "A#3", "D4"],
    "Em9/G":    ["G3", "B3", "D4", "F#4"],
    "A7b9":     ["G3", "B-3", "C#4", "E4"],
}
FIGURE = {"GM9b": "GM9", "A9sus4": "A7sus4 add 9"}

# Each bar: list of (beat_in_bar, chord key).
CYCLE_A = [[(0, "DM9")], [(0, "A/C#")], [(0, "Bm9")], [(0, "F#m7/A")],
           [(0, "GM9")], [(0, "Dadd9/F#")], [(0, "GM9b")], [(0, "A9sus4"), (2, "A9")]]
CYCLE_B = CYCLE_A[:4] + [[(0, "GM9")], [(0, "F#7b13")], [(0, "Em9/G")], [(0, "A7b9")]]
CYCLE_INTRO = CYCLE_A[:7] + [[(0, "A9")]]  # no sus4 under the canon line's C#

# Lead melody, one string per bar: "pitch:beats", r = rest.
MELODY_A = ["F#4:1 D5:1.5 C#5:.5 A4:1", "E5:1.5 D5:.5 C#5:1.5 B4:.5", "C#5:2 B4:1 A4:.5 B4:.5",
            "C#5:1.5 A4:.5 E4:2", "D4:1 B4:1.5 A4:.5 F#4:1", "A4:1.5 G4:.5 F#4:1 E4:1",
            "D4:1 G4:1 B4:1 D5:1", "E5:1.5 D5:.5 C#5:2"]
MELODY_B = ["A4:1 F#5:1.5 E5:.5 D5:1", "E5:1.5 C#5:.5 A4:2", "B4:.5 C#5:.5 D5:1 F#5:2",
            "E5:2 C#5:1 A4:1", "B4:.5 D5:.5 F#5:2 E5:1", "D5:1.5 A#4:.5 C#5:1 E5:1",
            "B4:1 D5:1 F#5:1.5 E5:.5", "E5:1 C#5:1 B-4:1 A4:1"]
MELODY_CODA = ["D5:2 r:.5 A4:.5 D5:1", "E5:4"]  # ends on the 9th: home, but not at peace

# Pachelbel's first-violin descent (public domain), one note per bar, as the
# music-box top line in the intro.
CANON_TOP = ["F#6", "E6", "D6", "C#6", "B5", "A5", "B5", "C#6"]

ARCO_VEL_TRIM = {45: -16}  # Meatbass arco A2 sample is ~12 dB hotter than its neighbours
HORN_TOP = 76  # above E5 the trumpet carries the flugel line alone

SECTIONS = [("intro", 1, 8), ("theme", 9, 16), ("coda", 25, 2)]


def bar_start(bar: int) -> float:
    return (bar - 1) * BEATS


def parse_line(line: str, start: float, vel: int) -> list[Note]:
    out, t = [], start
    for tok in line.split():
        name, dur = tok.split(":")
        d = float(dur)
        if name != "r":
            out.append(Note(t, d, P(name), vel))
        t += d
    return out


def build() -> dict:
    tracks: dict[str, list[Note]] = {k: [] for k in INSTRUMENTS}
    chords: list[tuple[float, float, str]] = []

    def add_chords(bar: int, cycle_bar: list[tuple[int, str]]):
        for i, (b, key) in enumerate(cycle_bar):
            end = cycle_bar[i + 1][0] if i + 1 < len(cycle_bar) else BEATS
            chords.append((bar_start(bar) + b, end - b, key))

    # ---- Intro (bars 1-8): music box, Rhodes, bowed ground bass -------------
    for i in range(8):
        bar, s = 1 + i, bar_start(1 + i)
        add_chords(bar, CYCLE_INTRO[i])
        key = CYCLE_INTRO[i][0][1]
        for j, v in enumerate(CHORD[key]):
            tracks["rhodes"].append(Note(s + j * 0.02, 3.9, P(v), 46 + 2 * j))
        # 3.8 beats: overlapping notes would trigger Meatbass's legato regions.
        p = P(GROUND[i]) + 12
        tracks["bass_arco"].append(Note(s, 3.8, p, 44 + 3 * i + ARCO_VEL_TRIM.get(p, 0)))
        top = P(CANON_TOP[i])
        pcs = sorted({P(v) % 12 for v in CHORD[key]} - {top % 12})
        above = sorted(top + ((pc - top) % 12) for pc in pcs)[:2]
        pattern = [top, above[0], above[1], above[0]] * 2
        for k, p in enumerate(pattern):
            tracks["glock"].append(Note(s + k * 0.5, 0.5, p, 74 if k % 4 == 0 else 52))

    # ---- Theme (bars 9-24): two passes over the ground --------------------
    for c, (cycle, melody) in enumerate([(CYCLE_A, MELODY_A), (CYCLE_B, MELODY_B)]):
        for i in range(8):
            bar = 9 + 8 * c + i
            s = bar_start(bar)
            add_chords(bar, cycle[i])
            # Rhodes comping: downbeat + "and of 2" push; follow mid-bar changes.
            for b, key in cycle[i]:
                hits = [(0, 1.45, 64), (1.5, 2.4, 56)] if len(cycle[i]) == 1 else [(b, 1.9, 60)]
                for t, d, v in hits:
                    for j, n in enumerate(CHORD[key]):
                        tracks["rhodes"].append(Note(s + t + j * 0.015, d, P(n), v + 2 * c + j))
            # Pizz bass: root, octave, fifth, chromatic approach to next root.
            root = P(GROUND[i])
            nxt = P(GROUND[(i + 1) % 8])
            approach = nxt - 1 if nxt - 1 != root else nxt + 1
            fifth = root + 7
            line = [(0, 1.4, root, 92), (1.5, 0.45, root + 12, 70), (2, 0.9, fifth, 80), (3, 0.9, approach, 76)]
            if c == 1 and i % 2 == 1:
                line[1] = (1.5, 0.45, root + 10 if i == 7 else root + 12, 74)
            for t, d, p, v in line:
                tracks["bass_pizz"].append(Note(s + t, d, p, v + 4 * c))
            # Melody: flugel layer (trumpet + horn); flute an octave up on pass 2.
            arc = [0, 4, 8, 6, 2, 4, 6, 10][i]
            for n in parse_line(melody[i], s, 70 + arc + 8 * c):
                tracks["trumpet"].append(n)
                if n.pitch <= HORN_TOP:
                    tracks["horn"].append(Note(n.start, n.dur, n.pitch, n.vel - 12))
                if c == 1:
                    tracks["flute"].append(Note(n.start, n.dur, n.pitch + 12, n.vel - 6))

    # ---- Coda (bars 25-26): land on Dmaj9, music box returns ---------------
    s = bar_start(25)
    chords.append((s, 8.0, "DM9"))
    for j, v in enumerate(CHORD["DM9"]):
        tracks["rhodes"].append(Note(s + j * 0.04, 7.8, P(v), 52))
    tracks["bass_pizz"].append(Note(s, 3.0, P("D2"), 88))
    tracks["bass_arco"].append(Note(s, 7.8, P("D2"), 50))
    for k, line in enumerate(MELODY_CODA):
        for n in parse_line(line, s + 4 * k, 72 - 6 * k):
            tracks["trumpet"].append(n)
            if n.pitch <= HORN_TOP:
                tracks["horn"].append(Note(n.start, n.dur, n.pitch, n.vel - 12))
            tracks["flute"].append(Note(n.start, n.dur, n.pitch + 12, n.vel - 14))
    for k, p in enumerate(["D7", "A6", "F#6", "E6"]):
        tracks["glock"].append(Note(s + 4 + k * 0.75, 0.75, P(p), 60 - 4 * k))

    for v in tracks.values():
        v.sort(key=lambda n: (n.start, n.pitch))
    return dict(bpm=BPM, lead_in=LEAD_IN, tracks=tracks, chords=chords,
                sections=SECTIONS, figures={k: FIGURE.get(k, k) for k in CHORD})


# Per-track humanisation: (timing sd seconds, mean lag seconds, velocity sd).
FEEL = {"rhodes": (0.006, 0.0, 3), "bass_arco": (0.004, 0.0, 2), "bass_pizz": (0.005, 0.0, 4),
        "trumpet": (0.010, 0.012, 3), "horn": (0.010, 0.016, 3), "flute": (0.010, 0.010, 3),
        "glock": (0.004, 0.0, 4)}


def write(song: dict) -> None:
    rng = random.Random(1979)
    mid_dir = BUILD / "midi"
    for name, notes in song["tracks"].items():
        if not notes:
            continue
        sd, lag, vsd = FEEL[name]
        t = INSTRUMENTS[name].get("transpose", 0)
        hum = [Note(n.start + LEAD_IN, n.dur, n.pitch + t, int(n.vel + rng.gauss(0, vsd))) for n in notes]
        lat = INSTRUMENTS[name].get("latency", 0.0)
        offs = [lag - lat + rng.gauss(0, sd) for _ in notes]
        write_midi(hum, mid_dir / f"{name}.mid", song["bpm"], offsets_s=offs, tail_beats=12)
    # Un-humanised note data for verification and score export.
    (BUILD / "song.json").write_text(json.dumps({
        **{k: v for k, v in song.items() if k != "tracks"},
        "tracks": {k: [asdict(n) for n in v] for k, v in song["tracks"].items()},
    }))


def export_score(song: dict) -> None:
    """Combined multi-track MIDI + MusicXML score with chord symbols (music21)."""
    from music21 import chord, harmony, instrument, meter, note, stream, tempo
    parts = {"trumpet": ("Flugelhorn (tpt+hn)", instrument.Trumpet()),
             "flute": ("Flute", instrument.Flute()),
             "glock": ("Glockenspiel", instrument.Glockenspiel()),
             "rhodes": ("Rhodes", instrument.ElectricPiano()),
             "bass_pizz": ("Double Bass pizz.", instrument.Contrabass()),
             "bass_arco": ("Double Bass arco", instrument.Contrabass())}
    score = stream.Score()
    for key, (label, inst) in parts.items():
        part = stream.Part(id=key)
        inst.partName = label
        part.insert(0, inst)
        part.insert(0, meter.TimeSignature("4/4"))
        if key == "trumpet":
            part.insert(0, tempo.MetronomeMark(number=BPM))
            for s, _, k in song["chords"]:
                part.insert(s, harmony.ChordSymbol(song["figures"][k]))
        groups: dict[tuple[float, float], list[int]] = {}
        for n in song["tracks"][key]:
            groups.setdefault((round(n.start * 4) / 4, round(n.dur * 4) / 4), []).append(n.pitch)
        for (s, d), ps in sorted(groups.items()):
            el = note.Note(ps[0]) if len(ps) == 1 else chord.Chord(ps)
            el.quarterLength = max(0.25, d)
            part.insert(s, el)
        score.insert(0, part)
    score.write("musicxml", fp=BUILD / "score.musicxml")
    score.write("midi", fp=BUILD / "canon_sketch_all_tracks.mid")


if __name__ == "__main__":
    BUILD.mkdir(exist_ok=True)
    song = build()
    write(song)
    export_score(song)
    total = max(n.start + n.dur for v in song["tracks"].values() for n in v)
    print(f"{total / BEATS:.1f} bars, {total * 60 / BPM:.1f} s; notes:",
          {k: len(v) for k, v in song["tracks"].items()})
