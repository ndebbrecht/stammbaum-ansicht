# Stammbaum-Ansicht

Eine mobile, tastatur- und Screenreader-taugliche Leseansicht für GEDCOM 5.5.1.
Personen, Familien, Ereignisse, GEDCOM-Quellen und Dokumente aus einem privaten
Archiv werden angezeigt. Die App verändert weder GEDCOM noch Originaldateien.

## Datenschutz

Dieses Repository enthält ausschließlich Programmcode und synthetische
Beispieldaten. Echte GEDCOM-Dateien, SQLite-Datenbanken, Belege, Screenshots und
Protokolle dürfen **niemals** in das öffentliche Repository oder dessen
Git-Historie gelangen. Datenbank und Archiv müssen außerhalb des Checkouts
liegen. `.gitignore` ist nur eine zusätzliche Sicherung, kein Ersatz für die
Prüfung vor dem Veröffentlichen.

Der Passwortschutz ist optional. Ohne ihn darf die App nur hinter einer
privaten Zugangsschicht wie Tailscale laufen. Für öffentlichen Betrieb sind
Passwortschutz **und HTTPS** erforderlich; der eingebaute HTTP-Server stellt
selbst kein TLS bereit. Ein Reverse-Proxy sollte zusätzlich Rate-Limits setzen.

## Docker Compose

Die Beispielkonfiguration verwendet ausschließlich synthetische Daten:

```sh
cp .env.example .env
docker compose up --build -d
```

Für eigene Daten in `.env` mindestens `GEDCOM_PATH` auf die **Datei** des
Exports setzen. `MEDIA_ROOT` ist der Ordner mit den im GEDCOM genannten
Bild-/PDF-Dateien, `ARCHIVE_ROOT` der zusätzliche Dokumentenordner. Alle
Pfade dürfen absolut sein; echte Daten bleiben außerhalb des öffentlichen
Repositorys. Der Import läuft bei **jedem Containerstart** und ersetzt die
private SQLite-Datenbank erst nach erfolgreichem Import. Die Originale werden
nur lesend eingebunden. `PORT` ist standardmäßig 8765 und wird aus
Sicherheitsgründen nur auf `127.0.0.1` des Docker-Hosts veröffentlicht.
Für Zugriff im vertrauenswürdigen lokalen Netzwerk kann zusätzlich
`compose.lan.yaml` verwendet werden. `LAN_ADDRESS` ist die lokale IPv4-Adresse
des Docker-Hosts; der Loopback-Zugriff bleibt dabei erhalten:

```sh
LAN_ADDRESS=192.0.2.10 docker compose -f compose.yaml -f compose.lan.yaml up --build -d
```

Die Beispieladresse muss durch die eigene LAN-Adresse ersetzt werden. Im
Browser eines anderen Geräts im selben Netzwerk dann
`http://LAN_ADDRESS:PORT/` öffnen. Die LAN-Freigabe ist **nicht** durch
Tailscale geschützt; ohne aktivierten Passwortschutz kann jedes Gerät mit
Zugriff auf dieses Netzwerk die privaten Daten lesen. Für fremde oder geteilte
Netze daher den optionalen Passwortschutz und HTTPS über einen Reverse-Proxy
verwenden. Keine Router-Portweiterleitung für diesen HTTP-Port einrichten.
`FEATURED_PERSON_ID` setzt die Startperson. Die Datenbank liegt in einem
benannten Docker-Volume; `restart: unless-stopped` sorgt für Wiederanlauf.
Auf macOS muss zusätzlich Docker Desktop beim Anmelden gestartet werden; die
Compose-Neustartregel allein startet Docker Desktop nicht.

Optionaler Passwortschutz mit Benutzername `stammbaum`:

```sh
mkdir -p /privater/pfad/stammbaum-auth
python3 auth.py --output /privater/pfad/stammbaum-auth/password.hash
```

Danach `AUTH_DIR=/privater/pfad/stammbaum-auth` und `AUTH_ENABLED=1` in der
privaten `.env` setzen und den Container neu starten. Das Passwort wird
interaktiv eingegeben und nur als PBKDF2-Hash gespeichert. Fehlt bei aktiviertem
Schutz die Hashdatei, startet die App nicht. Die HTTP-Basic-Anmeldung schützt
auch Bilder, PDFs und CSS. Für Internetzugriff ist HTTPS vor dem Container
zwingend, da Basic-Anmeldedaten sonst auf dem Transportweg lesbar sind.

Eine optionale private Datei `CONFIG_DIR/source_links.json` verbindet
GEDCOM-Quellen kontrolliert mit Dateien unter `ARCHIVE_ROOT`:

```json
{
  "sources": [
    {
      "source_id": "S1",
      "path": "register/beispiel.pdf",
      "page": 3,
      "status": "verified",
      "note": "Original geprüft",
      "transcription": "Beispieltext"
    }
  ]
}
```

`CONFIG_DIR` auf den privaten Ordner setzen. `path` ist relativ zum Archivroot.
`status` ist `suggested` oder `verified`; die App behauptet nie selbst, eine
Zuordnung sei geprüft. Unbekannte Quellen/Dateien oder ungültige Seitenzahlen
lassen den Import fehlschlagen, die bisherige Datenbank bleibt erhalten.
Sind Quellenmedien und Archivdateien byte-identisch, verknüpft der Import sie
auch automatisch anhand von SHA-256. Das bestätigt die **Dateiidentität**, nicht
die historische Aussage des Dokuments.

Bei Netzlaufwerken kann Docker Desktop eine umfangreiche SMB-Freigabe beim
Inventarisieren überlasten. Dann das Archiv zuerst auf dem Host inventarisieren
und aus der privaten Datenbank ein Manifest unter `CONFIG_DIR` erzeugen:

```sh
python3 export_archive_index.py --database /privat/stammbaum.sqlite --output /privat/config/archive-index.jsonl
```

Beim Containerstart wird dieses Manifest verwendet, sofern vorhanden; Docker
läuft dann nicht durch den gesamten Archivbaum. Nach Änderungen am Archiv muss
das Manifest aktualisiert werden. Einzelne Originaldateien bleiben weiterhin
unter `ARCHIVE_ROOT` nur lesend eingebunden.

## Lokal starten

Python 3.9 oder neuer genügt; es gibt keine Laufzeit-Abhängigkeiten.

```sh
python3 import_data.py --gedcom examples/beispiel.ged --database /tmp/stammbaum-beispiel.sqlite
python3 app.py --database /tmp/stammbaum-beispiel.sqlite --host 127.0.0.1 --port 8765
```

Für eigene Daten `--gedcom` und `--database` auf private Pfade außerhalb des
Repositorys setzen. Mit `--archive-root` beim Import und beim Serverstart wird
ein Dokumentenordner inventarisiert und lesend angezeigt. Die Inventarisierung
weist Dateien **nicht** automatisch Personen oder GEDCOM-Quellen zu.

GEDCOM-Mediendateien liegen ebenfalls außerhalb des Repositorys. `--media-root`
am Server verweist auf den privaten Ordner mit den im GEDCOM genannten Dateien.
Nur direkte, gültige Dateinamen im Ordner werden ausgeliefert; fehlende Medien
werden als solche gekennzeichnet. Mit `--featured-person-id` wird eine Person
aus der privaten Datenbank dauerhaft auf der Startseite hervorgehoben. Die ID
gehört in die private Serverkonfiguration, nicht in den öffentlichen Code.

## Aktueller Umfang

- Personensuche nach Name, Ereignisort, Ereignisjahr und vorhandenem oder fehlendem GEDCOM-Quellenverweis
- Personenseiten mit seitlichen Eltern- und Kinderkacheln, Partner direkt neben dem Namen und Geschwistern in eigenen, anklickbaren Kacheln; auf schmalen Bildschirmen ohne seitliches Scrollen gestapelt
- Verfügbare Personenbilder als Profilbild und kleine Vorschau bei Eltern, Kindern, Geschwistern und Partnern; Quellen in Übersichten nur als Büroklammer-Link, ausgeschriebene Angaben auf der Ereignis- bzw. Quellenseite
- Eigene Ereignisseiten und eine durchsuchbare Ereignisliste; Ortsangaben kürzen Bundesländer und Länder ab (z. B. NI, DE). Karten erscheinen als eingebettete Kachel auf der Ereignisseite, werden nur nach Klick geladen und übermitteln dann den vollständigen Ereignisort an Google Maps.
- Kompakter Familienbaum mit wählbarer Tiefe (2–5), nach Generationen geordneten Vorfahren und Nachkommen sowie aufklappbaren, semantisch verschachtelten Familienlinien; dazu kürzester Verbindungsweg zwischen zwei Personen
- Ereignisdetails mit GEDCOM-Quellenverweis, Belegstelle und getrenntem Scanstatus. Ein einzelner Scan der Quelle wird verlinkt; bei mehreren Dateien ohne passende Seitenzuordnung wird keine ereignisspezifische Datei behauptet.
- Import und Anzeige von GEDCOM-Notizen, Repositorien, weiteren Beziehungen sowie zusätzlichen Ereignistypen wie Einwanderung und Adoption
- Verlobung und weitere Familienereignisse auf den beteiligten Personenseiten
- Verknüpfte Bilder und Dokumente aus GEDCOM-Medienobjekten
- Automatischer Hell-/Dunkelmodus gemäß Geräteeinstellung
- Reduziertes Archivdesign mit klaren Datenbereichen, sichtbaren Tastaturfokussen und responsiver Darstellung ohne seitliches Scrollen
- Dauerhafte Startperson per privater Serveroption
- Getrenntes, nach Dateinamen durchsuchbares Dokumentenarchiv
- Getrennte Kennzeichnung fehlender formaler Quellenverweise, angehängter Medien und offener Original-Zuordnungen
- Quellenübersicht mit Anzahl der verknüpften Archivdateien und bei Ereignissen zitierten Quellen

Noch nicht enthalten: Bearbeitung und GEDCOM-Export. Die Baumansicht zeigt
jeweils bis zu fünf Generationen um eine Ausgangsperson, keinen vollständigen
interaktiven Gesamtbaum. Bei sehr großen Familienlinien begrenzt sie die
Anzeige auf 250 Personen je Richtung und erlaubt das Weiterwandern über
eine neue Ausgangsperson. Generationskarten ordnen sich auf schmalen
Bildschirmen neu an, ohne seitliches Scrollen zu erfordern; die einzelnen Namen
bleiben per Tastatur erreichbar. Die aufklappbare Familienliste zeigt die
genauen Verzweigungen, die kompakten Generationskarten nur die Ebene.
Der Import bildet nicht alle GEDCOM-Erweiterungen ab; insbesondere proprietäre
MacFamilyTree-Felder werden noch nicht vollständig interpretiert. Orts- und
Jahresfilter suchen in den textuellen Ereignisangaben, nicht in normierten
Kalenderdaten. Ein angehängtes Dokument ist nicht automatisch ein formaler
GEDCOM-Quellenverweis.
