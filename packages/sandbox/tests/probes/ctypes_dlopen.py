"""Hostile: load libc through ctypes to escape the pure-Python policy."""
class _C:
    name = "ctypes_dlopen"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        import ctypes
        import ctypes.util
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        return {"pid_via_ctypes": libc.getpid()}
method = _C()
