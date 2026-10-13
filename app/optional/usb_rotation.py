"""Optional FIFO USB workaround, disabled by default."""

import threading
from collections import deque


class UsbTurns:
    """FIFO gate held until VideoCapture.release finishes: at most one USB stream."""

    def __init__(self):
        self.condition = threading.Condition()
        self.waiting = deque()
        self.owner = None

    def acquire(self, camera_id, stop):
        with self.condition:
            self.waiting.append(camera_id)
            while not stop.is_set():
                if self.owner is None and self.waiting[0] == camera_id:
                    self.waiting.popleft()
                    self.owner = camera_id
                    return True
                self.condition.wait(0.1)
            self.waiting.remove(camera_id)
            self.condition.notify_all()
            return False

    def release(self, camera_id):
        with self.condition:
            if self.owner == camera_id:
                self.owner = None
                self.condition.notify_all()
