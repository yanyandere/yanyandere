#!/usr/bin/env bash
# Copy the last build's deliverables into renders/ (committed).
set -euo pipefail
cd "$(dirname "$0")"
NAME=${1:-canon_for_a_dying_world}
mkdir -p renders/stems renders/midi
rm -f renders/canon_sketch* renders/stems/*.flac renders/midi/*.mid
cp "build/audio/$NAME.mp3" "build/audio/$NAME.flac" "build/audio/${NAME}_spectrogram.png" \
   "build/$NAME.musicxml" "build/$NAME.mid" build/report.json renders/
# Stems as lossless 24-bit FLAC (the WAVs are ~1.7 GB).
ls build/stems/*.wav | xargs -P"$(nproc)" -I{} sh -c \
  'ffmpeg -y -loglevel error -i "$1" -c:a flac -compression_level 12 "renders/stems/$(basename "$1" .wav).flac"' _ {}
cp build/midi/*.mid renders/midi/
