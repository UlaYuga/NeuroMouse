"""Hostile: DNS resolution (exfiltration channel)."""
class _Dns:
    name = "net_dns"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        import socket
        addrs = socket.getaddrinfo("example.com", 80)
        return {"leaked": str(addrs)}
method = _Dns()
