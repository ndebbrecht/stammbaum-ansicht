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

## Aktueller Umfang

- Namenssuche über alle importierten Personen
- Eltern, Geschwister, Partner und Kinder als zugängliche Links
- Lebensereignisse mit vorhandenen GEDCOM-Quellenverweisen und Seitenangaben
- Getrenntes, nach Dateinamen durchsuchbares Dokumentenarchiv
- Deutliche Kennzeichnung fehlender Belege und offener Original-Zuordnungen

Noch nicht enthalten: Bearbeitung, GEDCOM-Export, geprüfte Verknüpfung zwischen
Archivscans und Fakten sowie eine grafische Mehrgenerationenansicht. Der Import
ist ein erster Leseimport und bildet nicht alle GEDCOM-Erweiterungen ab.
