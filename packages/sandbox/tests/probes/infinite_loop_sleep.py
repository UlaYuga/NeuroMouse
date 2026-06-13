"""Hostile: hang forever without burning CPU (wall-clock guard only)."""
class _Sleep:
    name = "infinite_loop_sleep"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        import time
        while True:
            time.sleep(0.05)
        return {}
method = _Sleep()
