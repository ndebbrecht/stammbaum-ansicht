import base64
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from app import Handler, archive_file_page, archive_page, connection_path, database, event_page, events_page, family_graph, format_place, person_page, source_page, tree_page
from auth import hash_password, verify_password
from export_archive_index import export
from import_data import build


EXAMPLE = Path(__file__).parents[1] / "examples" / "beispiel.ged"


class FeatureTest(unittest.TestCase):
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
                self.assertIn('src="/static/map.js"', event)
                self.assertNotIn("<iframe", event)

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
                self.assertIn('class="relation-rail relation-rail-children mobile-children"', page)
                self.assertIn('class="relation-rail relation-rail-children desktop-children"', page)
                self.assertIn('aria-label="Geschwister"', page)
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
