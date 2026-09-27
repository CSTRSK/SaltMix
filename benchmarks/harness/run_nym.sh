#!/bin/bash
# Nym-Messung ueber das Sandbox-Testnetz (kostenlos). Nutzt den mitgelieferten
# nym-socks5-client; die Mix-Delays kommen aus der Nym-Konfiguration und werden
# NICHT veraendert (Standardkonfiguration, wie vom Projekt ausgeliefert).
set -u
HIER="$(cd "$(dirname "$0")" && pwd)"
DATA="$(cd "$HIER/.." && pwd)/data"
NYM="${NYM_DIR:-$HOME/nym}"
WORK=/tmp/nym-bench
ANZAHL=${1:-300}
RATE=${2:-20}
mkdir -p "$WORK" "$DATA"

echo "== Sandbox-Umgebung holen =="
curl -sL -o "$WORK/sandbox.env" \
  "https://raw.githubusercontent.com/nymtech/nym/develop/envs/sandbox.env" || true
head -6 "$WORK/sandbox.env" 2>/dev/null

echo "== Netzwerk-Requester in der Sandbox suchen =="
curl -s -m 20 "https://sandbox-nym-api1.nymtech.net/api/v1/nym-nodes/described?size=60" \
  | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
except Exception as e:
    print('  API-Antwort nicht lesbar:', e); raise SystemExit(0)
kandidaten = []
for n in d.get('data', []):
    besch = n.get('description', {})
    rollen = besch.get('role') or besch.get('roles') or ''
    adresse = (besch.get('host_information', {}).get('keys', {}) or {}).get('ed25519', '')
    if 'requester' in str(rollen).lower() or 'requester' in json.dumps(besch).lower():
        kandidaten.append((n.get('node_id'), besch.get('host_information', {}).get('hostname'), adresse))
for k in kandidaten[:5]:
    print('  Requester-Kandidat:', k)
print(f'  gefunden: {len(kandidaten)}')
open('/tmp/nym-bench/requester.txt','w').write(kandidaten[0][2] if kandidaten else '')
"

REQ=$(cat "$WORK/requester.txt" 2>/dev/null || echo "")
if [ -z "$REQ" ]; then
  echo "  KEIN Netzwerk-Requester ueber die API gefunden."
  echo "  Nym wird als 'nicht gemessen' dokumentiert (Grund: kein oeffentlich"
  echo "  gelisteter Requester in der Sandbox erreichbar)."
  python3 - "$DATA/nym_nicht_gemessen.json" <<'PY'
import json, sys
json.dump({"status": "nicht gemessen",
           "grund": "Kein Netzwerk-Requester in der Sandbox-API gelistet; "
                    "ohne Requester ist kein Clearnet-Ziel erreichbar. "
                    "Mainnet wuerde Bandwidth-Credits (NYM) kosten.",
           "datum": "2026-09-27", "client": "nym-socks5-client v2026.18-essaouria"}, open(sys.argv[1], "w"), indent=1)
PY
  exit 0
fi

echo "== Nym-SOCKS5-Client starten (Requester $REQ) =="
rm -rf "$WORK/client"
"$NYM/nym-socks5-client" init --id bench --provider "$REQ" \
  --config-env-file "$WORK/sandbox.env" > "$WORK/init.log" 2>&1 || tail -5 "$WORK/init.log"
"$NYM/nym-socks5-client" run --id bench --config-env-file "$WORK/sandbox.env" \
  > "$WORK/run.log" 2>&1 &
NYM_PID=$!
sleep 25
grep -io "socks5.*127.0.0.1:[0-9]*\|Listening on.*" "$WORK/run.log" | tail -3
PORT=$(grep -oE "127\.0\.0\.1:[0-9]+" "$WORK/run.log" | head -1 | cut -d: -f2)
PORT=${PORT:-1080}
echo "  SOCKS5-Port: $PORT"

(
  while [ -d "/proc/$NYM_PID" ]; do
    cpu=$(awk '{print $14+$15}' "/proc/$NYM_PID/stat" 2>/dev/null || echo 0)
    rss=$(awk '/VmRSS/{print $2}' "/proc/$NYM_PID/status" 2>/dev/null || echo 0)
    echo "$(date +%s.%N) 0 $cpu $rss"; sleep 1
  done
) > "$DATA/nym_ressourcen.txt" &

echo "== Messung durch das Nym-Mixnetz (erwartet: Sekunden durch Mix-Delays) =="
python3 "$HIER/messe.py" --ziel example.com:80 --methode GET --socks "127.0.0.1:$PORT" \
  --anzahl "$ANZAHL" --rate "$RATE" --aufwaermen 5 --aus "$DATA/nym.jsonl" | tail -1
kill "$NYM_PID" 2>/dev/null
echo "== Nym fertig =="
