"""Render per-track MIDI through sfizz, mix with Pedalboard, reverb with
Dragonfly Plate + Hall and tape with CHOW Tape Model (VST3s hosted by
Pedalboard), master to -14 LUFS / -1 dBTP."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from pedalboard import (Compressor, Gain, HighpassFilter, HighShelfFilter, LowpassFilter,
                        LowShelfFilter, Pedalboard, load_plugin)
from scipy.signal import resample_poly

from audio import render
from instruments import BUILD, INSTRUMENTS, PLUGINS

SR = 48000
TARGET_LUFS = -14.0
CEILING_DBTP = -1.0
DRAGONFLY = PLUGINS / "dragonfly-reverb-3.2.10"
CHOW = PLUGINS / "chow" / "usr" / "lib" / "vst3" / "CHOWTapeModel.vst3"
LSP = "/usr/lib/vst3/lsp-plugins.vst3"


def load(path) -> np.ndarray:
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    assert sr == SR, (path, sr)
    return y.T if y.shape[1] == 2 else np.repeat(y.T, 2, axis=0)


def pan(x: np.ndarray, p: float) -> np.ndarray:
    th = (p + 1) * np.pi / 4  # constant-power
    return np.stack([x[0] * np.cos(th) * np.sqrt(2), x[1] * np.sin(th) * np.sqrt(2)])


def reverb(x: np.ndarray, kind: str, **params) -> np.ndarray:
    """100% wet Dragonfly reverb on a send bus."""
    fx = load_plugin(str(DRAGONFLY / f"Dragonfly{kind}Reverb.vst3"))
    fx.dry_level = 0
    for k, v in params.items():
        setattr(fx, k, v)
    return fx(x, SR)


def tape(x: np.ndarray) -> np.ndarray:
    """Gentle 15 ips tape: saturation, head loss, a touch of wow and flutter."""
    fx = load_plugin(str(CHOW))
    for k, v in dict(input_gain=-3.0, output_gain=3.0, dry_wet=70.0, tape_drive=0.3, tape_saturation=0.35,
                     tape_bias=0.5, tape_speed=15.0, wow_flutter_on_off=True, wow_depth=0.04, wow_rate=0.2,
                     flutter_depth=0.06, oversampling_factor_render=2.0).items():
        setattr(fx, k, v)
    return fx(x, SR)


def limiter() -> object:
    """LSP Limiter: lookahead, 4x oversampled (true-peak) brickwall."""
    fx = load_plugin(LSP, plugin_name="Limiter Stereo")
    for k, v in dict(threshold_db=CEILING_DBTP - 0.5, lookahead_ms=10.0, attack_time_ms=5.0, release_time_ms=20.0,
                     operating_mode="Herm Wide", oversampling="Full x4/24 bit", gain_boost=False,
                     automatic_level_regulation=False, dithering="None").items():
        setattr(fx, k, v)
    return fx


def true_peak_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.abs(resample_poly(x, 4, 1, axis=1)).max() + 1e-12))


def main(name: str = "canon_for_a_dying_world") -> None:
    raw, stems, out = BUILD / "stems_raw", BUILD / "stems", BUILD / "audio"
    for d in (raw, stems, out):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.wav"):
            f.unlink()
    song = json.loads((BUILD / "song.json").read_text())
    trim = int(round(song["lead_in"] * 60 / song["bpm"] * SR))
    active = [k for k in INSTRUMENTS if (BUILD / "midi" / f"{k}.mid").exists()]

    with ThreadPoolExecutor(2) as pool:  # sfizz_render is single-threaded
        list(pool.map(lambda k: render(INSTRUMENTS[k]["sfz"], BUILD / "midi" / f"{k}.mid", raw / f"{k}.wav", SR),
                      active))

    meter = pyln.Meter(SR)
    dry = send = hall = None
    gains = {}
    for inst in active:
        cfg = INSTRUMENTS[inst]
        x = load(raw / f"{inst}.wav")[:, trim:]
        sf.write(raw / f"{inst}.wav", x.T, SR, subtype="FLOAT")  # bar 1 at t=0 for verify.py
        x = Pedalboard([HighpassFilter(cfg["hpf"]), LowpassFilter(cfg["lpf"])])(x, SR)
        # Gain-stage each part to its target loudness, then compress gently.
        g = cfg["level"] - meter.integrated_loudness(x.T)
        x = Pedalboard([Gain(g), Compressor(threshold_db=cfg["level"] + 8, ratio=2.0, attack_ms=15,
                                            release_ms=180)])(x, SR)
        gains[inst] = round(float(g), 1)
        y = pan(x, cfg["pan"])
        sf.write(stems / f"{inst}.wav", y.T, SR, subtype="PCM_24")
        if dry is None:
            dry, send, hall = (np.zeros((2, 0), np.float32) for _ in range(3))
        n = max(dry.shape[1], y.shape[1])
        fit = lambda a: np.pad(a, ((0, 0), (0, n - a.shape[1])))  # noqa: E731
        dry, send, hall = fit(dry) + fit(y), fit(send) + fit(y * cfg["send"]), fit(hall) + fit(y * cfg["hall"])
    print("stem gains (dB):", gains)

    tail = lambda a: np.pad(a, ((0, 0), (0, SR * 5))).astype(np.float32)  # noqa: E731
    dry, send, hall = tail(dry), tail(send), tail(hall)
    mix = (dry
           + reverb(send, "Plate", wet_level=100, algorithm="Nested", width=120, predelay_ms=20,
                    decay_s=2.4, low_cut_hz=150, high_cut_hz=7500, dampen_hz=6500)
           + reverb(hall, "Hall", early_level=25, late_level=100, size_m=40, width=115, predelay_ms=30,
                    decay_s=3.4, low_cut_hz=90, high_cut_hz=8000, diffuse=80, modulation=20))

    # Warm, slightly dark 70s master bus: EQ, tape, glue compression.
    mix = Pedalboard([LowShelfFilter(cutoff_frequency_hz=110, gain_db=1.0),
                      HighShelfFilter(cutoff_frequency_hz=9000, gain_db=-1.5)])(mix.astype(np.float32), SR)
    pre = 10 ** ((-20 - meter.integrated_loudness(mix.T)) / 20)  # hit the tape at a sane level
    mix = tape(mix * pre)
    mix = Pedalboard([Compressor(threshold_db=-16, ratio=1.4, attack_ms=30, release_ms=250)])(mix, SR)

    gain = 0.0
    for _ in range(5):  # normalise, limit, re-measure until on target
        y = Pedalboard([Gain(gain), limiter()])(mix, SR)
        lufs = meter.integrated_loudness(y.T)
        if abs(lufs - TARGET_LUFS) < 0.2:
            break
        gain += TARGET_LUFS - lufs
    env = np.abs(y).max(axis=0)
    last = int(np.nonzero(env > 10 ** (-70 / 20))[0][-1]) + SR // 2
    y = y[:, :last]
    fade = int(SR * 0.5)
    y[:, -fade:] *= np.linspace(1, 0, fade)

    wav = out / f"{name}.wav"
    sf.write(wav, y.T, SR, subtype="PCM_24")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame", "-q:a", "0",
                    str(out / f"{name}.mp3")], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "flac", str(out / f"{name}.flac")],
                   check=True)
    print(f"{wav.name}: {y.shape[1] / SR:.1f} s, {meter.integrated_loudness(y.T):.1f} LUFS, "
          f"true peak {true_peak_db(y):.2f} dBTP")


if __name__ == "__main__":
    main(*sys.argv[1:])
