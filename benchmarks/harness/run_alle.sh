#!/bin/bash
# Gesamtlauf: alle Netze nacheinander (sequenziell, damit sich die Netze nicht
# gegenseitig die CPU streitig machen), danach gemeinsame Auswertung.
set -u
HIER="$(cd "$(dirname "$0")" && pwd)"
DATA="$(cd "$HIER/.." && pwd)/data"
mkdir -p "$DATA"
ANZAHL=${1:-300}
RATE=${2:-20}
LOG="$DATA/ablauf.log"
: > "$LOG"
sag() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

sag "Start Gesamtlauf (je $ANZAHL Nachrichten, $RATE/s)"
sag "Hintergrundlast zum Start: $(uptime)"

# Zielserver fuer die lokalen Tor-Messungen
pkill -f ziel_server.py 2>/dev/null
nohup python3 "$HIER/ziel_server.py" --port 8088 >> "$LOG" 2>&1 &
ZIEL_PID=$!
sleep 2

sag "--- 1/6 SaltMix: 3 Hops, Mix-Delay 2,0 s (Standard) ---"
bash "$HIER/run_saltmix.sh" saltmix_3hops_delay2 3 2.0 "$ANZAHL" "$RATE" 256 >> "$LOG" 2>&1

sag "--- 2/6 SaltMix: 3 Hops, Mix-Delay 0 s (Delay-Anteil isolieren) ---"
bash "$HIER/run_saltmix.sh" saltmix_3hops_nodelay 3 0 "$ANZAHL" "$RATE" 256 >> "$LOG" 2>&1

sag "--- 3/6 SaltMix: 7 Hops, Mix-Delay 2,0 s (Topologie-Variante) ---"
bash "$HIER/run_saltmix.sh" saltmix_7hops_delay2 7 2.0 "$ANZAHL" "$RATE" 256 >> "$LOG" 2>&1

sag "--- 4/6 Tor: oeffentliches Netz + Direktvergleich ---"
bash "$HIER/run_tor.sh" public "$ANZAHL" "$RATE" >> "$LOG" 2>&1

sag "--- 5/6 Tor: chutney-Testnetz (lokal, 3 Hops) ---"
bash "$HIER/run_tor.sh" chutney "$ANZAHL" "$RATE" >> "$LOG" 2>&1

sag "--- 6/6 Nym (Sandbox) und I2P (mit Fallback) ---"
bash "$HIER/run_nym.sh" "$ANZAHL" "$RATE" >> "$LOG" 2>&1
bash "$HIER/run_i2p.sh" 900 "$ANZAHL" "$RATE" >> "$LOG" 2>&1

kill "$ZIEL_PID" 2>/dev/null
pkill -f ziel_server.py 2>/dev/null

sag "--- Auswertung ---"
python3 "$HIER/auswerten.py" \
  "$DATA/saltmix_3hops_delay2_sink.jsonl" \
  "$DATA/saltmix_3hops_nodelay_sink.jsonl" \
  "$DATA/saltmix_7hops_delay2_sink.jsonl" \
  "$DATA/tor_public.jsonl" "$DATA/direkt_extern.jsonl" \
  "$DATA/tor_chutney.jsonl" "$DATA/direkt_lokal.jsonl" \
  "$DATA/nym.jsonl" "$DATA/i2p.jsonl" \
  --json "$DATA/latenz_zusammenfassung.json" >> "$LOG" 2>&1

python3 "$HIER/ressourcen_auswerten.py" \
  "$DATA/saltmix_3hops_delay2_ressourcen.json" \
  "$DATA/tor_public_ressourcen.txt" "$DATA/tor_chutney_ressourcen.txt" \
  "$DATA/nym_ressourcen.txt" "$DATA/i2p_ressourcen.txt" \
  --json "$DATA/ressourcen_zusammenfassung.json" >> "$LOG" 2>&1

sag "Fertig. Rohdaten in $DATA"
cat "$DATA/latenz_zusammenfassung.json" 2>/dev/null | head -40
