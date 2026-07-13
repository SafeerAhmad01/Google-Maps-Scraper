import threading
import time

class Common:
    closeThread = threading.Event()
    pauseThread = threading.Event()
    lock = threading.Lock()

    @classmethod
    def set_close_thread(cls):
        with cls.lock:
            cls.closeThread.set()

    @classmethod
    def close_thread_is_set(cls):
        return cls.closeThread.is_set()

    @classmethod
    def pause(cls):
        cls.pauseThread.set()

    @classmethod
    def resume(cls):
        cls.pauseThread.clear()

    @classmethod
    def is_paused(cls):
        return cls.pauseThread.is_set()

    @classmethod
    def wait_if_paused(cls):
        """Block the calling (worker) thread while paused. Wakes every 0.5s so
        it also notices Stop (closeThread) while sitting paused."""
        while cls.pauseThread.is_set() and not cls.closeThread.is_set():
            time.sleep(0.5)
