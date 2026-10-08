import argparse
from contextlib import closing
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import parse_qs, quote, urlsplit


ROOT = Path(__file__).parent
STYLE = (ROOT / "static" / "style.css").read_bytes()


def link(label, route):
    return f'<a href="{escape(route, quote=True)}">{escape(str(label))}</a>'


def person_link(person):
    return link(person["name"], f'/person/{quote(person["id"])}') if person else "Unbekannt"


def list_items(items):
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>" if items else "<p>Keine Einträge.</p>"


def layout(title, content):
    return f'''<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Stammbaum</title><meta name="color-scheme" content="light dark"><link rel="stylesheet" href="/static/style.css"></head>
<body><a class="skip" href="#inhalt">Zum Inhalt springen</a>
<header class="site-header"><div class="shell header-inner"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true">✦</span> Stammbaum</a><nav aria-label="Hauptnavigation">
<a href="/">Startseite</a><a href="/sources">Quellen</a><a href="/archive">Archiv</a></nav></div></header>
<main id="inhalt" class="shell" tabindex="-1">{content}</main>
<footer class="shell">Private Leseansicht · Angaben aus dem GEDCOM sind nicht automatisch geprüft. · Darstellung folgt dem Hell-/Dunkelmodus des Geräts.</footer></body></html>'''


def database(path):
    connection = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def overview(connection, query, featured_person_id=None, media_root=None):
    term = query.strip()[:100]
    if term:
        people = connection.execute(
            "SELECT * FROM people WHERE name LIKE ? COLLATE NOCASE OR surname LIKE ? COLLATE NOCASE ORDER BY name LIMIT 100",
            (f"%{term}%", f"%{term}%"),
        ).fetchall()
    else:
        people = connection.execute("SELECT * FROM people ORDER BY name LIMIT 50").fetchall()
    count = connection.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    featured = connection.execute("SELECT * FROM people WHERE id=?", (featured_person_id,)).fetchone() if featured_person_id else None
    featured_html = ""
    if featured:
        featured_media = media_for(connection, "person", featured["id"], media_root, limit=1, portrait=True)
        featured_html = f'''<section class="featured" aria-labelledby="featured-title"><div class="featured-copy">
<p class="eyebrow">Deine Startperson</p><h2 id="featured-title">{escape(featured['name'])}</h2>
<p>Hier beginnt deine Reise durch Familie, Ereignisse, Bilder und Quellen.</p>
<p>{link('Meine Seite öffnen →', f'/person/{quote(featured["id"])}')}</p></div>{featured_media}</section>'''
    content = f'''<section class="intro"><p class="eyebrow">Private Familiengeschichte</p><h1>Menschen. Geschichten. Verbindungen.</h1>
<p>Entdecke {count} Personen und die Spuren, die sie miteinander verbinden.</p></section>
{featured_html}<form class="search panel" action="/" method="get"><label for="name">Person suchen</label>
<div><input id="name" name="q" type="search" value="{escape(term, quote=True)}" autocomplete="off">
<button type="submit">Suchen</button></div></form>
<section class="panel" aria-labelledby="results"><h2 id="results">{'Suchergebnisse' if term else 'Personen entdecken'}</h2>
<p class="muted">{len(people)} Treffer angezeigt{' · maximal 100' if term else ' · die Suche umfasst alle Personen'}.</p>
{list_items([person_link(person) for person in people])}</section>'''
    return layout("Personen", content)


def media_for(connection, owner_type, owner_id, media_root=None, limit=None, portrait=False):
    media = connection.execute(
        "SELECT media.* FROM media_links JOIN media ON media.id=media_links.media_id "
        "WHERE media_links.owner_type=? AND media_links.owner_id=? ORDER BY media.title",
        (owner_type, owner_id),
    ).fetchall()
    entries = []
    for item in media[:limit] if limit else media:
        name = item["relative_path"]
        available = bool(name and media_root and (Path(media_root) / name).is_file())
        if available:
            route = f'/media/{quote(item["id"])}'
            if (item["mime_type"] or "").startswith("image/"):
                entries.append(f'<figure class="media-card"><a href="{route}"><img src="{route}" alt="{escape(item["title"], quote=True)}" loading="lazy"></a>'
                               f'<figcaption>{escape(item["title"])}</figcaption></figure>')
            else:
                entries.append(f'<div class="media-card document">{link("Dokument öffnen: " + item["title"], route)}</div>')
        elif not portrait:
            entries.append(f'<p class="muted">{escape(item["title"])} · Datei im Export nicht verfügbar</p>')
    if portrait:
        return entries[0] if entries and "<img " in entries[0] else '<div class="featured-symbol" aria-hidden="true">✦</div>'
    return '<div class="media-grid">' + "".join(entries) + '</div>' if entries else ""


def citations_for(connection, owner_type, owner_id):
    if owner_type == "fact":
        return connection.execute(
            "SELECT citations.source_id, citations.page, sources.title FROM citations LEFT JOIN sources ON sources.id=citations.source_id WHERE fact_id=?",
            (owner_id,),
        ).fetchall()
    return connection.execute(
        "SELECT record_citations.source_id, record_citations.page, sources.title FROM record_citations "
        "LEFT JOIN sources ON sources.id=record_citations.source_id WHERE owner_type=? AND owner_id=?",
        (owner_type, owner_id),
    ).fetchall()


def citations_html(citations):
    return list_items([
        link(item["title"] or f'Quelle {item["source_id"]}', f'/source/{quote(item["source_id"])}')
        + (f' · {escape(item["page"])}' if item["page"] else "") for item in citations
    ]) if citations else '<p class="unverified">Kein GEDCOM-Quellenverweis vorhanden.</p>'


def facts_html(connection, owner_type, owner_id, media_root=None):
    facts = connection.execute(
        "SELECT * FROM facts WHERE owner_type=? AND owner_id=? ORDER BY id", (owner_type, owner_id)
    ).fetchall()
    if not facts:
        return "<p>Keine Ereignisse im GEDCOM verzeichnet.</p>"
    entries = []
    for fact in facts:
        citations = citations_for(connection, "fact", str(fact["id"]))
        details = ", ".join(escape(value) for value in (fact["date_text"], fact["place"], fact["value"]) if value)
        media = media_for(connection, "fact", str(fact["id"]), media_root)
        evidence = f'<div class="evidence"><strong>Quellen</strong>{citations_html(citations)}</div>' if citations else '<p class="unverified">Kein GEDCOM-Quellenverweis vorhanden.</p>'
        entries.append(f'<li><article class="fact-card"><h3>{escape(fact["kind"])}</h3><p>{details or "Ohne weitere Angabe"}</p>'
                       f'{media}{evidence}</article></li>')
    return '<ol class="facts">' + "".join(entries) + "</ol>"


def person_page(connection, person_id, media_root=None):
    person = connection.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not person:
        return None
    parent_families = connection.execute(
        "SELECT families.* FROM families JOIN children ON children.family_id=families.id WHERE children.person_id=?",
        (person_id,),
    ).fetchall()
    own_families = connection.execute(
        "SELECT * FROM families WHERE husband_id=? OR wife_id=?", (person_id, person_id)
    ).fetchall()
    parents = []
    siblings = []
    for family in parent_families:
        for parent_id in (family["husband_id"], family["wife_id"]):
            parent = connection.execute("SELECT * FROM people WHERE id=?", (parent_id,)).fetchone()
            if parent:
                parents.append(person_link(parent))
        siblings.extend(person_link(child) for child in connection.execute(
            "SELECT people.* FROM people JOIN children ON children.person_id=people.id WHERE children.family_id=? AND people.id<>? ORDER BY name",
            (family["id"], person_id),
        ))
    families = []
    for family in own_families:
        partner_id = family["wife_id"] if family["husband_id"] == person_id else family["husband_id"]
        partner = connection.execute("SELECT * FROM people WHERE id=?", (partner_id,)).fetchone()
        children = connection.execute(
            "SELECT people.* FROM people JOIN children ON children.person_id=people.id WHERE children.family_id=? ORDER BY name",
            (family["id"],),
        ).fetchall()
        families.append(f'<article class="family"><h3>Familie mit {person_link(partner)}</h3>'
                        f'<h4>Kinder</h4>{list_items([person_link(child) for child in children])}'
                        f'{media_for(connection, "family", family["id"], media_root)}</article>')
    family_events = ''.join(f'<article class="family-event"><h3>Mit {person_link(connection.execute("SELECT * FROM people WHERE id=?", (family["wife_id"] if family["husband_id"] == person_id else family["husband_id"],)).fetchone())}</h3>'
                            f'{facts_html(connection, "family", family["id"], media_root)}</article>' for family in own_families)
    direct_media = media_for(connection, "person", person_id, media_root)
    direct_citations = citations_for(connection, "person", person_id)
    fact_ids = [str(row["id"]) for row in connection.execute(
        "SELECT id FROM facts WHERE owner_type='person' AND owner_id=?", (person_id,)
    )]
    fact_media = ''.join(media_for(connection, "fact", fact_id, media_root) for fact_id in fact_ids)
    content = f'''<p class="back">{link('← Zur Startseite', '/')}</p><section class="person-hero"><p class="eyebrow">Personenprofil</p><h1>{escape(person["name"])}</h1>
<p>Familie, Lebensereignisse und überlieferte Dokumente auf einen Blick.</p></section>
<nav class="section-nav" aria-label="Profilbereiche"><a href="#events">Ereignisse</a><a href="#family-events">Partnerschaft</a><a href="#media">Medien & Quellen</a><a href="#relations">Beziehungen</a></nav>
<div class="columns"><section class="panel" id="events" aria-labelledby="events-title"><h2 id="events-title">Lebensereignisse</h2>{facts_html(connection, "person", person_id, media_root)}</section>
<section class="panel" id="family-events" aria-labelledby="family-events-title"><h2 id="family-events-title">Partnerschaft & Hochzeit</h2>{family_events or '<p>Keine gemeinsamen Ereignisse im GEDCOM verzeichnet.</p>'}</section></div>
<section class="panel" id="media" aria-labelledby="media-title"><h2 id="media-title">Medien & Quellen</h2>
{direct_media or '<p>Keine direkt zugeordneten Medien.</p>'}<h3>Direkte Quellenverweise</h3>{citations_html(direct_citations)}
<h3>Dokumente zu Lebensereignissen</h3>{fact_media or '<p>Keine weiteren Dokumente zu Lebensereignissen.</p>'}</section>
<section class="panel" id="relations" aria-labelledby="relations-title"><h2 id="relations-title">Beziehungen</h2>
<h3>Eltern</h3>{list_items(parents)}<h3>Geschwister</h3>{list_items(siblings)}
<h3>Partner und Kinder</h3>{''.join(families) or '<p>Keine Familie im GEDCOM verknüpft.</p>'}</section>'''
    return layout(person["name"], content)


def sources_page(connection, query):
    term = query.strip()[:100]
    sources = connection.execute(
        "SELECT * FROM sources WHERE title LIKE ? COLLATE NOCASE ORDER BY title LIMIT 100", (f"%{term}%",)
    ).fetchall()
    count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    content = f'''<h1>GEDCOM-Quellen</h1><p>{count} Quelleneinträge aus dem Export. Die Zuordnung zu Archivdateien ist noch offen.</p>
<form class="search panel" action="/sources" method="get"><label for="source-search">Quelle suchen</label>
<div><input id="source-search" name="q" type="search" value="{escape(term, quote=True)}"><button>Suchen</button></div></form>
<section class="panel"><h2>Quellenliste</h2>{list_items([link(source['title'], f'/source/{quote(source["id"])}') for source in sources])}</section>'''
    return layout("GEDCOM-Quellen", content)


def source_page(connection, source_id, media_root=None):
    source = connection.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not source:
        return None
    people = connection.execute(
        "SELECT DISTINCT people.* FROM people JOIN facts ON facts.owner_id=people.id AND facts.owner_type='person' "
        "JOIN citations ON citations.fact_id=facts.id WHERE citations.source_id=? ORDER BY people.name",
        (source_id,),
    ).fetchall()
    fields = [("Urheber", source["author"]), ("Veröffentlichung", source["publication"]), ("Notiz", source["notes"])]
    metadata = "".join(f'<dt>{label}</dt><dd>{escape(value)}</dd>' for label, value in fields if value)
    content = f'''<p class="back">{link('← Zu den Quellen', '/sources')}</p><h1>{escape(source['title'])}</h1>
<p class="muted">GEDCOM-ID: {escape(source_id)} · Zuordnung zum Originaldokument noch nicht geprüft.</p>
<section class="panel"><h2>Quellenangaben</h2><dl>{metadata or '<dt>Metadaten</dt><dd>Keine weiteren Angaben im GEDCOM.</dd>'}</dl></section>
<section class="panel"><h2>Verknüpfte Medien</h2>{media_for(connection, "source", source_id, media_root) or '<p>Keine Medien verknüpft.</p>'}</section>
<section class="panel"><h2>Verknüpfte Personen</h2>{list_items([person_link(person) for person in people])}</section>'''
    return layout(source["title"], content)


def archive_page(connection, query, page):
    term = query.strip()[:100]
    current_page = min(max(page, 1), 10000)
    count = connection.execute("SELECT COUNT(*) FROM archive_files WHERE relative_path LIKE ?", (f"%{term}%",)).fetchone()[0]
    files = connection.execute(
        "SELECT * FROM archive_files WHERE relative_path LIKE ? ORDER BY relative_path LIMIT 50 OFFSET ?",
        (f"%{term}%", (current_page - 1) * 50),
    ).fetchall()
    items = [link(file["relative_path"], f'/document/{file["id"]}') for file in files]
    previous = link("← Vorherige", f'/archive?q={quote(term)}&page={current_page - 1}') if current_page > 1 else ""
    following = link("Nächste →", f'/archive?q={quote(term)}&page={current_page + 1}') if current_page * 50 < count else ""
    content = f'''<h1>Quellenarchiv</h1><p>{count} Dokumente gefunden. Originale bleiben unverändert auf dem privaten Speicher.
Eine automatische Zuordnung zu Personen oder Behauptungen erfolgt nicht.</p>
<form class="search panel" action="/archive" method="get"><label for="archive-search">Dateinamen suchen</label>
<div><input id="archive-search" name="q" type="search" value="{escape(term, quote=True)}"><button>Suchen</button></div></form>
<section class="panel"><h2>Dokumente</h2><p class="muted">Seite {current_page}</p>{list_items(items)}
<nav class="pagination" aria-label="Ergebnisseiten">{previous} {following}</nav></section>'''
    return layout("Quellenarchiv", content)


class Handler(BaseHTTPRequestHandler):
    database_path = None
    archive_root = None
    media_root = None
    featured_person_id = None

    def send_page(self, body, status=200, content_type="text/html; charset=utf-8"):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def send_document(self, path, mime_type):
        try:
            source = path.open("rb")
            size = path.stat().st_size
        except OSError:
            return self.send_page("Dokument derzeit nicht lesbar", 503)
        with source:
            requested_range = self.headers.get("Range", "")
            start, end = 0, size - 1
            if requested_range:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested_range)
                if not match:
                    return self.send_page("Ungültiger Bereich", 416)
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
                if start >= size or end < start:
                    return self.send_page("Bereich nicht verfügbar", 416)
            self.send_response(206 if requested_range else 200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Disposition", "inline")
            if requested_range:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        parsed = urlsplit(self.path)
        route = parsed.path
        parameters = parse_qs(parsed.query)
        if route == "/static/style.css":
            return self.send_page(STYLE, content_type="text/css; charset=utf-8")
        try:
            with closing(database(self.database_path)) as connection:
                if route == "/":
                    body = overview(connection, parameters.get("q", [""])[0], self.featured_person_id, self.media_root)
                elif route == "/sources":
                    body = sources_page(connection, parameters.get("q", [""])[0])
                elif route == "/archive":
                    try:
                        page = int(parameters.get("page", ["1"])[0])
                    except ValueError:
                        page = 1
                    body = archive_page(connection, parameters.get("q", [""])[0], page)
                elif re.fullmatch(r"/person/[A-Za-z0-9_-]+", route):
                    body = person_page(connection, route.rsplit("/", 1)[1], self.media_root)
                elif re.fullmatch(r"/source/[A-Za-z0-9_-]+", route):
                    body = source_page(connection, route.rsplit("/", 1)[1], self.media_root)
                elif re.fullmatch(r"/media/[A-Za-z0-9_-]+", route):
                    if not self.media_root:
                        return self.send_page("Medien nicht eingerichtet", 404)
                    item = connection.execute("SELECT * FROM media WHERE id=?", (route.rsplit("/", 1)[1],)).fetchone()
                    if not item or not item["relative_path"]:
                        return self.send_page("Medium nicht gefunden", 404)
                    root = Path(self.media_root).resolve()
                    path = (root / item["relative_path"]).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        return self.send_page("Medium nicht gefunden", 404)
                    return self.send_document(path, item["mime_type"] or "application/octet-stream")
                elif re.fullmatch(r"/document/[0-9]+", route):
                    if not self.archive_root:
                        return self.send_page("Archiv nicht eingerichtet", 404)
                    file = connection.execute("SELECT * FROM archive_files WHERE id=?", (int(route.rsplit("/", 1)[1]),)).fetchone()
                    if not file:
                        return self.send_page("Dokument nicht gefunden", 404)
                    root = Path(self.archive_root).resolve()
                    path = (root / file["relative_path"]).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        return self.send_page("Dokument nicht gefunden", 404)
                    return self.send_document(path, file["mime_type"])
                else:
                    body = None
        except sqlite3.Error as error:
            print(f"Database error: {error}", file=sys.stderr, flush=True)
            return self.send_page(layout("Fehler", "<h1>Datenbank nicht erreichbar</h1>"), 503)
        return self.send_page(body if body else layout("Nicht gefunden", "<h1>Seite nicht gefunden</h1>"), 200 if body else 404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Private read-only family tree viewer")
    parser.add_argument("--database", required=True)
    parser.add_argument("--archive-root")
    parser.add_argument("--media-root", help="Private directory containing GEDCOM media files")
    parser.add_argument("--featured-person-id", help="Private GEDCOM ID shown on the start page")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args()
    Handler.database_path = Path(arguments.database).expanduser()
    Handler.archive_root = arguments.archive_root
    Handler.media_root = arguments.media_root
    Handler.featured_person_id = arguments.featured_person_id
    server = ThreadingHTTPServer((arguments.host, arguments.port), Handler)
    print(f"Listening on http://{arguments.host}:{arguments.port}", flush=True)
    server.serve_forever()
