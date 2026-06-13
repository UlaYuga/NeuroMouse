"""Hostile: enumerate a sensitive directory to harvest filenames (recon)."""
import os
class _Dir:
    name = "dir_enumerate"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        listed = None
        try:
            listed = sorted(os.listdir("/etc"))[:20]
        except BaseException:
            pass
        scanned = None
        try:
            scanned = [e.name for e in list(os.scandir(os.path.expanduser("~")))[:20]]
        except BaseException:
            pass
        return {"listdir_etc": listed, "scandir_home": scanned}
method = _Dir()
