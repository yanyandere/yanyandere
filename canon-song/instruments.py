"""Instrument registry: which third-party SFZ library plays each part, its
playable range, and its mix settings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIBS = ROOT / ".cache" / "libs"
MODELS = ROOT / ".cache" / "models"
BUILD = ROOT / "build"

VSCO = LIBS / "VSCO-2-CE"
MEAT = LIBS / "karoryfer.meatbass" / "Programs"
RHODES = LIBS / "jlearman.jRhodes3d"

# range: (low, high) sounding MIDI notes, in the sample set and idiomatic.
# transpose: semitones added before sending to sfizz (measured by test_instruments.py).
# latency: seconds the samples take to speak; MIDI is sent that much earlier
#   (measured from basic-pitch onsets).
# pan: -1 left .. 1 right. send/hall: Dragonfly Plate / Hall send levels.
INSTRUMENTS = {
    "rhodes":    dict(sfz=RHODES / "jRhodes3d-st.sfz", range=(40, 84), gain_db=-2.0, pan=0.0, send=0.22, hall=0.15,
                      hpf=70, lpf=12000),
    "bass_arco": dict(sfz=MEAT / "03_arco_5vel.sfz", range=(28, 62), gain_db=-1.0, pan=0.0, send=0.12, hall=0.12,
                      hpf=35, lpf=6000),
    "bass_pizz": dict(sfz=MEAT / "04_pizz.sfz", range=(28, 62), gain_db=0.0, pan=0.0, send=0.08, hall=0.06,
                      hpf=35, lpf=6000),
    # Flugelhorn stand-in: soft vibrato trumpet layered with horn in unison,
    # low-passed for the darker flugel tone (no free flugelhorn library exists).
    "trumpet":   dict(sfz=VSCO / "TrumpetSusVib.sfz", range=(54, 79), gain_db=-3.0, pan=-0.12, send=0.30, hall=0.2,
                      hpf=150, lpf=5200),
    "horn":      dict(sfz=VSCO / "FHornSus.sfz", range=(50, 77), latency=0.065, gain_db=-8.0, pan=-0.12, send=0.30, hall=0.2,
                      hpf=90, lpf=4500),
    "flute":     dict(sfz=VSCO / "FluteSusVib.sfz", range=(60, 93), gain_db=-5.0, pan=0.22, send=0.32, hall=0.25,
                      hpf=250, lpf=14000),
    # VSCO maps the glockenspiel an octave low: MIDI 67 sounds G5 (784 Hz).
    "glock":     dict(sfz=VSCO / "Glockenspiel.sfz", range=(79, 108), transpose=-12, gain_db=4.0, pan=0.35, send=0.40, hall=0.35,
                      hpf=500, lpf=16000),
}
