from pathlib import Path
import sqlite3
import tempfile
import unittest

from import_data import build
from app import overview, person_page, source_page


class SyntheticImportTest(unittest.TestCase):
    def test_people_relationships_and_citation(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "family.sqlite"
            counts = build(Path(__file__).parents[1] / "examples" / "beispiel.ged", database_path)
            self.assertEqual(counts["people"], 3)
            self.assertEqual(counts["citations"], 1)
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
            try:
                child = person_page(connection, "I3")
                self.assertIn("Ada Beispiel", child)
                self.assertIn("Ben Beispiel", child)
                self.assertIn("Kein GEDCOM-Quellenverweis", person_page(connection, "I2") or "")
                self.assertIn("Fiktives Geburtsregister", person_page(connection, "I1") or "")
                self.assertIn("Ada Beispiel", source_page(connection, "S1") or "")
            finally:
                connection.close()

    def test_family_events_and_linked_media(self):
        gedcom = """0 @I1@ INDI
1 NAME Ada /Beispiel/
1 OBJE @M1@
1 EDUC
2 DATE 2 JAN 2000
2 OBJE @M2@
1 FAMS @F1@
0 @I2@ INDI
1 NAME Ben /Beispiel/
0 @F1@ FAM
1 WIFE @I1@
1 HUSB @I2@
1 ENGA
2 DATE 3 MAR 2001
1 MRCI
2 DATE 4 APR 2002
0 @M1@ OBJE
1 FILE portrait.jpg
1 TITL Porträt
0 @M2@ OBJE
1 FILE urkunde.pdf
1 TITL Abschlussurkunde
0 TRLR
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "portrait.jpg").write_bytes(b"synthetic")
            (root / "urkunde.pdf").write_bytes(b"synthetic")
            (root / "family.ged").write_text(gedcom)
            database_path = root / "family.sqlite"
            counts = build(root / "family.ged", database_path)
            self.assertEqual(counts["media"], 2)
            self.assertEqual(counts["media_links"], 2)
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
            try:
                profile = person_page(connection, "I1", root)
                self.assertIn("Verlobung", profile)
                self.assertIn("Kirchliche Trauung", profile)
                self.assertIn('src="/media/M1"', profile)
                self.assertIn('href="/media/M2"', profile)
                home = overview(connection, "", "I1", root)
                self.assertIn("Deine Startperson", home)
                self.assertIn('href="/person/I1"', home)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
