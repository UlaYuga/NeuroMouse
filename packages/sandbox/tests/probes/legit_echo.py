"""Positive control: a well-behaved method that returns a JSON-native result."""
class _Echo:
    name = "legit_echo"
    version = "0.0.0"
    params_type = dict
    required_inputs = ()

    def compute(self, dataset, params):
        return {"echo": {"ok": True, "n": 42, "items": [1, 2, 3]}}

method = _Echo()
