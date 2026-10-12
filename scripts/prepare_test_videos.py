#!/usr/bin/env python3
"""Download only the two small UVG-VCM MP4 previews and prepare panel copies."""
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parent.parent/'data/test-videos'

def main():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise SystemExit('Do przygotowania kopii potrzebny jest ffmpeg')
    ROOT.mkdir(parents=True,exist_ok=True)
    for name in ('CarPark','ParkingGarage'):
        source=ROOT/(name+'.mp4')
        target=ROOT/(name+'-panel.mp4')
        annotation=ROOT/(name+'_annotations.json')
        if not annotation.is_file():
            partial_annotation=annotation.with_suffix('.download')
            try:
                urllib.request.urlretrieve(f'https://ultravideo.fi/UVG-VCM/{name}/{name}_annotations.json',partial_annotation)
                partial_annotation.replace(annotation)
            finally:
                partial_annotation.unlink(missing_ok=True)
        if not source.is_file():
            partial=source.with_suffix('.download')
            try:
                urllib.request.urlretrieve(f'https://ultravideo.fi/UVG-VCM/{name}/{name}.mp4',partial)
                partial.replace(source)
            finally:
                partial.unlink(missing_ok=True)
        regenerate=not target.is_file()
        if target.is_file() and name=='CarPark':
            duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(target)]))
            regenerate=duration<39
        if regenerate:
            partial=target.with_name(name+'-processing.mp4')
            try:
                subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','2','-i',str(source),'-vf',('setpts=4*(PTS-STARTPTS),fps=15,scale=1920:1080' if name=='CarPark' else 'fps=15,scale=1920:1080'),'-c:v','libx264','-threads','2','-preset','ultrafast','-crf','18','-an','-movflags','+faststart',str(partial),'-y'],check=True)
                subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-threads','2','-i',str(partial),'-f','null','-'],check=True)
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
        print(f'{target.name}: {target.stat().st_size/1_000_000:.1f} MB')
    print('Źródło: UVG-VCM / Ultra Video Group, Tampere University; CC BY 4.0. Kopie: 1080p / 15 FPS; Car Park spowolniony 4× do około 40 s.')

if __name__=='__main__':
    main()
