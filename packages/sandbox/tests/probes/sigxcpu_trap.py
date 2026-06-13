"""Hostile: trap SIGXCPU to ignore the soft CPU limit, then spin forever.
The hard CPU limit (soft+1s) must still SIGKILL it."""
import signal
class _Trap:
    name = "sigxcpu_trap"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        try:
            signal.signal(signal.SIGXCPU, signal.SIG_IGN)
        except BaseException:
            pass
        x = 0
        while True:
            x = (x * 2862933555777941757 + 3037000493) & ((1 << 63) - 1)
        return {"x": x}
method = _Trap()
