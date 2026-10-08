import argparse
import json
import mimetypes
import os
from pathlib import Path
import sqlite3
import tempfile


SCHEMA = """
CREATE TABLE people (id TEXT PRIMARY KEY, name TEXT NOT NULL, given_name TEXT, surname TEXT, sex TEXT);
CREATE TABLE families (id TEXT PRIMARY KEY, husband_id TEXT, wife_id TEXT);
CREATE TABLE children (family_id TEXT NOT NULL, person_id TEXT NOT NULL, PRIMARY KEY (family_id, person_id));
CREATE TABLE facts (id INTEGER PRIMARY KEY, owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT, date_text TEXT, place TEXT);
CREATE TABLE sources (id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT, publication TEXT, notes TEXT);
CREATE TABLE citations (fact_id INTEGER NOT NULL, source_id TEXT NOT NULL, page TEXT, detail TEXT);
CREATE TABLE record_citations (owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, source_id TEXT NOT NULL, page TEXT);
CREATE TABLE media (id TEXT PRIMARY KEY, title TEXT NOT NULL, relative_path TEXT, mime_type TEXT);
CREATE TABLE media_links (owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, media_id TEXT NOT NULL,
    PRIMARY KEY (owner_type, owner_id, media_id));
CREATE TABLE archive_files (id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE, size_bytes INTEGER NOT NULL, mime_type TEXT NOT NULL, metadata_json TEXT);
CREATE INDEX facts_owner ON facts(owner_type, owner_id);
CREATE INDEX citations_fact ON citations(fact_id);
CREATE INDEX media_links_owner ON media_links(owner_type, owner_id);
CREATE INDEX archive_files_path ON archive_files(relative_path);
"""

FACT_NAMES = {
    "BIRT": "Geburt", "DEAT": "Tod", "BAPM": "Taufe", "CHR": "Taufe",
    "BURI": "Bestattung", "MARR": "Heirat", "DIV": "Scheidung",
    "OCCU": "Beruf", "RESI": "Wohnort", "EVEN": "Ereignis",
    "EDUC": "Ausbildung", "GRAD": "Abschluss", "ENGA": "Verlobung",
    "MARL": "Aufgebot", "MARB": "Aufgebot", "MRCI": "Kirchliche Trauung",
    "MRRE": "Hochzeitsfeier",
}
DOCUMENT_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


class Node:
    def __init__(self, tag, value=""):
        self.tag = tag
        self.value = value
        self.children = []

    def first(self, tag):
        return next((child for child in self.children if child.tag == tag), None)

    def all(self, tag):
        return [child for child in self.children if child.tag == tag]

    def text(self, tag):
        child = self.first(tag)
        return child.value if child else ""


def records(path):
    current = None
    stack = []
    with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline=None) as source:
        for raw_line in source:
            pieces = raw_line.rstrip("\r\n").split(" ", 2)
            if len(pieces) < 2 or not pieces[0].isdigit():
                continue
            level = int(pieces[0])
            if level == 0:
                if current:
                    yield current
                if len(pieces) == 3 and pieces[1].startswith("@"):
                    current = (pieces[1].strip("@"), Node(pieces[2]))
                    stack = [current[1]]
                else:
                    current = None
                    stack = []
                continue
            if not current or level > len(stack):
                continue
            tag = pieces[1]
            value = pieces[2] if len(pieces) > 2 else ""
            if tag in ("CONT", "CONC") and stack:
                stack[level - 1].value += ("\n" if tag == "CONT" else "") + value
                continue
            node = Node(tag, value)
            parent = stack[level - 1]
            parent.children.append(node)
            stack = stack[:level] + [node]
    if current:
        yield current


def add_fact(database, owner_type, owner_id, kind, node):
    database.execute(
        "INSERT INTO facts(owner_type,owner_id,kind,value,date_text,place) VALUES (?,?,?,?,?,?)",
        (owner_type, owner_id, FACT_NAMES[kind], node.value, node.text("DATE"), node.text("PLAC")),
    )
    fact_id = database.execute("SELECT last_insert_rowid()").fetchone()[0]
    for citation in node.all("SOUR"):
        if citation.value.startswith("@"):
            database.execute(
                "INSERT INTO citations(fact_id,source_id,page,detail) VALUES (?,?,?,?)",
                (fact_id, citation.value.strip("@"), citation.text("PAGE"), citation.text("DATA")),
            )
    add_media_links(database, "fact", str(fact_id), node)


def add_media_links(database, owner_type, owner_id, node):
    for media in node.all("OBJE"):
        if media.value.startswith("@") and media.value.endswith("@"):
            database.execute(
                "INSERT OR IGNORE INTO media_links VALUES (?,?,?)",
                (owner_type, owner_id, media.value.strip("@")),
            )


def add_record_citations(database, owner_type, owner_id, node):
    for citation in node.all("SOUR"):
        if citation.value.startswith("@") and citation.value.endswith("@"):
            database.execute(
                "INSERT INTO record_citations VALUES (?,?,?,?)",
                (owner_type, owner_id, citation.value.strip("@"), citation.text("PAGE")),
            )


def import_gedcom(database, path):
    for record_id, record in records(path):
        if record.tag == "INDI":
            name_node = record.first("NAME")
            raw_name = name_node.value if name_node else ""
            name = raw_name.replace("/", "").strip() or "Unbekannte Person"
            database.execute(
                "INSERT INTO people VALUES (?,?,?,?,?)",
                (record_id, name, name_node.text("GIVN") if name_node else "",
                 name_node.text("SURN") if name_node else "", record.text("SEX")),
            )
            for node in record.children:
                if node.tag in FACT_NAMES:
                    add_fact(database, "person", record_id, node.tag, node)
            add_media_links(database, "person", record_id, record)
            add_record_citations(database, "person", record_id, record)
        elif record.tag == "FAM":
            database.execute(
                "INSERT INTO families VALUES (?,?,?)",
                (record_id, record.text("HUSB").strip("@"), record.text("WIFE").strip("@")),
            )
            for child in record.all("CHIL"):
                database.execute("INSERT OR IGNORE INTO children VALUES (?,?)", (record_id, child.value.strip("@")))
            for node in record.children:
                if node.tag in FACT_NAMES:
                    add_fact(database, "family", record_id, node.tag, node)
            add_media_links(database, "family", record_id, record)
            add_record_citations(database, "family", record_id, record)
        elif record.tag == "SOUR":
            database.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?)",
                (record_id, record.text("TITL") or f"Quelle {record_id}", record.text("AUTH"),
                 record.text("PUBL"), record.text("TEXT") or record.text("NOTE")),
            )
            add_media_links(database, "source", record_id, record)
        elif record.tag == "OBJE":
            file_name = record.text("FILE")
            safe_name = Path(file_name).name if file_name and not Path(file_name).is_absolute() else ""
            if safe_name != file_name or Path(safe_name).suffix.lower() not in DOCUMENT_SUFFIXES:
                safe_name = ""
            database.execute(
                "INSERT INTO media VALUES (?,?,?,?)",
                (record_id, record.text("TITL") or safe_name or f"Medium {record_id}",
                 safe_name or None, mimetypes.guess_type(safe_name)[0] if safe_name else None),
            )


def index_archive(database, archive_root):
    root = Path(archive_root)
    for directory, _, filenames in os.walk(root):
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() not in DOCUMENT_SUFFIXES:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            relative_path = str(path.relative_to(root))
            database.execute(
                "INSERT INTO archive_files(relative_path,size_bytes,mime_type,metadata_json) VALUES (?,?,?,?)",
                (relative_path, stat.st_size, mimetypes.guess_type(path.name)[0] or "application/octet-stream", None),
            )


def build(gedcom_path, database_path, archive_root=None):
    destination = Path(database_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="stammbaum-", suffix=".sqlite", dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        database = sqlite3.connect(temporary_path)
        try:
            database.executescript(SCHEMA)
            import_gedcom(database, gedcom_path)
            if archive_root:
                index_archive(database, archive_root)
            database.commit()
            counts = {table: database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("people", "families", "sources", "facts", "citations", "media", "media_links", "archive_files")}
        finally:
            database.close()
        temporary_path.chmod(0o600)
        temporary_path.replace(destination)
        return counts
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import GEDCOM into a private, read-only SQLite database")
    parser.add_argument("--gedcom", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--archive-root")
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.gedcom, arguments.database, arguments.archive_root), ensure_ascii=False))
