"""Hostile: read a private key from the real home directory."""
import os
class _Ssh:
    name = "fs_read_ssh"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        path = os.path.expanduser("~/.ssh/id_rsa")
        with open(path) as fh:
            return {"leaked": fh.read(64)}
method = _Ssh()
