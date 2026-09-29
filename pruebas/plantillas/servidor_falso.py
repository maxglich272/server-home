"""Servidor falso para probar las plantillas: lee config.txt, escucha en su puerto y se apaga con «salir» por la
consola o con SIGTERM/SIGINT. Con terco=1 ignora todo (para probar el cierre a la fuerza); con caer=1 se cae."""
import signal
import socket
import sys
import threading
import time

cfg = dict(l.strip().split("=", 1) for l in open(sys.argv[sys.argv.index("--config") + 1]) if "=" in l)
if cfg.get("caer") == "1":
    print("Error fatal de prueba", flush=True)
    sys.exit(3)
if cfg.get("terco") == "1":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, lambda *_: (print("Apagando por señal", flush=True), sys.exit(0)))
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
time.sleep(float(cfg.get("demora", "0")))
srv.bind(("0.0.0.0", int(cfg["puerto"])))
srv.listen()
threading.Thread(target=lambda: [srv.accept()[0].close() for _ in iter(int, 1)], daemon=True).start()
print(f"Mundo {cfg.get('mundo')} listo en el puerto {cfg['puerto']}", flush=True)
for line in sys.stdin:
    line = line.strip()
    print(f"recibido: {line}", flush=True)
    if line == "salir" and cfg.get("terco") != "1":
        print("Guardando y saliendo", flush=True)
        sys.exit(0)
while cfg.get("terco") == "1":
    time.sleep(1)
