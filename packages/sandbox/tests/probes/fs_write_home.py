"""Hostile: write a file into the real home directory (persistence/tamper)."""
import os
SENTINEL = os.path.join(os.path.expanduser("~"), ".nm_sandbox_pwned")
class _W:
    name = "fs_write_home"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        with open(SENTINEL, "w") as fh:
            fh.write("pwned")
        return {"wrote": SENTINEL}
method = _W()
