# SaltMix Latenz-Benchmark gegen Tor

**Testdatum:** 27.09.2026, 23:21–23:40 UTC
**Status:** SaltMix ist ein Proof of Concept. Diese Zahlen messen den **Latenzpreis**
seiner Entwurfsentscheidungen, nicht einen Produktivvergleich.

---

## 1. Fairness-Hinweis (direkt bei den Ergebnissen, nicht im Anhang)

* **Kein Vergleich mit einem gleichartigen Mixnetz.** Der einzige geeignete
  Vergleichskandidat mit Mix-Verzögerung wäre Nym gewesen; die Messung ist
  fehlgeschlagen (Abschnitt 4). Der Vergleich mit Tor ist ein Vergleich mit
  einem **anderen Bedrohungsmodell**: Tor ist auf niedrige Latenz ausgelegt und
  hat keine künstliche Verzögerung, SaltMix ist auf Korrelationswiderstand
  ausgelegt und bezahlt ihn mit Verzögerung.
* **Der belastbare Vergleich ist der ohne Mix-Delay.** Nur dort wird dieselbe
  Sache gemessen: die Kosten eines 3-Hop-Circuits auf identischer Hardware.
  SaltMix liegt dabei mit 5,8 ms gegen 2,1 ms in **derselben Größenordnung** wie
  Tor — der Unterschied ist der Implementierungs- und Protokollaufwand des PoC,
  nicht dessen Mixing.
* **Die 2.700-fache Differenz der Standardkonfiguration ist keine
  Leistungsaussage.** Sie ist die eingestellte 2-Sekunden-Poisson-Verzögerung pro
  Hop, also die bewusste Entwurfsentscheidung. Sie steht hier, weil sie den Preis
  des Designs beziffert — nicht als Vergleich mit Tor.
* **Der Vergleich mit dem öffentlichen Tor-Netz ist ausdrücklich kein
  Qualitätsvergleich.** Dort hat Tor rund 7.000 Relays und echte geografische
  Strecken; SaltMix lief als 3 lokale Prozesse. Die Zahl zeigt den Unterschied
  zwischen Laboraufbau und weltweitem Netz.
* **SaltMix hat absichtlich keine Netzwerkschicht.** Der PoC übergibt ein
  `forward_fn`, es gibt keine Sockets. Für diese Messung ergänzt eine Harness TCP
  auf 127.0.0.1 und einen asyncio-Task pro Paket; die Mix-Logik (`peel_layer`,
  ReplayGuard, `mixing_delay`) stammt **unverändert** aus dem Repo. Nur
  `mixing_delay` wird zum Protokollieren mitgeschnitten.
* **Anonymität wird hier nicht gemessen.** Mit drei lokalen Prozessen existiert
  kein Anonymitätsset. Die Zahlen belegen den Preis des Designs, nicht seinen Nutzen.

## 2. Testaufbau

| Parameter | Wert |
|---|---|
| Hardware | IONOS VPS, AMD EPYC-Milan, 2 vCPU (1 Kern, 2 Threads), 1,5 GB RAM, AlmaLinux 9.8 |
| Hintergrundlast beim Start | Load 0,47 (NKN-Node läuft dauerhaft, trifft alle Netze gleich) |
| Nutzlast | 256 Byte pro Nachricht, alle Netze identisch |
| Nachrichten | 300 pro Netz, **Zielrate** 20/s (pro Netz definiert, siehe Ergebnistabelle) |
| SaltMix-Nodes | 3 Hops (Standard) und 7 Hops (Topologie-Variante), ein Prozess je Hop |
| SaltMix-Paketgröße | 412 Byte bei 3 Hops (256 Nutzlast + 48 Byte Salt+MAC pro Hop) |
| Tor (öffentlich) | 0.4.9.11, Standardkonfiguration, SOCKS5, keine Tuning-Parameter |
| Tor (chutney) | `networks/basic`: 3 Verzeichnisautoritäten, 8 Relays, 2 Clients; Circuit 3 Hops |
| Ziel | SaltMix: lokaler Sink · Tor: Zieladresse über Umgebungsvariable (`ZIEL_OEFFENTLICH`) |

## 3. Ergebnisse

| Netz | Median | p95 | p99 | Angebotene Last | Tatsächlich gesendet | Angekommen | CPU¹ | RAM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SaltMix 3 Hops, **Mix-Delay 1 ms** | **0,0058 s** | 0,0094 s | 0,0107 s | 20/s | 20,07/s | 300/300 | 1,30 % | 72,3 MB |
| Tor chutney, 3 Hops lokal | **0,0021 s** | 0,0033 s | 0,0190 s | 20/s | 20,07/s | 300/300 | 5,48 % | 403,5 MB |
| SaltMix 3 Hops, Mix-Delay 2,0 s | 5,638 s | 11,494 s | 15,880 s | 20/s | 20,07/s | 300/300 | 0,99 % | 72,7 MB |
| SaltMix 7 Hops, Mix-Delay 2,0 s | 13,2245 s | 22,7662 s | 24,7579 s | 20/s | 20,07/s | 295/300 (1,67 % Verlust) | 2,11 % | 169,8 MB |
| Tor öffentlich, 3 Hops | 0,0978 s | 0,1814 s | 0,2867 s | 20/s | **8,53/s** | 300/300 (kein Verlust) | 1,38 % | 95,3 MB |
| Direktvergleich lokal (ohne Tor) | 0,0002 s | 0,0003 s | 0,0008 s | 20/s | 20,07/s | 300/300 | — | — |
| Direktvergleich extern (ohne Tor) | 0,0041 s | 0,0053 s | 0,0064 s | 20/s | 20,07/s | 300/300 | — | — |
| Nym (Sandbox-Testnetz) | nicht messbar | | | | | | | |
| I2P | nicht messbar | | | | | | | |

¹ CPU in Prozent einer Kernstunde, summiert über alle Prozesse des Netzes,
sekündlich abgetastet. SaltMix: 3 bzw. 7 Node-Prozesse. chutney: 10 Tor-Prozesse.
Tor öffentlich: ein Prozess.

**Zur Spalte „Tatsächlich gesendet":** Bei Tor öffentlich wurden 8,53/s statt der
angestrebten 20/s erreicht. Ursache ist nicht das Netz, sondern der Client: er
sendet sequenziell und wartet je Anfrage auf die Antwort (kein Pipelining), die
Rate ist damit durch die Round-Trip-Zeit begrenzt (1/0,117 s ≈ 8,5/s). Die
**Abschlussquote liegt bei 100 %** (300/300 angekommen), es ging nichts verloren.
Bei den SaltMix-Reihen sendet der Client ohne Warten, dort wurde die Zielrate
erreicht. Die Spalte misst also die **angebotene Last**, nicht die
Übertragungskapazität des Netzes.

**Zu p99 bei n=300:** Der p99 beruht auf den drei höchsten von 300 Werten und ist
damit eine sehr grobe Schätzung. Für belastbare Tail-Aussagen wären mindestens
einige Tausend Messungen nötig. Das gilt für alle Netze in dieser Tabelle.

### Der Vergleich ohne Mix-Delay (Hauptvergleich)

| | 3 Hops, lokal | über Direktpfad |
|---|---:|---:|
| SaltMix, Mix-Delay 1 ms | 5,8 ms | 0,0 ms |
| Tor chutney, Standard | 2,1 ms | 0,2 ms |
| Faktor | **2,8-fach** | — |

Auf identischer Hardware und Topologie, ohne künstliche Verzögerung, liegen beide
in derselben Größenordnung: SaltMix kostet rund das 2,8-Fache eines
Tor-Circuits. Der Aufwand des PoC ist damit messbar, aber nicht dramatisch.

### Der Vergleich mit Mix-Delay (Preis des Designs)

| | 3 Hops, lokal |
|---|---:|
| SaltMix, Mix-Delay 2,0 s | 5,638 s |
| Tor chutney, Standard | 0,0021 s |
| Faktor | 2.685-fach |

**Diese Zahl ist keine Leistungsaussage.** Tor hat keine Mix-Verzögerung; die
Differenz ist exakt der eingestellte Verzögerungswert des Designs. Sie zeigt, was
Korrelationswiderstand in diesem Entwurf kostet — nicht, wie gut der Code ist.

### Delay-Anteil getrennt

| Netz | Gesamtlatenz | Transport | Mix-Delay | Anteil |
|---|---:|---:|---:|---:|
| SaltMix 3 Hops | 5,638 s | 0,0058 s | **5,632 s** | **99,9 %** |
| Tor chutney | 0,0021 s | 0,0002 s | 0,0019 s Netzwerkpfad | — |
| Tor öffentlich | 0,0978 s | 0,0041 s | 0,0937 s Netzwerkpfad | — |

**Nachweis für SaltMix:** Die Mix-Nodes protokollieren jede gezogene Verzögerung.
960 Ziehungen mit Mittel **2,0199 s** (eingestellt: 2,0 s), Summe 1.939 s über
320 Nachrichten = 6,06 s pro Nachricht — gemessen 6,13 s Mittel. Die Theorie
(Erlang-3 bei Mittel 2,0 s je Hop mit drei Hops) sagt 6,0 s, gemessen 6,13 s (+2 %).

**Tor hat keine künstliche Mix-Verzögerung.** Die 2,1 ms im Testnetz bzw. 97,8 ms
im öffentlichen Netz sind reine Netzwerkstrecke.

### Reproduktion

```bash
# SaltMix (3 Hops, Standard-Delay), 300 Nachrichten bei 20/s
benchmarks/harness/run_saltmix.sh saltmix_3hops_delay2 3 2.0 300 20 256

# SaltMix ohne Mix-Delay (1 ms statt 0, weil mixing_delay(0) ZeroDivisionError wirft)
benchmarks/harness/run_saltmix.sh saltmix_3hops_1ms 3 0.001 300 20 256

# Tor öffentlich + Direktvergleich (Zieladresse setzen)
ZIEL_OEFFENTLICH=<erreichbare-adresse>:8088 benchmarks/harness/run_tor.sh public 300 20

# Tor-Testnetz (chutney) - Client-Ports stehen in <chutney-dir>/net/nodes/*/torrc
python3 benchmarks/harness/messe.py --ziel <adresse>:8088 --socks 127.0.0.1:9008 \
  --anzahl 300 --rate 20 --aus benchmarks/data/tor_chutney.jsonl

# Auswertung
benchmarks/harness/auswerten.py benchmarks/data/*_sink.jsonl
benchmarks/harness/ressourcen_auswerten.py benchmarks/data/*_ressourcen.*
```

Rohdaten liegen als JSONL (eine Zeile je Nachricht mit Latenz und Zeitstempel)
und JSON (Quantile, Ressourcen, gezogene Delays) unter `benchmarks/data/`.

## 4. Warum Nym und I2P fehlen

* **Nym:** Das Sandbox-Testnetz ist erreichbar (10 Nodes), der SOCKS5-Client ist
  installiert. Der `--provider` verlangt das vollständige Nym-Adressformat
  (`identität.verschlüsselung@gateway`); die Sandbox-API liefert nur die
  Identität, nicht die Verschlüsselungskomponente. Mainnet-Requests brauchen
  Bandwidth-Credits. Nach drei Versuchen abgebrochen, nicht gemessen.
  **Damit fehlt der eigentlich passende Vergleichspartner** (gleiches
  Bedrohungsmodell mit Mix-Delay).
* **I2P:** Kein Paket in AlmaLinux 9 (EPEL und RPMfusion geprüft). Ein manueller
  Java-Aufbau braucht rund 400 MB RAM zusätzlich und 10–30 Minuten Tunnel-Warmup —
  auf einem 1,5-GB-VPS nicht vertretbar. Nicht gemessen.

**Hinweis zur chutney-Messung:** Die ersten Versuche scheiterten an einer falschen
Pfadannahme im Messskript (chutney benennt Client-Knoten mit `c` am Ende, etwa
`net/nodes/008c`, nicht `*client*`). Nach der Korrektur bootstrappten beide
Clients auf 100 % und die Messung lief mit 0 % Verlust durch.

## 5. Einordnung

* **Ohne Mix-Delay ist SaltMix konkurrenzfähig:** 5,8 ms gegen 2,1 ms für einen
  3-Hop-Circuit auf derselben Maschine. Der PoC ist also nicht langsam, er ist
  absichtlich langsam konfiguriert.
* **Mit Mix-Delay kostet das Design 5,6 Sekunden** bei drei Hops. Das ist die
  2-Sekunden-Poisson-Verzögerung pro Hop, keine Implementierungsschwäche.
* **Die Ressourcen sind unauffällig:** 24,2 MB pro SaltMix-Node gegen 40,4 MB pro
  chutney-Tor-Prozess und 95,3 MB für einen öffentlichen Tor-Client.
* **Der Lastvergleich ist keine Kapazitätsaussage.** SaltMix erreichte die
  Zielrate, weil der Client ohne Warten sendet; Tor öffentlich wurde durch die
  sequenzielle Anfrage/Antwort-Kopplung auf 8,53/s begrenzt, ohne Verlust. Ein
  echter Sättigungstest steht aus.
* **Die Anonymitätsmenge ist hier null.** Drei lokale Prozesse bzw. acht Relays
  sind kein reales Anonymitätsset. Die Messung belegt ausschließlich den
  Latenzpreis.

## 6. Offene Punkte

1. **Nym nachholen** — ohne ihn fehlt der Vergleich mit gleichem Bedrohungsmodell.
2. **Sättigungstest** für SaltMix (mehrere parallele Absender) und Tor
   (parallele Verbindungen), um die Spalte „angebotene Last" zu einer
   Kapazitätsaussage zu machen.
3. SaltMix über mehrere Maschinen verteilen, damit WAN- statt Loopback-Latenz gemessen wird.
4. I2P auf einem Host mit genug RAM.
5. `mixing_delay(0)` sollte im Repo einen definierten Wert liefern statt
   `ZeroDivisionError` — der PoC wird sonst bei „Delay aus" unbenutzbar.
6. Mehr Wiederholungen (mindestens einige Tausend Nachrichten), damit p99
   belastbar wird.
