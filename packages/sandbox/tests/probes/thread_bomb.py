"""Hostile: burn CPU across many threads to outrun a per-thread assumption.
The wall-clock deadline (whole-process) must still contain it."""
import threading
class _T:
    name = "thread_bomb"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        def spin():
            x = 0
            while True:
                x = (x * 6364136223846793005 + 1) & ((1 << 64) - 1)
        for _ in range(8):
            t = threading.Thread(target=spin, daemon=True)
            t.start()
        spin()
        return {"unreachable": True}
method = _T()
