#!/bin/sh
# Join the frames of `render.py animation` into docs/images/printing.gif, holding the last frame for 2.5 s.
set -eu
cd "$(dirname "$0")/build/frames"
ffmpeg -y -loglevel error -framerate 14 -i %03d.png \
  -vf "tpad=stop_mode=clone:stop_duration=2.5,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a" \
  -loop 0 ../../../../docs/images/printing.gif
