#!/usr/bin/env python3
"""Generate private Docker settings from this host; never print addresses or keys."""
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def write_private(path,content):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as stream:
        stream.write(content)
    path.chmod(0o600)


def main():
    for name in ('data','dsecret','secret','logi'):
        (ROOT/name).mkdir(exist_ok=True)
    (ROOT/'dsecret').chmod(0o700)
    (ROOT/'secret').chmod(0o700)
    key=ROOT/'secret/integration.key'
    if not key.exists():
        fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            stream.write(secrets.token_urlsafe(48)+'\n')
    key.chmod(0o600)
    address=os.environ.get('PANEL_BIND_IP')
    if not address:
        result=subprocess.run(['ip','-j','-4','addr','show','tailscale0'],capture_output=True,text=True)
        interfaces=json.loads(result.stdout) if result.returncode==0 else []
        address=next((a['local'] for i in interfaces for a in i.get('addr_info',[]) if a['family']=='inet'),'127.0.0.1')
    port=int(os.environ.get('PANEL_PORT','10000'))
    if not 1<=port<=65535:
        raise ValueError('Nieprawidłowy port')
    import ipaddress
    ipaddress.IPv4Address(address)
    write_private(ROOT/'dsecret/docker.env',f'APP_UID={os.getuid()}\nAPP_GID={os.getgid()}\nPANEL_BIND_IP={address}\nPANEL_PORT={port}\n')
    # Explicit video devices, no privileged container or complete /dev mount.
    devices=[p for p in sorted(Path('/dev').glob('video*')) if stat.S_ISCHR(p.stat().st_mode)]
    panel={}
    if devices:
        panel['devices']=[f'{p}:{p}:rw' for p in devices]
        panel['group_add']=sorted({str(p.stat().st_gid) for p in devices})
        by_id=Path('/dev/v4l/by-id')
        if by_id.is_dir():
            panel['volumes']=[{'type':'bind','source':str(by_id),'target':str(by_id),'read_only':True}]
    configuration={'services':{'panel':panel}}
    proxy_ca=os.environ.get('CODEX_PROXY_CERT')
    if proxy_ca:
        certificate=Path(proxy_ca)
        if not certificate.is_file():
            raise ValueError('Nie znaleziono skonfigurowanego certyfikatu proxy')
        configuration['secrets']={'proxy_ca':{'file':str(certificate)}}
        panel['build']={'secrets':['proxy_ca']}
        panel.setdefault('volumes',[]).append({'type':'bind','source':str(certificate),'target':'/run/proxy-ca.pem','read_only':True})
        panel['environment']={'SSL_CERT_FILE':'/run/proxy-ca.pem'}
    write_private(ROOT/'dsecret/compose.usb.json',json.dumps(configuration,indent=2)+'\n')
    print(f'Konfiguracja Dockera zapisana prywatnie w dsecret; urządzenia wideo: {len(devices)}.')

if __name__=='__main__':
    main()
