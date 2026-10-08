import base64
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from app import Handler, archive_file_page, archive_page, connection_path, database, event_page, family_graph, source_page, tree_page
from auth import hash_password, verify_password
from export_archive_index import export
from import_data import build


EXAMPLE = Path(__file__).parents[1] / "examples" / "beispiel.ged"


class FeatureTest(unittest.TestCase):
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
