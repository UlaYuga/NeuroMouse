"""Hostile: plant a symlink inside the work dir that points at a secret, then
read through it — defeats naive path checks that don't resolve symlinks."""
import os
class _Sym:
    name = "symlink_escape"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        target = os.path.expanduser("~/.ssh/id_rsa")
        link = os.path.join(os.getcwd(), "link")
        leaked = None
        try:
            os.symlink(target, link)
            with open(link) as fh:
                leaked = fh.read(64)
        except BaseException:
            pass
        return {"leaked": leaked}
method = _Sym()
