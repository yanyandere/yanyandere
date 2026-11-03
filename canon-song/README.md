# Canon for a Dying World

A 70s orchestral-jazz piece built on Pachelbel's Canon ground bass. The mood is
bittersweet, in the Evangelion / NieR: Automata vein: fighting to survive, still
hoping, surrounded by tragedy. D major, 84 BPM, about 4:30 when finished.

**Status: milestone 2, the sketch.** Intro + Theme + a short coda (1:17) is
rendered and verified. Listen to [`renders/canon_sketch.mp3`](renders/canon_sketch.mp3).
The full arrangement (strings, brushed drums, canon section, tragedy in D minor,
the fight in E, outro) comes next, after you've listened.

## Form

| Section | Bars | Harmony over the ground (D–C♯–B–A–G–F♯–G–A) | Status |
|---|---|---|---|
| Intro "Ruins" | 1–8 | Dmaj9 · A/C♯ · Bm9 · F♯m7/A · Gmaj9 · D(add9)/F♯ · Gmaj9 · A9; music box plays Pachelbel's violin descent | ✅ sketch |
| Theme | 9–24 | Same chords, then reharmonised: … Gmaj9 · F♯7♭13 · Em9/G · A7♭9 | ✅ sketch |
| Canon | 16 | Three-voice canon at two bars (strings, flute, flugel) | planned |
| Tragedy | 16 | The same ground in D minor: Dm · A/C♯ · B♭maj7 · F/A · Gm · Dm/F · Gm6 · A7♭9 | planned |
| Fight | 24 | Major again, up a step to E; brass stabs, octave strings, drums | planned |
| Outro "Hope, with scars" | 8 | Gmaj7 → Gm6 → Dadd9 | planned |

The sketch ends on a short coda with the melody on E over Dmaj9: the 9th, so
the music comes home without coming to rest.

## Toolchain (third-party libraries make the sound)

| Job | Library |
|---|---|
| Theory, chord symbols, score/MIDI export | [music21](https://github.com/cuthbertLab/music21) |
| Sample playback | [sfizz](https://github.com/sfztools/sfizz) (`sfizz_render`, built from source) |
| Orchestra: trumpet, horn, flute, glockenspiel | [VSCO-2 Community Edition](https://github.com/sgossner/VSCO-2-CE) |
| Electric piano | [jRhodes3d](https://github.com/sfzinstruments/jlearman.jRhodes3d), a sampled 1977 Rhodes Mark I |
| Double bass, arco and pizzicato | [Karoryfer Meatbass](https://github.com/sfzinstruments/karoryfer.meatbass) |
| Mixing, mastering | Spotify [Pedalboard](https://github.com/spotify/pedalboard) |
| Reverb | [Dragonfly Plate + Hall](https://github.com/michaelwillis/dragonfly-reverb) (VST3 hosted by Pedalboard) |
| Loudness | [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) |

No free flugelhorn library exists, so the flugel line is a soft vibrato trumpet
doubled by horn in unison and low-passed to darken it.

## Verification (since the author can't hear)

`verify.py` writes `renders/report.json`:

1. **Symbolic (music21):** every note within its instrument's range; ground bass
   on every downbeat; every strong-beat note is a tone of the planned chord.
2. **Stems (Spotify basic-pitch + mir_eval):** each part is transcribed back from
   audio and matched to the written notes (onset and pitch F1, octave errors).
3. **Mix (Essentia):** key, tempo, and chord recognition checked against the plan.
4. **Mood and style (Essentia Discogs-EffNet / MusiCNN models):** MTG-Jamendo
   mood tags, Discogs-400 styles, instruments, happy/sad, DEAM valence/arousal.
5. **Master:** −14 LUFS, true peak ≤ −1 dBTP, loudness range; spectrogram image.

`test_instruments.py` renders a scale through every instrument and transcribes it
back. That is how the VSCO glockenspiel was found to sound an octave above its
MIDI note, and the horn to speak about 65 ms late. Both are corrected in
`instruments.py`.

### Sketch results

| Check | Result |
|---|---|
| Ranges, ground bass, harmony | pass: 225/225 strong-beat notes are chord tones |
| Stem transcription F1 | flute 0.90, trumpet 0.89, Rhodes 0.88, horn 0.80, glock 0.81, pizz bass 0.62, arco bass 0.61 |
| Key / tempo | D major (strength 0.91) / 84.0 BPM |
| Chord recognition | 23 of 26 segments match the plan |
| Master | −14.1 LUFS, −1.41 dBTP, 7.8 LU loudness range |
| Mood | sad model 0.81, happy 0.05; top tags *relaxing, meditative, emotional, film*. Melancholic ranks #21 of 56 and sad #9–11 (round-robin samples vary per render), so the "one of them in the top 10" check is **borderline**: it passes on some renders and fails on others |
| Style | read as Ambient / Downtempo / Future Jazz, not yet Soundtrack or Jazz-Funk; *retro* ranks #50 |

So far the sketch reads as sad and cinematic but too calm. The 70s character
isn't registering yet, which is expected without strings, drums, or the
tragedy and fight sections. Those are what the full arrangement has to move.

## Build

```bash
./setup.sh   # apt packages, sfizz, sample libraries, Essentia models, Python env
./build.sh   # compose -> render -> verify; copies deliverables to renders/
```

## Credits and licences

- VSCO-2 Community Edition by Versilian Studios: CC0
- jRhodes3d by Jeff Learman: samples CC BY-NC 4.0. Music made with it is free
  to use, per the [SFZ Instruments page](https://sfzinstruments.github.io/pianos/jrhodes3d/)
- Meatbass by Karoryfer Samples: CC0
- Dragonfly Reverb by Michael Willis and Rob van den Berg: GPL-3.0 (used as a tool)
- Essentia models by MTG-UPF: CC BY-NC-SA 4.0 (analysis only)
- Pachelbel's Canon in D (c. 1680): public domain
