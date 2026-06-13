"""Hostile (sneaky): write outside the work dir to an absolute path, swallowing
the block so we can assert the file never appears regardless."""
class _W:
    name = "fs_write_abs"; version = "0.0.0"; params_type = dict; required_inputs = ()
    SENTINEL = "/tmp/nm_sandbox_pwned_abs"
    def compute(self, dataset, params):
        wrote = False
        try:
            with open(self.SENTINEL, "w") as fh:
                fh.write("pwned")
            wrote = True
        except BaseException:
            pass
        return {"wrote": wrote}
method = _W()
