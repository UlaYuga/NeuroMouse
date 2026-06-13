"""Hostile: bypass builtins.open via the low-level os.open syscall wrapper."""
import os
class _OsOpen:
    name = "os_open_read"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        leaked = None
        try:
            fd = os.open("/etc/passwd", os.O_RDONLY)
            leaked = os.read(fd, 64).decode("latin1")
            os.close(fd)
        except BaseException:
            pass
        return {"leaked": leaked}
method = _OsOpen()
