"""Render per-track MIDI through sfizz, mix with Pedalboard, reverb with
Dragonfly Plate + Hall (VST3, hosted by Pedalboard), master to -14 LUFS / -1 dBTP."""
from __future__ import annotations

import subprocess
import sys

import json

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from pedalboard import (Compressor, Gain, HighpassFilter, HighShelfFilter, Limiter,
                        LowpassFilter, LowShelfFilter, Pedalboard, load_plugin)
from scipy.signal import resample_poly

from audio import render
from instruments import BUILD, INSTRUMENTS, ROOT

SR = 48000
TARGET_LUFS = -14.0
CEILING_DBTP = -1.0


def load(path) -> np.ndarray:
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    assert sr == SR, (path, sr)
    return y.T if y.shape[1] == 2 else np.repeat(y.T, 2, axis=0)


def pan(x: np.ndarray, p: float) -> np.ndarray:
    th = (p + 1) * np.pi / 4  # constant-power
    return np.stack([x[0] * np.cos(th) * np.sqrt(2), x[1] * np.sin(th) * np.sqrt(2)])


DRAGONFLY = ROOT / ".cache" / "plugins" / "dragonfly-reverb-3.2.10"


def reverb(x: np.ndarray, kind: str, **params) -> np.ndarray:
    """100% wet Dragonfly reverb on a send bus."""
    fx = load_plugin(str(DRAGONFLY / f"Dragonfly{kind}Reverb.vst3"))
    fx.dry_level = 0
    for k, v in params.items():
        setattr(fx, k, v)
    return fx(x, SR)


def true_peak_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.abs(resample_poly(x, 4, 1, axis=1)).max() + 1e-12))


def main(name: str = "canon_sketch") -> None:
    raw, stems, out = BUILD / "stems_raw", BUILD / "stems", BUILD / "audio"
    for d in (raw, stems, out):
        d.mkdir(parents=True, exist_ok=True)

    song = json.loads((BUILD / "song.json").read_text())
    trim = int(round(song["lead_in"] * 60 / song["bpm"] * SR))
    dry = send = hall = None
    for inst, cfg in INSTRUMENTS.items():
        mid = BUILD / "midi" / f"{inst}.mid"
        if not mid.exists():
            continue
        render(cfg["sfz"], mid, raw / f"{inst}.wav", SR)
        x = load(raw / f"{inst}.wav")[:, trim:]
        sf.write(raw / f"{inst}.wav", x.T, SR, subtype="FLOAT")  # bar 1 at t=0 for verify.py
        chain = Pedalboard([HighpassFilter(cfg["hpf"]), LowpassFilter(cfg["lpf"]),
                            Compressor(threshold_db=-20, ratio=2.0, attack_ms=15, release_ms=180),
                            Gain(cfg["gain_db"])])
        y = pan(chain(x, SR), cfg["pan"])
        sf.write(stems / f"{inst}.wav", y.T, SR, subtype="PCM_24")
        if dry is None:
            dry, send, hall = (np.zeros((2, 0), np.float32) for _ in range(3))
        n = max(dry.shape[1], y.shape[1])
        fit = lambda a: np.pad(a, ((0, 0), (0, n - a.shape[1])))  # noqa: E731
        dry, send, hall = fit(dry) + fit(y), fit(send) + fit(y * cfg["send"]), fit(hall) + fit(y * cfg["hall"])

    tail = lambda a: np.pad(a, ((0, 0), (0, SR * 4))).astype(np.float32)  # noqa: E731
    dry, send, hall = tail(dry), tail(send), tail(hall)
    mix = (dry
           + reverb(send, "Plate", wet_level=100, algorithm="Nested", width=120, predelay_ms=20,
                    decay_s=2.4, low_cut_hz=150, high_cut_hz=7500, dampen_hz=6500)
           + reverb(hall, "Hall", early_level=25, late_level=100, size_m=36, width=110, predelay_ms=28,
                    decay_s=3.2, low_cut_hz=90, high_cut_hz=8000, diffuse=80, modulation=20))

    # Warm, slightly dark 70s master bus.
    bus = Pedalboard([LowShelfFilter(cutoff_frequency_hz=110, gain_db=1.0),
                      HighShelfFilter(cutoff_frequency_hz=9000, gain_db=-1.5),
                      Compressor(threshold_db=-16, ratio=1.6, attack_ms=30, release_ms=250)])
    mix = bus(mix.astype(np.float32), SR)

    meter = pyln.Meter(SR)
    gain = 0.0
    for _ in range(4):  # normalise, limit, re-measure until on target
        y = Pedalboard([Gain(gain), Limiter(threshold_db=CEILING_DBTP - 0.6, release_ms=120)])(mix, SR)
        lufs = meter.integrated_loudness(y.T)
        if abs(lufs - TARGET_LUFS) < 0.2:
            break
        gain += TARGET_LUFS - lufs
    # trim trailing silence below -70 dBFS, keep a 0.5 s fade
    env = np.abs(y).max(axis=0)
    last = int(np.nonzero(env > 10 ** (-70 / 20))[0][-1]) + SR // 2
    y = y[:, :last]
    fade = int(SR * 0.5)
    y[:, -fade:] *= np.linspace(1, 0, fade)

    wav = out / f"{name}.wav"
    sf.write(wav, y.T, SR, subtype="PCM_24")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "320k", str(out / f"{name}.mp3")], check=True)
    print(f"{wav.name}: {y.shape[1] / SR:.1f} s, {meter.integrated_loudness(y.T):.1f} LUFS, "
          f"true peak {true_peak_db(y):.2f} dBTP")


if __name__ == "__main__":
    main(*sys.argv[1:])
