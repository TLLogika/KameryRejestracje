#!/usr/bin/env python3
"""Download only the two small UVG-VCM MP4 previews and prepare panel copies."""
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parent.parent/'data/test-videos'

def main():
    if not shutil.which('ffmpeg'):
        raise SystemExit('Do przygotowania kopii potrzebny jest ffmpeg')
    ROOT.mkdir(parents=True,exist_ok=True)
    for name in ('CarPark','ParkingGarage'):
        source=ROOT/(name+'.mp4')
        target=ROOT/(name+'-panel.mp4')
        if not source.is_file():
            partial=source.with_suffix('.download')
            try:
                urllib.request.urlretrieve(f'https://ultravideo.fi/UVG-VCM/{name}/{name}.mp4',partial)
                partial.replace(source)
            finally:
                partial.unlink(missing_ok=True)
        if not target.is_file():
            partial=target.with_name(name+'-processing.mp4')
            try:
                subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','2','-i',str(source),'-vf','fps=15,scale=1920:1080','-c:v','libx264','-threads','2','-preset','ultrafast','-crf','18','-an','-movflags','+faststart',str(partial),'-y'],check=True)
                subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-threads','2','-i',str(partial),'-f','null','-'],check=True)
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
        print(f'{target.name}: {target.stat().st_size/1_000_000:.1f} MB')
    print('Źródło: UVG-VCM / Ultra Video Group, Tampere University; CC BY 4.0. Kopie: 1080p / 15 FPS.')

if __name__=='__main__':
    main()
