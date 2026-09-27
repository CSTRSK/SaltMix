#!/bin/bash
# Tor-Messung, zwei Modi:
#   public  : oeffentliches Tor-Netz, Standardkonfiguration (3 Hops), Ziel extern
#             + Direktvergleich zum selben Ziel (ohne Tor) als Basislinie
#   chutney : lokales Tor-Testnetz (networks/basic, 3 Verzeichnisautoritaeten
#             + 5 Relays, Client-Circuit 3 Hops) -> direkt vergleichbar mit
#             dem lokalen SaltMix-Aufbau
set -u
HIER="$(cd "$(dirname "$0")" && pwd)"
DATA="$(cd "$HIER/.." && pwd)/data"
mkdir -p "$DATA"
MODUS=${1:?public|chutney}
ZIEL_EXTERN="http://example.com/"
ZIEL_LOKAL="${ZIEL_LOKAL:-127.0.0.1:8088}"   # ggf. eigene erreichbare Adresse setzen
ANZAHL=${2:-300}
RATE=${3:-20}

case "$MODUS" in
public)
  TORRC=/tmp/tor-bench/torrc
  mkdir -p /tmp/tor-bench
  cat > "$TORRC" <<EOF
SocksPort 9050
DataDirectory /tmp/tor-bench/data
Log notice file /tmp/tor-bench/tor.log
EOF
  pkill -f "tor -f $TORRC" 2>/dev/null
  tor -f "$TORRC" > /tmp/tor-bench/stdout.log 2>&1 &
  TOR_PID=$!
  echo "== warte auf Tor-Bootstrap =="
  for i in $(seq 1 60); do
    grep -q "Bootstrapped 100%" /tmp/tor-bench/tor.log 2>/dev/null && break
    sleep 3
  done
  grep "Bootstrapped" /tmp/tor-bench/tor.log | tail -1

  echo "== Ressourcen-Sampling startet =="
  (
    while [ -d "/proc/$TOR_PID" ]; do
      cpu=$(awk '{print $14+$15}' "/proc/$TOR_PID/stat" 2>/dev/null || echo 0)
      rss=$(awk '/VmRSS/{print $2}' "/proc/$TOR_PID/status" 2>/dev/null || echo 0)
      echo "$(date +%s.%N) 0 $cpu $rss"
      sleep 1
    done
  ) > "$DATA/tor_public_ressourcen.txt" &

  echo "== Direktvergleich (ohne Tor) =="
  python3 "$HIER/messe.py" --ziel example.com:80 --methode GET --anzahl "$ANZAHL" --rate "$RATE" \
    --aus "$DATA/direkt_extern.jsonl" | tail -1

  echo "== Tor (oeffentlich, 3 Hops) =="
  python3 "$HIER/messe.py" --ziel example.com:80 --methode GET --socks 127.0.0.1:9050 \
    --anzahl "$ANZAHL" --rate "$RATE" --aus "$DATA/tor_public.jsonl" | tail -1
  kill "$TOR_PID" 2>/dev/null
  ;;
chutney)
  CH="${CHUTNEY_DIR:-$HOME/chutney}"
  cd "$CH"
  ./chutney stop networks/basic > /dev/null 2>&1
  echo "== chutney networks/basic starten (8 Tor-Prozesse, kann 2-4 min dauern) =="
  ./chutney start networks/basic 2>&1 | tail -3
  ./chutney wait_for_bootstrap networks/basic 2>&1 | tail -3 || true
  mapfile -t CLIENT_TORRCS < <(ls -d "$CH"/net/nodes/*client*/torrc 2>/dev/null | head -1)
  CLIENT_TORRC="${CLIENT_TORRCS[0]:-}"
  if [ -z "$CLIENT_TORRC" ]; then
    echo "  kein chutney-Client gefunden"; ./chutney stop networks/basic >/dev/null 2>&1; exit 1
  fi
  SOCKS=$(grep -i "^SocksPort" "$CLIENT_TORRC" | head -1 | awk '{print $2}' | cut -d' ' -f1)
  echo "  Client-Torrc: $CLIENT_TORRC, SocksPort: $SOCKS"
  grep -qi "ClientRejectInternalAddresses" "$CLIENT_TORRC" || \
    echo "ClientRejectInternalAddresses 0" >> "$CLIENT_TORRC"
  ./chutney stop networks/basic > /dev/null 2>&1
  ./chutney start networks/basic > /dev/null 2>&1
  ./chutney wait_for_bootstrap networks/basic > /dev/null 2>&1 || true

  echo "== Ressourcen aller chutney-Tor-Prozesse =="
  (
    while true; do
      for pid in $(pgrep -f "chutney/net/nodes"); do
        cpu=$(awk '{print $14+$15}' "/proc/$pid/stat" 2>/dev/null || echo 0)
        rss=$(awk '/VmRSS/{print $2}' "/proc/$pid/status" 2>/dev/null || echo 0)
        echo "$(date +%s.%N) $pid $cpu $rss"
      done
      sleep 1
    done
  ) > "$DATA/tor_chutney_ressourcen.txt" 2>/dev/null &
  RESS=$!

  ZIEL="$ZIEL_LOKAL"
  if ! python3 "$HIER/messe.py" --ziel "$ZIEL_LOKAL" --anzahl 5 --aufwaermen 0 --rate 0 \
        --socks "127.0.0.1:$SOCKS" --aus /tmp/chutney_probe.jsonl > /dev/null 2>&1; then
    echo "  interno Adresse vom Circuit abgelehnt -> nehme oeffentliche IP"
    ZIEL="${ZIEL_OEFFENTLICH:-$ZIEL_LOKAL}"
  fi
  echo "== chutney-Messung (Ziel $ZIEL) =="
  python3 "$HIER/messe.py" --ziel "$ZIEL" --socks "127.0.0.1:$SOCKS" \
    --anzahl "$ANZAHL" --rate "$RATE" --aus "$DATA/tor_chutney.jsonl" | tail -1
  python3 "$HIER/messe.py" --ziel "$ZIEL" --anzahl "$ANZAHL" --rate "$RATE" \
    --aus "$DATA/direkt_lokal.jsonl" | tail -1
  kill "$RESS" 2>/dev/null
  cd "$CH" && ./chutney stop networks/basic > /dev/null 2>&1
  ;;
*)
  echo "Modus muss public oder chutney sein"; exit 1;;
esac
echo "== Tor-$MODUS fertig =="
