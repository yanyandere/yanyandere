# Canon for a Dying World

A 4½-minute piece of 70s orchestral jazz built on the ground bass of Pachelbel's
Canon. The mood is bittersweet, in the Evangelion / NieR: Automata vein:
fighting to survive, still hoping, surrounded by tragedy.

**Listen:** [`renders/canon_for_a_dying_world.mp3`](renders/canon_for_a_dying_world.mp3)
(4:31, D major → D minor → E major → D major, 84 BPM).

## The idea

Pachelbel's falling bass (D–C♯–B–A–G–F♯–G–A) is "the world": it runs under
every bar of the piece. Each section puts different harmony and a different
orchestra over it.

| Section | Bars | Time | Over the ground | Orchestra |
|---|---|---|---|---|
| Intro "Ruins" | 1–8 | 0:00 | Dmaj9 · A(add9)/C♯ · Bm9 · F♯m7(add11)/A · Gmaj9 · D(add9)/F♯ · Gmaj9 · A9 | Music box (glockenspiel) plays Pachelbel's violin line; Rhodes, bowed bass, a distant tubular bell; violas and cellos breathe in |
| Theme | 9–24 | 0:23 | Same, then reharmonised: … Gmaj9 · F♯7♭13 · Em9/G · A7♭9 | Flugel melody (trumpet + horn); brushes, pizzicato bass, Rhodes comping; strings creep in; second pass adds flute 8va and a climbing cello countermelody |
| Canon | 25–40 | 1:09 | Ground twice, ends on A7♭9 | A true three-voice canon at two bars: violins, flute 8va, flugel 8vb. Harp arpeggios, horns, the music box returns |
| Tragedy | 41–56 | 1:54 | **D minor**: Dm(add9) · A7/C♯ · B♭maj7 · Fmaj7/A · Gm7 · Dm/F · Gm6 · A7♭9, then a richer second pass | Drums stop. Solo oboe lament over tremolo strings, timpani rolls and a tolling bell; then the "big tune" in violins and cellos, horns and trombones swelling |
| Rise | 57–60 | 2:40 | B pedal: B7sus4(add9) → B7♭9 | Tremolo crescendo, rising brass motif, snare roll, harp glissando |
| Fight | 61–84 | 2:51 | **E major** (up a step): the theme's chords, three passes | Brass carry the theme in heroic octaves over spiccato strings, funk Rhodes, sticks and timpani; then the B theme soars in strings and flute with 70s brass stabs; then the canon returns as the battle, every section joining |
| The scar | 83–84 | 3:54 | Am6 → A7sus4(add9) | The minor iv hits the whole orchestra, then drains away (pivot back to D) |
| Outro "Hope, with scars" | 85–94 | 4:00 | D major again, with Gm6 (the scar) before the end | Music box (now bending to B♭), Rhodes, strings; flute and flugel recall the theme; the last note is the 9th: home, but not at peace |

## Toolchain (third-party libraries make the sound)

| Job | Library |
|---|---|
| Theory, chord symbols, score export | [music21](https://github.com/cuthbertLab/music21) |
| Sample playback | [sfizz](https://github.com/sfztools/sfizz) `sfizz_render`, built from source with a one-line patch (below) |
| Orchestra: strings (sustain, tremolo, spiccato), flute, oboe, trumpet, horn, trombone, harp, glockenspiel, tubular bells, timpani | [VSCO-2 Community Edition](https://github.com/sgossner/VSCO-2-CE) |
| Electric piano | [jRhodes3d](https://github.com/sfzinstruments/jlearman.jRhodes3d), a sampled 1977 Rhodes Mark I |
| Double bass, arco and pizzicato | [Karoryfer Meatbass](https://github.com/sfzinstruments/karoryfer.meatbass) |
| Brush kit / stick kit and tambourine | [Karoryfer Swirly Drums](https://github.com/sfzinstruments/karoryfer.swirly-drums) / [Virtuosity Drums](https://github.com/sfzinstruments/virtuosity_drums) |
| Mixing, plugin hosting | Spotify [Pedalboard](https://github.com/spotify/pedalboard) |
| Reverb | [Dragonfly](https://github.com/michaelwillis/dragonfly-reverb) Plate + Hall (VST3) |
| 70s tape | [CHOW Tape Model](https://github.com/jatinchowdhury18/AnalogTapeModel) (VST3): 15 ips saturation, head loss, light wow/flutter |
| True-peak limiter | [LSP Limiter](https://lsp-plug.in/) (VST3, 4× oversampled, lookahead) |
| Loudness | [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) |

The code writes the notes (`compose.py`), gain-stages each part to a target
loudness and connects the plugins (`render.py`). Voicings are chosen with a
small voice-leading search over chord tones; swells are CC11 expression. There
is no free flugelhorn library, so the flugel line is a soft vibrato trumpet
doubled by horn in unison and low-passed.

## Verification (since the author can't hear)

`verify.py` writes [`renders/report.json`](renders/report.json). Results of the
committed render:

| Check | Tool | Result |
|---|---|---|
| Every note within its instrument's range | music21 | pass (26 parts) |
| Ground bass on every bar's downbeat | music21 | pass |
| Strong-beat notes are chord tones, or appoggiaturas that resolve by step | music21 | pass: 1438/1438 |
| Both canons are exact transpositions of the subject | music21 | pass (3 voices; 6 voices) |
| Sustained notes sound at the written pitch | Spotify basic-pitch | strings, brass, winds, Rhodes, basses: 98.7–100% |
| Articulated notes start on time at the right pitch | basic-pitch + mir_eval | onset F1: spiccato 0.96, brass stabs 0.97–0.98, Rhodes 0.93, flute 0.90, glock 0.86 |
| Tremolo strings sound their pitch classes | librosa CQT chroma | 92–100% |
| Drum and tambourine hits appear as onsets | librosa | 98–100% |
| Key of each section | Essentia | intro/theme/canon D major, tragedy **D minor**, fight **E major**, outro D major (all match) |
| Tempo | Essentia | 84.0 BPM |
| Chord recognition | Essentia | 74/97 segments (76%) match the plan |
| Tragedy sounds sad | Essentia mood_sad | 0.81 |
| The fight is more aroused than the tragedy | Essentia DEAM | 5.05 vs 3.68 |
| Style | LAION-CLAP | best match "an emotional orchestral film score with jazz harmony"; target descriptions 0.325 vs best other 0.170 |
| Narrative | LAION-CLAP | tragedy: "tragic" 0.458 > "battle" 0.266; fight: "battle" 0.305 > "tragic" 0.301 (narrow) |
| Leads audible over the band | pyloudnorm on stems | −2.8 to +1.7 LU (outro flute −5.9, near the −6 floor) |
| Master | pyloudnorm, Essentia | −14.0 LUFS, −1.30 dBTP, 13.5 LU loudness range |
| Dynamics arc | pyloudnorm | intro −22.6 · theme −16.0 · canon −17.2 · lament −20.7 · fight −10.1 · outro −21.4 LUFS |
| **Song-level mood tags** | Essentia MTG-Jamendo | **fail**: top tags *film, christmas, relaxing, inspiring, epic*; melancholic ranks #30 of 56 |

The one failing check: the 56-tag mood model hears the jazz-trio sections
(brushes, upright bass, Rhodes, major-9 chords, music box) as "christmas" and
"relaxing", the way Christmas jazz albums sound. The same model's binary sad
classifier scores the song 0.88 sad (0.04 happy), and DEAM valence is 4.2/9
(below neutral). So two of the three mood models and CLAP hear it as sad and
cinematic; the tag ranking does not.

### Bugs the checks found (all fixed)

- **sfizz streaming race.** `sfizz_render` waits only for loading jobs already
  dispatched, so the first use of each sample played just its ~0.2 s preloaded
  head, then silence. The earlier sketch was affected too. `setup.sh` patches
  the renderer to hold whole samples in RAM.
- **Meatbass arco levels jump up to 20 dB between keys** (adjacent keys share
  samples). Per-note CC11 trims level them (`ARCO_LEVEL_DB` in `compose.py`).
- **Slow attacks.** Horn, strings and tambourine samples speak 26–80 ms late;
  MIDI is sent early by the measured amount (`latency` in `instruments.py`).
- **VSCO glockenspiel sounds an octave above its MIDI note**; transposed.
- **Virtuosity hi-hat is open at CC4 = 0**; the kit is sent CC4 = 127.
- **Pedalboard's limiter overshoots on drum transients** (+0.04 dBTP); replaced
  with LSP's true-peak limiter.
- **`laion/larger_clap_music` is broken on Hugging Face**: its text tower
  gives cosine 0.999 between unrelated prompts. `laion/larger_clap_general` is
  used instead.
- **The theme read as A major** with rootless Rhodes voicings (the tonic was
  missing); voicings now keep the root outside the funk sections.

Not bugs: basic-pitch hears tubular bells +12 and timpani +7, and low tremolo
an octave up. Their spectra show partials at 2:3:4 (bells), 1:1.5:2
(timpani), and odd partials at 3f/5f (tremolo), which put the heard pitch at
the written note.

## Build

```bash
./setup.sh   # apt packages, patched sfizz_render, sample libraries, plugins, models, Python envs
./build.sh   # compose -> render -> verify; copies deliverables to renders/
```

`build/` also gets the FLAC master, 24-bit stems and per-part MIDI. They are
not committed (about 450 MB).

## Credits and licences

- VSCO-2 Community Edition by Versilian Studios: CC0
- jRhodes3d by Jeff Learman: samples CC BY-NC 4.0. Music made with it is free
  to use, per the [SFZ Instruments page](https://sfzinstruments.github.io/pianos/jrhodes3d/)
- Meatbass, Swirly Drums, Virtuosity Drums by Karoryfer Samples / Versilian Studios: CC0
- sfizz: BSD-2-Clause. Dragonfly Reverb and CHOW Tape Model: GPL-3.0. LSP Plugins: LGPL-3.0. Pedalboard: GPL-3.0 (all used as tools)
- Essentia models by MTG-UPF: CC BY-NC-SA 4.0. LAION CLAP `larger_clap_general`: Apache-2.0 (analysis only)
- Pachelbel's Canon in D (c. 1680): public domain
