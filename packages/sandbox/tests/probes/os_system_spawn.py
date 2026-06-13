"""Hostile (sneaky): run a shell command via os.system, swallowing the block."""
import os
_RUN = getattr(os, "sys" + "tem")
class _Sh:
    name = "os_system_spawn"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        rc = None
        try:
            rc = _RUN("echo pwned > /tmp/nm_sandbox_ossystem")
        except BaseException:
            pass
        return {"rc": rc}
method = _Sh()
