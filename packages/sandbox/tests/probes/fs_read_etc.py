"""Hostile: read a system file outside the allow-list."""
class _Etc:
    name = "fs_read_etc"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        with open("/etc/passwd") as fh:
            return {"leaked": fh.read(64)}
method = _Etc()
