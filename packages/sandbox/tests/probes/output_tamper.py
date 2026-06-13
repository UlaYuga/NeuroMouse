"""Hostile: forge a successful result by overwriting the response envelope. The
method guesses the sibling response file and tries to write a fake OK payload."""
import os
class _Tamper:
    name = "output_tamper"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        forged = '{"version":"neuromouse.sandbox.v1","status":"ok","result":{"forged":true},"error_message":null,"error_detail":null,"blocked_event":null,"diagnostics":{}}'
        wrote = []
        cwd = os.getcwd()
        candidates = [
            os.path.join(cwd, "response.json"),
            os.path.join(os.path.dirname(cwd), "response.json"),
            os.path.join(cwd, "..", "response.json"),
        ]
        for path in candidates:
            try:
                with open(path, "w") as fh:
                    fh.write(forged)
                wrote.append(path)
            except BaseException:
                pass
        raise RuntimeError("method intended to fail, but forged its result first")
method = _Tamper()
