# SiliconNet

[English](README.md) · [Türkçe](README.tr.md) · **Deutsch**

Ein lokaler DPI-Umgehungsproxy für macOS. Er läuft auf Ihrem eigenen Mac,
lauscht auf `127.0.0.1` und leitet die von Ihnen konfigurierten Seiten über
einen lokalen Proxy, der das TLS-ClientHello fragmentiert — so kann eine
Deep-Packet-Inspection-Box den Servernamen nicht lesen und die Verbindung nicht
verwerfen.

![macOS 12+](https://img.shields.io/badge/macOS-12%2B-black)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![License MIT](https://img.shields.io/badge/License-MIT-green)

## Wozu es dient

Manche Netzwerke sperren Seiten anhand des `SNI`-Felds im TLS-Handshake — des
Servernamens, den Ihr Browser im Klartext sendet, bevor die Verschlüsselung
beginnt — und setzen die Verbindung zurück, sobald er auf einer Sperrliste
steht. Dieselben Netzwerke vergiften häufig auch das DNS, sodass die Domain auf
eine Sperrseite statt auf den echten Server auflöst.

SiliconNet adressiert beides:

- **DNS over HTTPS.** Konfigurierte Domains werden über einen verschlüsselten
  DoH-Resolver aufgelöst, eine vergiftete lokale DNS-Antwort wird nie benutzt.
- **TLS-Record-Fragmentierung.** Das ClientHello wird auf zwei TLS-Records
  aufgeteilt; eine DPI-Box, die nur einen Record prüft, sieht den vollständigen
  Servernamen nie. Fünfundzwanzig Strategien stehen bereit; die Engine misst,
  welche in Ihrem Netz funktioniert, und behält sie bei.

Nur die von Ihnen gelisteten Seiten laufen über den Proxy. Alles andere
verbindet sich normal.

**Dies ist kein VPN und kein Anonymisierungswerkzeug.** Es verbirgt Ihre
IP-Adresse nicht; die besuchte Seite sieht weiterhin Ihre echte Adresse. Es
ändert lediglich, *wie* die Verbindung geöffnet wird, damit ein Filter
dazwischen sie nicht einordnen kann. Nutzen Sie es nur, wo es Ihnen erlaubt ist.

## Voraussetzungen

| | |
|---|---|
| Betriebssystem | macOS 12 Monterey oder neuer — **nur macOS**, es gibt keine Windows- oder Linux-Version |
| Python | 3.10+ (Homebrew, python.org oder Command Line Tools) |
| Rechte | Keine bei einem Admin-Konto; bei einem Standardkonto fragt macOS einmal nach dem Passwort |

Der Launcher installiert die Python-Pakete (`pystray`, `Pillow`, PyObjC) in eine
lokale virtuelle Umgebung. Es wird nichts systemweit installiert, kein Dienst
eingerichtet und nichts läuft als root.

## Installation

```bash
git clone https://github.com/erkmenboz/siliconnet.git
cd siliconnet
./siliconnet-launcher.sh
```

Im Finder können Sie auch **`SiliconNet.command`** doppelklicken; damit öffnet
sich das Terminal und derselbe Launcher wird ausgeführt.

Beim ersten Start wird `.venv` erstellt und die Abhängigkeiten werden
installiert. Schlägt `python3 -m venv` fehl, installieren Sie die Command Line
Tools:

```bash
xcode-select --install
```

Wenn Sie statt zu klonen ein fertiges Archiv geladen haben, kann macOS es unter
Quarantäne stellen:

```bash
xattr -dr com.apple.quarantine siliconnet-macos-<version>
```

## Verwendung

Sobald es läuft:

- Das **Menüleistensymbol** erscheint oben rechts neben WLAN und Uhr. Ein
  einzelner Klick öffnet das Menü — Status, Ping, Dashboard, Neustart, Beenden.
- Das **Dashboard** liegt unter **<http://127.0.0.1:8888>**.

Im Dashboard fügen Sie die zu leitenden Domains hinzu, sehen, welche Strategie
gewinnt, und wechseln Sprache (EN/TR/DE) sowie Erscheinungsbild (hell/dunkel).

**Automatisch bei der Anmeldung starten:** Dashboard → **Einstellungen** →
**Autostart**. Das installiert einen LaunchAgent auf Benutzerebene in
`~/Library/LaunchAgents`. Verschieben Sie den Projektordner danach nicht — der
Agent speichert den vollständigen Pfad.

**Beenden:** Menüleiste → **Exit**. Das Terminalfenster zu schließen genügt
nicht; beim Beenden müssen Ihre Proxy-Einstellungen wiederhergestellt werden.

## Funktionsweise

SiliconNet schreibt den HTTP- und HTTPS-Proxy jedes aktiven Netzwerkdienstes mit
dem mitgelieferten Werkzeug `networksetup`, sichert die vorherigen Werte in
`macos_proxy_state.json` und stellt sie beim Beenden wieder her.

Auf den meisten privaten Macs ist der angemeldete Benutzer Administrator, und
`networksetup` übernimmt die Änderung ohne Passwort. Verweigert macOS sie — bei
einem Standardkonto oder der Option „Administratorpasswort verlangen" — wird
derselbe Befehlssatz einmalig über `osascript … with administrator privileges`
wiederholt, was den systemeigenen Passwortdialog zeigt. Brechen Sie ihn ab,
bleiben Ihre Einstellungen unangetastet.

Manche Programme bringen einen eigenen HTTP-Stack mit und ignorieren die
macOS-Proxy-Einstellung vollständig (der Updater von Discord ist der typische
Fall). Solange SiliconNet den Proxy verwaltet, veröffentlicht es zusätzlich
`HTTP_PROXY`/`HTTPS_PROXY` in der launchd-Sitzung, damit danach gestartete
Programme den Proxy erreichen. Beides wird beim Beenden zurückgenommen.

### Wo Ihre Daten liegen

```text
~/Library/Application Support/SiliconNet
```

| Datei | Zweck |
|---|---|
| `config.json` | Seiten, Ports, Datenschutz- und Leistungseinstellungen |
| `bypass.log` | Warn-/Fehlerprotokoll (für Details `DPI_BYPASS_LOG_LEVEL=INFO`) |
| `macos_proxy_state.json` | Ihr vorheriger Proxy-Zustand, beim Beenden wiederhergestellt |
| `strategy_cache.json` | Welche Strategie für welche Seite funktioniert |
| `ai_strategy.json` | Daten des adaptiven Strategielernens |
| `stats.json` | Laufzeitzähler |

LaunchAgent-Protokolle landen in `~/Library/Logs/SiliconNet/`. Nichts wird
irgendwohin gesendet; alles bleibt auf Ihrem Mac. Siehe
[PRIVACY.md](PRIVACY.md).

## Fehlerbehebung

**Kein Internet, nachdem SiliconNet unerwartet beendet wurde.** Ihr System-Proxy
zeigt möglicherweise noch auf einen Port, auf dem nichts lauscht. Starten Sie
SiliconNet erneut — es erkennt und bereinigt eine verwaiste Einstellung beim
Start — oder schalten Sie den Proxy manuell ab:

```bash
networksetup -setwebproxystate Wi-Fi off
networksetup -setsecurewebproxystate Wi-Fi off
```

**Eine Seite öffnet sich weiterhin nicht.** Programme, die *vor* dem Aktivieren
des Proxys gestartet wurden, haben die Einstellung womöglich nicht übernommen;
beenden und erneut öffnen. Browser lesen die Proxy-Einstellung beim Start,
beenden Sie den Browser daher vollständig (⌘Q), statt nur das Fenster zu
schließen.

**Kein Menüleistensymbol.** Dafür werden `pystray`, `Pillow` und PyObjC
benötigt, die der Launcher in `.venv` installiert. Starten Sie die Anwendung mit
einem anderen Interpreter, wird das Symbol übersprungen und alles andere
funktioniert weiter. Auf einem MacBook mit Notch kann eine volle Menüleiste das
Symbol ebenfalls verdecken — das Dashboard bleibt unter der obigen Adresse
erreichbar.

**Sehen, was passiert:** mit `DPI_BYPASS_LOG_LEVEL=INFO ./siliconnet-launcher.sh`
starten oder im Dashboard den Reiter **Logs** öffnen.

## Bauen und prüfen

```bash
./run_tests.sh                      # Testsuite
scripts/build_macos_release.sh      # sauberes Archiv in dist/
scripts/verify_macos_release.sh     # Tests + Paketierungsprüfungen
```

## Danksagung und Lizenz

SiliconNet steht unter der MIT-Lizenz.

Proxy-Kern, Strategie-Engine und Dashboard sind von CleanNet abgeleitet (MIT,
Copyright © 2026 digaxie). Der ursprüngliche Copyright-Hinweis bleibt in
[LICENSE](LICENSE) erhalten.

Die macOS-Integrationsschicht wurde für dieses Projekt geschrieben:
Proxy-Verwaltung über `networksetup`, Autostart per LaunchAgent, der
`lsof`-basierte Flow-Parser, das Menüleistensymbol und die Kompatibilitäts-
schicht für Umgebungsvariablen.
