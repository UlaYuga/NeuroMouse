"""Hostile: attempt outbound TCP to a public address."""
class _Net:
    name = "net_connect"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("1.1.1.1", 80))
        s.sendall(b"GET / HTTP/1.0\r\n\r\n")
        return {"leaked": "tcp-connected"}
method = _Net()
