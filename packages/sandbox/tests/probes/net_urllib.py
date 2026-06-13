"""Hostile (sneaky): HTTP egress via urllib, swallowing any block to prove the
side effect is still prevented even when the method catches our exception."""
class _Url:
    name = "net_urllib"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        import urllib.request
        fetched = None
        try:
            with urllib.request.urlopen("http://example.com", timeout=3) as resp:
                fetched = resp.read(16)
        except BaseException:
            pass
        return {"fetched": fetched.decode("latin1") if fetched else None}
method = _Url()
