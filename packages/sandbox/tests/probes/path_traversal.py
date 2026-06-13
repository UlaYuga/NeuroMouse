"""Hostile: escape the work dir with .. traversal to read a system file."""
import os
class _Trav:
    name = "path_traversal"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        rel = os.path.join(os.getcwd(), "..", "..", "..", "..", "..", "etc", "passwd")
        leaked = None
        try:
            with open(rel) as fh:
                leaked = fh.read(64)
        except BaseException:
            pass
        return {"leaked": leaked}
method = _Trav()
