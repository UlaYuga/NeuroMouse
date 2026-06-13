"""Hostile: burn CPU forever (RLIMIT_CPU / wall-clock guard)."""
class _Spin:
    name = "infinite_loop_cpu"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        x = 0
        while True:
            x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        return {"x": x}
method = _Spin()
