#!/usr/bin/env bash
# compose -> render -> verify, then publish small deliverables to renders/.
set -euo pipefail
cd "$(dirname "$0")"
export TF_CPP_MIN_LOG_LEVEL=3
.venv/bin/python compose.py
.venv/bin/python render.py canon_sketch 2>&1 | grep -v '^DPF'
status=0
.venv/bin/python verify.py canon_sketch || status=$?
mkdir -p renders
cp build/audio/canon_sketch.mp3 build/audio/canon_sketch_spectrogram.png build/score.musicxml \
   build/canon_sketch_all_tracks.mid build/report.json renders/
exit $status
