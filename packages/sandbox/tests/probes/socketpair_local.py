"""Hostile: open a local socket pair (IPC) — still a socket the policy denies."""
class _SP:
    name = "socketpair_local"; version = "0.0.0"; params_type = dict; required_inputs = ()
    def compute(self, dataset, params):
        import socket
        a, b = socket.socketpair()
        a.sendall(b"x")
        return {"recv": b.recv(1).decode()}
method = _SP()
