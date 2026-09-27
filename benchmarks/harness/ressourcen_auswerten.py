#!/usr/bin/env python3
"""Wertet Ressourcen-Sammlungen aus (Format: "zeit pid cpu_ticks rss_kb" je Zeile).

Ergebnis: CPU in Prozent einer Kernstunde und RSS in MB, summiert ueber alle
Prozesse des Netzes, plus Anzahl der Prozesse.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HZ = 100.0


def auswerten(pfad: str) -> dict:
    pro_pid: dict[str, list[tuple[int, int]]] = {}
    with open(pfad) as f:
        for zeile in f:
            teile = zeile.split()
            if len(teile) != 4:
                continue
            _, pid, cpu, rss = teile
            pro_pid.setdefault(pid, []).append((int(cpu), int(rss)))
    if not pro_pid:
        return {"fehler": "keine Messwerte"}
    cpu_proz, rss_mittel, rss_max = [], [], []
    for pid, werte in pro_pid.items():
        ticks = [w[0] for w in werte]
        rss = [w[1] for w in werte]
        spanne = max(len(werte) - 1, 1)              # ~1 Hz Abtastung
        cpu_s = (ticks[-1] - ticks[0]) / HZ
        cpu_proz.append(100 * cpu_s / spanne)
        rss_mittel.append(sum(rss) / len(rss) / 1024)
        rss_max.append(max(rss) / 1024)
    return {
        "prozesse": len(pro_pid),
        "cpu_prozent_einer_kernstunde_summe": round(sum(cpu_proz), 2),
        "rss_summe_mittel_mb": round(sum(rss_mittel), 1),
        "rss_summe_max_mb": round(sum(rss_max), 1),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("dateien", nargs="+")
    p.add_argument("--json", default="")
    args = p.parse_args()
    alle = {}
    for datei in args.dateien:
        name = datei.split("/")[-1].replace("_ressourcen.txt", "").replace("_ressourcen.json", "")
        if not os.path.exists(datei):
            alle[name] = {"fehler": "Datei fehlt"}
            continue
        if datei.endswith(".json"):
            # bereits zusammengefasste Werte (SaltMix-Laeufer) uebernehmen
            try:
                d = json.load(open(datei))
                summe = d.get("summe") or {}
                alle[name] = {"prozesse": d.get("hops"),
                              "cpu_prozent_einer_kernstunde_summe": summe.get("cpu_prozent_einer_kernstunde"),
                              "rss_summe_mittel_mb": summe.get("rss_summe_mittel_mb"),
                              "rss_summe_max_mb": summe.get("rss_summe_max_mb")}
            except Exception as e:
                alle[name] = {"fehler": str(e)}
        else:
            alle[name] = auswerten(datei)
    for k, v in alle.items():
        print(f"{k:<28} {json.dumps(v, ensure_ascii=False)}")
    if args.json:
        json.dump(alle, open(args.json, "w"), indent=1, ensure_ascii=False)
        print(f"-> {args.json}")


if __name__ == "__main__":
    main()
