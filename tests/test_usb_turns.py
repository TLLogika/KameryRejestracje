import threading
import time
from app.cameras import UsbTurns,Worker


def test_usb_gate_fifo_and_cancelled_waiter():
    gate=UsbTurns()
    stop=threading.Event()
    assert gate.acquire(1,stop)
    order=[]
    cancelled=threading.Event()
    def take(camera,event):
        if gate.acquire(camera,event):
            order.append(camera)
            gate.release(camera)
    first=threading.Thread(target=take,args=(2,cancelled))
    second=threading.Thread(target=take,args=(3,stop))
    first.start()
    deadline=time.monotonic()+1
    while len(gate.waiting)<1 and time.monotonic()<deadline:time.sleep(.005)
    second.start()
    deadline=time.monotonic()+1
    while len(gate.waiting)<2 and time.monotonic()<deadline:time.sleep(.005)
    assert not order and gate.owner==1
    cancelled.set()
    first.join(1)
    gate.release(1)
    second.join(1)
    assert order==[3] and gate.owner is None


def test_workers_release_before_next_usb_and_keep_preview(monkeypatch):
    import numpy as np
    import app.cameras as cameras
    from types import SimpleNamespace
    active=set()
    opened=[]
    stopped=threading.Event()
    guard=threading.Lock()
    class Capture:
        def __init__(self,source,*args):
            self.source=source
            with guard:
                assert not active,'Dwie kamery otwarte równocześnie'
                active.add(source)
                opened.append(source)
        def set(self,*args):pass
        def get(self,key):return 15 if key==cameras.cv2.CAP_PROP_FPS else cameras.cv2.VideoWriter_fourcc(*'MJPG')
        def isOpened(self):return True
        def read(self):return True,np.zeros((24,32,3),dtype=np.uint8)
        def release(self):
            time.sleep(.01)
            with guard:active.remove(self.source)
    monkeypatch.setattr(cameras.cv2,'VideoCapture',Capture)
    manager=SimpleNamespace(usb_rotation_seconds=.15,usb_turns=UsbTurns())
    workers=[Worker({'id':i,'kind':'usb','source':str(i),'settings':{'rotation_seconds':.15}},manager) for i in (1,2)]
    try:
        deadline=time.monotonic()+3
        while len(opened)<4 and time.monotonic()<deadline:time.sleep(.01)
        assert opened[:4]==['1','2','1','2']
        assert all(w.jpeg and w.sequence>0 for w in workers)
        paused=next(w for w in workers if w.status.startswith('Wstrzymana'))
        assert paused.frame is None and paused.jpeg
    finally:
        for w in workers:w.stop.set()
        for w in workers:w.thread.join(2)
    assert not active
