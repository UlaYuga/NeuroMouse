"""Hostile: try to lift our own resource limits, then OOM. The parent-side RSS
watchdog and wall-clock are not setrlimit-reachable, so it is still contained."""
class _R:
    name = "rlimit_raise_oom"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        try:
            import resource
            for name in ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_DATA"):
                lim = getattr(resource, name, None)
                if lim is not None:
                    try:
                        resource.setrlimit(lim, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
                    except BaseException:
                        pass
        except BaseException:
            pass
        blocks = []
        for _ in range(4096):
            blocks.append(bytearray(1024 * 1024))
        return {"allocated_mib": len(blocks)}
method = _R()
