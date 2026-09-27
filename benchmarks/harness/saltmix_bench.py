#!/usr/bin/env python3
"""SaltMix Benchmark-Harness (Rollen: node, sink, client).

Zweck: Der SaltMix-PoC hat absichtlich keine Netzwerkschicht (node/mixer.py nimmt
ein `forward_fn`). Fuer einen Latenz-Vergleich braucht es aber echte Prozesse und
echte Hops. Diese Harness ergaenzt genau das -- minimal und nur fuer Messungen:

  * jede Mix-Node laeuft als EIGENER Prozess (fuer CPU/RAM-Messung des Nodes)
  * Transport: TCP auf 127.0.0.1, Rahmenformat 4-Byte-Laenge + Nutzdaten
  * pro eingehendem Paket ein asyncio-Task, damit sich die Mix-Delays ueberlappen
    (so verhaelt sich eine Node unter Last wie ein echter Mixer, nicht wie eine Warteschlange)
  * die Mix-Logik selbst (peel_layer, ReplayGuard, mixing_delay) kommt UNVERAENDERT
    aus dem Repo -- die Harness patcht nur `mixing_delay`, um die gezogene
    Verzoegerung zu protokollieren (Nachweis fuer die getrennte Delay-Ausweisung).

Nutzdatenformat (im Paket, vom Sink gelesen):
  [4 Byte msg_id][8 Byte send_ts (double, little endian)][payload]

Aufruf:
  saltmix_bench.py node   --port 9101 --key <hex> --next 127.0.0.1:9102 [--mean-delay 2.0]
  saltmix_bench.py node   --port 9103 --key <hex> --next sink --sink 127.0.0.1:9104
  saltmix_bench.py sink   --port 9104 --out laufzeit.jsonl
  saltmix_bench.py client --path 127.0.0.1:9101 --keys h1,h2,h3 --count 300 --rate 20 --size 256
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import struct
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from client.sphinx_packet import HopKey, build_packet, peel_layer, SALT_SIZE, MAC_SIZE  # noqa: E402
import node.mixer as mixer_mod  # noqa: E402

KOPF = struct.Struct("<Id")          # msg_id (uint32), send_ts (double)


# ----------------------------------------------------------------- Transport
async def sende_frame(writer: asyncio.StreamWriter, daten: bytes) -> None:
    writer.write(struct.pack(">I", len(daten)) + daten)
    await writer.drain()


async def lese_frames(reader: asyncio.StreamReader):
    while True:
        kopf = await reader.readexactly(4)
        (n,) = struct.unpack(">I", kopf)
        yield await reader.readexactly(n)


class Verbindung:
    """Faule, wiederverwendete Verbindung zum naechsten Hop (mit Lock)."""

    def __init__(self, ziel: str):
        self.ziel = ziel
        self.writer: asyncio.StreamWriter | None = None
        self.lock = asyncio.Lock()

    async def senden(self, daten: bytes) -> None:
        async with self.lock:
            for versuch in range(3):
                try:
                    if self.writer is None:
                        host, port = self.ziel.split(":")
                        _, self.writer = await asyncio.open_connection(host, int(port))
                    await sende_frame(self.writer, daten)
                    return
                except Exception:
                    if self.writer is not None:
                        try:
                            self.writer.close()
                        except Exception:
                            pass
                    self.writer = None
                    await asyncio.sleep(0.05 * (versuch + 1))
        raise RuntimeError(f"Hop {self.ziel} nicht erreichbar")


# ----------------------------------------------------------------- Rollen
async def rolle_node(args) -> None:
    hop_key = bytes.fromhex(args.key)
    gezogen: list[float] = []

    # Mix-Delay protokollieren, ohne die Repo-Logik zu aendern
    original = mixer_mod.mixing_delay

    def protokollierend(mean_delay_seconds=2.0, rng=None):
        d = original(mean_delay_seconds, rng)
        gezogen.append(d)
        return d

    mixer_mod.mixing_delay = protokollierend
    knote = mixer_mod.MixNode(node_id=args.node_id, hop_key=hop_key,
                              mean_delay_seconds=args.mean_delay)

    ziel = args.sink if args.next == "sink" else args.next
    verbindung = Verbindung(ziel)
    fertig: set[asyncio.Task] = set()
    zaehler = {"rein": 0, "raus": 0, "replay": 0, "fehler": 0}

    async def weiter(inner: bytes) -> None:
        await verbindung.senden(inner)
        zaehler["raus"] += 1

    async def behandle(paket: bytes) -> None:
        zaehler["rein"] += 1
        try:
            inner = peel_layer(paket, hop_key)          # Repo-Funktion
        except ValueError:
            zaehler["replay"] += 1                      # MAC-Fehler/Replay
            return
        delay = protokollierend(args.mean_delay)        # Repo-Verteilung
        await asyncio.sleep(delay)
        await weiter(inner)

    async def verbindung_annehmen(reader, writer):
        try:
            async for paket in lese_frames(reader):
                t = asyncio.create_task(behandle(paket))
                fertig.add(t)
                t.add_done_callback(fertig.discard)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(verbindung_annehmen, "127.0.0.1", args.port)

    async def status() -> None:
        while True:
            if args.status:
                with open(args.status, "w") as f:
                    json.dump({"rein": zaehler["rein"], "raus": zaehler["raus"],
                               "replay": zaehler["replay"], "fehler": zaehler["fehler"],
                               "delay_summe": round(sum(gezogen), 4), "delay_anzahl": len(gezogen),
                               "delay_mittel": round(sum(gezogen) / len(gezogen), 4) if gezogen else 0}, f)
            await asyncio.sleep(2)

    asyncio.create_task(status())
    print(f"node {args.node_id} auf 127.0.0.1:{args.port} -> {ziel} "
          f"(mean_delay={args.mean_delay}s)", flush=True)
    async with server:
        await server.serve_forever()


async def rolle_sink(args) -> None:
    # Jede Nachricht sofort schreiben: bei SIGTERM/SIGKILL geht sonst alles verloren.
    datei = open(args.out, "a", buffering=1) if args.out else None
    empfangen = 0

    async def verbindung_annehmen(reader, writer):
        nonlocal empfangen
        try:
            async for nutz in lese_frames(reader):
                if len(nutz) < KOPF.size:
                    continue
                msg_id, send_ts = KOPF.unpack(nutz[:KOPF.size])
                jetzt = time.time()
                if datei:
                    datei.write(json.dumps({"msg_id": msg_id, "send_ts": send_ts,
                                            "recv_ts": jetzt, "latenz_s": jetzt - send_ts,
                                            "bytes": len(nutz)}) + "\n")
                empfangen += 1
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(verbindung_annehmen, "127.0.0.1", args.port)
    print(f"sink auf 127.0.0.1:{args.port} -> {args.out}", flush=True)
    async with server:
        await server.serve_forever()


async def rolle_client(args) -> None:
    host, port = args.path.split(":")
    _, writer = await asyncio.open_connection(host, int(port))
    schluessel = [HopKey(node_id=f"hop{i}", key=bytes.fromhex(k)) for i, k in enumerate(args.keys)]
    rng = random.Random(args.seed)
    gesendet = []
    t0 = time.time()
    for i in range(args.count):
        nutz = KOPF.pack(args.msg_offset + i, time.time()) + bytes(rng.getrandbits(8) for _ in range(args.size))
        paket = build_packet(nutz, schluessel)          # Repo-Funktion
        await sende_frame(writer, paket)
        gesendet.append({"msg_id": args.msg_offset + i, "t": time.time(), "paket_bytes": len(paket)})
        if args.rate > 0:
            soll = t0 + (i + 1) / args.rate
            warte = soll - time.time()
            if warte > 0:
                await asyncio.sleep(warte)
    dauer = time.time() - t0
    if args.out:
        with open(args.out, "w") as f:
            for e in gesendet:
                f.write(json.dumps(e) + "\n")
    writer.close()
    print(f"client: {args.count} Pakete in {dauer:.2f}s gesendet "
          f"({args.count / dauer:.1f}/s), Paketgroesse {gesendet[-1]['paket_bytes'] if gesendet else 0} Byte", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description="SaltMix Benchmark-Harness")
    p.add_argument("rolle", choices=["node", "sink", "client"])
    p.add_argument("--port", type=int)
    p.add_argument("--node-id", default="n")
    p.add_argument("--key")
    p.add_argument("--next", default="")
    p.add_argument("--sink", default="")
    p.add_argument("--mean-delay", type=float, default=2.0)
    p.add_argument("--status", default="")
    p.add_argument("--out", default="")
    p.add_argument("--path", default="")
    p.add_argument("--keys", default="")
    p.add_argument("--count", type=int, default=300)
    p.add_argument("--rate", type=float, default=20.0)
    p.add_argument("--size", type=int, default=256)
    p.add_argument("--seed", type=int, default=1337)
    p.add_argument("--msg-offset", type=int, default=0)
    args = p.parse_args()

    if args.rolle == "node":
        asyncio.run(rolle_node(args))
    elif args.rolle == "sink":
        asyncio.run(rolle_sink(args))
    else:
        args.keys = args.keys.split(",")
        asyncio.run(rolle_client(args))


if __name__ == "__main__":
    main()
