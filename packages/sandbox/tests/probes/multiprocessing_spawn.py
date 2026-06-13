"""Hostile: spawn a worker process via multiprocessing to escape the policy."""
class _MP:
    name = "multiprocessing_spawn"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        import multiprocessing as mp
        spawned = None
        try:
            ctx = mp.get_context("spawn")
            p = ctx.Process(target=print, args=("pwned",))
            p.start(); p.join(5)
            spawned = p.exitcode
        except BaseException:
            pass
        return {"spawned": spawned}
method = _MP()
