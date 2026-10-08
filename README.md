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

Die App enthält keine Anmeldung. Sie darf nur hinter einer privaten
Zugangsschicht wie Tailscale bereitgestellt werden.

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

- Namenssuche über alle importierten Personen
- Eltern, Geschwister, Partner und Kinder als zugängliche Links
- Lebensereignisse mit vorhandenen GEDCOM-Quellenverweisen und Seitenangaben
- Verlobung und weitere Familienereignisse auf den beteiligten Personenseiten
- Verknüpfte Bilder und Dokumente aus GEDCOM-Medienobjekten
- Automatischer Hell-/Dunkelmodus gemäß Geräteeinstellung
- Dauerhafte Startperson per privater Serveroption
- Getrenntes, nach Dateinamen durchsuchbares Dokumentenarchiv
- Deutliche Kennzeichnung fehlender Belege und offener Original-Zuordnungen

Noch nicht enthalten: Bearbeitung, GEDCOM-Export, geprüfte Verknüpfung zwischen
Archivscans und Fakten sowie eine grafische Mehrgenerationenansicht. Der Import
ist ein erster Leseimport und bildet nicht alle GEDCOM-Erweiterungen ab. Ein
angehängtes Dokument ist nicht automatisch ein formaler GEDCOM-Quellenverweis.
