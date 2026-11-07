"""Instrument registry: which third-party SFZ library plays each part, its
playable range, and its mix settings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIBS = ROOT / ".cache" / "libs"
MODELS = ROOT / ".cache" / "models"
PLUGINS = ROOT / ".cache" / "plugins"
BUILD = ROOT / "build"

VSCO = LIBS / "VSCO-2-CE"
MEAT = LIBS / "karoryfer.meatbass" / "Programs"
RHODES = LIBS / "jlearman.jRhodes3d"
SWIRLY = LIBS / "karoryfer.swirly-drums" / "Programs"
VIRT = LIBS / "virtuosity_drums" / "Programs"


# range: (low, high) sounding MIDI notes, in the sample set and idiomatic.
# transpose: semitones added before sending to sfizz (measured by test_instruments.py).
# latency: seconds the samples take to speak; MIDI is sent that much earlier
#   (test_instruments.py onset lag minus basic-pitch's ~15 ms detector bias).
# Tubular bells and timpani are mapped correctly even though basic-pitch reads
# them +12 / +7: their spectra show partials at 2:3:4 (bells) and 1:1.5:2
# (timpani) of the written pitch, which is what the ear hears.
# level: target integrated loudness (LUFS) of the processed stem before the
#   master bus, i.e. the part's place in the mix. Parts that only play in quiet
#   sections (oboe lament, tremolo bed, bells) sit lower so the arc survives.
# pan: -1 left .. 1 right. send/hall: Dragonfly Plate / Hall send levels.
# Swells use CC11, which sfizz applies to every instrument by default
# (amplitude = (cc/127)^2).
# drums: unpitched, skipped by pitch checks.
_I = dict
INSTRUMENTS = {
    # --- rhythm section
    "rhodes":     _I(sfz=RHODES / "jRhodes3d-st.sfz", range=(40, 84), level=-24, pan=0.0, send=0.22, hall=0.12, hpf=70, lpf=12000),
    "bass_pizz":  _I(sfz=MEAT / "04_pizz.sfz", range=(28, 62), level=-21, pan=0.0, send=0.06, hall=0.05, hpf=35, lpf=6000),
    "bass_arco":  _I(sfz=MEAT / "03_arco_5vel.sfz", range=(28, 62), level=-27, pan=0.05, send=0.10, hall=0.14, hpf=32, lpf=6000),
    "drums_brush": _I(sfz=SWIRLY / "Basic_kit.sfz", range=(36, 64), drums=True, level=-27, pan=0.0, send=0.10, hall=0.10, hpf=40, lpf=16000),
    "drums_sticks": _I(sfz=VIRT / "02-full-kit.sfz", range=(35, 96), drums=True, level=-19, pan=0.0, send=0.08, hall=0.10, hpf=35, lpf=17000),
    "perc":       _I(sfz=VIRT / "01-basic-kit.sfz", range=(54, 84), drums=True, latency=0.04, level=-31, pan=0.3, send=0.12, hall=0.15, hpf=200, lpf=16000),
    # --- lead voices. Flugelhorn stand-in: soft vibrato trumpet doubled by
    # horn in unison, low-passed (no free flugelhorn library exists).
    "trumpet":    _I(sfz=VSCO / "TrumpetSusVib.sfz", range=(54, 79), level=-20, pan=-0.08, send=0.28, hall=0.20, hpf=150, lpf=5200),
    "horn":       _I(sfz=VSCO / "FHornSus.sfz", range=(50, 77), latency=0.05, level=-27, pan=-0.08, send=0.25, hall=0.22, hpf=90, lpf=4500),
    "flute":      _I(sfz=VSCO / "FluteSusVib.sfz", range=(60, 93), level=-23, pan=0.22, send=0.30, hall=0.25, hpf=250, lpf=14000),
    "oboe":       _I(sfz=VSCO / "OboeSusVib.sfz", range=(58, 88), level=-26, pan=0.08, send=0.28, hall=0.28, hpf=200, lpf=12000),
    # --- strings (ensembles)
    "violins":    _I(sfz=VSCO / "ViolinEnsSusVib.sfz", range=(55, 86), latency=0.073, level=-21, pan=-0.35, send=0.18, hall=0.30, hpf=180, lpf=13000),
    "violas":     _I(sfz=VSCO / "ViolaEnsSusVib.sfz", range=(48, 79), latency=0.067, level=-26, pan=0.12, send=0.15, hall=0.30, hpf=120, lpf=10000),
    "cellos":     _I(sfz=VSCO / "CelloEnsSusVib.sfz", range=(36, 74), latency=0.08, level=-23, pan=0.32, send=0.12, hall=0.28, hpf=60, lpf=8000),
    "violins_trem": _I(sfz=VSCO / "ViolinEnsTrem.sfz", range=(55, 86), latency=0.033, level=-30, pan=-0.3, send=0.15, hall=0.32, hpf=200, lpf=12000),
    "violas_trem": _I(sfz=VSCO / "ViolaEnsTrem.sfz", range=(48, 79), latency=0.026, level=-32, pan=0.12, send=0.15, hall=0.32, hpf=130, lpf=10000),
    "cellos_trem": _I(sfz=VSCO / "CelloEnsTrem.sfz", range=(36, 74), latency=0.05, level=-30, pan=0.3, send=0.12, hall=0.30, hpf=60, lpf=8000),
    "violins_spic": _I(sfz=VSCO / "ViolinEnsSpic.sfz", range=(55, 86), latency=0.062, level=-23, pan=-0.25, send=0.12, hall=0.22, hpf=200, lpf=13000),
    # --- brass section
    "horns":      _I(sfz=VSCO / "FHornSus.sfz", range=(41, 77), latency=0.05, level=-24, pan=-0.22, send=0.18, hall=0.30, hpf=80, lpf=6000),
    "trombones":  _I(sfz=VSCO / "TromboneSus.sfz", range=(40, 65), level=-24, pan=0.28, send=0.15, hall=0.25, hpf=60, lpf=7000),
    "trumpets_stac": _I(sfz=VSCO / "TrumpetStac.sfz", range=(54, 82), level=-22, pan=0.15, send=0.20, hall=0.20, hpf=200, lpf=9000),
    "trombones_stac": _I(sfz=VSCO / "TromboneStac.sfz", range=(40, 70), level=-23, pan=0.3, send=0.18, hall=0.20, hpf=70, lpf=7000),
    # --- colour
    "glock":      _I(sfz=VSCO / "Glockenspiel.sfz", range=(79, 108), transpose=-12, level=-29, pan=0.35, send=0.35, hall=0.30, hpf=500, lpf=16000),
    "harp":       _I(sfz=VSCO / "Harp.sfz", range=(28, 101), level=-28, pan=-0.45, send=0.25, hall=0.30, hpf=60, lpf=14000),
    "bells":      _I(sfz=VSCO / "TubularBells.sfz", range=(60, 79), level=-31, pan=0.2, send=0.20, hall=0.45, hpf=150, lpf=12000),
    "timpani":    _I(sfz=VSCO / "Timpani.sfz", range=(36, 60), level=-22, pan=0.0, send=0.10, hall=0.35, hpf=35, lpf=6000),
    "timp_roll":  _I(sfz=VSCO / "TimpaniRolls.sfz", range=(36, 60), level=-29, pan=0.0, send=0.10, hall=0.35, hpf=35, lpf=6000),
}
