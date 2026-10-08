import base64
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from app import Handler, anniversaries_page, archive_file_page, archive_page, chronology_key, connection_path, database, event_page, events_page, exact_gedcom_day, export_page, export_record_page, families_page, family_graph, family_page, format_place, media_library_page, media_page, overview, person_page, place_page, places_page, reports_page, source_page, statistics_page, timeline_page, tree_page
from auth import hash_password, verify_password
from export_archive_index import export
from import_data import build


EXAMPLE = Path(__file__).parents[1] / "examples" / "beispiel.ged"


class FeatureTest(unittest.TestCase):
    def test_read_only_reports_count_records_and_only_exact_anniversaries(self):
        gedcom = """0 @I1@ INDI
1 NAME Ada /Beispiel/
1 BIRT
2 DATE 3 MAY 1880
2 PLAC Musterstadt
1 DEAT
2 DATE ABT 3 MAY 1950
0 @I2@ INDI
1 NAME Bea /Beispiel/
1 BIRT
2 DATE MAY 1882
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 MARR
2 DATE 20 MAY 1900
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            build(root / "family.ged", database_path)
            with database(database_path) as connection:
                self.assertIn('href="/reports/statistics"', reports_page(connection))
                statistics = statistics_page(connection)
                self.assertIn('<dt>Personen</dt><dd>2</dd>', statistics)
                self.assertIn('<dt>Ereignisse</dt><dd>4</dd>', statistics)
                self.assertIn('href="/?q=Beispiel"', statistics)
                self.assertIn('href="/?q=Ada"', statistics)
                self.assertIn('href="/events?q=Musterstadt"', statistics)
                may = anniversaries_page(connection, 5)
                self.assertIn("3. Mai", may)
                self.assertIn("20. Mai", may)
                self.assertIn("2 Jahrestage", may)
                self.assertNotIn("ABT 3 MAY", may)
                self.assertNotIn("MAY 1882", may)
                self.assertIn('href="/event/4"', may)
                self.assertIn('href="/family/F1"', families_page(connection, "Beispiel", 1))
                family = family_page(connection, "F1")
                self.assertIn('href="/person/I1"', family)
                self.assertIn('href="/person/I2"', family)
                self.assertIn('href="/event/4"', family)
                self.assertIn('href="/family/F1"', person_page(connection, "I1"))
                timeline = timeline_page(connection, "I1")
                self.assertIn('href="/timeline/I1"', person_page(connection, "I1"))
                self.assertLess(timeline.index('href="/event/1"'), timeline.index('href="/event/4"'))
                self.assertLess(timeline.index("Ohne eindeutiges Jahr"), timeline.index('href="/event/2"'))
        self.assertIsNone(exact_gedcom_day("29 FEB 1900"))
        self.assertIsNone(exact_gedcom_day("BET 1 JAN 1900 AND 2 JAN 1900"))
        self.assertEqual(chronology_key("MAY 1882"), (1882, 5, 0))
        self.assertIsNone(chronology_key("ABT 3 MAY 1950"))

    def test_event_source_and_external_media_details(self):
        gedcom = """0 @I1@ INDI
1 NAME Ada /Beispiel/
1 DEAT
2 DATE 1 JAN 1900
2 CAUS Beispielursache
2 AGNC Musterbehörde
2 SOUR @S1@
3 PAGE 12
1 OBJE @M1@
1 OBJE @M2@
0 @S1@ SOUR
1 TITL Musterquelle
1 DATE 1900
1 PLAC Musterstadt
1 AGNC Musterarchiv
1 REFN Signatur 7
1 REFT Kirchenbuch – Taufen
1 ABBR Kurzform
0 @M1@ OBJE
1 TITL Externes Musterbild
1 URL https://example.invalid/bild.jpg
1 DATE 1901
1 NOTE Mediennotiz
0 @M2@ OBJE
1 TITL Unsicherer Verweis
1 URL javascript:alert(1)
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            build(root / "family.ged", database_path)
            with database(database_path) as connection:
                fact = connection.execute("SELECT cause, agency FROM facts WHERE kind='Tod'").fetchone()
                self.assertEqual(tuple(fact), ("Beispielursache", "Musterbehörde"))
                profile = person_page(connection, "I1", root)
                event = event_page(connection, 1, root)
                for page in (profile, event):
                    self.assertIn("Todesursache", page)
                    self.assertIn("Beispielursache", page)
                    self.assertIn("Zuständige Stelle", page)
                self.assertIn('href="https://example.invalid/bild.jpg"', profile)
                self.assertIn('href="/media-info/M1"', profile)
                self.assertNotIn('href="javascript:', profile)
                medium = media_page(connection, "M1", root)
                self.assertIn("Externes Medium öffnen", medium)
                self.assertIn("1901", medium)
                self.assertIn("Mediennotiz", medium)
                self.assertIn('href="/person/I1"', medium)
                self.assertIn('href="/media-info/M1"', media_library_page(connection, "Externes", 1, root))
                self.assertNotIn('href="/media-info/M2"', media_library_page(connection, "Externes", 1, root))
                self.assertIn('href="/media-info/M1"', export_record_page(connection, 3))
                self.assertNotIn('href="javascript:', media_page(connection, "M2", root))
                source = source_page(connection, "S1", root)
                for field in ("Musterarchiv", "Signatur 7", "Kirchenbuch – Taufen", "Kurzform", "GEDCOM-Belegstelle: 12"):
                    self.assertIn(field, source)
                self.assertIn("keinem Archivscan", source)

    def test_all_export_records_remain_readable(self):
        gedcom = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Ada /Beispiel/
1 LABL @L1@
1 _UNSUPPORTED Beispielwert
1 BIRT
2 PLAC Musterstadt
0 _PLAC Musterstadt
1 _ALT Altstadt
1 MAP
2 LATI N52.123456
2 LONG E7.123456
0 _PLAC Musterstadt
1 _GEO Beispielsweise
0 @L1@ LABL
1 TITL Forschungsfall
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            counts = build(root / "family.ged", database_path)
            self.assertEqual((counts["export_records"], counts["places"], counts["labels"], counts["person_labels"]),
                             (6, 2, 1, 1))
            with database(database_path) as connection:
                reconstructed = ''.join(row[0] for row in connection.execute("SELECT raw_text FROM export_records ORDER BY id"))
                self.assertEqual(reconstructed, gedcom)
                self.assertIn("_UNSUPPORTED Beispielwert", export_record_page(connection, 2))
                self.assertIn("Felder und Verweise", export_record_page(connection, 2))
                self.assertIn('href="/export-record/5"', export_record_page(connection, 2))
                self.assertGreater(counts["export_nodes"], 0)
                self.assertIn("HEAD", export_page(connection, "", "", 1))
                self.assertIn("Musterstadt", places_page(connection, "", 1))
                self.assertIn("Altstadt", place_page(connection, 3))
                self.assertIn("Forschungsfall", person_page(connection, "I1"))
                self.assertIn("_UNSUPPORTED", person_page(connection, "I1"))
                self.assertIn("Ortsdatensatz", event_page(connection, 1))

    def test_uncommon_events_are_not_relegated_to_raw_export(self):
        gedcom = """0 @I1@ INDI
1 NAME Ada /Beispiel/
1 MISE
2 DATE 1 JAN 1900
2 PLAC Musterstadt
3 MAP
4 LATI N52.123456
4 LONG E7.123456
1 LATR
2 DATE 2 JAN 1900
1 MIAW Musterorden
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            counts = build(root / "family.ged", database_path)
            self.assertEqual(counts["facts"], 3)
            with database(database_path) as connection:
                profile = person_page(connection, "I1")
                self.assertIn("MacFamilyTree-Ereignis MISE", profile)
                self.assertIn("Letzte Ölung", profile)
                self.assertIn("Militärische Auszeichnung", profile)
                self.assertIn("Koordinaten aus dem GEDCOM", event_page(connection, 1))

    def test_export_details_and_event_icons_keep_readable_labels(self):
        gedcom = """0 @I1@ INDI
1 NAME Ada /Beispiel/
2 TYPE maiden
2 _CRE 1 JAN 2020
2 CHAN 2 JAN 2020
1 SEX F
1 _FID ABC12345
1 EMAIL ada@example.invalid
2 CHAN 3 JAN 2020
1 RELI Beispielglaube
2 _CRE 4 JAN 2020
1 _UNSUPPORTED Beispielwert
1 BIRT
2 DATE 1 JAN 1900
2 PLAC Musterstadt
0 _PLAC Musterstadt
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            build(root / "family.ged", database_path)
            with database(database_path) as connection:
                profile = person_page(connection, "I1")
                self.assertIn('class="detail-grid"', profile)
                for label in ("Name", "Geburtsname", "Geschlecht", "weiblich", "E-Mail", "Religion",
                              "ada@example.invalid", "Beispielglaube", "Exportfeld _UNSUPPORTED",
                              "Beispielwert", "Geburt", "Datum", "Ort"):
                    self.assertIn(label, profile)
                self.assertNotIn("ABC12345", profile)
                self.assertNotIn("1 JAN 2020", profile)
                self.assertNotIn("2 JAN 2020", profile)
                self.assertNotIn("3 JAN 2020", profile)
                self.assertNotIn("4 JAN 2020", profile)
                self.assertIn('class="tile-icon"', profile)
                self.assertIn('class="fact-card"', profile)
                self.assertIn('aria-hidden="true" focusable="false"', profile)
                original = export_record_page(connection, 1)
                self.assertIn("ABC12345", original)
                self.assertIn("4 JAN 2020", original)
                event = event_page(connection, 1)
                self.assertIn('class="title-icon"', event)
                self.assertIn("Geburt", event)
                self.assertIn('href="/place/2"', event)
                self.assertIn('class="title-icon"', place_page(connection, 2))

    def test_exported_start_person_and_coordinates(self):
        gedcom = """0 @I1@ INDI
1 NAME Ada /Beispiel/
1 _STP
1 BIRT
2 PLAC Musterstadt
3 MAP
4 LATI N52.123456
4 LONG W7.123456
0 @I2@ INDI
1 NAME Ben /Beispiel/
1 BIRT
2 PLAC Anderstadt
3 MAP
4 LATI N999
4 LONG E7
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            build(root / "family.ged", database_path)
            with database(database_path) as connection:
                self.assertIn('id="featured-title">Ada Beispiel', overview(connection, ""))
                self.assertEqual(tuple(connection.execute("SELECT latitude, longitude FROM facts WHERE id=1").fetchone()),
                                 (52.123456, -7.123456))
                event = event_page(connection, 1)
                self.assertIn('data-map-query="52.123456,-7.123456"', event)
                self.assertIn('data-map-label="Musterstadt"', event)
                self.assertIn("Koordinaten aus dem GEDCOM", event)
                self.assertNotIn("<iframe", event)
                self.assertIsNone(connection.execute("SELECT latitude FROM facts WHERE id=2").fetchone()[0])
                self.assertIn('data-map-query="Anderstadt"', event_page(connection, 2))

    def test_place_abbreviations_and_opt_in_event_map(self):
        self.assertEqual(format_place("Bad Iburg,,Landkreis Osnabrück,,Niedersachsen,Deutschland"),
                         "Bad Iburg, Landkreis Osnabrück, NI, DE")
        self.assertEqual(format_place("Wien,Österreich"), "Wien, AT")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gedcom = """0 @I1@ INDI
1 NAME Ada /Beispiel/
1 BIRT
2 DATE 1 JAN 2000
2 PLAC Bad Iburg,,Landkreis Osnabrück,,Niedersachsen,Deutschland
0 TRLR
"""
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            build(root / "family.ged", database_path)
            with database(database_path) as connection:
                profile = person_page(connection, "I1")
                event = event_page(connection, 1)
                self.assertIn("Bad Iburg, Landkreis Osnabrück, NI, DE", profile)
                self.assertIn("Bad Iburg, Landkreis Osnabrück, NI, DE", event)
                self.assertIn('data-map-query="Bad Iburg, Landkreis Osnabrück, Niedersachsen, Deutschland"', event)
                self.assertIn('href="#map">Karte zum Ort ansehen', event)
                self.assertIn('id="map"', event)
                self.assertLess(event.index('id="map"'), event.index('id="sources"'))
                self.assertIn('src="/static/map.js"', event)
                self.assertNotIn("<iframe", event)
                self.assertNotIn("https://www.google.com/maps/search/", event)

    def test_person_navigation_shows_parents_children_partners_and_siblings(self):
        gedcom = """0 @I1@ INDI
1 NAME Clara /Beispiel/
1 OBJE @M1@
0 @I2@ INDI
1 NAME Ada /Beispiel/
1 OBJE @M2@
0 @I3@ INDI
1 NAME Ben /Beispiel/
0 @I4@ INDI
1 NAME Dora /Beispiel/
1 OBJE @M3@
0 @I5@ INDI
1 NAME Emil /Beispiel/
0 @I6@ INDI
1 NAME Frieda /Beispiel/
1 OBJE @M4@
0 @I7@ INDI
1 NAME Greta /Beispiel/
0 @I8@ INDI
1 NAME Hans /Beispiel/
0 @F1@ FAM
1 WIFE @I2@
1 HUSB @I3@
1 CHIL @I1@
1 CHIL @I4@
0 @F2@ FAM
1 WIFE @I1@
1 HUSB @I5@
1 CHIL @I6@
1 CHIL @I7@
0 @F3@ FAM
1 WIFE @I1@
1 HUSB @I8@
0 @M1@ OBJE
1 FILE clara.jpg
1 TITL Profilbild Clara
0 @M2@ OBJE
1 FILE ada.jpg
1 TITL Foto Ada
0 @M3@ OBJE
1 FILE dora.jpg
1 TITL Foto Dora
0 @M4@ OBJE
1 FILE frieda.jpg
1 TITL Foto Frieda
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("clara.jpg", "ada.jpg", "dora.jpg", "frieda.jpg"):
                (root / name).write_bytes(b"synthetic image")
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            build(root / "family.ged", database_path)
            with database(database_path) as connection:
                page = person_page(connection, "I1", root)
                self.assertIn('class="relation-rail relation-rail-parents', page)
                self.assertIn('class="family-rail"', page)
                self.assertIn('class="relation-rail relation-rail-children mobile-children"', page)
                self.assertIn('class="relation-rail relation-rail-children desktop-children"', page)
                self.assertIn('aria-label="Geschwister"', page)
                self.assertLess(page.index('aria-label="Geschwister"'), page.index('class="person-content"'))
                self.assertIn('class="profile-portrait"', page)
                self.assertIn('src="/media/M1"', page)
                self.assertIn('src="/media/M2" alt=""', page)
                self.assertIn('src="/media/M3" alt=""', page)
                self.assertIn('src="/media/M4" alt=""', page)
                self.assertIn('href="/person/I4"', page)
                self.assertIn('class="partner-link" href="/person/I5"', page)
                self.assertIn('class="partner-link" href="/person/I8"', page)
                self.assertIn('href="/person/I6"', page)
                self.assertIn('href="/person/I7"', page)
                self.assertNotIn('role="tab"', page)
                self.assertNotIn('Familie mit', page)

    def test_birth_address_and_godfather_are_visible(self):
        gedcom = """0 @I1@ INDI
1 NAME Clara /Beispiel/
1 BIRT
2 DATE 1 JAN 2000
2 PLAC Musterstadt
2 ADDR Musterklinik
1 ASSO @I2@
2 RELA Godfather
0 @I2@ INDI
1 NAME Emil /Beispiel/
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            build(root / "family.ged", database_path)
            with database(database_path) as connection:
                self.assertEqual(connection.execute("SELECT address FROM facts WHERE id=1").fetchone()[0], "Musterklinik")
                profile = person_page(connection, "I1")
                self.assertIn("Genauer Ort", profile)
                self.assertIn("Musterklinik", profile)
                self.assertIn('Pate: <a href="/person/I2">Emil Beispiel</a>', profile)
                self.assertNotIn("Godfather", profile)
                event = event_page(connection, 1)
                self.assertIn("Genauer Ort", event)
                self.assertIn("Musterklinik", event)

    def test_wedding_witnesses_remain_labeled_text_without_guessed_person_links(self):
        gedcom = """0 @I1@ INDI
1 NAME Ada /Beispiel/
0 @I2@ INDI
1 NAME Ben /Beispiel/
0 @I3@ INDI
1 NAME Clara /Beispiel/
0 @F1@ FAM
1 WIFE @I1@
1 HUSB @I2@
1 MARR Trauzeugen: Clara Beispiel
2 DATE 1 JAN 2000
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            build(root / "family.ged", database_path)
            with database(database_path) as connection:
                profile = person_page(connection, "I1")
                event = event_page(connection, 1)
                self.assertIn("<dt>Trauzeugen</dt><dd>Clara Beispiel</dd>", profile)
                self.assertIn("<dt>Trauzeugen</dt><dd>Clara Beispiel</dd>", event)
                self.assertNotIn('href="/person/I3"', profile)

    def test_multigeneration_tree_respects_depth_and_family_branches(self):
        gedcom = """0 @I1@ INDI
1 NAME Alma /Beispiel/
0 @I2@ INDI
1 NAME Berta /Beispiel/
0 @I3@ INDI
1 NAME Clara /Beispiel/
0 @I4@ INDI
1 NAME Dora /Beispiel/
0 @I5@ INDI
1 NAME Emma /Beispiel/
0 @F1@ FAM
1 WIFE @I1@
1 CHIL @I2@
0 @F2@ FAM
1 WIFE @I2@
1 CHIL @I3@
0 @F3@ FAM
1 WIFE @I3@
1 CHIL @I4@
0 @F4@ FAM
1 WIFE @I4@
1 CHIL @I5@
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            build(root / "family.ged", database_path)
            with database(database_path) as connection:
                short = tree_page(connection, "I3", 2)
                self.assertIn('href="/person/I2"', short)
                self.assertIn('href="/person/I4"', short)
                self.assertNotIn('href="/person/I1"', short)
                self.assertNotIn('href="/person/I5"', short)
                long = tree_page(connection, "I3", 3)
                self.assertIn('href="/person/I1"', long)
                self.assertIn('href="/person/I5"', long)
                self.assertIn('class="generation-group" aria-labelledby="ancestors-title"', long)
                self.assertIn('class="generation-group" aria-labelledby="descendants-title"', long)
                self.assertIn('class="generation-card"', long)
                self.assertIn('class="generation-grid band-count-1"', long)
                self.assertNotIn('style="', long)
                self.assertIn('Elternteil von Clara Beispiel', long)
                self.assertIn('Kind von Clara Beispiel', long)
                self.assertIn('Familienlinien als verschachtelte Liste', long)
                self.assertLess(long.index('aria-label="Großeltern, Generation 3"'),
                                long.index('aria-label="Eltern, Generation 2"'))
                ancestors = tree_page(connection, "I3", 8, "ancestors")
                self.assertIn('href="/person/I1"', ancestors)
                self.assertNotIn('href="/person/I4"', ancestors)
                self.assertNotIn('id="descendants-title"', ancestors)
                self.assertIn('<option value="8" selected>', ancestors)
                descendants = tree_page(connection, "I3", 8, "descendants")
                self.assertIn('href="/person/I5"', descendants)
                self.assertNotIn('href="/person/I2"', descendants)
                self.assertNotIn('id="ancestors-title"', descendants)
                self.assertLess(long.index('id="focus-title"'),
                                long.index('aria-label="Kinder, Generation 2"'))
                self.assertIn('aria-label="Eltern von Clara Beispiel"', long)
                self.assertIn('aria-label="Kinder von Clara Beispiel"', long)
                self.assertIn('value="3" selected', long)

    def test_exact_source_media_match_is_verified(self):
        gedcom = """0 @I1@ INDI
1 NAME Ada /Beispiel/
1 BIRT
2 SOUR @S1@
0 @S1@ SOUR
1 TITL Synthetische Quelle
1 OBJE @M1@
0 @M1@ OBJE
1 FILE scan.pdf
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            archive = root / "archive"
            media.mkdir()
            archive.mkdir()
            (media / "scan.pdf").write_bytes(b"same synthetic file")
            (archive / "copy.pdf").write_bytes(b"same synthetic file")
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            counts = build(root / "family.ged", database_path, archive, media_root=media)
            self.assertEqual(counts["source_archive_links"], 1)
            manifest = root / "archive-index.jsonl"
            export(database_path, manifest)
            counts = build(root / "family.ged", database_path, archive, media_root=media,
                           archive_index_path=manifest)
            self.assertEqual(counts["archive_files"], 1)
            self.assertEqual(counts["source_archive_links"], 1)
            with database(database_path) as connection:
                page = source_page(connection, "S1", media)
                self.assertIn("Dateizuordnung geprüft", page)
                self.assertIn("copy.pdf", page)
                self.assertIn("SHA-256", page)
                archive = archive_page(connection, "", 1)
                self.assertIn("Dateidetails", source_page(connection, "S1", media))
                self.assertIn("Details", archive)
                self.assertIn("Synthetische Quelle", archive_file_page(connection, 1))

    def test_source_archive_mapping_and_event_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive"
            (archive / "register").mkdir(parents=True)
            (archive / "register" / "example.pdf").write_bytes(b"synthetic PDF")
            links = root / "links.json"
            links.write_text(json.dumps({"sources": [{"source_id": "S1", "path": "register/example.pdf",
                                                      "page": 3, "status": "verified", "transcription": "Beispieltext"}]}))
            database_path = root / "family.sqlite"
            counts = build(EXAMPLE, database_path, archive, links)
            self.assertEqual(counts["source_archive_links"], 1)
            with database(database_path) as connection:
                source = source_page(connection, "S1")
                self.assertIn("Dateizuordnung geprüft", source)
                self.assertIn("Beispieltext", source)
                self.assertIn("#page=3", source)
                self.assertIn("/event/", source)
                event = event_page(connection, 1)
                self.assertIn("Fiktives Geburtsregister", event)
                self.assertIn('id="sources"', event)
                self.assertIn("GEDCOM-Belegstelle: Seite 3", event)
                self.assertIn("Archivscan zur Belegseite öffnen", event)
                self.assertIn("#page=3", event)
                self.assertIn("Dateizuordnung geprüft", event)
                event_list = events_page(connection, "", 1)
                self.assertIn('href="/event/1#sources"', event_list)
                self.assertNotIn("Fiktives Geburtsregister", event_list)
                self.assertIn("Ada Beispiel", tree_page(connection, "I3"))
                path = connection_path(family_graph(connection), "I1", "I3")
                self.assertEqual(path[-1], ("I3", "Elternteil von"))
            links.write_text(json.dumps({"sources": [{"source_id": "S1", "path": "missing.pdf",
                                                      "status": "verified"}]}))
            with self.assertRaises(ValueError):
                build(EXAMPLE, database_path, archive, links)
            with database(database_path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM source_archive_links").fetchone()[0], 1)

    def test_event_does_not_guess_between_source_scans(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive"
            archive.mkdir()
            for name in ("first.pdf", "second.pdf"):
                (archive / name).write_bytes(b"synthetic PDF")
            links = root / "links.json"
            links.write_text(json.dumps({"sources": [
                {"source_id": "S1", "path": "first.pdf", "status": "verified"},
                {"source_id": "S1", "path": "second.pdf", "status": "verified"},
            ]}))
            database_path = root / "family.sqlite"
            build(EXAMPLE, database_path, archive, links)
            with database(database_path) as connection:
                event = event_page(connection, 1)
                self.assertIn("2 Archivdateien der Quelle zugeordnet", event)
                self.assertNotIn("Archivscan öffnen", event)
                self.assertIn("GEDCOM-Belegstelle: Seite 3", event)
                uncited = event_page(connection, 2)
                self.assertIn("Kein formaler GEDCOM-Quellenverweis", uncited)
                self.assertIn("Keine Medien angehängt", uncited)

    def test_password_protects_pages_and_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "family.sqlite"
            build(EXAMPLE, database_path)
            password_hash = hash_password("synthetic-secret")
            self.assertTrue(verify_password("synthetic-secret", password_hash))
            self.assertFalse(verify_password("wrong", password_hash))

            class ProtectedHandler(Handler):
                pass

            ProtectedHandler.database_path = database_path
            ProtectedHandler.password_hash = password_hash
            ProtectedHandler.archive_root = None
            ProtectedHandler.media_root = None
            ProtectedHandler.featured_person_id = None
            server = ThreadingHTTPServer(("127.0.0.1", 0), ProtectedHandler)
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                for route in ("/", "/static/style.css"):
                    with self.assertRaises(HTTPError) as result:
                        urlopen(base + route)
                    self.assertEqual(result.exception.code, 401)
                credential = base64.b64encode(b"stammbaum:synthetic-secret").decode()
                request = Request(base + "/", headers={"Authorization": "Basic " + credential})
                with urlopen(request) as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
