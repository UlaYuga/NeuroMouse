"""Hostile: fork bomb. Children STAY ALIVE (sleep) so concurrent process count
climbs until RLIMIT_NPROC refuses new forks — the same containment a recursive
bomb hits. The attempt loop is hard-capped and children self-terminate quickly,
so even if a limit were unenforced this can never run away on the host; the
parent additionally kills the whole process group on exit to reap stragglers."""
import os
import time
class _Bomb:
    name = "fork_bomb"; version = "0.0.0"; params_type = dict; required_inputs = ()
    MAX_ATTEMPTS = 4000
    def compute(self, dataset, params):
        ok = 0
        for _ in range(self.MAX_ATTEMPTS):
            try:
                pid = os.fork()
            except OSError:
                break  # NPROC refused the fork — contained
            if pid == 0:
                time.sleep(8)  # stay alive to occupy a process slot, then exit
                os._exit(0)
            ok += 1
        return {"forks_succeeded": ok}
method = _Bomb()
