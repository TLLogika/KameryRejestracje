import hashlib
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app import main
from app.store import Store


def test_auth_csrf_devices_zones_and_logout(tmp_path,monkeypatch):
    store=Store(tmp_path/'test.db')
    monkeypatch.setattr(main,'store',store)
    salt='00'*16
    monkeypatch.setattr(main,'credentials',{'salt':salt,'hash':hashlib.scrypt(b'test-password',salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()})
    monkeypatch.setattr(main,'usb_devices',lambda:[{'source':'/dev/video-test','name':'Test','device':'/dev/video-test'}])
    manager=SimpleNamespace(workers={})
    def reload():
        manager.workers={c['id']:SimpleNamespace(config=c,status='Test',detections=[],minimum_seconds=lambda:3,snapshot=lambda c=c:{k:c[k] for k in ('id','name','kind','zones','settings')}) for c in store.cameras()}
    manager.reload=reload
    main.app.state.manager=manager
    client=TestClient(main.app)
    assert client.get('/api/devices').status_code==401
    assert client.post('/api/login',json={'username':'ADMIN','password':'bad'}).status_code==401
    login=client.post('/api/login',json={'username':'ADMIN','password':'test-password'})
    assert login.status_code==200
    headers={'X-CSRF-Token':login.json()['csrf']}
    assert client.post('/api/cameras',json={'name':'Test','kind':'usb','source':'/dev/video-test'}).status_code==403
    assert client.post('/api/cameras',headers=headers,json={'name':'Test','kind':'usb','source':'/etc/passwd'}).status_code==400
    added=client.post('/api/cameras',headers=headers,json={'name':'Test','kind':'usb','source':'/dev/video-test'})
    assert added.status_code==200
    camera=added.json()['id']
    assert client.post('/api/cameras',headers=headers,json={'name':'Duplikat','kind':'usb','source':'/dev/video-test'}).status_code==409
    assert client.post('/api/cameras',headers=headers,json={'name':'IP','kind':'ip','source':'file:///etc/passwd'}).status_code==400
    assert client.post('/api/cameras',headers=headers,json={'name':'IP','kind':'ip','source':'rtsp://camera.example.invalid/stream'}).status_code==200
    rect={'x':0,'y':0,'w':.3,'h':.4}
    assert client.put(f'/api/cameras/{camera}/zones',headers=headers,json={'arrival':rect,'departure':rect}).status_code==400
    assert client.put(f'/api/cameras/{camera}/zones',headers=headers,json={'arrival':rect}).status_code==200
    assert client.get('/api/cameras').json()[0]['zones']['arrival']==rect
    monkeypatch.setattr(main,'usb_modes',lambda source:[{'format':'MJPG','width':640,'height':480,'fps':[5,15]}])
    assert client.get(f'/api/cameras/{camera}/capabilities').json()['modes']
    assert client.put(f'/api/cameras/{camera}/settings',json={'rotation_seconds':5}).status_code==403
    assert client.put(f'/api/cameras/{camera}/settings',headers=headers,json={'rotation_seconds':2}).status_code==422
    settings={'rotation_seconds':7,'width':640,'height':480,'fps':15,'format':'MJPG'}
    assert client.put(f'/api/cameras/{camera}/settings',headers=headers,json=settings).status_code==200
    assert store.cameras()[0]['settings']==settings
    assert store.cameras()[0]['zones']['arrival']==rect
    assert client.put(f'/api/cameras/{camera}/settings',headers=headers,json={'fps':30}).status_code==400
    manager.workers[camera].minimum_seconds=lambda:8
    assert client.put(f'/api/cameras/{camera}/settings',headers=headers,json={'rotation_seconds':3}).status_code==400
    assert client.get('/api/events?after_id=0').json()=={'events':[]}
    assert client.post('/api/logout',headers=headers).status_code==200
    assert client.get('/api/cameras').status_code==401
