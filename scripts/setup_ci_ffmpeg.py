"""Expose the pinned imageio-ffmpeg wheel binary to subsequent GitHub CI steps."""
import os
from pathlib import Path
import imageio_ffmpeg

binary = Path(imageio_ffmpeg.get_ffmpeg_exe())
if not binary.is_file():
    raise SystemExit('The pinned wheel does not contain a usable ffmpeg executable')
directory = Path(os.environ['RUNNER_TEMP'])/'iqscope-media-bin'
directory.mkdir(exist_ok=True)
link = directory/'ffmpeg'
link.unlink(missing_ok=True)
link.symlink_to(binary)
with Path(os.environ['GITHUB_PATH']).open('a') as handle:
    handle.write(str(directory)+'\n')
print('Configured bundled CI ffmpeg')
