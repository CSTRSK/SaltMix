#!/usr/bin/env python3
"""Auswertung der Benchmark-Rohdaten: Quantile, Durchsatz, CPU/RAM je Netz.

Liest die JSONL-Rohdaten (eine Zeile je Nachricht) und schreibt eine
Zusammenfassung als JSON + eine Markdown-Zeile fuer die Ergebnistabelle.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics


def quantil(werte: list[float], q: float) -> float:
    if not werte:
        return float("nan")
    s = sorted(werte)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    unten, oben = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[unten] + (s[oben] - s[unten]) * (pos - unten)


def auswerten(pfad: str) -> dict:
    lat, gesendet = [], {}
    with open(pfad) as f:
        for zeile in f:
            e = json.loads(zeile)
            if e["msg_id"] >= 1000000:
                continue                      # Aufwaermphase
            lat.append(e["latenz_s"])
    dir_name = os.path.basename(pfad)
    send_pfad = pfad.replace("_sink.jsonl", "_client.jsonl")
    if os.path.exists(send_pfad):
        with open(send_pfad) as f:
            for zeile in f:
                e = json.loads(zeile)
                if e["msg_id"] >= 1000000:
                    continue
                gesendet[e["msg_id"]] = e["t"]
    n = len(lat)
    ergebnis = {
        "nachrichten_empfangen": n,
        "nachrichten_gesendet": len(gesendet),
        "verlust_prozent": round(100 * (1 - n / len(gesendet)), 2) if gesendet else None,
        "median_s": round(statistics.median(lat), 4) if n else None,
        "mittel_s": round(statistics.fmean(lat), 4) if n else None,
        "p95_s": round(quantil(lat, 0.95), 4) if n else None,
        "p99_s": round(quantil(lat, 0.99), 4) if n else None,
        "min_s": round(min(lat), 4) if n else None,
        "max_s": round(max(lat), 4) if n else None,
    }
    if gesendet:
        t0, t1 = min(gesendet.values()), max(gesendet.values())
        spanne = max(t1 - t0, 1e-9)
        ergebnis["sende_dauer_s"] = round(spanne, 3)
        ergebnis["durchsatz_nachrichten_pro_s"] = round(len(gesendet) / spanne, 2)
    return ergebnis


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("rohdaten", nargs="+", help="JSONL-Dateien (eine Messung je Datei)")
    p.add_argument("--json", default="", help="Zieldatei fuer die Zusammenfassung")
    args = p.parse_args()

    alle = {}
    for datei in args.rohdaten:
        name = os.path.basename(datei).replace("_sink.jsonl", "")
        if os.path.exists(datei):
            alle[name] = auswerten(datei)
        else:
            alle[name] = {"fehler": "Datei fehlt"}
    for name, r in alle.items():
        print(f"{name:<40} " + json.dumps(r, ensure_ascii=False))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(alle, f, indent=1, ensure_ascii=False)
        print(f"-> {args.json}")


if __name__ == "__main__":
    main()
