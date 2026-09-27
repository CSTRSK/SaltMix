#!/bin/bash
# I2P-Messung: Java + offizieller I2P-Installer, Standardkonfiguration.
# I2P braucht 10-30 min Tunnel-Warmup und ~400 MB RAM. Wenn das im Zeitfenster
# nicht klappt, wird das ERGEBNIS als "nicht gemessen" mit Grund dokumentiert
# (statt Zahlen zu erfinden).
set -u
HIER="$(cd "$(dirname "$0")" && pwd)"
DATA="$(cd "$HIER/.." && pwd)/data"
WORK=/tmp/i2p-bench
mkdir -p "$WORK" "$DATA"
WARMUP_MAX=${1:-900}          # Sekunden, die auf Tunnel gewartet wird
ANZAHL=${2:-300}
RATE=${3:-20}

echo "== Java pruefen/installieren =="
command -v java >/dev/null 2>&1 || dnf install -y java-17-openjdk-headless 2>&1 | tail -2
java -version 2>&1 | head -1

echo "== I2P-Installer besorgen =="
cd "$WORK"
if [ ! -f i2pinstall.jar ]; then
  URL=$(timeout 25 curl -s https://geti2p.net/en/download | grep -oE 'https://[^"]*i2pinstall_[0-9._]+\.jar' | head -1)
  if [ -z "$URL" ]; then
    echo "  Download-URL nicht gefunden"
  else
    echo "  $URL"
    timeout 120 curl -sL -o i2pinstall.jar "$URL"
  fi
fi
if [ ! -s i2pinstall.jar ]; then
  python3 - "$DATA/i2p_nicht_gemessen.json" <<'PY'
import json, sys
json.dump({"status": "nicht gemessen",
           "grund": "I2P-Installer nicht beziehbar (geti2p.net nicht parsebar/erreichbar). "
                    "Kein I2P-Paket in AlmaLinux 9 (EPEL/RPMfusion geprueft).",
           "datum": "2026-09-27"}, open(sys.argv[1], "w"), indent=1)
PY
  exit 0
fi

echo "== I2P installieren =="
java -jar i2pinstall.jar -console <<< $'\n1\n1\n\n\n\n' > install.log 2>&1 || true
I2P_BIN=$(find "$WORK" -name i2prouter -type f 2>/dev/null | head -1)
if [ -z "$I2P_BIN" ]; then
  echo "  Installation nicht erfolgreich (kein i2prouter gefunden)"
  python3 - "$DATA/i2p_nicht_gemessen.json" <<'PY'
import json, sys
json.dump({"status": "nicht gemessen",
           "grund": "Konsoleninstallation des I2P-Installers in dieser Umgebung nicht erfolgreich.",
           "datum": "2026-09-27"}, open(sys.argv[1], "w"), indent=1)
PY
  exit 0
fi

echo "== I2P starten und auf Tunnel warten (max ${WARMUP_MAX}s) =="
"$I2P_BIN" start > "$WORK/start.log" 2>&1 &
I2P_PID=$!
BEREIT=0
for i in $(seq 1 $((WARMUP_MAX / 15))); do
  if timeout 10 curl -s -x 127.0.0.1:4444 -o /dev/null "http://example.com/" 2>/dev/null; then
    BEREIT=1; break
  fi
  sleep 15
done

if [ "$BEREIT" -eq 0 ]; then
  echo "  Tunnel nach ${WARMUP_MAX}s nicht bereit"
  python3 - "$DATA/i2p_nicht_gemessen.json" "$WARMUP_MAX" <<'PY'
import json, sys
json.dump({"status": "nicht gemessen",
           "grund": f"I2P-Tunnel innerhalb von {sys.argv[2]}s nicht aufgebaut "
                    "(Standardkonfiguration, kein Tuning). Fuer belastbare Zahlen "
                    "braucht I2P deutlich laengeren Warmup.",
           "datum": "2026-09-27"}, open(sys.argv[1], "w"), indent=1)
PY
  "$I2P_BIN" stop > /dev/null 2>&1
  exit 0
fi

echo "== I2P-Messung ueber HTTP-Proxy 127.0.0.1:4444 =="
(
  while true; do
    for pid in $(pgrep -f -i "i2p" | head -20); do
      cpu=$(awk '{print $14+$15}' "/proc/$pid/stat" 2>/dev/null || echo 0)
      rss=$(awk '/VmRSS/{print $2}' "/proc/$pid/status" 2>/dev/null || echo 0)
      echo "$(date +%s.%N) $pid $cpu $rss"
    done
    sleep 1
  done
) > "$DATA/i2p_ressourcen.txt" 2>/dev/null &
RESS=$!

# messe.py kann nur SOCKS; I2P bietet HTTP-Proxy -> einfacher curl-basierter Lauf
python3 - "$ANZAHL" "$DATA/i2p.jsonl" <<'PY'
import json, subprocess, sys, time
anzahl, ziel = int(sys.argv[1]), sys.argv[2]
zeiten = []
t0 = time.perf_counter()
for i in range(anzahl):
    t1 = time.perf_counter()
    subprocess.run(["curl", "-s", "-x", "127.0.0.1:4444", "-o", "/dev/null",
                    "--max-time", "120", "http://example.com/"], check=False)
    zeiten.append({"msg_id": i, "latenz_s": time.perf_counter() - t1, "t": time.time()})
    soll = t0 + (i + 1) / 20
    if (w := soll - time.perf_counter()) > 0:
        time.sleep(w)
with open(ziel, "w") as f:
    for e in zeiten:
        f.write(json.dumps(e) + "\n")
print(f"{ziel}: {len(zeiten)} Anfragen")
PY
kill "$RESS" 2>/dev/null
"$I2P_BIN" stop > /dev/null 2>&1
echo "== I2P fertig =="
