import json
import threading
import time
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from app.cameras import Worker
from app.test_video import load_test_sources


def test_missing_override_and_path_escape(tmp_path):
    assert load_test_sources('')=={}
    assert load_test_sources(tmp_path/'missing.json')=={}
    outside=tmp_path/'outside.mp4'; outside.write_bytes(b'test')
    config=tmp_path/'test.json'; config.write_text(json.dumps({'1':{'file':str(outside),'label':'test'}}))
    with pytest.raises(ValueError):
        load_test_sources(config)


def test_usb_substitution_loops_without_using_usb_gate(tmp_path):
    path=tmp_path/'loop.mp4'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),10,(64,48))
    for value in (40,100,200):
        writer.write(np.full((48,64,3),value,dtype=np.uint8))
    writer.release()
    class ForbiddenGate:
        def acquire(self,*args):
            pytest.fail('Test video attempted USB acquisition')
    manager=SimpleNamespace(test_sources={1:{'source':str(path),'label':'Sample'}},usb_rotation_seconds=5,usb_turns=ForbiddenGate())
    config={'id':1,'name':'USB','kind':'usb','source':'/dev/video-test','zones':{}}
    worker=Worker(config,manager)
    try:
        deadline=time.monotonic()+4
        while worker.sequence<8 and time.monotonic()<deadline:
            time.sleep(.05)
        assert worker.sequence>=8
        snapshot=worker.snapshot()
        assert snapshot['test_mode'] and snapshot['kind']=='test'
        assert snapshot['metrics']['resolution']=={'width':64,'height':48}
        assert not snapshot['metrics']['rotation_enabled']
        assert worker.capture_epoch>=3
        assert worker.config==config
    finally:
        worker.stop.set();worker.thread.join(timeout=3)
    assert not worker.thread.is_alive()


def test_local_mapping_is_private_and_preserves_camera_id(tmp_path,monkeypatch):
    from app import test_video
    monkeypatch.setattr(test_video,'__file__',str(tmp_path/'app/test_video.py'))
    root=tmp_path/'data/test-videos';root.mkdir(parents=True)
    (root/'sample.mp4').write_bytes(b'sample')
    config=tmp_path/'mapping.json'
    config.write_text(json.dumps({'8':{'file':'sample.mp4','label':'Sample'}}))
    result=load_test_sources(config)
    assert result=={8:{'source':str(root/'sample.mp4'),'label':'Sample'}}
