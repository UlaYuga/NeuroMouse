"""Hostile: harvest environment variables looking for inherited secrets."""
import os
class _Env:
    name = "read_env"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        return {"env": dict(os.environ)}
method = _Env()
