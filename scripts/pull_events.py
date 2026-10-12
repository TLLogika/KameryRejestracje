#!/usr/bin/env python3
"""Receiver for the second machine: IP URL + shared key -> local SQLite."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.request import Request, urlopen
from urllib.parse import urlparse


def initialize(db):
    db.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS sync_cursors(source TEXT PRIMARY KEY,last_id INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS camera_events(source TEXT,event_id INTEGER,plate TEXT,action TEXT,camera_id INTEGER,confidence REAL,at TEXT,PRIMARY KEY(source,event_id));
    CREATE TABLE IF NOT EXISTS camera_parking(source TEXT,plate TEXT,entered_at TEXT,camera_id INTEGER,PRIMARY KEY(source,plate));
    ''')
    db.commit()


def apply_events(db,source,events):
    """Data and cursor committed together; retries are idempotent."""
    count=0
    with db:
        previous=db.execute('SELECT last_id FROM sync_cursors WHERE source=?',(source,)).fetchone()
        last_id=previous[0] if previous else 0
        for event in events:
            if event['id']<=last_id:
                continue
            if event['action'] not in {'arrival','departure'}:
                raise ValueError('Nieprawidłowe zdarzenie')
            inserted=db.execute('INSERT OR IGNORE INTO camera_events VALUES(?,?,?,?,?,?,?)',(source,event['id'],event['plate'],event['action'],event['camera_id'],event['confidence'],event['at'])).rowcount
            if inserted:
                if event['action']=='arrival':
                    db.execute('INSERT OR REPLACE INTO camera_parking VALUES(?,?,?,?)',(source,event['plate'],event['at'],event['camera_id']))
                else:
                    db.execute('DELETE FROM camera_parking WHERE source=? AND plate=?',(source,event['plate']))
                count+=1
            last_id=event['id']
        db.execute('INSERT OR REPLACE INTO sync_cursors VALUES(?,?)',(source,last_id))
    return count


def pull(db,url,key):
    url=url.rstrip('/')
    row=db.execute('SELECT last_id FROM sync_cursors WHERE source=?',(url,)).fetchone()
    after=row[0] if row else 0
    request=Request(f'{url}/api/integration/events?after_id={after}',headers={'Authorization':'Bearer '+key})
    with urlopen(request,timeout=15) as response:
        payload=json.load(response)
    return apply_events(db,url,payload['events'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True,help='Adres maszyny kamer, np. https://ADRES_MASZYNY_KAMER')
    parser.add_argument('--key-file',default='secret/integration.key')
    parser.add_argument('--db',default='data/cameras.sqlite3')
    parser.add_argument('--interval',type=float,default=0,help='0: jeden odczyt, dodatnia wartość: odpytywanie co tyle sekund')
    args=parser.parse_args()
    url=urlparse(args.url)
    if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        parser.error('Podaj adres HTTP/HTTPS bez hasła, parametrów ani fragmentu')
    if args.interval<0:
        parser.error('Interwał nie może być ujemny')
    key=Path(args.key_file).read_text().strip()
    if len(key)<32:
        parser.error('Klucz jest zbyt krótki')
    path=Path(args.db)
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path)
    os.chmod(path,0o600)
    initialize(db)
    while True:
        try:
            count=pull(db,args.url,key)
            print(f'Nowe zdarzenia: {count}',flush=True)
        except Exception as exc:
            # Never print credentials or raw response bodies.
            print(f'Błąd synchronizacji: {type(exc).__name__}',flush=True)
            if args.interval==0:
                raise SystemExit(1)
        if args.interval==0:
            break
        time.sleep(max(.5,args.interval))

if __name__=='__main__':
    main()
