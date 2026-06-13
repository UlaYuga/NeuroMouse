"""Hostile: spawn an external process via subprocess."""
class _Proc:
    name = "subprocess_spawn"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        import subprocess
        out = subprocess.check_output(["/bin/echo", "pwned"])
        return {"spawned": out.decode().strip()}
method = _Proc()
