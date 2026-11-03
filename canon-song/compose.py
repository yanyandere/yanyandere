"""The song as data: Pachelbel's ground bass under a 70s jazz reharmonisation.

`python compose.py` writes per-track MIDI (humanised, for rendering), a
quantised multi-track MIDI and MusicXML score, and build/song.json for
verify.py.

Form (84 BPM, 4/4, 94 bars):
  intro 1-8 · theme 9-24 · canon 25-40 · tragedy (D minor) 41-56 ·
  rise 57-60 · fight (E major) 61-84 · outro 85-94
"""
from __future__ import annotations

import itertools
import json
import random
from dataclasses import asdict
from functools import lru_cache
from itertools import combinations

import mido
from music21 import harmony
from music21 import pitch as m21pitch

from audio import PPQ, Note, write_midi
from instruments import BUILD, INSTRUMENTS

TITLE = "canon_for_a_dying_world"
BPM = 84
BEATS = 4
LEAD_IN = 2.0  # beats of silence before bar 1; sfizz drops notes at tick 0. render.py trims it.

SECTIONS = [("intro", 1, 8), ("theme", 9, 16), ("canon", 25, 16), ("tragedy", 41, 16),
            ("rise", 57, 4), ("fight", 61, 24), ("outro", 85, 10)]
TOTAL_BARS = 94


def P(name: str) -> int:
    return m21pitch.Pitch(name).midi


def bar_start(bar: int) -> float:
    return (bar - 1) * BEATS


# ------------------------------------------------------------------ harmony
# One entry per bar: a music21 figure, or [(beat, figure), ...] for mid-bar
# changes. Every bar's bass note is Pachelbel's ground (D-C#-B-A-G-F#-G-A),
# in D major, D minor, then E major.
D_A = ["DM9", "A add 9/C#", "Bm9", "F#m7 add 11/A", "GM9", "Dadd9/F#", "GM9", "A9"]
D_THEME_A = D_A[:7] + [[(0, "A7sus4 add 9"), (2, "A9")]]
D_THEME_B = D_A[:5] + ["F#7b13", "Em9/G", "A7b9"]
D_CANON = D_A + D_A[:7] + ["A7b9"]
TRAG = ["Dm add 9", "A7/C#", "B-M7", "FM7/A", "Gm7", "Dm/F", "Gm6", "A7b9",
        "Dm9", "A7b9/C#", "B-M7 add #11", "FM7/A", "Gm9", "Dm7/F", "Gm6", "A7b9"]
RISE = ["B7sus4 add 9", "B7sus4 add 9", "B7b9", "B7b9"]
E_A = ["EM9", "B add 9/D#", "C#m9", "G#m7 add 11/B", "AM9", "Eadd9/G#", "AM9",
       [(0, "B7sus4 add 9"), (2, "B9")]]
E_B = E_A[:5] + ["G#7b13", "F#m9/A", "B7b9"]
# The fight ends on the minor iv (Am6), which pivots to A9sus4 = V of D.
E_C = E_A[:6] + ["Am6", "A7sus4 add 9"]
# Outro: the minor iv (Gm6) is the scar; the final chord rests on the 9th.
OUTRO = D_A[:6] + ["Gm6", [(0, "A7sus4 add 9"), (2, "A9")], "Dadd9", "Dadd9"]
PROGRESSION = D_A + D_THEME_A + D_THEME_B + D_CANON + TRAG + RISE + E_A + E_B + E_C + OUTRO
assert len(PROGRESSION) == TOTAL_BARS


def bar_chords(bar: int) -> list[tuple[float, str]]:
    e = PROGRESSION[bar - 1]
    return [(0, e)] if isinstance(e, str) else e


def chord_at(beat: float) -> str:
    bar = int(beat // BEATS) + 1
    fig = None
    for t, f in bar_chords(bar):
        if beat - bar_start(bar) + 1e-6 >= t:
            fig = f
    return fig


@lru_cache(None)
def info(fig: str):
    """(pitch classes, root, guide tones {3rd, 7th}, bass) of a figure."""
    cs = harmony.ChordSymbol(fig)
    pcs = frozenset(p.pitchClass for p in cs.pitches)
    guide = frozenset(x.pitchClass for x in (cs.third, cs.seventh) if x is not None)
    return pcs, cs.root().pitchClass, guide, cs.bass().pitchClass


def ground(fig: str, lo: int = 29) -> int:
    """The chord's bass note in the low register F1..E2."""
    pc = info(fig)[3]
    return lo + (pc - lo) % 12


def near(fig: str, target: int) -> int:
    pcs = info(fig)[0]
    return min((p for p in range(target - 6, target + 7) if p % 12 in pcs), key=lambda p: (abs(p - target), p))


def voicing(fig: str, prev: list[int] | None, lo: int, hi: int, n: int, rootless: bool = False) -> list[int]:
    """n chord tones in [lo, hi] with smooth voice leading from prev.

    Prefers guide tones (3rd/7th), distinct pitch classes, and avoids
    semitone clusters and minor 9ths between voices.
    """
    pcs, root, guide, _ = info(fig)
    cands = [p for p in range(lo, hi + 1) if p % 12 in pcs and not (rootless and p % 12 == root)]
    best, best_cost = None, float("inf")
    for combo in combinations(cands, n):
        if any(b - a < 2 for a, b in zip(combo, combo[1:])):
            continue
        pcset = {p % 12 for p in combo}
        cost = 3.0 * (n - len(pcset))
        cost += 6.0 * max(0, min(len(guide), n) - len(guide & pcset))
        cost += 4.0 * sum(1 for a, b in combinations(combo, 2) if (b - a) % 12 == 1)
        if prev and len(prev) == n:
            cost += sum(abs(a - b) for a, b in zip(combo, prev))
        else:
            cost += abs(sum(combo) / n - (lo + hi) / 2)
        if cost < best_cost:
            best, best_cost = combo, cost
    if best is None:
        raise ValueError(f"no {n}-note voicing of {fig} in {lo}-{hi}")
    return list(best)


# ------------------------------------------------------------------ melodies
# One string per bar, "pitch:beats", r = rest, a trailing "!" marks an
# appoggiatura (a strong-beat dissonance that must resolve by step).
MELODY_A = ["F#4:1 D5:1.5 C#5:.5 A4:1", "E5:1.5 D5:.5 C#5:1.5 B4:.5", "C#5:2 B4:1 A4:.5 B4:.5",
            "C#5:1.5 A4:.5 E4:2", "D4:1 B4:1.5 A4:.5 F#4:1", "A4:1.5 G4:.5 F#4:1 E4:1",
            "D4:1 G4:1 B4:1 D5:1", "E5:1.5 D5:.5 C#5:2"]
MELODY_B = ["A4:1 F#5:1.5 E5:.5 D5:1", "E5:1.5 C#5:.5 A4:2", "B4:.5 C#5:.5 D5:1 F#5:2",
            "E5:2 C#5:1 A4:1", "B4:.5 D5:.5 F#5:2 E5:1", "D5:1.5 A#4:.5 C#5:1 E5:1",
            "B4:1 D5:1 F#5:1.5 E5:.5", "E5:1 C#5:1 B-4:1 A4:1"]
# Cello countermelody to MELODY_B: climbs while the ground falls.
CELLO_B = ["F#3:2 A3:2", "A3:2 C#4:2", "D4:2 F#4:2", "E4:2 C#4:2", "B3:2 D4:2", "A#3:2 C#4:2",
           "G3:1 B3:1 D4:1 F#4:1", "G4:2 B-3:1 C#4:1"]
# Canon subject. Written so that bar j fits the chords at j, j+2 and j+4,
# so three voices entering two bars apart stay consonant on strong beats.
SUBJECT = ["A4:1.5 B4:.5 D5:1 F#5:1", "E5:2 A5:1 G5:.5 F#5:.5", "F#5:1.5 E5:.5 D5:1 B4:1",
           "A4:1.5 B4:.5 E5:2", "D5:.5 E5:.5 F#5:1 A5:1.5 G5:.5", "E5:1 D5:.5 C#5:.5 A4:2",
           "F#5:1.5 E5:.5 D5:2", "C#5:1 B4:1 A4:1.5 B4:.5", "D5:.5 C#5:.5 D5:.5 E5:.5 F#5:1 A5:1",
           "A5:1.5 G5:.5 E5:1 C#5:1", "D5:1 F#5:.5 E5:.5 D5:1 B4:.5 C#5:.5", "E5:1 C#5:.5 B4:.5 A4:2",
           "B4:.5 C#5:.5 D5:1 F#5:1.5 E5:.5", "A5:1.5 F#5:.5 E5:2", "D5:1 B4:1 A4:1 B4:.5 C#5:.5",
           "E5:1 G5:1 B-5:2"]
# Tragedy: a lament for oboe, then the "big tune" in violins and cellos.
TRAG_1 = ["A4:1.5 D5:.5 F5:2", "G5:1 F5:1 E5:2", "D5:1 F5:1.5 E5:.5 D5:1", "C5:3 r:.5 A4:.5",
          "B-4:1.5 A4:.5 B-4:1 D5:1", "F5:1.5 E5:.5 D5:1 A4:1", "E5:1 D5:1 B-4:1.5 A4:.5", "A4:1 B-4:1 A4:2"]
TRAG_2 = ["D5:1 A5:1.5 G5:.5 F5:1", "E5:1.5 F5:.5 E5:1 C#5:1", "D5:.5 E5:.5 F5:1 A5:2", "G5:1.5! F5:.5 E5:2",
          "B-5:1 A5:1 G5:1 F5:1", "A5:1.5 G5:.5 F5:1 E5:1", "D5:1 E5:1 G5:1 B-5:1", "A5:2 C#6:2"]
OBOE_COUNTER = ["A4:2 C5:2", "B-4:2 A4:2", "A4:2 F4:2", "E4:2 F4:1 G4:1", "B-4:2 A4:2", "A4:2 C5:2",
                "B-4:2 D5:2", "C#5:2 B-4:2"]
RISE_MOTIF = ["B3:2 E4:2", "F#4:2 A4:2", "B4:2 C5:2", "D#5:4"]
OUTRO_TPT = ["D4:1 B4:1.5 A4:.5 F#4:1", "A4:1.5 G4:.5 F#4:1 E4:1", "D4:1 G4:1 B-4:1 D5:1", "E5:1.5 D5:.5 C#5:2"]
CODA = ["D5:2 r:.5 A4:.5 D5:1", "E5:4"]  # ends on the 9th: home, but not at peace

# Pachelbel's first-violin descent (public domain), one note per bar: the music box.
CANON_TOP = ["F#6", "E6", "D6", "C#6", "B5", "A5", "B5", "C#6"]
OUTRO_TOP = ["F#6", "E6", "D6", "C#6", "B5", "A5", "B-5", "B5"]  # the music box bends to minor too

# Meatbass arco sustain level (dB RMS) per key at velocity 65, measured with
# sfizz_render. Adjacent keys share samples, so levels jump by up to 20 dB;
# the same pattern holds at every velocity. trim_arco() evens it out with CC11.
ARCO_LEVEL_DB = dict(zip(range(29, 53), [
    -35.0, -38.1, -34.9, -30.7, -32.2, -30.5, -26.0, -26.9, -25.9, -35.2, -35.6, -35.4,
    -39.0, -40.4, -39.3, -28.9, -29.2, -29.0, -40.4, -40.5, -40.7, -45.3, -45.7, -45.4]))
ARCO_TARGET_DB = min(ARCO_LEVEL_DB.values())
HORN_TOP = 76  # above E5 the trumpet carries the flugel line alone
BELL = P("D5")

BR = dict(kick=36, snare=38, dig=39, stir=60, pedal=44, crash=49, ride=51)  # Swirly (brushes)
ST = dict(kick=36, snare=38, ghost=39, hat=42, crash=49, ride=51, bell=53, tom_hi=48, tom_lo=41,
          roll=96, flam=95)  # Virtuosity (sticks)
PC = dict(tamb=54)


# --------------------------------------------------------------------- song
class Song:
    def __init__(self):
        self.tracks: dict[str, list[Note]] = {k: [] for k in INSTRUMENTS}
        self.cc: dict[str, list[tuple[float, int, int]]] = {k: [] for k in INSTRUMENTS}
        self.prev: dict[str, list[int]] = {}
        self.canons: list[dict] = []

    def note(self, track, start, dur, pitch, vel, tag=""):
        n = Note(round(start, 4), round(dur, 4), int(pitch), int(max(1, min(127, vel))), tag)
        self.tracks[track].append(n)
        return n

    def line(self, track, bars: list[str], first_bar: int, vel, transpose=0, arc=None, vel_step=0):
        out = []
        for i, text in enumerate(bars):
            t = bar_start(first_bar + i)
            v = vel + (arc[i % len(arc)] if arc else 0) + vel_step * i
            for tok in text.split():
                name, dur = tok.split(":")
                tag = "app" if dur.endswith("!") else ""
                d = float(dur.rstrip("!"))
                if name != "r":
                    out.append(self.note(track, t, d, P(name) + transpose, v, tag))
                t += d
        return out

    def chord(self, track, start, dur, pitches, vel, roll=0.0):
        for j, p in enumerate(sorted(pitches)):
            self.note(track, start + j * roll, dur - j * roll, p, vel + j)

    def pad(self, track, bar, n, lo, hi, vel, rootless=False, gap=0.05):
        """Voice-led sustained chord for every chord in the bar."""
        chords = bar_chords(bar)
        for i, (b, fig) in enumerate(chords):
            end = chords[i + 1][0] if i + 1 < len(chords) else BEATS
            v = voicing(fig, self.prev.get(track), lo, hi, n, rootless)
            self.prev[track] = v
            for p in v:
                self.note(track, bar_start(bar) + b, end - b - gap, p, vel)

    def expr(self, track, *points, step=0.25):
        """CC11 expression, piecewise linear through (beat, value) points."""
        for (a, v0), (b, v1) in zip(points, points[1:]):
            n = max(1, int(round((b - a) / step)))
            for i in range(n + (1 if (b, v1) == points[-1] else 0)):
                self.cc[track].append((a + (b - a) * i / n, 11, round(v0 + (v1 - v0) * i / n)))

    def arch(self, track, first_bar, bars, lo, hi):
        a, b = bar_start(first_bar), bar_start(first_bar + bars)
        self.expr(track, (a, lo), ((a + b) / 2, hi), (b - 0.25, lo))


def B(bar, beat=0.0):
    return bar_start(bar) + beat


def harp_gliss(s, start, dur, lo, hi, fig, vel, down=False):
    ps = [p for p in range(lo, hi + 1) if p % 12 in info(fig)[0]]
    ps = ps[::-1] if down else ps
    step = dur / len(ps)
    for k, p in enumerate(ps):
        s.note("harp", start + k * step, dur - k * step + 1.0, p, vel + int(12 * k / len(ps)), tag="orn")


def music_box(s, bar, top_name, vel=(74, 52), half_notes=False):
    top, t0 = P(top_name), bar_start(bar)
    if half_notes:
        for beat in (0, 2):
            pcs = info(chord_at(t0 + beat))[0]
            p = top if beat == 0 else min(top + ((pc - top) % 12 or 12) for pc in pcs)
            s.note("glock", t0 + beat, 2, p, vel[0] if beat == 0 else vel[1])
        return
    for k in range(8):
        pcs = sorted(info(chord_at(t0 + k * 0.5))[0] - {top % 12})
        above = sorted(top + ((pc - top) % 12) for pc in pcs)[:2]
        s.note("glock", t0 + k * 0.5, 0.5, [top, above[0], above[1], above[0]][k % 4],
               vel[0] if k % 4 == 0 else vel[1])


def harmonize_below(s, track, notes, lo, dvel=-10):
    """Second voice: the nearest chord tone a third or more below each note."""
    for n in notes:
        pcs = info(chord_at(n.start + 0.01))[0]
        cands = [p for p in range(n.pitch - 9, n.pitch - 2) if p % 12 in pcs and p >= lo]
        if cands:
            s.note(track, n.start, n.dur, max(cands), n.vel + dvel)


# ------------------------------------------------------------ rhythm parts
def rhodes_bar(s, bar, style, vel):
    t0 = bar_start(bar)
    chords = bar_chords(bar)

    def v(fig):
        s.prev["rhodes"] = voicing(fig, s.prev.get("rhodes"), 52, 76, 4, rootless=style == "funk")
        return s.prev["rhodes"]

    if style == "whole":
        for i, (b, fig) in enumerate(chords):
            end = chords[i + 1][0] if i + 1 < len(chords) else BEATS
            s.chord("rhodes", t0 + b, end - b - 0.1, v(fig), vel, roll=0.02)
    elif style == "half":
        for beat in (0, 2):
            s.chord("rhodes", t0 + beat, 1.9, v(chord_at(t0 + beat)), vel - (4 if beat else 0), roll=0.02)
    elif style == "comp":  # ballad comping: downbeat + "and of 2" push
        if len(chords) == 1:
            vo = v(chords[0][1])
            s.chord("rhodes", t0, 1.45, vo, vel, roll=0.015)
            s.chord("rhodes", t0 + 1.5, 2.4, vo, vel - 8, roll=0.015)
        else:
            for b, fig in chords:
                s.chord("rhodes", t0 + b, 1.9, v(fig), vel - 4, roll=0.015)
    elif style == "funk":
        for beat, dur, dv in [(0, 0.6, 0), (0.75, 0.35, -14), (1.5, 0.45, -8), (2.5, 0.5, -4), (3.25, 0.35, -14)]:
            s.chord("rhodes", t0 + beat, dur, v(chord_at(t0 + beat)), vel + dv, roll=0.008)


def bass_bar(s, bar, style, vel, nxt_fig=None):
    t0 = bar_start(bar)
    fig0 = bar_chords(bar)[0][1]
    root = ground(fig0)
    nxt = ground(nxt_fig or bar_chords(bar + 1)[0][1]) if bar < TOTAL_BARS else root
    approach = nxt - 1 if nxt - 1 != root else nxt + 1
    mid = near(chord_at(t0 + 2), root + 7)
    if style == "ballad":
        line = [(0, 1.4, root, 0), (1.5, 0.45, root + 12, -22), (2, 0.9, mid, -12), (3, 0.9, approach, -16)]
    elif style == "two":
        line = [(0, 1.8, root, 0), (2, 1.8, mid, -10)]
    elif style == "walk":
        line = [(0, 0.9, root, 0), (1, 0.9, near(fig0, root + 4), -14), (2, 0.9, mid, -8), (3, 0.9, approach, -12)]
    elif style == "funk":
        line = [(0, 0.45, root, 0), (0.75, 0.2, root + 12, -20), (1.5, 0.4, root, -10),
                (2, 0.45, mid, -6), (2.75, 0.2, root + 12, -20), (3.5, 0.4, approach, -10)]
    for beat, dur, p, dv in line:
        s.note("bass_pizz", t0 + beat, dur, p, vel + dv)


def arco_ground(s, bar, vel, octave=0, dur=3.8):
    # 3.8 beats: overlapping notes would trigger Meatbass's legato regions.
    s.note("bass_arco", bar_start(bar), dur, ground(bar_chords(bar)[0][1]) + octave, vel)


def trim_arco(s):
    """Per-note CC11 that levels Meatbass arco's samples, on top of the swells.

    CC11 maps to amplitude as (cc/127)^2, so a gain of g dB is cc * 10^(g/40).
    """
    expr = sorted(s.cc["bass_arco"])

    def expr_at(t):
        v = 127
        for b, _, val in expr:
            if b > t + 1e-9:
                break
            v = val
        return v

    out = []
    for n in sorted(s.tracks["bass_arco"], key=lambda n: n.start):
        f = 10 ** ((ARCO_TARGET_DB - ARCO_LEVEL_DB[n.pitch]) / 40)
        out.append((max(0.0, n.start - 0.05), 11, round(expr_at(n.start) * f)))
        out += [(b, 11, round(v * f)) for b, _, v in expr if n.start < b < n.start + n.dur]
    s.cc["bass_arco"] = out


def brush_bar(s, bar, vel, busy=False):
    t0 = bar_start(bar)
    s.note("drums_brush", t0, 4.0, BR["stir"], vel + 20)  # swirl through the bar
    s.note("drums_brush", t0, 0.5, BR["kick"], vel)
    if bar % 2 == 0:
        s.note("drums_brush", t0 + 1.5, 0.5, BR["kick"], vel - 20)
    s.note("drums_brush", t0 + 2, 0.5, BR["snare"], vel + 6)  # half-time backbeat
    for g in (1.75, 3.5):
        s.note("drums_brush", t0 + g, 0.25, BR["dig"], vel - 38)
    for b in (1, 3):
        s.note("drums_brush", t0 + b, 0.5, BR["pedal"], vel - 10)
    if busy:
        for b in (0, 1, 1.5, 2, 3, 3.5):
            s.note("drums_brush", t0 + b, 0.5, BR["ride"], vel - 14 if b % 1 == 0 else vel - 28)


def brush_fill(s, bar, vel):
    for k in range(8):
        s.note("drums_brush", B(bar, 2 + k * 0.25), 0.25, BR["snare"], vel + 5 * k)


def stick_bar(s, bar, vel, ride=False):
    t0 = bar_start(bar)
    for b, dv in ((0, 0), (0.75, -16), (2.5, -10)) + (((3.75, -24),) if bar % 2 == 0 else ()):
        s.note("drums_sticks", t0 + b, 0.25, ST["kick"], vel + dv)
    for b in (1, 3):
        s.note("drums_sticks", t0 + b, 0.25, ST["snare"], vel + 6)
    for b in (1.75, 2.25, 3.25):
        s.note("drums_sticks", t0 + b, 0.25, ST["ghost"], vel - 66)
    if ride:
        for k in range(8):
            s.note("drums_sticks", t0 + k * 0.5, 0.5, ST["bell"] if k % 2 == 0 else ST["ride"],
                   vel - 22 if k % 2 == 0 else vel - 34)
    else:
        for k in range(16):
            s.note("drums_sticks", t0 + k * 0.25, 0.25, ST["hat"], vel - (14 if k % 4 == 0 else 28 if k % 2 == 0 else 48))


def crash(s, bar, vel=110, brush=False):
    if brush:
        s.note("drums_brush", B(bar), 2, BR["crash"], vel)
    else:
        s.note("drums_sticks", B(bar), 2, ST["crash"], vel)
        s.note("drums_sticks", B(bar), 0.25, ST["kick"], vel)


def tom_fill(s, bar, vel, from_beat=2):
    n = int((4 - from_beat) / 0.25)
    for k in range(n):
        key = ST["snare"] if k < n // 4 else ST["tom_hi"] if k < n // 2 else ST["tom_lo"]
        s.note("drums_sticks", B(bar, from_beat + k * 0.25), 0.25, key, vel + int(25 * k / n))


def perc_bar(s, bar, vel):
    """Tambourine on the backbeat (shaker and congas read as "relaxing")."""
    for b in (1, 3):
        s.note("perc", B(bar, b), 0.25, PC["tamb"], vel)


def spic_bar(s, bar, vel):
    """Violin spiccato ostinato in 16ths, Pachelbel's broken-chord shape."""
    t0 = bar_start(bar)
    for beat in range(4):
        fig = chord_at(t0 + beat)
        s.prev["violins_spic"] = v = voicing(fig, s.prev.get("violins_spic"), 64, 81, 3)
        for k, (idx, dv) in enumerate(((0, 0), (2, -26), (1, -16), (2, -26))):
            s.note("violins_spic", t0 + beat + k * 0.25, 0.22, v[idx], vel + dv)


def harp_arps(s, bar, lo, hi, vel, eighths=False):
    t0 = bar_start(bar)
    if eighths:  # up and down over 5 chord tones
        for half in (0, 2):
            fig = chord_at(t0 + half)
            s.prev["harp"] = v = voicing(fig, s.prev.get("harp"), lo, hi, 5)
            for k, idx in enumerate((0, 2, 4, 3)):
                s.note("harp", t0 + half + k * 0.5, 1.5, v[idx], vel - (0 if k == 0 else 10))
    else:
        fig = bar_chords(bar)[0][1]
        s.prev["harp"] = v = voicing(fig, s.prev.get("harp"), lo, hi, 4)
        for k in range(4):
            fig_k = chord_at(t0 + k)
            p = v[k] if v[k] % 12 in info(fig_k)[0] else near(fig_k, v[k])
            s.note("harp", t0 + k, 2.0, p, vel - (0 if k == 0 else 8))


# ----------------------------------------------------------------- sections
def intro(s):
    for i in range(8):
        bar = 1 + i
        rhodes_bar(s, bar, "whole", 46 + i)
        arco_ground(s, bar, 44 + 3 * i, octave=12)
        music_box(s, bar, CANON_TOP[i])
    s.note("bells", B(1), 8, BELL, 72)
    s.note("bells", B(5), 8, BELL, 56)
    for bar in range(5, 9):
        s.pad("violas", bar, 1, 57, 67, 50)
        s.pad("cellos", bar, 1, 45, 57, 52)
    s.arch("violas", 5, 4, 72, 108)
    s.arch("cellos", 5, 4, 72, 108)
    harp_gliss(s, B(8, 1.5), 2.5, 57, 93, "A9", 58)


def theme(s):
    for c, mel in enumerate((MELODY_A, MELODY_B)):
        for i in range(8):
            bar = 9 + 8 * c + i
            rhodes_bar(s, bar, "comp", 64 + 2 * c)
            bass_bar(s, bar, "ballad", 92 + 4 * c)
            brush_bar(s, bar, 66 + 6 * c, busy=c == 1)
        notes = s.line("trumpet", mel, 9 + 8 * c, 70 + 8 * c, arc=[0, 4, 8, 6, 2, 4, 6, 10])
        for n in notes:
            if n.pitch <= HORN_TOP:
                s.note("horn", n.start, n.dur, n.pitch, n.vel - 12)
            if c == 1:
                s.note("flute", n.start, n.dur, n.pitch + 12, n.vel - 6)
    # strings creep in under the second half of A, then carry a countermelody in B
    for bar in range(13, 25):
        s.pad("violins", bar, 2, 74, 86, 48 if bar < 17 else 56)
    for bar in range(13, 17):
        s.pad("cellos", bar, 1, 45, 57, 54)
    for bar in range(17, 25):
        s.pad("violas", bar, 1, 57, 69, 54)
    s.line("cellos", CELLO_B, 17, 62, arc=[0, 2, 4, 6, 4, 6, 8, 10])
    s.arch("violins", 13, 4, 70, 100)
    s.arch("violins", 17, 4, 80, 112)
    s.arch("violins", 21, 4, 84, 118)
    s.arch("cellos", 13, 4, 72, 105)
    s.expr("cellos", (B(17), 85), (B(21), 110), (B(24, 3.75), 120))
    s.arch("violas", 17, 8, 80, 112)
    crash(s, 17, 62, brush=True)
    harp_gliss(s, B(24, 1.0), 3.0, 55, 94, "A7b9", 64)
    brush_fill(s, 24, 46)


def canon(s):
    for i in range(16):
        bar = 25 + i
        p2 = i >= 8
        rhodes_bar(s, bar, "half" if p2 else "whole", 52 if p2 else 48)
        bass_bar(s, bar, "walk" if p2 else "two", 90 if p2 else 86,
                 nxt_fig=TRAG[0] if bar == 40 else None)
        brush_bar(s, bar, 70 + (6 if p2 else 0), busy=True)
        s.pad("violas", bar, 1, 57, 67, 66 if p2 else 56)
        s.pad("cellos", bar, 1, 45, 57, 68 if p2 else 58)
        if p2:
            music_box(s, bar, CANON_TOP[i - 8], vel=(64, 50), half_notes=True)
            harp_arps(s, bar, 50, 79, 60, eighths=True)
            s.pad("horns", bar, 2, 53, 69, 52)
    crash(s, 25, 80, brush=True)
    # three-voice canon at two bars: violins, flute (+8va), flugel (-8va)
    s.line("violins", SUBJECT, 25, 72, arc=[0, 2, 4, 2], vel_step=1)
    s.line("flute", SUBJECT[:14], 27, 62, transpose=12, arc=[0, 2, 4, 2], vel_step=1)
    v3 = s.line("trumpet", SUBJECT[:12], 29, 70, transpose=-12, arc=[0, 2, 4, 2], vel_step=1)
    for n in v3:
        s.note("horn", n.start, n.dur, n.pitch, n.vel - 10)
    s.canons.append(dict(name="canon (bars 25-40)", subject=SUBJECT, voices=[
        ("violins", B(25), 0, 16), ("flute", B(27), 12, 14), ("trumpet", B(29), -12, 12)]))
    for k in range(4):
        s.arch("violins", 25 + 4 * k, 4, 84 + 4 * k, 112 + 4 * k)
        s.arch("violas", 25 + 4 * k, 4, 80, 108)
        s.arch("cellos", 25 + 4 * k, 4, 80, 108)
    s.arch("flute", 27, 14, 92, 120)
    s.arch("horns", 33, 8, 70, 110)
    s.note("timp_roll", B(40), 3.9, P("A2"), 70)
    s.expr("timp_roll", (B(40), 50), (B(40, 3.75), 105))


def tragedy(s):
    for i in range(16):
        bar = 41 + i
        arco_ground(s, bar, 62 if i < 8 else 74)
        if i < 8:
            s.pad("violins_trem", bar, 2, 62, 77, 46)
            s.pad("violas_trem", bar, 1, 53, 65, 46)
            s.pad("cellos_trem", bar, 1, 43, 55, 50)
        else:
            s.pad("violas", bar, 2, 55, 69, 66)
            harp_arps(s, bar, 40, 64, 56)
    s.line("oboe", TRAG_1, 41, 64, arc=[0, 4, 2, 0, 2, 6, 4, 0])
    for k in range(4):
        s.arch("oboe", 41 + 2 * k, 2, 88, 122)
    for t in ("violins_trem", "violas_trem", "cellos_trem"):
        s.arch(t, 41, 4, 70, 104)
        s.arch(t, 45, 4, 76, 112)
    # the big tune: violins with cellos an octave below; oboe turns countermelody
    s.line("violins", TRAG_2, 49, 82, arc=[0, 2, 4, 6, 6, 8, 10, 14])
    s.line("cellos", TRAG_2, 49, 80, transpose=-12, arc=[0, 2, 4, 6, 6, 8, 10, 14])
    s.line("oboe", OBOE_COUNTER, 49, 58)
    s.expr("oboe", (B(49), 90), (B(57) - 0.25, 110))
    for t in ("violins", "cellos"):
        s.expr(t, (B(49), 92), (B(51), 112), (B(53), 100), (B(55), 115), (B(56, 3.75), 127))
    s.arch("violas", 49, 8, 85, 112)
    for bar in range(53, 57):
        s.pad("horns", bar, 2, 53, 69, 62)
    s.expr("horns", (B(53), 60), (B(56, 3.75), 120))
    for bar in (55, 56):
        s.pad("trombones", bar, 2, 45, 60, 66)
    s.expr("trombones", (B(55), 60), (B(56, 3.75), 118))
    for bar, v in ((41, 74), (45, 62), (49, 76), (53, 66)):
        s.note("bells", B(bar), 8, BELL, v)
    # timpani: D under the tonic and Gm6 bars, moving to A only under A7b9
    for bar, beats, note, vel in ((41, 7.9, "D2", 52), (47, 3.9, "D2", 56), (48, 3.9, "A2", 62),
                                  (49, 7.9, "D2", 62), (55, 3.9, "D2", 70), (56, 3.9, "A2", 82)):
        s.note("timp_roll", B(bar), beats, P(note), vel)
    s.expr("timp_roll", (B(41), 70), (B(43) - 0.25, 50), (B(47), 60), (B(48) - 0.25, 80), (B(48), 80),
           (B(49) - 0.25, 105), (B(49), 80), (B(51) - 0.25, 60), (B(55), 70), (B(56) - 0.25, 95), (B(56), 95),
           (B(57) - 0.25, 127))


def rise(s):
    s.cc["drums_sticks"].append((0.0, 4, 127))  # Virtuosity hi-hat: CC4 0 = open, 127 = closed
    for i in range(4):
        bar = 57 + i
        s.note("bass_arco", B(bar), 3.8, P("B1"), 82)
        s.chord("cellos_trem", B(bar), 3.9, [P("B2"), P("F#3")], 78)
        s.pad("violins_trem", bar, 2, 66, 83, 74)
        s.pad("violas_trem", bar, 1, 55, 69, 72)
        s.note("drums_sticks", B(bar), 0.5, ST["kick"], 64 + 8 * i)
        s.note("drums_sticks", B(bar, 2), 0.5, ST["kick"], 58 + 8 * i)
    for t in ("violins_trem", "violas_trem", "cellos_trem", "bass_arco"):
        s.expr(t, (B(57), 64), (B(60, 3.75), 127))
    s.line("horns", RISE_MOTIF, 57, 84, vel_step=6)
    s.line("trombones", RISE_MOTIF, 57, 84, transpose=-12, vel_step=6)
    s.expr("horns", (B(57), 90), (B(60, 3.75), 127))
    s.expr("trombones", (B(57), 90), (B(60, 3.75), 127))
    s.line("trumpet", ["D#5:2 F#5:2"], 60, 100)
    s.note("timp_roll", B(57), 7.9, P("B2"), 70)
    s.note("timp_roll", B(59), 7.9, P("B2"), 90)
    s.expr("timp_roll", (B(57), 55), (B(59) - 0.25, 90), (B(59), 80), (B(60, 3.75), 127))
    s.note("drums_sticks", B(59), 7.9, ST["roll"], 100)
    s.cc["drums_sticks"] += [(B(59) + k * 0.25, 1, round(20 + 107 * k / 31)) for k in range(32)]
    harp_gliss(s, B(60, 1.5), 2.5, 47, 95, "B7b9", 70)


def fight(s):
    for i in range(24):
        bar = 61 + i
        p = i // 8  # pass 0, 1, 2
        if bar < 83:
            rhodes_bar(s, bar, "funk" if p < 2 else "half", 80 + 4 * p)
            bass_bar(s, bar, "funk", 100 + 3 * p)
            stick_bar(s, bar, 96 + 4 * p, ride=p == 2)
            if p >= 1:
                perc_bar(s, bar, 70 + 4 * p)
            s.pad("violas", bar, 2, 55, 72, 84 + 4 * p)
        if p == 0 or (p == 2 and bar < 81):  # cellos drive the ground an octave up
            g = ground(bar_chords(bar)[0][1]) + 12
            for beat, d, dv in ((0, 1.4, 0), (1.5, 0.9, -12), (2.5, 1.4, -6)):
                s.note("cellos", B(bar, beat), d, g, 96 + dv)
        if p != 1 and bar < 83:
            spic_bar(s, bar, 92 + 4 * p)
        if p == 2 and bar < 81:
            s.pad("trombones", bar, 2, 45, 62, 82)
        if p != 1 and bar < 83:  # timpani on every downbeat while fighting
            s.note("timpani", B(bar), 1.5, 36 + (info(bar_chords(bar)[0][1])[3] - 36) % 12, 108)
        if p == 1:
            s.pad("horns", bar, 2, 53, 69, 76)
        if p >= 1 and bar < 83:  # 70s brass stabs on "and of 2" and "and of 4"
            for beat, dv in ((1.5, 0), (3.5, -8)):
                fig = chord_at(B(bar, beat))
                for tr, lo, hi in (("trumpets_stac", 64, 79), ("trombones_stac", 50, 64)):
                    s.prev[tr] = v = voicing(fig, s.prev.get(tr), lo, hi, 2)
                    for q in v:
                        s.note(tr, B(bar, beat), 0.3, q, 104 + dv)
        if p == 2 and bar < 79:
            s.pad("horns", bar, 2, 53, 69, 84)
    for bar in (61, 69, 77):
        crash(s, bar, 112)
    for bar in (69, 73):
        s.note("timpani", B(bar), 2, P("E2"), 112)
    for bar in (64, 80):
        tom_fill(s, bar, 84, from_beat=3)

    # pass 1: the theme in the brass
    lead = s.line("trumpet", MELODY_A, 61, 98, transpose=2, arc=[0, 4, 8, 6, 2, 4, 6, 10])
    harmonize_below(s, "trumpet", lead, 56)
    for n in lead:  # flugel double, horns an octave down, trombones two: a heroic unison
        if n.pitch <= HORN_TOP:
            s.note("horn", n.start, n.dur, n.pitch, n.vel - 10)
        s.note("horns", n.start, n.dur, n.pitch - 12, n.vel - 8)
        s.note("trombones", n.start, n.dur, n.pitch - 24, n.vel - 10)
    s.arch("trombones", 61, 8, 96, 120)
    s.arch("violas", 61, 8, 96, 120)
    harp_gliss(s, B(68, 1.5), 2.5, 47, 95, "B9", 72)
    tom_fill(s, 68, 88)

    # pass 2: the B theme in soaring strings, flute on top
    s.line("violins", MELODY_B, 69, 100, transpose=2, arc=[0, 4, 6, 4, 2, 4, 8, 10])
    s.line("flute", MELODY_B, 69, 94, transpose=14, arc=[0, 4, 6, 4, 2, 4, 8, 10])
    s.expr("flute", (B(69), 110), (B(84, 3.75), 120))
    s.line("cellos", CELLO_B, 69, 92, transpose=2, arc=[0, 2, 4, 6, 4, 6, 8, 10])
    s.expr("violins", (B(69), 100), (B(73), 118), (B(76, 3.75), 127))
    s.expr("cellos", (B(69), 100), (B(76, 3.75), 124))
    s.arch("violas", 69, 8, 96, 120)
    s.arch("horns", 69, 8, 84, 116)
    harp_gliss(s, B(76, 1.5), 2.5, 47, 95, "B7b9", 74)
    tom_fill(s, 76, 92, from_beat=2)

    # pass 3: the canon returns as the battle: everyone joins in
    s.line("violins", SUBJECT[:6], 77, 104, transpose=2, arc=[0, 2, 4, 2])
    s.line("flute", SUBJECT[:6], 77, 96, transpose=2, arc=[0, 2, 4, 2])
    s.line("trumpet", SUBJECT[:4], 79, 102, transpose=-10, arc=[0, 2, 4, 2])
    s.line("horns", SUBJECT[:4], 79, 96, transpose=-10, arc=[0, 2, 4, 2])
    s.line("cellos", SUBJECT[:2], 81, 100, transpose=-22)
    s.line("trombones", SUBJECT[:2], 81, 100, transpose=-22)
    s.canons.append(dict(name="battle canon (bars 77-82)", subject=SUBJECT, voices=[
        ("violins", B(77), 2, 6), ("flute", B(77), 2, 6), ("trumpet", B(79), -10, 4),
        ("horns", B(79), -10, 4), ("cellos", B(81), -22, 2), ("trombones", B(81), -22, 2)]))
    for bar in range(77, 83):
        arco_ground(s, bar, 86)
    s.expr("violins", (B(77), 110), (B(82, 3.75), 127))
    s.expr("cellos", (B(77), 110), (B(82, 3.75), 127))
    s.expr("trombones", (B(77), 100), (B(82, 3.75), 124))
    s.expr("horns", (B(77), 100), (B(82, 3.75), 124))
    s.arch("violas", 77, 6, 100, 124)

    # bar 83: the scar (Am6) hits the whole orchestra, then everything drains away
    crash(s, 83, 118)
    s.note("drums_sticks", B(83), 4, ST["crash"], 100)
    s.note("timpani", B(83), 2, P("A2"), 120)
    s.note("timp_roll", B(83, 0.5), 7.3, P("A2"), 90)
    s.expr("timp_roll", (B(83, 0.5), 110), (B(84, 3.75), 40))
    s.note("bass_pizz", B(83), 2, P("A1"), 104)
    s.note("bass_arco", B(83), 7.8, P("A1"), 90)
    s.expr("bass_arco", (B(83), 127), (B(84, 3.75), 70))
    tutti = [("violins", 2, 72, 86), ("violas", 2, 57, 72), ("cellos", 2, 45, 60), ("horns", 2, 53, 69),
             ("trombones", 2, 45, 60), ("trumpet", 2, 64, 77), ("flute", 1, 81, 88)]
    for tr, n, lo, hi in tutti:
        s.pad(tr, 83, n, lo, hi, 108)
    rhodes_bar(s, 83, "whole", 88)
    s.chord("harp", B(83), 4, voicing("Am6", None, 40, 76, 6), 90, roll=0.04)
    for tr, n, lo, hi in tutti[:5]:
        s.pad(tr, 84, max(1, n - (tr in ("violas", "cellos"))), lo, hi, 70)
        s.expr(tr, (B(83, 0.25), 127), (B(84), 92), (B(84, 3.75), 62))
    rhodes_bar(s, 84, "whole", 60)
    harp_gliss(s, B(84, 0.5), 3.0, 57, 93, "A7sus4 add 9", 58, down=True)


def outro(s):
    for i in range(8):
        bar = 85 + i
        rhodes_bar(s, bar, "whole", 46)
        arco_ground(s, bar, 54, octave=12)
        music_box(s, bar, OUTRO_TOP[i], vel=(70, 50))
        s.pad("violins", bar, 2, 74, 86, 48)
        s.pad("violas", bar, 1, 57, 67, 48)
        s.pad("cellos", bar, 1, 45, 57, 50)
        if i >= 4:
            harp_arps(s, bar, 50, 74, 48)
    for t in ("violins", "violas", "cellos"):
        s.arch(t, 85, 4, 70, 100)
        s.arch(t, 89, 4, 74, 104)
    s.expr("bass_arco", (B(85), 100), (B(94, 3.75), 90))
    s.line("flute", MELODY_A[:4], 85, 60, transpose=12, arc=[0, 4, 6, 2])
    s.expr("flute", (B(85), 100), (B(89) - 0.25, 100))
    tpt = s.line("trumpet", OUTRO_TPT, 89, 62, arc=[0, 4, 6, 8])
    for n in tpt:
        s.note("horn", n.start, n.dur, n.pitch, n.vel - 12)
    # final chord, held: home, with the 9th on top
    t = B(93)
    s.chord("rhodes", t, 7.8, voicing("Dadd9", s.prev["rhodes"], 52, 76, 4), 50, roll=0.05)
    s.note("bass_arco", t, 7.8, P("D2"), 52)
    for tr, n, lo, hi in (("violins", 2, 74, 86), ("violas", 1, 57, 67), ("cellos", 1, 45, 57)):
        s.pad(tr, 93, n, lo, hi, 46)
        s.tracks[tr][-n:] = [Note(x.start, 7.8, x.pitch, x.vel, x.tag) for x in s.tracks[tr][-n:]]
        s.expr(tr, (t, 96), (t + 7.75, 50))
    coda = s.line("trumpet", CODA, 93, 66)
    for n in coda:
        s.note("horn", n.start, n.dur, n.pitch, n.vel - 12)
        s.note("flute", n.start, n.dur, n.pitch + 12, n.vel - 18)
    s.expr("flute", (t, 90), (t + 7.75, 70))
    s.note("bells", t, 8, BELL, 52)
    harp_gliss(s, t, 2.0, 50, 86, "Dadd9", 50)
    for k, p in enumerate(["D7", "A6", "F#6", "E6"]):
        s.note("glock", B(94, k * 0.75), 0.75, P(p), 58 - 4 * k)


def build() -> dict:
    s = Song()
    for section in (intro, theme, canon, tragedy, rise, fight, outro):
        section(s)
    trim_arco(s)
    chords = []
    for bar in range(1, TOTAL_BARS + 1):
        cs = bar_chords(bar)
        for i, (b, fig) in enumerate(cs):
            end = cs[i + 1][0] if i + 1 < len(cs) else BEATS
            chords.append((bar_start(bar) + b, end - b, fig))
    for v in s.tracks.values():
        v.sort(key=lambda n: (n.start, n.pitch))
    return dict(bpm=BPM, lead_in=LEAD_IN, beats_per_bar=BEATS, total_bars=TOTAL_BARS, tracks=s.tracks,
                cc=s.cc, chords=chords, sections=SECTIONS, canons=s.canons, title=TITLE)


# Per-track humanisation: (timing sd seconds, mean lag seconds, velocity sd).
FEEL = {"rhodes": (0.006, 0.0, 3), "bass_pizz": (0.005, 0.0, 4), "bass_arco": (0.004, 0.0, 2),
        "drums_brush": (0.006, 0.0, 5), "drums_sticks": (0.004, 0.0, 4), "perc": (0.006, 0.0, 5),
        "trumpet": (0.010, 0.012, 3), "horn": (0.010, 0.016, 3), "flute": (0.010, 0.010, 3),
        "oboe": (0.010, 0.010, 3), "violins": (0.008, 0.010, 3), "violas": (0.008, 0.012, 3),
        "cellos": (0.008, 0.012, 3), "violins_trem": (0.006, 0.0, 2), "violas_trem": (0.006, 0.0, 2),
        "cellos_trem": (0.006, 0.0, 2), "violins_spic": (0.005, 0.0, 4), "horns": (0.010, 0.016, 3),
        "trombones": (0.010, 0.014, 3), "trumpets_stac": (0.006, 0.004, 4),
        "trombones_stac": (0.006, 0.006, 4), "glock": (0.004, 0.0, 4), "harp": (0.005, 0.0, 3),
        "bells": (0.003, 0.0, 2), "timpani": (0.004, 0.0, 3), "timp_roll": (0.004, 0.0, 2)}


def write(song: dict) -> None:
    rng = random.Random(1979)
    mid_dir = BUILD / "midi"
    for f in mid_dir.glob("*.mid"):
        f.unlink()
    for name, notes in song["tracks"].items():
        if not notes:
            continue
        sd, lag, vsd = FEEL[name]
        cfg = INSTRUMENTS[name]
        t, lat = cfg.get("transpose", 0), cfg.get("latency", 0.0)
        hum = [Note(n.start + LEAD_IN, n.dur, n.pitch + t, int(n.vel + rng.gauss(0, vsd))) for n in notes]
        offs = [lag - lat + rng.gauss(0, sd) for _ in notes]
        cc = [(b + LEAD_IN, num, val) for b, num, val in song["cc"][name]]
        write_midi(hum, mid_dir / f"{name}.mid", song["bpm"], cc=cc, offsets_s=offs, tail_beats=12)
    (BUILD / "song.json").write_text(json.dumps({
        **{k: v for k, v in song.items() if k not in ("tracks", "cc")},
        "tracks": {k: [asdict(n) for n in v] for k, v in song["tracks"].items()},
    }))


GM = {"rhodes": 4, "bass_pizz": 32, "bass_arco": 43, "trumpet": 56, "horn": 60, "flute": 73, "oboe": 68,
      "violins": 48, "violas": 48, "cellos": 48, "violins_trem": 44, "violas_trem": 44, "cellos_trem": 44,
      "violins_spic": 48, "horns": 60, "trombones": 57, "trumpets_stac": 56, "trombones_stac": 57,
      "glock": 9, "harp": 46, "bells": 14, "timpani": 47, "timp_roll": 47}


def export_multitrack(song: dict, path) -> None:
    """Quantised multi-track MIDI with GM programs, for opening in a DAW."""
    mf = mido.MidiFile(ticks_per_beat=PPQ)
    meta = mido.MidiTrack([mido.MetaMessage("track_name", name="Canon for a Dying World"),
                           mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)),
                           mido.MetaMessage("time_signature", numerator=4, denominator=4)])
    mf.tracks.append(meta)
    channels = itertools.cycle([c for c in range(16) if c != 9])
    for name, notes in song["tracks"].items():
        if not notes:
            continue
        drums = INSTRUMENTS[name].get("drums")
        ch = 9 if drums else next(channels)
        ev = [(n.start, 1, mido.Message("note_on", note=n.pitch, velocity=n.vel, channel=ch)) for n in notes]
        ev += [(n.start + n.dur, 0, mido.Message("note_off", note=n.pitch, velocity=0, channel=ch)) for n in notes]
        ev += [(b, 0, mido.Message("control_change", control=c, value=v, channel=ch)) for b, c, v in song["cc"][name]]
        ev.sort(key=lambda e: (e[0], e[1]))
        tr = mido.MidiTrack([mido.MetaMessage("track_name", name=name)])
        if not drums:
            tr.append(mido.Message("program_change", program=GM[name], channel=ch))
        last = 0
        for beat, _, msg in ev:
            tick = int(round(beat * PPQ))
            tr.append(msg.copy(time=tick - last))
            last = tick
        mf.tracks.append(tr)
    mf.save(path)


def export_score(song: dict, path) -> None:
    """MusicXML score with chord symbols (music21). Pitched parts only."""
    from music21 import chord, instrument, meter, note, stream, tempo
    order = ["flute", "oboe", "horns", "trumpet", "trombones", "glock", "bells", "timpani", "harp", "rhodes",
             "violins", "violins_spic", "violins_trem", "violas", "violas_trem", "cellos", "cellos_trem",
             "bass_pizz", "bass_arco"]
    score = stream.Score()
    for key in order:
        notes = song["tracks"][key]
        part = stream.Part(id=key)
        inst = instrument.Instrument()
        inst.partName = key.replace("_", " ")
        part.insert(0, inst)
        part.insert(0, meter.TimeSignature("4/4"))
        if key == "flute":
            part.insert(0, tempo.MetronomeMark(number=BPM))
            for st, _, fig in song["chords"]:
                part.insert(st, harmony.ChordSymbol(fig))
        groups: dict[tuple[float, float], list[int]] = {}
        for n in notes:
            groups.setdefault((round(n.start * 4) / 4, max(0.25, round(n.dur * 4) / 4)), []).append(n.pitch)
        for (st, d), ps in sorted(groups.items()):
            el = note.Note(ps[0]) if len(set(ps)) == 1 else chord.Chord(sorted(set(ps)))
            el.quarterLength = d
            part.insert(st, el)
        score.insert(0, part)
    score.write("musicxml", fp=path)


if __name__ == "__main__":
    BUILD.mkdir(exist_ok=True)
    song = build()
    write(song)
    export_multitrack(song, BUILD / f"{TITLE}.mid")
    export_score(song, BUILD / f"{TITLE}.musicxml")
    total = max(n.start + n.dur for v in song["tracks"].values() for n in v)
    print(f"{total / BEATS:.1f} bars, {total * 60 / BPM:.1f} s; "
          f"{sum(len(v) for v in song['tracks'].values())} notes in "
          f"{sum(1 for v in song['tracks'].values() if v)} tracks")
