import argparse
from hashlib import sha256
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import tempfile


SCHEMA = """
CREATE TABLE people (id TEXT PRIMARY KEY, name TEXT NOT NULL, given_name TEXT, surname TEXT, sex TEXT, is_start INTEGER NOT NULL DEFAULT 0);
CREATE TABLE families (id TEXT PRIMARY KEY, husband_id TEXT, wife_id TEXT);
CREATE TABLE children (family_id TEXT NOT NULL, person_id TEXT NOT NULL, PRIMARY KEY (family_id, person_id));
CREATE TABLE facts (id INTEGER PRIMARY KEY, owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT, date_text TEXT, place TEXT, address TEXT, latitude REAL, longitude REAL);
CREATE TABLE sources (id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT, publication TEXT, notes TEXT);
CREATE TABLE citations (fact_id INTEGER NOT NULL, source_id TEXT NOT NULL, page TEXT, detail TEXT);
CREATE TABLE record_citations (owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, source_id TEXT NOT NULL, page TEXT);
CREATE TABLE media (id TEXT PRIMARY KEY, title TEXT NOT NULL, relative_path TEXT, mime_type TEXT);
CREATE TABLE media_links (owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, media_id TEXT NOT NULL,
    PRIMARY KEY (owner_type, owner_id, media_id));
CREATE TABLE archive_files (id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE, size_bytes INTEGER NOT NULL, mime_type TEXT NOT NULL, metadata_json TEXT);
CREATE TABLE source_archive_links (source_id TEXT NOT NULL, archive_file_id INTEGER NOT NULL,
    page INTEGER, status TEXT NOT NULL, note TEXT, transcription TEXT,
    PRIMARY KEY (source_id, archive_file_id, page));
CREATE TABLE notes (id TEXT PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE note_links (owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, note_id TEXT, text TEXT);
CREATE TABLE repositories (id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT);
CREATE TABLE source_repositories (source_id TEXT NOT NULL, repository_id TEXT NOT NULL,
    call_number TEXT, PRIMARY KEY (source_id, repository_id));
CREATE TABLE associations (person_id TEXT NOT NULL, other_person_id TEXT NOT NULL, relation TEXT);
CREATE TABLE export_records (id INTEGER PRIMARY KEY, xref TEXT, tag TEXT NOT NULL, value TEXT NOT NULL, raw_text TEXT NOT NULL);
CREATE TABLE export_nodes (id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL, parent_id INTEGER, tag TEXT NOT NULL, value TEXT NOT NULL);
CREATE TABLE places (record_id INTEGER PRIMARY KEY, name TEXT NOT NULL, latitude REAL, longitude REAL, alternate_names TEXT NOT NULL, geo TEXT, format_id TEXT);
CREATE TABLE labels (id TEXT PRIMARY KEY, title TEXT NOT NULL, color TEXT);
CREATE TABLE person_labels (person_id TEXT NOT NULL, label_id TEXT NOT NULL, PRIMARY KEY (person_id, label_id));
CREATE INDEX facts_owner ON facts(owner_type, owner_id);
CREATE INDEX citations_fact ON citations(fact_id);
CREATE INDEX media_links_owner ON media_links(owner_type, owner_id);
CREATE INDEX archive_files_path ON archive_files(relative_path);
CREATE INDEX archive_files_size ON archive_files(size_bytes);
CREATE INDEX source_archive_links_source ON source_archive_links(source_id);
CREATE INDEX note_links_owner ON note_links(owner_type, owner_id);
CREATE INDEX associations_person ON associations(person_id);
CREATE INDEX export_records_tag ON export_records(tag);
CREATE INDEX export_records_xref ON export_records(xref);
CREATE INDEX export_nodes_record ON export_nodes(record_id);
CREATE INDEX places_name ON places(name);
"""

FACT_NAMES = {
    "BIRT": "Geburt", "DEAT": "Tod", "BAPM": "Taufe", "CHR": "Taufe",
    "BURI": "Bestattung", "MARR": "Heirat", "DIV": "Scheidung",
    "OCCU": "Beruf", "RESI": "Wohnort", "EVEN": "Ereignis",
    "EDUC": "Ausbildung", "GRAD": "Abschluss", "ENGA": "Verlobung",
    "MARL": "Aufgebot", "MARB": "Aufgebot", "MRCI": "Kirchliche Trauung",
    "MRRE": "Hochzeitsfeier",
    "ADOP": "Adoption", "EMIG": "Auswanderung", "IMMI": "Einwanderung",
    "CENS": "Volkszählung", "NATU": "Einbürgerung", "RETI": "Ruhestand",
    "CONF": "Konfirmation", "CREM": "Einäscherung", "WILL": "Testament",
    "PROB": "Nachlassverfahren", "ANUL": "Annullierung", "DIVF": "Scheidungsantrag",
    "LATR": "Letzte Ölung", "ORDN": "Ordination", "FUNE": "Trauerfeier",
    "FCOM": "Erstkommunion", "MISE": "MacFamilyTree-Ereignis MISE",
    "MIIN": "MacFamilyTree-Ereignis MIIN", "MIDE": "MacFamilyTree-Ereignis MIDE",
    "MIAW": "Militärische Auszeichnung",
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
                else:
                    current = (None, Node(pieces[1], pieces[2] if len(pieces) > 2 else ""))
                stack = [current[1]]
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
    place = node.first("PLAC")
    mapping = place.first("MAP") if place else None
    latitude = coordinate(mapping.text("LATI"), "NS", 90) if mapping else None
    longitude = coordinate(mapping.text("LONG"), "EW", 180) if mapping else None
    if latitude is None or longitude is None:
        latitude = longitude = None
    database.execute(
        "INSERT INTO facts(owner_type,owner_id,kind,value,date_text,place,address,latitude,longitude) VALUES (?,?,?,?,?,?,?,?,?)",
        (owner_type, owner_id, FACT_NAMES[kind], node.value, node.text("DATE"), node.text("PLAC"), node.text("ADDR"), latitude, longitude),
    )
    fact_id = database.execute("SELECT last_insert_rowid()").fetchone()[0]
    for citation in node.all("SOUR"):
        if citation.value.startswith("@"):
            database.execute(
                "INSERT INTO citations(fact_id,source_id,page,detail) VALUES (?,?,?,?)",
                (fact_id, citation.value.strip("@"), citation.text("PAGE"), citation.text("DATA")),
            )
    add_media_links(database, "fact", str(fact_id), node)
    add_note_links(database, "fact", str(fact_id), node)


def coordinate(value, directions, limit):
    if not re.fullmatch(rf"[{directions}]\d+(?:\.\d+)?", value):
        return None
    number = float(value[1:])
    if number > limit:
        return None
    return -number if value[0] == directions[1] else number


def add_note_links(database, owner_type, owner_id, node):
    for note in node.all("NOTE"):
        reference = note.value.startswith("@") and note.value.endswith("@")
        database.execute(
            "INSERT INTO note_links VALUES (?,?,?,?)",
            (owner_type, owner_id, note.value.strip("@") if reference else None,
             None if reference else note.value),
        )


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
                "INSERT INTO people VALUES (?,?,?,?,?,?)",
                (record_id, name, name_node.text("GIVN") if name_node else "",
                 name_node.text("SURN") if name_node else "", record.text("SEX"), int(record.first("_STP") is not None)),
            )
            for node in record.children:
                if node.tag in FACT_NAMES:
                    add_fact(database, "person", record_id, node.tag, node)
            add_media_links(database, "person", record_id, record)
            add_record_citations(database, "person", record_id, record)
            add_note_links(database, "person", record_id, record)
            for association in record.all("ASSO"):
                if association.value.startswith("@") and association.value.endswith("@"):
                    database.execute("INSERT INTO associations VALUES (?,?,?)",
                                     (record_id, association.value.strip("@"), association.text("RELA")))
            for label in record.all("LABL"):
                if label.value.startswith("@") and label.value.endswith("@"):
                    database.execute("INSERT OR IGNORE INTO person_labels VALUES (?,?)",
                                     (record_id, label.value.strip("@")))
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
            add_note_links(database, "family", record_id, record)
        elif record.tag == "SOUR":
            database.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?)",
                (record_id, record.text("TITL") or f"Quelle {record_id}", record.text("AUTH"),
                 record.text("PUBL"), record.text("TEXT")),
            )
            add_media_links(database, "source", record_id, record)
            add_note_links(database, "source", record_id, record)
            for repository in record.all("REPO"):
                if repository.value.startswith("@") and repository.value.endswith("@"):
                    database.execute("INSERT OR IGNORE INTO source_repositories VALUES (?,?,?)",
                                     (record_id, repository.value.strip("@"), repository.text("CALN")))
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
        elif record.tag == "NOTE":
            database.execute("INSERT INTO notes VALUES (?,?)", (record_id, record.value))
        elif record.tag == "REPO":
            database.execute("INSERT INTO repositories VALUES (?,?,?)",
                             (record_id, record.text("NAME") or f"Archiv {record_id}", record.text("ADDR")))
        elif record.tag == "LABL":
            database.execute("INSERT INTO labels VALUES (?,?,?)",
                             (record_id, record.text("TITL") or f"Kennzeichnung {record_id}", record.text("COLR")))


def import_export_records(database, path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as source:
        current = []
        for line in source:
            if line.startswith("0 ") and current:
                add_export_record(database, current)
                current = []
            current.append(line)
        if current:
            add_export_record(database, current)
    raw_rows = database.execute("SELECT id, xref, tag, value FROM export_records ORDER BY id").fetchall()
    parsed_count = 0
    for record_id, record in records(path):
        if parsed_count >= len(raw_rows):
            raise ValueError("More parsed records than original records")
        raw = raw_rows[parsed_count]
        parsed_count += 1
        if raw[2] != record.tag or raw[1] != record_id:
            raise ValueError("Parsed records are not aligned with the export")
        add_export_nodes(database, raw[0], None, record.children)
        if record.tag != "_PLAC":
            continue
        if raw[3] != record.value:
            raise ValueError("Place records are not aligned with the export")
        mapping = record.first("MAP")
        latitude = coordinate(mapping.text("LATI"), "NS", 90) if mapping else None
        longitude = coordinate(mapping.text("LONG"), "EW", 180) if mapping else None
        if latitude is None or longitude is None:
            latitude = longitude = None
        database.execute("INSERT INTO places VALUES (?,?,?,?,?,?,?)",
                         (raw[0], record.value, latitude, longitude,
                          json.dumps([node.value for node in record.all("_ALT")], ensure_ascii=False),
                          record.text("_GEO"), record.text("_PTE").strip("@")))
    if parsed_count != len(raw_rows):
        raise ValueError("Original records were not all parsed")


def add_export_nodes(database, record_id, parent_id, nodes):
    for node in nodes:
        database.execute("INSERT INTO export_nodes(record_id,parent_id,tag,value) VALUES (?,?,?,?)",
                         (record_id, parent_id, node.tag, node.value))
        node_id = database.execute("SELECT last_insert_rowid()").fetchone()[0]
        add_export_nodes(database, record_id, node_id, node.children)


def add_export_record(database, lines):
    first = lines[0].rstrip("\r\n").split(" ", 2)
    if len(first) > 2 and first[1].startswith("@"):
        xref, tag, value = first[1].strip("@"), first[2].split(" ", 1)[0], ""
    else:
        xref, tag, value = None, first[1], first[2] if len(first) > 2 else ""
    database.execute("INSERT INTO export_records(xref,tag,value,raw_text) VALUES (?,?,?,?)",
                     (xref, tag, value, "".join(lines)))


def index_archive(database, archive_root):
    root = Path(archive_root)
    if not root.is_dir():
        raise FileNotFoundError(f"Archive root not found: {root}")

    def fail_scan(error):
        raise error

    for directory, _, filenames in os.walk(root, onerror=fail_scan):
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() not in DOCUMENT_SUFFIXES:
                continue
            stat = path.stat()
            relative_path = str(path.relative_to(root))
            database.execute(
                "INSERT INTO archive_files(relative_path,size_bytes,mime_type,metadata_json) VALUES (?,?,?,?)",
                (relative_path, stat.st_size, mimetypes.guess_type(path.name)[0] or "application/octet-stream", None),
            )


def import_archive_index(database, path):
    with Path(path).open("r", encoding="utf-8") as source:
        for line in source:
            entry = json.loads(line)
            relative_path = entry["relative_path"]
            candidate = Path(relative_path)
            if candidate.is_absolute() or ".." in candidate.parts or not relative_path:
                raise ValueError("Archive index contains an unsafe path")
            database.execute(
                "INSERT INTO archive_files(relative_path,size_bytes,mime_type,metadata_json) VALUES (?,?,?,?)",
                (relative_path, entry["size_bytes"], entry["mime_type"], entry.get("metadata_json")),
            )


def file_hash(path):
    digest = sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def match_source_media(database, media_root, archive_root):
    if not media_root or not archive_root:
        return
    media_directory = Path(media_root).resolve()
    archive_directory = Path(archive_root).resolve()
    rows = database.execute(
        "SELECT media_links.owner_id AS source_id, media.id AS media_id, media.relative_path "
        "FROM media_links JOIN media ON media.id=media_links.media_id "
        "WHERE media_links.owner_type='source' AND media.relative_path IS NOT NULL"
    ).fetchall()
    for source_id, media_id, relative_path in rows:
        source_path = (media_directory / relative_path).resolve()
        if not source_path.is_relative_to(media_directory) or not source_path.is_file():
            continue
        candidates = database.execute(
            "SELECT id, relative_path FROM archive_files WHERE size_bytes=?", (source_path.stat().st_size,)
        ).fetchall()
        if not candidates:
            continue
        source_digest = file_hash(source_path)
        matches = []
        for archive_id, archive_path in candidates:
            candidate = (archive_directory / archive_path).resolve()
            if candidate.is_relative_to(archive_directory) and candidate.is_file() and file_hash(candidate) == source_digest:
                matches.append((archive_id, archive_path))
        if matches:
            archive_id, _ = min(matches, key=lambda item: (not item[1].startswith("medien-kuratiert/"), len(item[1])))
            database.execute(
                "INSERT INTO source_archive_links VALUES (?,?,?,?,?,?)",
                (source_id, archive_id, None, "verified", "Identische Datei zum GEDCOM-Medium " + media_id + " (SHA-256).", None),
            )
            database.execute("UPDATE archive_files SET metadata_json=? WHERE id=?",
                             (json.dumps({"sha256": source_digest}), archive_id))


def import_source_links(database, path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError("Source links file needs a sources array")
    for entry in data["sources"]:
        if not isinstance(entry, dict) or entry.get("status") not in ("suggested", "verified"):
            raise ValueError("Each source link needs suggested or verified status")
        source = database.execute("SELECT id FROM sources WHERE id=?", (entry.get("source_id"),)).fetchone()
        document = database.execute("SELECT id FROM archive_files WHERE relative_path=?", (entry.get("path"),)).fetchone()
        if not source or not document:
            raise ValueError("Source or archive path in source links file was not imported")
        page = entry.get("page")
        if page is not None and (type(page) is not int or page < 1):
            raise ValueError("Source link page must be a positive integer")
        existing = database.execute(
            "SELECT rowid FROM source_archive_links WHERE source_id=? AND archive_file_id=? "
            "AND (page=? OR (page IS NULL AND ? IS NULL))",
            (source[0], document[0], page, page),
        ).fetchone()
        if existing:
            database.execute(
                "UPDATE source_archive_links SET status=?, note=?, transcription=? WHERE rowid=?",
                (entry["status"], entry.get("note"), entry.get("transcription"), existing[0]),
            )
        else:
            database.execute(
                "INSERT INTO source_archive_links VALUES (?,?,?,?,?,?)",
                (source[0], document[0], page, entry["status"], entry.get("note"), entry.get("transcription")),
            )


def build(gedcom_path, database_path, archive_root=None, source_links_path=None, media_root=None,
          archive_index_path=None):
    destination = Path(database_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="stammbaum-", suffix=".sqlite", dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        database = sqlite3.connect(temporary_path)
        try:
            database.executescript(SCHEMA)
            import_gedcom(database, gedcom_path)
            import_export_records(database, gedcom_path)
            if archive_index_path:
                import_archive_index(database, archive_index_path)
            elif archive_root:
                index_archive(database, archive_root)
            match_source_media(database, media_root, archive_root)
            if source_links_path:
                import_source_links(database, source_links_path)
            database.commit()
            counts = {table: database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("people", "families", "sources", "facts", "citations", "media", "media_links", "archive_files", "source_archive_links", "export_records", "export_nodes", "places", "labels", "person_labels")}
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
    parser.add_argument("--source-links")
    parser.add_argument("--media-root")
    parser.add_argument("--archive-index")
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.gedcom, arguments.database, arguments.archive_root, arguments.source_links,
                           arguments.media_root, arguments.archive_index), ensure_ascii=False))
