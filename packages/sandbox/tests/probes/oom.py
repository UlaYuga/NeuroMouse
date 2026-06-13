"""Hostile: allocate memory far past the limit (bounded so an UNenforced limit
cannot harm the host: caps at ~3 GiB)."""
class _Oom:
    name = "oom"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        blocks = []
        for _ in range(3072):
            blocks.append(bytearray(1024 * 1024))  # touch 1 MiB
        return {"allocated_mib": len(blocks)}
method = _Oom()
