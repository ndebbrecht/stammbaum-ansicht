import os
from pathlib import Path

from import_data import build


def main():
    gedcom = Path("/input/tree.ged")
    database = Path("/data/stammbaum.sqlite")
    if not gedcom.is_file():
        raise SystemExit("GEDCOM file is not mounted at /input/tree.ged")
    if os.environ.get("AUTH_ENABLED", "0") not in ("0", "1"):
        raise SystemExit("AUTH_ENABLED must be 0 or 1")
    arguments = ["python", "app.py", "--database", str(database), "--host", "0.0.0.0", "--port", "8765"]
    media_root = Path("/media")
    archive_root = Path("/archive")
    if media_root.is_dir():
        arguments.extend(("--media-root", str(media_root)))
    if archive_root.is_dir():
        arguments.extend(("--archive-root", str(archive_root)))
    featured = os.environ.get("FEATURED_PERSON_ID", "").strip()
    if featured:
        arguments.extend(("--featured-person-id", featured))
    if os.environ["AUTH_ENABLED"] == "1":
        password_file = Path("/auth/password.hash")
        if not password_file.is_file():
            raise SystemExit("AUTH_ENABLED=1 requires /auth/password.hash")
        arguments.extend(("--password-hash-file", str(password_file)))
    source_links = Path("/config/source_links.json")
    archive_index = Path("/config/archive-index.jsonl")
    counts = build(gedcom, database, archive_root if archive_root.is_dir() else None,
                   source_links if source_links.is_file() else None,
                   media_root if media_root.is_dir() else None,
                   archive_index if archive_index.is_file() else None)
    print("Imported " + ", ".join(f"{key}={value}" for key, value in counts.items()), flush=True)
    os.execvp(arguments[0], arguments)


if __name__ == "__main__":
    main()
