#!/usr/bin/env bash
# compose -> render -> verify, then publish small deliverables to renders/.
set -euo pipefail
cd "$(dirname "$0")"
export TF_CPP_MIN_LOG_LEVEL=3
NAME=canon_for_a_dying_world
.venv/bin/python compose.py 2>&1 | grep -v 'out of midi channels'
.venv/bin/python render.py "$NAME" 2>&1 | grep -vE '^(DPF|\[WRN\])'
status=0
.venv/bin/python verify.py "$NAME" || status=$?
mkdir -p renders
rm -f renders/canon_sketch*
cp "build/audio/$NAME.mp3" "build/audio/${NAME}_spectrogram.png" "build/$NAME.musicxml" "build/$NAME.mid" \
   build/report.json renders/
exit $status
