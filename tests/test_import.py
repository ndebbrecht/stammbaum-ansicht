from pathlib import Path
import sqlite3
import tempfile
import unittest

from import_data import build
from app import person_page, source_page


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
                self.assertIn("Kein Beleg im GEDCOM", person_page(connection, "I2") or "")
                self.assertIn("Fiktives Geburtsregister", person_page(connection, "I1") or "")
                self.assertIn("Ada Beispiel", source_page(connection, "S1") or "")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
