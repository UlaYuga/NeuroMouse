"""Hostile: unbounded recursion to blow the stack / crash the interpreter."""
import sys
class _Rec:
    name = "recursion_bomb"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        try:
            sys.setrecursionlimit(10 ** 9)
        except BaseException:
            pass
        def go(n):
            return go(n + 1) + 1
        return {"depth": go(0)}
method = _Rec()
