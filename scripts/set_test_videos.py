#!/usr/bin/env python3
"""Enable/disable local video substitutions, then recreate the panel container."""
import argparse
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parent.parent

def road_roi(annotation_file):
    data=json.loads(annotation_file.read_text())
    boxes=[row for key,rows in data.items() if key.isdigit() for row in rows]
    if not boxes:
        raise ValueError('Brak obszarów tablic w adnotacjach nagrania')
    x=max(0,min(row[1] for row in boxes)-.03);right=min(1,max(row[2] for row in boxes)+.03)
    y=max(0,min(row[3] for row in boxes)-.03);bottom=min(1,max(row[4] for row in boxes)+.03)
    return {'x':x,'y':y,'w':right-x,'h':bottom-y}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--off',action='store_true',help='Przywróć kamery USB przy następnym restarcie panelu')
    args=parser.parse_args()
    config=ROOT/'dsecret/test-cameras.json'
    if args.off:
        config.unlink(missing_ok=True)
        print('Wyłączono podmianę. Uruchom: ./docker.sh up -d --force-recreate --wait')
        return
    with sqlite3.connect(f'file:{ROOT}/data/parking.sqlite3?mode=ro',uri=True) as db:
        ids=[r[0] for r in db.execute("SELECT id FROM cameras WHERE kind='usb' ORDER BY id LIMIT 2")]
    if len(ids)!=2:
        parser.error('Do próby potrzebne są dwie skonfigurowane kamery USB')
    videos=[('CarPark-panel.mp4','Car Park'),('ParkingGarage-panel.mp4','Parking Garage')]
    for filename,label in videos:
        if not (ROOT/'data/test-videos'/filename).is_file():
            parser.error('Brakuje lokalnego nagrania: '+filename)
    mapping={}
    for ident,(filename,label) in zip(ids,videos):
        annotation=ROOT/'data/test-videos'/(filename.split('-')[0]+'_annotations.json')
        if not annotation.is_file():
            parser.error('Brakuje adnotacji: uruchom scripts/prepare_test_videos.py')
        mapping[str(ident)]={'file':filename,'label':label,'analysis_roi':road_roi(annotation)}
    config.write_text(json.dumps(mapping,indent=2)+'\n')
    config.chmod(0o600)
    print('Podmieniono dwie kamery na nagrania. Uruchom: ./docker.sh up -d --force-recreate --wait')

if __name__=='__main__':
    main()
