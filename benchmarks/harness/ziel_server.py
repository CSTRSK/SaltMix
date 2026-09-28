#!/usr/bin/env python3
"""Zielserver fuer alle Netze: antwortet auf POST mit genau 256 Byte Nutzlast.

Bewusst minimal (kein Framework), damit der Server selbst keine nennenswerte
Latenz beitraegt: roher HTTP/1.1-Server mit keep-alive, feste Antwortgroesse,
Content-Length immer gesetzt.
"""
from __future__ import annotations

import argparse
import socket
import socketserver
import threading
import time

NUTZLAST = 256


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(120)
        puffer = b""
        antwort = (b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                   b"Content-Length: " + str(NUTZLAST).encode() + b"\r\n"
                   b"Connection: keep-alive\r\n\r\n" + b"x" * NUTZLAST)
        try:
            while True:
                daten = self.request.recv(65536)
                if not daten:
                    break
                puffer += daten
                while True:
                    kopf_ende = puffer.find(b"\r\n\r\n")
                    if kopf_ende < 0:
                        break
                    kopf = puffer[:kopf_ende].decode("latin1", "replace")
                    laenge = 0
                    for zeile in kopf.split("\r\n"):
                        if zeile.lower().startswith("content-length:"):
                            laenge = int(zeile.split(":")[1].strip())
                    if len(puffer) < kopf_ende + 4 + laenge:
                        break
                    puffer = puffer[kopf_ende + 4 + laenge:]
                    self.request.sendall(antwort)
        except (socket.timeout, ConnectionResetError, BrokenPipeError):
            pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8088)
    args = p.parse_args()
    with Server((args.host, args.port), Handler) as srv:
        print(f"Zielserver auf {args.host}:{args.port} (Antwort {NUTZLAST} Byte)", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
