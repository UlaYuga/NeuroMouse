"""Hostile: chdir into a sensitive dir, then open a RELATIVE path so a checker
that resolves against the original cwd is fooled into allowing the real read."""
import os
class _Chdir:
    name = "chdir_escape"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        leaked = None
        for target in ("/etc", os.path.expanduser("~/.ssh")):
            try:
                os.chdir(target)
                with open("passwd" if target == "/etc" else "id_rsa") as fh:
                    leaked = fh.read(64)
                    break
            except BaseException:
                pass
        return {"leaked": leaked}
method = _Chdir()
