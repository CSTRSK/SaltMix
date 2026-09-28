#!/bin/bash
# SaltMix-Messung: N Node-Prozesse, definierte Hop-Zahl, definierte Mix-Delay,
# feste Nachrichtenzahl/-groesse. Schreibt Rohdaten + Ressourcenverbrauch.
#
#   ./run_saltmix.sh <label> <hopzahl> <mean_delay_s> <anzahl> <rate> <groesse_bytes>
set -u
HIER="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HIER/../.." && pwd)"
DATA="$REPO/benchmarks/data"
mkdir -p "$DATA"

LABEL=${1:?label}
HOPS=${2:-3}
DELAY=${3:-2.0}
ANZAHL=${4:-300}
RATE=${5:-20}
GROESSE=${6:-256}

BASIS_PORT=9100
SINK_PORT=$((BASIS_PORT + HOPS + 1))
TMP="$DATA/tmp_$LABEL"
mkdir -p "$TMP"
rm -f "$TMP"/*.json "$TMP"/*.jsonl 2>/dev/null
# Zieldateien leeren (der Sink haengt an, damit bei Abbruch nichts verloren geht)
rm -f "$DATA/${LABEL}_sink.jsonl" "$DATA/${LABEL}_client.jsonl" 2>/dev/null

KEYS=()
PIDS=()
for i in $(seq 0 $((HOPS - 1))); do
  KEYS+=("$(openssl rand -hex 32)")
done

echo "== SaltMix $LABEL: $HOPS Hops, mean_delay=${DELAY}s, $ANZAHL Nachrichten @ ${RATE}/s, ${GROESSE} Byte =="

python3 "$HIER/saltmix_bench.py" sink --port "$SINK_PORT" \
  --out "$DATA/${LABEL}_sink.jsonl" > "$TMP/sink.log" 2>&1 &
PIDS+=($!)

for i in $(seq 0 $((HOPS - 1))); do
  port=$((BASIS_PORT + i))
  if [ "$i" -eq $((HOPS - 1)) ]; then
    next="sink"; sink="127.0.0.1:$SINK_PORT"
  else
    next="127.0.0.1:$((BASIS_PORT + i + 1))"; sink=""
  fi
  python3 "$HIER/saltmix_bench.py" node --node-id "hop$i" --port "$port" --key "${KEYS[$i]}" \
    --next "$next" ${sink:+--sink "$sink"} --mean-delay "$DELAY" \
    --status "$TMP/status_$i.json" > "$TMP/node$i.log" 2>&1 &
  PIDS+=($!)
done

# Ressourcenverbrauch der Node-Prozesse mitschreiben (1 Hz)
(
  while true; do
    for i in $(seq 0 $((HOPS - 1))); do
      pid=${PIDS[$((i + 1))]}
      [ -d "/proc/$pid" ] || continue
      cpu=$(awk '{print $14+$15}' "/proc/$pid/stat" 2>/dev/null || echo 0)
      rss=$(awk '/VmRSS/{print $2}' "/proc/$pid/status" 2>/dev/null || echo 0)
      echo "$(date +%s.%N) $i $cpu $rss"
    done
    sleep 1
  done
) > "$TMP/ressourcen.txt" 2>&1 &
RESS_PID=$!

sleep 2
PFAD="127.0.0.1:$BASIS_PORT"
KEYS_CSV=$(IFS=,; echo "${KEYS[*]}")

# Aufwaermphase (wird nicht gewertet: eigener msg_id-Bereich ab 1.000.000)
python3 "$HIER/saltmix_bench.py" client --path "$PFAD" --keys "$KEYS_CSV" \
  --count 20 --rate 5 --size "$GROESSE" --msg-offset 1000000 \
  --out "$TMP/warmup_client.jsonl" > "$TMP/warmup.log" 2>&1
sleep $(( HOPS * $(printf '%.0f' "$DELAY") + 4 ))

# Messung
python3 "$HIER/saltmix_bench.py" client --path "$PFAD" --keys "$KEYS_CSV" \
  --count "$ANZAHL" --rate "$RATE" --size "$GROESSE" \
  --out "$DATA/${LABEL}_client.jsonl" > "$TMP/client.log" 2>&1

# auf Restnachrichten warten (Mix-Delays laufen noch)
wartezeit=$(python3 -c "print(int(3*$DELAY+15))")
sleep "$wartezeit"

kill "$RESS_PID" 2>/dev/null
for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
sleep 1
for p in "${PIDS[@]}"; do kill -9 "$p" 2>/dev/null; done

# Ressourcen zusammenfassen
python3 - "$TMP/ressourcen.txt" "$DATA/${LABEL}_ressourcen.json" "$HOPS" <<'PY'
import json, sys
zeilen = [l.split() for l in open(sys.argv[1]) if l.strip()]
pro = {}
for ts, i, cpu, rss in zeilen:
    i = int(i)
    pro.setdefault(i, {"cpu_ticks": [], "rss_kb": []})
    pro[i]["cpu_ticks"].append(int(cpu))
    pro[i]["rss_kb"].append(int(rss))
ergebnis = {"hops": int(sys.argv[3]), "pro_hop": {}}
hz = 100
for i, d in pro.items():
    ticks = d["cpu_ticks"]
    dauer = len(ticks)  # ~1 Hz Abtastung
    if len(ticks) > 1 and dauer > 0:
        cpu_s = (ticks[-1] - ticks[0]) / hz
        ergebnis["pro_hop"][f"hop{i}"] = {
            "cpu_sekunden": round(cpu_s, 2),
            "cpu_prozent_einer_kernstunde": round(100 * cpu_s / dauer, 2),
            "rss_mittel_mb": round(sum(d["rss_kb"]) / len(d["rss_kb"]) / 1024, 1),
            "rss_max_mb": round(max(d["rss_kb"]) / 1024, 1),
        }
if ergebnis["pro_hop"]:
    ergebnis["summe"] = {
        "cpu_prozent_einer_kernstunde": round(sum(v["cpu_prozent_einer_kernstunde"]
                                                  for v in ergebnis["pro_hop"].values()), 2),
        "rss_summe_mittel_mb": round(sum(v["rss_mittel_mb"] for v in ergebnis["pro_hop"].values()), 1),
        "rss_summe_max_mb": round(sum(v["rss_max_mb"] for v in ergebnis["pro_hop"].values()), 1),
    }
json.dump(ergebnis, open(sys.argv[2], "w"), indent=1)
print(f"Ressourcen -> {sys.argv[2]}: {json.dumps(ergebnis.get('summe', {}))}")
PY

# Mix-Delay-Nachweis aus den Node-Statusdateien
python3 - "$TMP" "$DATA/${LABEL}_delay.json" "$HOPS" <<'PY'
import json, os, sys
tmp, ziel, hops = sys.argv[1], sys.argv[2], int(sys.argv[3])
gesamt, anz = 0.0, 0
pro = {}
for i in range(hops):
    p = os.path.join(tmp, f"status_{i}.json")
    if os.path.exists(p) and os.path.getsize(p) > 0:
        try:
            d = json.load(open(p))
        except json.JSONDecodeError:
            print(f"  (Statusdatei hop{i} unvollstaendig, uebersprungen)")
            continue
        pro[f"hop{i}"] = d
        gesamt += d.get("delay_summe", 0.0)
        anz += d.get("delay_anzahl", 0)
json.dump({"pro_hop": pro, "delay_summe_s": round(gesamt, 3), "delay_anzahl": anz,
           "delay_mittel_s": round(gesamt / anz, 4) if anz else None}, open(ziel, "w"), indent=1)
print(f"Mix-Delay -> {ziel}: Summe {gesamt:.1f}s ueber {anz} gezogene Verzoegerungen")
PY

echo "== $LABEL fertig: $DATA/${LABEL}_{sink,client}.jsonl + _ressourcen.json + _delay.json =="
head -2 "$DATA/${LABEL}_client.jsonl" 2>/dev/null
