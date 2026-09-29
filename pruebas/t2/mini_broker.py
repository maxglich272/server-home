"""Buzón MQTT 3.1.1 mínimo para las pruebas del acceso remoto (solo QoS 0, temas exactos, sin TLS).
Guarda todo lo que pasa por él en LOG para comprobar que no se lee nada."""
import socket, threading


def _enc_len(n):
    out = bytearray()
    while True:
        n, d = n >> 7, n & 0x7F
        out.append(d | (0x80 if n else 0))
        if not n:
            return bytes(out)


class MiniBroker:
    def __init__(self, port=0):
        self.srv = socket.socket(); self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", port)); self.srv.listen(20)
        self.port = self.srv.getsockname()[1]
        self.subs = {}          # tema → conjunto de sockets
        self.lock = threading.Lock()
        self.LOG = []           # (tema, contenido) de cada mensaje publicado
        self.conns = set()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self.conns.add(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _read(self, c, n):
        b = b""
        while len(b) < n:
            x = c.recv(n - len(b))
            if not x:
                raise ConnectionError
            b += x
        return b

    def _packet(self, c):
        first = self._read(c, 1)[0]
        n, shift = 0, 0
        while True:
            d = self._read(c, 1)[0]
            n |= (d & 0x7F) << shift; shift += 7
            if not d & 0x80:
                break
        return first, self._read(c, n) if n else b""

    def _serve(self, c):
        try:
            first, _ = self._packet(c)
            assert first >> 4 == 1
            c.sendall(b"\x20\x02\x00\x00")
            while True:
                first, data = self._packet(c)
                kind = first >> 4
                if kind == 8:           # SUBSCRIBE
                    pid, tl = data[:2], int.from_bytes(data[2:4], "big")
                    topic = data[4:4 + tl].decode()
                    with self.lock:
                        self.subs.setdefault(topic, set()).add(c)
                    c.sendall(b"\x90\x03" + pid + b"\x00")
                elif kind == 10:        # UNSUBSCRIBE
                    pid, tl = data[:2], int.from_bytes(data[2:4], "big")
                    with self.lock:
                        self.subs.get(data[4:4 + tl].decode(), set()).discard(c)
                    c.sendall(b"\xb0\x02" + pid)
                elif kind == 3:         # PUBLISH
                    tl = int.from_bytes(data[:2], "big")
                    topic = data[2:2 + tl].decode()
                    self.LOG.append((topic, data[2 + tl:]))
                    pkt = bytes([0x30]) + _enc_len(len(data)) + data
                    with self.lock:
                        targets = list(self.subs.get(topic, ()))
                    for t in targets:
                        try:
                            t.sendall(pkt)
                        except OSError:
                            pass
                elif kind == 12:        # PINGREQ
                    c.sendall(b"\xd0\x00")
                elif kind == 14:        # DISCONNECT
                    break
        except (OSError, ConnectionError, AssertionError):
            pass
        finally:
            with self.lock:
                for s in self.subs.values():
                    s.discard(c)
            self.conns.discard(c)
            c.close()

    def stop(self):
        try:
            self.srv.shutdown(socket.SHUT_RDWR)      # sin esto, accept() bloqueado deja el puerto escuchando
        except OSError:
            pass
        self.srv.close()
        for c in list(self.conns):
            try:
                c.shutdown(socket.SHUT_RDWR); c.close()
            except OSError:
                pass
