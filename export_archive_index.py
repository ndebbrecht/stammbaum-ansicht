import argparse
import json
from pathlib import Path
import sqlite3
import tempfile


def export(database_path, output_path):
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f"file:{Path(database_path).resolve()}?mode=ro", uri=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="archive-index-", suffix=".jsonl",
                                     dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            for relative_path, size_bytes, mime_type, metadata_json in connection.execute(
                "SELECT relative_path,size_bytes,mime_type,metadata_json FROM archive_files ORDER BY relative_path"
            ):
                temporary.write(json.dumps({"relative_path": relative_path, "size_bytes": size_bytes,
                                            "mime_type": mime_type, "metadata_json": metadata_json},
                                           ensure_ascii=False) + "\n")
        finally:
            connection.close()
    temporary_path.chmod(0o600)
    temporary_path.replace(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export a private archive manifest from an existing database")
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    export(arguments.database, arguments.output)
