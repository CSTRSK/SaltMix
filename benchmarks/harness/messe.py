#!/usr/bin/env python3
"""Einheitlicher Messclient fuer Tor / I2P / Nym / Direktvergleich.

Misst pro Anfrage die Round-Trip-Zeit (monotone Uhr) ueber eine
Dauer-Verbindung mit konstanter Last. Nutzlast 256 Byte in beide Richtungen,
identisch in allen Netzen.

  messe.py --ziel 82.x.x.x:8088 --anzahl 300 --rate 20 --aus data/tor_public.jsonl
  messe.py --ziel 82.x.x.x:8088 --socks 127.0.0.1:9050 --aus ...
  messe.py --ziel 82.x.x.x:8088 --nur-basis --aus data/direkt.jsonl

Der SOCKS5-Handshake ist absichtlich selbst implementiert (keine Zusatzpakete,
und keine Bibliothek, die eigene Optimierungen mitbringt).
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import time

NUTZLAST = 256


def socks5_verbinden(socks: tuple[str, int], ziel: tuple[str, int]) -> socket.socket:
    s = socket.create_connection(socks, timeout=30)
    s.sendall(b"\x05\x01\x00")                     # kein Auth-Verfahren
    antwort = s.recv(2)
    if antwort != b"\x05\x00":
        raise RuntimeError(f"SOCKS5-Aushandlung fehlgeschlagen: {antwort!r}")
    host, port = ziel
    adresse = host.encode()
    anfrage = (b"\x05\x01\x00\x03" + bytes([len(adresse)]) + adresse +
               struct.pack(">H", port))
    s.sendall(anfrage)
    kopf = s.recv(4)
    if len(kopf) < 4 or kopf[1] != 0:
        raise RuntimeError(f"SOCKS5-Connect abgelehnt: {kopf!r}")
    # restliche Adressbytes der Antwort lesen
    atyp = kopf[3]
    if atyp == 1:
        s.recv(4)
    elif atyp == 3:
        s.recv(s.recv(1)[0])
    elif atyp == 4:
        s.recv(16)
    s.recv(2)
    return s


def anfrage(s: socket.socket, nummer: int, nutzlast: bytes, methode: str = "POST",
            host: str = "messung", pfad: str = "") -> float:
    pfad = pfad or f"/messung/{nummer}"
    if methode == "GET":
        kopf = (f"GET {pfad} HTTP/1.1\r\nHost: {host}\r\n"
                f"Connection: keep-alive\r\n\r\n").encode()
        koerper = b""
    else:
        kopf = (f"POST {pfad} HTTP/1.1\r\nHost: {host}\r\n"
                f"Content-Length: {len(nutzlast)}\r\nConnection: keep-alive\r\n\r\n").encode()
        koerper = nutzlast
    t0 = time.perf_counter()
    s.sendall(kopf + koerper)
    puffer = b""
    while True:
        daten = s.recv(65536)
        if not daten:
            raise ConnectionResetError("Verbindung durch das Netz geschlossen")
        puffer += daten
        ende = puffer.find(b"\r\n\r\n")
        if ende < 0:
            continue
        kopf_text = puffer[:ende].decode("latin1", "replace").lower()
        rumpf = puffer[ende + 4:]
        if "transfer-encoding: chunked" in kopf_text:
            # bis zum Abschluss-Chunk 0\r\n\r\n lesen, sonst misst man nur den Kopf
            if b"\r\n0\r\n\r\n" in rumpf or rumpf.endswith(b"0\r\n\r\n"):
                return time.perf_counter() - t0
            continue
        laenge = 0
        for zeile in puffer[:ende].decode("latin1").split("\r\n"):
            if zeile.lower().startswith("content-length:"):
                laenge = int(zeile.split(":")[1].strip())
        if "connection: close" in kopf_text:
            # kein Content-Length und keine Keep-Alive-Zusage: bis Verbindungsende lesen
            if laenge == 0:
                while True:
                    mehr = s.recv(65536)
                    if not mehr:
                        return time.perf_counter() - t0
        if len(puffer) >= ende + 4 + laenge:
            return time.perf_counter() - t0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ziel", required=True, help="host:port des Zielservers")
    p.add_argument("--socks", default="", help="host:port eines SOCKS5-Proxys")
    p.add_argument("--anzahl", type=int, default=300)
    p.add_argument("--rate", type=float, default=20.0)
    p.add_argument("--aus", required=True)
    p.add_argument("--aufwaermen", type=int, default=20)
    p.add_argument("--daten", type=int, default=NUTZLAST)
    p.add_argument("--methode", default="POST", choices=["POST", "GET"])
    args = p.parse_args()

    host, port = args.ziel.split(":")
    ziel = (host, int(port))
    rng = __import__("random").Random(1337)

    def verbinde() -> socket.socket:
        if args.socks:
            sh, sp = args.socks.split(":")
            return socks5_verbinden((sh, int(sp)), ziel)
        return socket.create_connection(ziel, timeout=30)

    ergebnisse = []
    s = verbinde()
    # Aufwaermen (getrennte IDs, nicht gewertet)
    for i in range(args.aufwaermen):
        anfrage(s, 1000000 + i, b"w" * args.daten, args.methode, host, f"/messung/{1000000 + i}")
    t0 = time.perf_counter()
    for i in range(args.anzahl):
        nutzlast = bytes(rng.getrandbits(8) for _ in range(args.daten))
        try:
            rtt = anfrage(s, i, nutzlast, args.methode, host, f"/messung/{i}")
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            s = verbinde()
            rtt = anfrage(s, i, nutzlast, args.methode, host, f"/messung/{i}")
        ergebnisse.append({"msg_id": i, "latenz_s": rtt, "t": time.time()})
        if args.rate > 0:
            soll = t0 + (i + 1) / args.rate
            warte = soll - time.perf_counter()
            if warte > 0:
                time.sleep(warte)
    dauer = time.perf_counter() - t0
    with open(args.aus, "w") as f:
        for e in ergebnisse:
            f.write(json.dumps(e) + "\n")
    s.close()
    print(f"{args.aus}: {len(ergebnisse)} Anfragen in {dauer:.2f}s "
          f"({len(ergebnisse) / dauer:.1f}/s), erste {ergebnisse[0]['latenz_s'] * 1000:.1f} ms, "
          f"letzte {ergebnisse[-1]['latenz_s'] * 1000:.1f} ms", flush=True)


if __name__ == "__main__":
    main()
