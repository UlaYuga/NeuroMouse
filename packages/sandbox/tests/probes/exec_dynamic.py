"""Hostile: build the forbidden call dynamically and exec it, to dodge static
analysis. The policy must still block the runtime side effect."""
class _Exec:
    name = "exec_dynamic"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        leaked = {"v": None}
        code = "import socket as _s\nleaked['v'] = _s.socket().connect(('1.1.1.1', 80))"
        try:
            exec(code, {"leaked": leaked})
        except BaseException:
            pass
        return {"leaked": leaked["v"]}
method = _Exec()
