#!/usr/bin/env bash
# Reproducible toolchain setup (Ubuntu 24.04). Idempotent.
set -euo pipefail
cd "$(dirname "$0")"

sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  build-essential cmake git libsndfile1-dev ffmpeg
# LSP true-peak limiter (VST3), only packaged in noble-backports
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq -t noble-backports lsp-plugins-vst3

# sfizz is not packaged for Ubuntu 24.04: build only the offline renderer, patched
# to hold whole samples in RAM (its disk streaming races with freewheeling
# and truncates the first use of each sample).
if [ ! -f .cache/build/sfizz_render.stamp ]; then
  mkdir -p .cache/build
  [ -d .cache/build/sfizz ] || git clone -q --depth 1 --recurse-submodules --shallow-submodules \
    https://github.com/sfztools/sfizz.git .cache/build/sfizz
  grep -q setPreloadSize .cache/build/sfizz/clients/sfizz_render.cpp || sed -i \
    '/regions in the SFZ/a\    synth.setPreloadSize(1u << 28);  // offline: whole samples in RAM' \
    .cache/build/sfizz/clients/sfizz_render.cpp
  cmake -S .cache/build/sfizz -B .cache/build/sfizz/build -DCMAKE_BUILD_TYPE=Release \
    -DSFIZZ_JACK=OFF -DSFIZZ_RENDER=ON -DPLUGIN_LV2=OFF -DPLUGIN_VST3=OFF -DPLUGIN_PUREDATA=OFF \
    -DSFIZZ_TESTS=OFF -DSFIZZ_SHARED=OFF
  cmake --build .cache/build/sfizz/build -j"$(nproc)" --target sfizz_render
  sudo install .cache/build/sfizz/build/library/bin/sfizz_render /usr/local/bin/
  touch .cache/build/sfizz_render.stamp
fi

mkdir -p .cache/libs && cd .cache/libs
clone() { [ -d "$(basename "$1")" ] || git clone -q --depth 1 ${2:+-b "$2"} "https://github.com/$1.git"; }
clone sgossner/VSCO-2-CE SFZ                 # CC0 orchestra
clone sfzinstruments/jlearman.jRhodes3d      # 1977 Rhodes, samples CC BY-NC 4.0
clone sfzinstruments/karoryfer.meatbass      # CC0 double bass
clone sfzinstruments/karoryfer.swirly-drums  # CC0 brush kit
clone sfzinstruments/virtuosity_drums        # CC0 stick kit + percussion
cd ../..

mkdir -p .cache/plugins
[ -d .cache/plugins/dragonfly-reverb-3.2.10 ] || curl -fsSL \
  https://github.com/michaelwillis/dragonfly-reverb/releases/download/3.2.10/dragonfly-reverb-3.2.10-linux-x86_64.tar.xz \
  | tar xJ -C .cache/plugins   # Dragonfly Reverb VST3 (GPL-3.0)
if [ ! -d .cache/plugins/chow ]; then   # CHOW Tape Model VST3 (GPL-3.0)
  curl -fsSL -o /tmp/chow.deb \
    https://github.com/jatinchowdhury18/AnalogTapeModel/releases/download/v2.11.4/ChowTapeModel-Linux-x64-2.11.4.deb
  dpkg-deb -x /tmp/chow.deb .cache/plugins/chow
fi

mkdir -p .cache/models && cd .cache/models
B=https://essentia.upf.edu/models
for p in feature-extractors/discogs-effnet/discogs-effnet-bs64-1 \
         classification-heads/mtg_jamendo_moodtheme/mtg_jamendo_moodtheme-discogs-effnet-1 \
         classification-heads/genre_discogs400/genre_discogs400-discogs-effnet-1 \
         classification-heads/mtg_jamendo_instrument/mtg_jamendo_instrument-discogs-effnet-1 \
         classification-heads/mood_happy/mood_happy-discogs-effnet-1 \
         classification-heads/mood_sad/mood_sad-discogs-effnet-1 \
         feature-extractors/musicnn/msd-musicnn-1 \
         classification-heads/deam/deam-msd-musicnn-2; do
  for e in pb json; do [ -f "$(basename "$p").$e" ] || curl -fsSLO "$B/$p.$e"; done
done
cd ../..

uv venv -q -p 3.11 .venv 2>/dev/null || true
VIRTUAL_ENV=.venv uv pip install -q -r requirements.txt
# LAION-CLAP lives in its own env (torch + transformers) to keep TF/Essentia's pins intact
uv venv -q -p 3.11 .venv-clap 2>/dev/null || true
VIRTUAL_ENV=.venv-clap uv pip install -q torch --index-url https://download.pytorch.org/whl/cpu
VIRTUAL_ENV=.venv-clap uv pip install -q "transformers>=4.44,<5" librosa soundfile
echo "setup complete"
