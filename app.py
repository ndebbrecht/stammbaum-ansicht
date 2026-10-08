import argparse
import base64
import binascii
from collections import deque
from contextlib import closing
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from threading import Lock
import time
from urllib.parse import parse_qs, quote, urlsplit

from auth import verify_password
from import_data import FACT_NAMES


ROOT = Path(__file__).parent
STYLE = (ROOT / "static" / "style.css").read_bytes()
MAP_SCRIPT = (ROOT / "static" / "map.js").read_bytes()

STATE_CODES = {
    "baden-württemberg": "BW", "bayern": "BY", "berlin": "BE", "brandenburg": "BB",
    "bremen": "HB", "hamburg": "HH", "hessen": "HE", "mecklenburg-vorpommern": "MV",
    "niedersachsen": "NI", "nordrhein-westfalen": "NW", "rheinland-pfalz": "RP",
    "saarland": "SL", "sachsen": "SN", "sachsen-anhalt": "ST", "schleswig-holstein": "SH",
    "thüringen": "TH",
}
COUNTRY_CODES = {
    "deutschland": "DE", "germany": "DE", "österreich": "AT", "austria": "AT",
    "schweiz": "CH", "switzerland": "CH", "frankreich": "FR", "france": "FR",
    "niederlande": "NL", "netherlands": "NL", "belgien": "BE", "belgium": "BE",
    "polen": "PL", "poland": "PL", "dänemark": "DK", "denmark": "DK",
    "italien": "IT", "italy": "IT", "spanien": "ES", "spain": "ES",
    "vereinigtes königreich": "GB", "united kingdom": "GB", "england": "GB",
    "vereinigte staaten": "US", "united states": "US", "usa": "US",
}
GEDCOM_LABELS = {
    "NAME": "Name", "GIVN": "Vorname", "SURN": "Nachname", "NICK": "Rufname",
    "SEX": "Geschlecht", "BIRT": "Geburt", "DEAT": "Tod", "CHR": "Taufe",
    "MARR": "Heirat", "DATE": "Datum", "PLAC": "Ort", "MAP": "Karte",
    "LATI": "Breitengrad", "LONG": "Längengrad", "RELI": "Religion",
    "EMAIL": "E-Mail", "PHON": "Telefon", "OCCU": "Beruf", "RESI": "Wohnort",
    "NOTE": "Notiz", "SOUR": "Quelle", "PAGE": "Belegstelle", "OBJE": "Medium",
    "FILE": "Datei", "TITL": "Titel", "AUTH": "Urheber", "PUBL": "Veröffentlichung",
    "REPO": "Archiv", "_ALT": "Alternativer Name", "_GEO": "Geografische Kennung",
    "LABL": "Kennzeichnung", "_STP": "Startperson", "_FID": "Dateikennung",
    "ADDR": "Adresse", "WWW": "Website", "EYES": "Augenfarbe", "HAIR": "Haarfarbe",
    "HEIG": "Körpergröße", "COLO": "Hautfarbe", "SECG": "Weiterer Vorname",
    "NPFX": "Namenspräfix", "NSFX": "Namenszusatz", "TYPE": "Namensart",
}
ICON_PATHS = {
    "event": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    "birth": '<path d="M12 3v18M3 12h18M6 6l12 12M18 6 6 18"/><circle cx="12" cy="12" r="3"/>',
    "memorial": '<path d="M12 3c2 3 3 4 3 6a3 3 0 0 1-6 0c0-2 1-3 3-6ZM8 15h8v6H8zM6 21h12"/>',
    "rings": '<circle cx="9" cy="12" r="5"/><circle cx="15" cy="12" r="5"/>',
    "book": '<path d="M12 6c-2-2-5-2-9-2v15c4 0 7 0 9 2 2-2 5-2 9-2V4c-4 0-7 0-9 2Zm0 0v15"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>',
    "place": '<path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
    "journey": '<path d="M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4"/>',
    "document": '<path d="M6 2h8l5 5v15H6zM14 2v5h5M9 12h7M9 16h7"/>',
    "person": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3-7 8-7s8 3 8 7"/>',
    "family": '<circle cx="8" cy="8" r="3"/><circle cx="17" cy="8" r="3"/><path d="M2 20c0-4 2-7 6-7s6 3 6 7m0 0c0-4 1-7 3-7 4 0 5 3 5 7"/>',
    "cross": '<path d="M12 3v18M5 10h14"/>',
    "paperclip": '<path d="m8 12 6-6a4 4 0 0 1 6 6l-8 8a6 6 0 0 1-9-9l8-8"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/>',
    "phone": '<path d="M7 3h3l1 4-2 2a14 14 0 0 0 6 6l2-2 4 1v3a3 3 0 0 1-3 3A16 16 0 0 1 4 6a3 3 0 0 1 3-3Z"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c-3 3-3 15 0 18m0-18c3 3 3 15 0 18"/>',
    "eye": '<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/>',
    "ruler": '<path d="m5 17 12-12 3 3L8 20l-3-3ZM12 10l2 2m1-5 2 2m-8 4 2 2"/>',
    "palette": '<circle cx="12" cy="12" r="9"/><circle cx="7" cy="10" r="1"/><circle cx="12" cy="6" r="1"/><circle cx="17" cy="10" r="1"/><path d="M12 21c-2 0-3-1-3-3s2-3 4-3h2"/>',
    "medal": '<path d="M7 3h10l-2 7H9L7 3ZM9 10l-2 3 5 3 5-3-2-3M12 16v5m-3-2 3 2 3-2"/>',
}
DETAIL_ICONS = {
    "NAME": "person", "SEX": "person", "EMAIL": "mail", "PHON": "phone",
    "ADDR": "place", "WWW": "globe", "RELI": "book", "EYES": "eye",
    "HAIR": "person", "HEIG": "ruler", "COLO": "palette",
}
NAME_TYPES = {
    "married": "Ehename", "maiden": "Geburtsname", "aka": "Auch bekannt als",
    "other": "Weiterer Name", "nick": "Rufname", "variation": "Namensvariante",
}
DETAIL_METADATA = {"CHAN", "_CRE", "_COR"}
RELATION_LABELS = {"Godfather": "Pate", "Godmother": "Patin"}
EVENT_ICONS = {
    "Geburt": "birth", "Tod": "memorial", "Bestattung": "memorial", "Trauerfeier": "memorial",
    "Heirat": "rings", "Verlobung": "rings", "Aufgebot": "rings", "Kirchliche Trauung": "rings",
    "Hochzeitsfeier": "rings", "Scheidung": "document", "Taufe": "cross", "Konfirmation": "cross",
    "Erstkommunion": "cross", "Letzte Ölung": "cross", "Ordination": "cross",
    "Ausbildung": "book", "Abschluss": "book", "Beruf": "briefcase",
    "Wohnort": "place", "Einwanderung": "journey", "Auswanderung": "journey",
    "Adoption": "family", "Volkszählung": "family",
    "Militärische Auszeichnung": "medal",
}


def icon(name):
    return (f'<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
            f'{ICON_PATHS[name]}</svg>')


def event_icon(kind):
    return icon(EVENT_ICONS.get(kind, "event"))


def link(label, route):
    return f'<a href="{escape(route, quote=True)}">{escape(str(label))}</a>'


def person_link(person):
    return link(person["name"], f'/person/{quote(person["id"])}') if person else "Unbekannt"


def list_items(items):
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>" if items else "<p>Keine Einträge.</p>"


def place_parts(place):
    return [part.strip() for part in place.split(",") if part.strip()]


def format_place(place):
    parts = place_parts(place)
    if not parts:
        return ""
    parts[-1] = COUNTRY_CODES.get(parts[-1].casefold(), parts[-1])
    parts = [STATE_CODES.get(part.casefold(), part) for part in parts]
    return ", ".join(parts)


def layout(title, content):
    return f'''<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Stammbaum</title><meta name="color-scheme" content="light dark"><link rel="stylesheet" href="/static/style.css"></head>
<body><a class="skip" href="#inhalt">Zum Inhalt springen</a>
<header class="site-header"><div class="shell header-inner"><a class="brand" href="/">Stammbaum</a><nav aria-label="Hauptnavigation">
<a href="/">Startseite</a><a href="/events">Ereignisse</a><a href="/places">Orte</a><a href="/sources">Quellen</a><a href="/archive">Archiv</a><a href="/export">Exportdaten</a></nav></div></header>
<main id="inhalt" class="shell" tabindex="-1">{content}</main>
<footer class="shell">Private Leseansicht · Angaben aus dem GEDCOM sind nicht automatisch geprüft. · Darstellung folgt dem Hell-/Dunkelmodus des Geräts.</footer></body></html>'''


def database(path):
    connection = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def original_record_link(connection, xref):
    record = connection.execute("SELECT id FROM export_records WHERE xref=? ORDER BY id LIMIT 1", (xref,)).fetchone()
    return link("Originaldaten ansehen", f'/export-record/{record["id"]}') if record else ""


def export_tree(connection, record_id, excluded_tags=None, included_tags=None):
    nodes = connection.execute("SELECT id, parent_id, tag, value FROM export_nodes WHERE record_id=? ORDER BY id",
                               (record_id,)).fetchall()
    children = {}
    for node in nodes:
        children.setdefault(node["parent_id"], []).append(node)
    references = {}

    def value_html(value):
        match = re.fullmatch(r"@([A-Za-z0-9_-]+)@", value)
        if match:
            reference = match.group(1)
            if reference not in references:
                found = connection.execute("SELECT id FROM export_records WHERE xref=? ORDER BY id LIMIT 1",
                                           (reference,)).fetchone()
                references[reference] = found["id"] if found else None
            if references[reference]:
                return link(reference, f'/export-record/{references[reference]}')
        return escape(value).replace("\n", "<br>")

    def render(parent_id):
        entries = []
        for node in children.get(parent_id, []):
            if parent_id is None:
                if excluded_tags and node["tag"] in excluded_tags:
                    continue
                if included_tags is not None and node["tag"] not in included_tags:
                    continue
            label = GEDCOM_LABELS.get(node["tag"], node["tag"])
            description = f'{escape(label)} <code>({escape(node["tag"])})</code>'
            if node["value"]:
                description += f': {value_html(node["value"])}'
            nested = render(node["id"])
            entries.append(f'<li>{description}{nested}</li>')
        return '<ul class="record-tree">' + ''.join(entries) + '</ul>' if entries else ''

    return render(None)


def person_additional_html(connection, record_id):
    excluded = set(FACT_NAMES) | {"FAMS", "FAMC", "OBJE", "NOTE", "ASSO", "SOUR", "LABL", "_FID", "_STP"} | DETAIL_METADATA
    fields = connection.execute(
        "SELECT id, tag, value FROM export_nodes WHERE record_id=? AND parent_id IS NULL ORDER BY id", (record_id,)
    ).fetchall()
    cards = []
    for field in fields:
        tag = field["tag"]
        if tag in excluded:
            continue
        children = connection.execute(
            "SELECT tag, value FROM export_nodes WHERE parent_id=? ORDER BY id", (field["id"],)
        ).fetchall()
        details = []
        for child in children:
            child_tag = child["tag"]
            if child_tag in DETAIL_METADATA or not child["value"]:
                continue
            if tag == "NAME" and child_tag in {"GIVN", "SURN"} and field["value"]:
                continue
            child_value = NAME_TYPES.get(child["value"], child["value"]) if tag == "NAME" and child_tag == "TYPE" else child["value"]
            details.append(f'<div><dt>{escape(GEDCOM_LABELS.get(child_tag, child_tag))}</dt>'
                           f'<dd>{escape(child_value)}</dd></div>')
        value = field["value"].replace("/", "") if tag == "NAME" else field["value"]
        if tag == "SEX":
            value = {"M": "männlich", "F": "weiblich", "U": "unbekannt"}.get(value, value)
        if not value and not details:
            continue
        title = GEDCOM_LABELS.get(tag, f"Exportfeld {tag}")
        body = f'<p>{escape(value)}</p>' if value else ''
        if details:
            body += '<dl class="detail-fields">' + ''.join(details) + '</dl>'
        symbol = DETAIL_ICONS.get(tag, "document")
        cards.append(f'<article class="detail-card"><div class="tile-icon">{icon(symbol)}</div>'
                     f'<div class="tile-content"><h3>{escape(title)}</h3>{body}</div></article>')
    return '<div class="detail-grid">' + ''.join(cards) + '</div>' if cards else '<p>Keine weiteren Angaben.</p>'


def export_page(connection, query, tag, page):
    term = query.strip()[:100]
    tag = tag.strip()[:20]
    page = min(max(page, 1), 10000)
    types = connection.execute("SELECT tag, COUNT(*) AS count FROM export_records GROUP BY tag ORDER BY tag").fetchall()
    if tag not in {item["tag"] for item in types}:
        tag = ""
    condition = "WHERE raw_text LIKE ?" + (" AND tag=?" if tag else "")
    values = (f"%{term}%",) + ((tag,) if tag else ())
    count = connection.execute(f"SELECT COUNT(*) FROM export_records {condition}", values).fetchone()[0]
    rows = connection.execute(f"SELECT id, xref, tag, value FROM export_records {condition} ORDER BY id LIMIT 50 OFFSET ?",
                              (*values, (page - 1) * 50)).fetchall()
    type_options = ''.join(f'<option value="{escape(item["tag"], quote=True)}"{" selected" if item["tag"] == tag else ""}>'
                           f'{escape(item["tag"])} ({item["count"]})</option>' for item in types)
    entries = [link(f'{row["tag"]} · {row["xref"] or row["value"] or "ohne Kennung"}', f'/export-record/{row["id"]}')
               for row in rows]
    previous = link("← Vorherige", f'/export?q={quote(term)}&tag={quote(tag)}&page={page - 1}') if page > 1 else ""
    following = link("Nächste →", f'/export?q={quote(term)}&tag={quote(tag)}&page={page + 1}') if page * 50 < count else ""
    content = f'''<h1>Originaldaten des Exports</h1><p>{count} von {sum(item['count'] for item in types)} Datensätzen angezeigt.</p>
<p>Hier sind auch Felder und MacFamilyTree-Erweiterungen lesbar, für die es noch keine eigene Fachansicht gibt.</p>
<form class="search panel" action="/export" method="get"><label for="export-search">In Originaldaten suchen</label>
<input id="export-search" name="q" type="search" value="{escape(term, quote=True)}">
<label for="export-type">Datensatzart</label><select id="export-type" name="tag"><option value="">Alle</option>{type_options}</select>
<button>Suchen</button></form><section class="panel"><h2>Datensätze</h2>{list_items(entries)}
<nav class="pagination" aria-label="Exportseiten">{previous} {following}</nav></section>'''
    return layout("Exportdaten", content)


def export_record_page(connection, record_id):
    record = connection.execute("SELECT * FROM export_records WHERE id=?", (record_id,)).fetchone()
    if not record:
        return None
    lines = record["raw_text"].splitlines()
    entries = ''.join(f'<li><code>{escape(line)}</code></li>' for line in lines)
    related = ""
    if record["tag"] == "INDI":
        related = link("Zum Personenprofil", f'/person/{quote(record["xref"])}')
    elif record["tag"] == "SOUR":
        related = link("Zur Quellenansicht", f'/source/{quote(record["xref"])}')
    elif record["tag"] == "_PLAC":
        related = link("Zur Ortsansicht", f'/place/{record_id}')
    title = f'{record["tag"]} · {record["xref"] or record["value"] or "ohne Kennung"}'
    content = f'''<p class="back">{link('← Alle Exportdaten', '/export')}</p><h1>{escape(title)}</h1>
<p>{len(lines)} Originalzeilen. {related}</p>
<section class="panel"><h2>Felder und Verweise</h2>{export_tree(connection, record_id) or '<p>Keine weiteren Felder.</p>'}</section>
<details class="panel"><summary>Originalzeilen anzeigen</summary><ol class="gedcom-lines">{entries}</ol></details>'''
    return layout("Originaldaten", content)


def places_page(connection, query, page):
    term = query.strip()[:100]
    page = min(max(page, 1), 10000)
    pattern = f"%{term}%"
    count = connection.execute("SELECT COUNT(*) FROM places WHERE name LIKE ? OR alternate_names LIKE ?", (pattern, pattern)).fetchone()[0]
    rows = connection.execute("SELECT record_id, name, latitude FROM places WHERE name LIKE ? OR alternate_names LIKE ? "
                              "ORDER BY name, record_id LIMIT 50 OFFSET ?", (pattern, pattern, (page - 1) * 50)).fetchall()
    entries = [icon("place") + link(row["name"], f'/place/{row["record_id"]}') + (" · Koordinaten vorhanden" if row["latitude"] is not None else "")
               for row in rows]
    previous = link("← Vorherige", f'/places?q={quote(term)}&page={page - 1}') if page > 1 else ""
    following = link("Nächste →", f'/places?q={quote(term)}&page={page + 1}') if page * 50 < count else ""
    content = f'''<h1>Orte</h1><p>{count} Ortsdatensätze im Export.</p>
<form class="search panel" action="/places" method="get"><label for="place-search">Ort suchen</label>
<div><input id="place-search" name="q" type="search" value="{escape(term, quote=True)}"><button>Suchen</button></div></form>
<section class="panel"><h2>Ortsverzeichnis</h2>{list_items(entries)}<nav class="pagination" aria-label="Ortsseiten">{previous} {following}</nav></section>'''
    return layout("Orte", content)


def place_page(connection, record_id):
    place = connection.execute("SELECT * FROM places WHERE record_id=?", (record_id,)).fetchone()
    if not place:
        return None
    facts = connection.execute("SELECT * FROM facts WHERE place=? ORDER BY id LIMIT 100", (place["name"],)).fetchall()
    count = connection.execute("SELECT COUNT(*) FROM facts WHERE place=?", (place["name"],)).fetchone()[0]
    alternate = json.loads(place["alternate_names"])
    metadata = f'<dt>Alternative Namen</dt><dd>{escape(", ".join(alternate))}</dd>' if alternate else ""
    if place["geo"]:
        metadata += f'<dt>Geografische Kennung</dt><dd>{escape(place["geo"])}</dd>'
    if place["latitude"] is not None:
        metadata += f'<dt>GEDCOM-Koordinaten</dt><dd>{place["latitude"]:.6f}, {place["longitude"]:.6f}</dd>'
    event_links = [link(fact["kind"], f'/event/{fact["id"]}') + ' · ' + event_owner(connection, fact) for fact in facts]
    content = f'''<p class="back">{link('← Zu den Orten', '/places')}</p><h1 class="title-icon">{icon("place")}{escape(format_place(place['name']))}</h1>
<p>{original_record_link_by_id(record_id)} · {count} verknüpfte Ereignisse.</p>
<section class="panel"><h2>Ortsangaben</h2><dl>{metadata or '<dt>Weitere Angaben</dt><dd>Keine im Export.</dd>'}</dl></section>
<section class="panel"><h2>Ereignisse an diesem Ort</h2>{list_items(event_links)}
{f'<p>Es werden die ersten 100 Ereignisse angezeigt. {link("Weitere Ereignisse suchen", "/events?q=" + quote(place["name"]))}</p>' if count > 100 else ''}</section>'''
    return layout(place["name"], content)


def original_record_link_by_id(record_id):
    return link("Originaldaten ansehen", f'/export-record/{record_id}')


def overview(connection, query, featured_person_id=None, media_root=None, place="", year="", evidence=""):
    term = query.strip()[:100]
    place = place.strip()[:100]
    year = year.strip() if len(year.strip()) == 4 and year.strip().isdigit() else ""
    evidence = evidence if evidence in ("with", "without") else ""
    conditions = ["(people.name LIKE ? COLLATE NOCASE OR people.surname LIKE ? COLLATE NOCASE)"]
    values = [f"%{term}%", f"%{term}%"]
    if place or year:
        fact_conditions = ["facts.owner_type='person'", "facts.owner_id=people.id"]
        if place:
            fact_conditions.append("facts.place LIKE ? COLLATE NOCASE")
            values.append(f"%{place}%")
        if year:
            fact_conditions.append("facts.date_text LIKE ?")
            values.append(f"%{year}%")
        conditions.append("EXISTS (SELECT 1 FROM facts WHERE " + " AND ".join(fact_conditions) + ")")
    if evidence:
        source_exists = "EXISTS (SELECT 1 FROM facts JOIN citations ON citations.fact_id=facts.id WHERE facts.owner_type='person' AND facts.owner_id=people.id)"
        conditions.append(source_exists if evidence == "with" else "NOT " + source_exists)
    filtered = bool(term or place or year or evidence)
    people = connection.execute("SELECT people.* FROM people WHERE " + " AND ".join(conditions)
                                + " ORDER BY people.name LIMIT ?", (*values, 100 if filtered else 50)).fetchall()
    count = connection.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    featured = connection.execute("SELECT * FROM people WHERE id=?", (featured_person_id,)).fetchone() if featured_person_id else None
    if not featured and not featured_person_id:
        featured = connection.execute("SELECT * FROM people WHERE is_start=1 ORDER BY id LIMIT 1").fetchone()
    featured_html = ""
    if featured:
        featured_media = portrait_figure(featured, person_image(connection, featured["id"], media_root), "media-card")
        featured_html = f'''<section class="featured{' has-portrait' if featured_media else ''}" aria-labelledby="featured-title"><div class="featured-copy">
<p class="eyebrow">Startperson</p><h2 id="featured-title">{escape(featured['name'])}</h2>
<p>Festgelegter Ausgangspunkt für Personen, Ereignisse und Quellen.</p>
<p>{link('Personenprofil öffnen →', f'/person/{quote(featured["id"])}')}</p></div>{featured_media}</section>'''
    content = f'''<section class="intro"><p class="eyebrow">Familienforschung</p><h1>Familienarchiv</h1>
<p>{count} Personen im importierten Stammbaum.</p></section>
{featured_html}<form class="search panel" action="/" method="get"><h2>Personen suchen</h2>
<div class="search-fields"><div class="form-field"><label for="name">Name</label><input id="name" name="q" type="search" value="{escape(term, quote=True)}" autocomplete="off"></div>
<div class="form-field"><label for="place">Ort eines Lebensereignisses</label><input id="place" name="place" type="search" value="{escape(place, quote=True)}"></div>
<div class="form-field"><label for="year">Jahr eines Lebensereignisses</label><input id="year" name="year" type="text" inputmode="numeric" pattern="[0-9]{{4}}" maxlength="4" value="{escape(year, quote=True)}"></div>
<div class="form-field"><label for="evidence">Quellenverweis</label><select id="evidence" name="evidence">
<option value="">Alle</option><option value="with"{' selected' if evidence == 'with' else ''}>Mit Quellenverweis</option>
<option value="without"{' selected' if evidence == 'without' else ''}>Ohne Quellenverweis</option></select></div></div>
<p class="muted">Ort und Jahr müssen im selben Lebensereignis vorkommen. Ein Quellenverweis bedeutet keine historische Prüfung.</p>
<button type="submit">Suchen</button></form>
<section class="panel" aria-labelledby="results"><h2 id="results">{'Suchergebnisse' if filtered else 'Personenverzeichnis'}</h2>
<p class="muted">{len(people)} Treffer angezeigt{' · maximal 100' if filtered else ' · für alle Personen die Suche verwenden'}.</p>
{list_items([person_link(person) for person in people])}</section>'''
    return layout("Personen", content)


def media_for(connection, owner_type, owner_id, media_root=None):
    media = connection.execute(
        "SELECT media.* FROM media_links JOIN media ON media.id=media_links.media_id "
        "WHERE media_links.owner_type=? AND media_links.owner_id=? ORDER BY media.title",
        (owner_type, owner_id),
    ).fetchall()
    entries = []
    for item in media:
        name = item["relative_path"]
        available = bool(name and media_root and (Path(media_root) / name).is_file())
        if available:
            route = f'/media/{quote(item["id"])}'
            if (item["mime_type"] or "").startswith("image/"):
                entries.append(f'<figure class="media-card"><a href="{route}"><img src="{route}" alt="{escape(item["title"], quote=True)}" loading="lazy"></a>'
                               f'<figcaption>{escape(item["title"])}</figcaption></figure>')
            else:
                entries.append(f'<div class="media-card document">{icon("document")}{link("Dokument öffnen: " + item["title"], route)}</div>')
        else:
            entries.append(f'<p class="muted">{escape(item["title"])} · Datei im Export nicht verfügbar</p>')
    return '<div class="media-grid">' + "".join(entries) + '</div>' if entries else ""


def person_image(connection, person_id, media_root):
    if not media_root:
        return None
    root = Path(media_root).resolve()
    images = connection.execute(
        "SELECT media.* FROM media_links JOIN media ON media.id=media_links.media_id "
        "WHERE media_links.owner_type='person' AND media_links.owner_id=? "
        "AND media.mime_type LIKE 'image/%' ORDER BY media.title", (person_id,)
    ).fetchall()
    images.sort(key=lambda item: (not any(word in item["title"].casefold()
                                          for word in ("portr", "profil", "foto")), item["title"].casefold()))
    for item in images:
        if item["relative_path"]:
            path = (root / item["relative_path"]).resolve()
            if path.is_relative_to(root) and path.is_file():
                return item
    return None


def portrait_figure(person, image, css_class):
    if not image:
        return ""
    route = f'/media/{quote(image["id"])}'
    title = escape(image["title"])
    alt = escape(f'Bild zu {person["name"]}: {image["title"]}', quote=True)
    return (f'<figure class="{css_class}"><a href="{route}"><img src="{route}" alt="{alt}"></a>'
            f'<figcaption>{title}</figcaption></figure>')


def citations_for(connection, owner_type, owner_id):
    if owner_type == "fact":
        return connection.execute(
            "SELECT citations.source_id, citations.page, citations.detail, sources.title FROM citations LEFT JOIN sources ON sources.id=citations.source_id WHERE fact_id=?",
            (owner_id,),
        ).fetchall()
    return connection.execute(
        "SELECT record_citations.source_id, record_citations.page, sources.title FROM record_citations "
        "LEFT JOIN sources ON sources.id=record_citations.source_id WHERE owner_type=? AND owner_id=?",
        (owner_type, owner_id),
    ).fetchall()


def citations_html(connection, citations, media_root=None):
    if not citations:
        return '<p class="unverified">Kein formaler GEDCOM-Quellenverweis für dieses Ereignis.</p>'
    entries = []
    for citation in citations:
        source_id = citation["source_id"]
        source_route = f'/source/{quote(source_id)}'
        archive_links = connection.execute(
            "SELECT archive_file_id, page, status FROM source_archive_links WHERE source_id=? ORDER BY archive_file_id",
            (source_id,),
        ).fetchall()
        page_number = re.fullmatch(r"(?:Seite\s*|S\.?\s*)?(\d+)", (citation["page"] or "").strip(), re.IGNORECASE)
        matching_page = [item for item in archive_links if item["page"] is not None
                         and page_number and str(item["page"]) == page_number.group(1)]
        direct_links = matching_page or (archive_links if len(archive_links) == 1 else [])
        if len(direct_links) == 1:
            document = direct_links[0]
            route = f'/document/{document["archive_file_id"]}'
            if document["page"]:
                route += f'#page={document["page"]}'
            status = "Dateizuordnung geprüft" if document["status"] == "verified" else "Dateizuordnung vorgeschlagen"
            label = "Archivscan zur Belegseite öffnen" if matching_page else "Einzigen Archivscan der Quelle öffnen"
            scan = f'<p>{link(label, route)} · {status}'
            if not matching_page and citation["page"]:
                scan += ' · Belegseite im Scan nicht zugeordnet'
            scan += '</p>'
        elif archive_links:
            scan = (f'<p>{len(archive_links)} Archivdateien der Quelle zugeordnet; keine eindeutig diesem Ereignis '
                    f'zugeordnete Datei oder Seite. {link("Archivdateien der Quelle prüfen", source_route)}</p>')
        else:
            media = connection.execute(
                "SELECT media.id, media.relative_path FROM media_links JOIN media ON media.id=media_links.media_id "
                "WHERE media_links.owner_type='source' AND media_links.owner_id=? AND media.relative_path IS NOT NULL",
                (source_id,),
            ).fetchall()
            available = [item for item in media if media_root and (Path(media_root) / item["relative_path"]).is_file()]
            scan = (f'<p>{link("Quelldatei öffnen", "/media/" + quote(available[0]["id"]))} · '
                    'Datei an Quelle angehängt; Belegseite nicht zugeordnet.</p>' if len(available) == 1
                    else '<p>Kein eindeutig verknüpfter Originalscan für dieses Ereignis.</p>')
        page = f'<p>GEDCOM-Belegstelle: {escape(citation["page"])}</p>' if citation["page"] else '<p>Keine Belegstelle im GEDCOM angegeben.</p>'
        detail = f'<p>{escape(citation["detail"])}</p>' if citation["detail"] else ''
        entries.append(f'<li><article class="source-card"><h4>{link(citation["title"] or f"Quelle {source_id}", source_route)}</h4>'
                       f'{page}{detail}{scan}</article></li>')
    return '<ul class="source-cards">' + ''.join(entries) + '</ul>'


def citation_marker(route, label):
    return (f'<a class="citation-clip" href="{escape(route, quote=True)}">'
            f'{icon("paperclip")}<span class="sr-only">{escape(label)}</span></a>')


def notes_html(connection, owner_type, owner_id):
    notes = connection.execute(
        "SELECT COALESCE(notes.text, note_links.text) AS text FROM note_links "
        "LEFT JOIN notes ON notes.id=note_links.note_id WHERE owner_type=? AND owner_id=?",
        (owner_type, owner_id),
    ).fetchall()
    entries = [f'<span class="transcription">{escape(note["text"])}</span>' for note in notes if note["text"]]
    return list_items(entries) if entries else ""


def facts_html(connection, owner_type, owner_id, media_root=None):
    facts = connection.execute(
        "SELECT * FROM facts WHERE owner_type=? AND owner_id=? ORDER BY id", (owner_type, owner_id)
    ).fetchall()
    if not facts:
        return "<p>Keine Ereignisse im GEDCOM verzeichnet.</p>"
    entries = []
    for fact in facts:
        citations = citations_for(connection, "fact", str(fact["id"]))
        fields = [("Datum", fact["date_text"]), ("Ort", format_place(fact["place"] or "")),
                  ("Genauer Ort", fact["address"]), ("Angabe", fact["value"])]
        details = ''.join(f'<div><dt>{label}</dt><dd>{escape(value)}</dd></div>' for label, value in fields if value)
        details = f'<dl class="fact-meta">{details}</dl>' if details else '<p>Ohne weitere Angabe</p>'
        media = media_for(connection, "fact", str(fact["id"]), media_root)
        notes = notes_html(connection, "fact", str(fact["id"]))
        source_link = citation_marker(f'/event/{fact["id"]}#sources',
                                      f'{len(citations)} Quelle(n) zu {fact["kind"]} anzeigen') if citations else ''
        entries.append(f'<li><article class="fact-card"><div class="tile-icon">{event_icon(fact["kind"])}</div>'
                       f'<div class="tile-content"><h3>{link(fact["kind"], "/event/" + str(fact["id"]))}{source_link}</h3>'
                       f'{details}{notes}{media}</div></article></li>')
    return '<ol class="facts">' + "".join(entries) + "</ol>"


def person_page(connection, person_id, media_root=None):
    person = connection.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not person:
        return None
    labels = connection.execute("SELECT labels.title FROM person_labels JOIN labels ON labels.id=person_labels.label_id "
                                "WHERE person_labels.person_id=? ORDER BY labels.title", (person_id,)).fetchall()
    label_html = f'<p>Kennzeichnungen: {escape(", ".join(item["title"] for item in labels))}</p>' if labels else ''
    record = connection.execute("SELECT id FROM export_records WHERE tag='INDI' AND xref=?", (person_id,)).fetchone()
    additional_fields = person_additional_html(connection, record["id"]) if record else '<p>Keine weiteren Angaben.</p>'
    parent_families = connection.execute(
        "SELECT families.* FROM families JOIN children ON children.family_id=families.id WHERE children.person_id=?",
        (person_id,),
    ).fetchall()
    own_families = connection.execute(
        "SELECT * FROM families WHERE husband_id=? OR wife_id=?", (person_id, person_id)
    ).fetchall()
    parents = {}
    siblings = {}
    for family in parent_families:
        for parent_id in (family["husband_id"], family["wife_id"]):
            parent = connection.execute("SELECT * FROM people WHERE id=?", (parent_id,)).fetchone()
            if parent:
                parents[parent["id"]] = parent
        for sibling in connection.execute(
            "SELECT people.* FROM people JOIN children ON children.person_id=people.id WHERE children.family_id=? AND people.id<>? ORDER BY name",
            (family["id"], person_id),
        ):
            siblings[sibling["id"]] = sibling
    partners = {}
    children = {}
    family_media = []
    for family in own_families:
        partner_id = family["wife_id"] if family["husband_id"] == person_id else family["husband_id"]
        partner = connection.execute("SELECT * FROM people WHERE id=?", (partner_id,)).fetchone()
        if partner:
            partners[partner["id"]] = partner
        for child in connection.execute(
            "SELECT people.* FROM people JOIN children ON children.person_id=people.id WHERE children.family_id=? ORDER BY name",
            (family["id"],),
        ):
            children[child["id"]] = child
        media = media_for(connection, "family", family["id"], media_root)
        if media:
            family_media.append(f'<section><h3>Mit {person_link(partner)}</h3>{media}</section>')
    family_events = ''.join(f'<article class="family-event"><h3>Mit {person_link(connection.execute("SELECT * FROM people WHERE id=?", (family["wife_id"] if family["husband_id"] == person_id else family["husband_id"],)).fetchone())}</h3>'
                            f'{facts_html(connection, "family", family["id"], media_root)}</article>' for family in own_families)
    direct_media = media_for(connection, "person", person_id, media_root)
    direct_citations = citations_for(connection, "person", person_id)
    direct_source_links = ''.join(citation_marker(f'/source/{quote(citation["source_id"])}',
                                                 f'Quelle zur Person öffnen: {citation["title"] or citation["source_id"]}')
                                  for citation in direct_citations)
    fact_ids = [str(row["id"]) for row in connection.execute(
        "SELECT id FROM facts WHERE owner_type='person' AND owner_id=?", (person_id,)
    )]
    fact_media = ''.join(media_for(connection, "fact", fact_id, media_root) for fact_id in fact_ids)
    associations = connection.execute(
        "SELECT people.*, associations.relation FROM associations JOIN people ON people.id=associations.other_person_id "
        "WHERE associations.person_id=? ORDER BY people.name", (person_id,),
    ).fetchall()
    relatives = [person, *parents.values(), *partners.values(), *children.values(), *siblings.values()]
    images = {member["id"]: person_image(connection, member["id"], media_root) for member in relatives}

    def preview(member):
        image = images[member["id"]]
        if not image:
            return ""
        return f'<img class="person-preview" src="/media/{quote(image["id"])}" alt="" loading="lazy">'

    def relative_link(member):
        return (f'<a href="/person/{quote(member["id"])}">{preview(member)}'
                f'<span>{escape(member["name"])}</span></a>')

    def relation_rail(heading, people, side, variant=""):
        items = ''.join(f'<li>{relative_link(member)}</li>' for member in people.values())
        return (f'<nav class="relation-rail relation-rail-{side}{" " + variant if variant else ""}" aria-label="{heading}">'
                f'<h2>{heading}</h2>'
                + (f'<ul>{items}</ul>' if items else f'<p>Keine {heading.lower()} verknüpft.</p>') + '</nav>')

    partner_links = ''.join(f'<a class="partner-link" href="/person/{quote(member["id"])}">'
                            f'{preview(member)}<span>Partner: {escape(member["name"])}</span></a>' for member in partners.values())
    sibling_links = ''.join(f'<li>{relative_link(member)}</li>' for member in siblings.values())
    sibling_section = (f'<nav class="sibling-strip" aria-label="Geschwister"><h2>Geschwister</h2>'
                       f'<ul>{sibling_links}</ul></nav>') if siblings else ''
    association_links = list_items([
        f'{escape(RELATION_LABELS.get(member["relation"], member["relation"] or "Beziehung"))}: '
        f'{person_link(member)}' for member in associations
    ]) if associations else ''
    content = f'''<div class="person-layout"><aside class="family-rail">{relation_rail("Eltern", parents, "parents")}{sibling_section}</aside>
{relation_rail("Kinder", children, "children", "mobile-children")}
<div class="person-content"><p class="back">{link('← Zur Startseite', '/')}</p>
<section class="person-hero{' has-portrait' if images[person_id] else ''}"><div class="profile-summary"><div><p class="eyebrow">Personenprofil</p><div class="person-heading"><h1>{escape(person["name"])}</h1>
{f'<div class="partner-actions">{partner_links}</div>' if partner_links else ''}</div>
<p>Lebensereignisse, Quellen und Medien aus dem importierten GEDCOM.</p>{label_html}
<p>{original_record_link(connection, person_id)}</p></div>
{portrait_figure(person, images[person_id], "profile-portrait")}</div></section>
<nav class="section-nav" aria-label="Profilbereiche"><a href="#events">Ereignisse</a><a href="#family-events">Partnerschaft</a><a href="#media">Medien & Quellen</a><a href="#details">Weitere Angaben</a><a href="#relations">Beziehungen</a></nav>
<div class="columns"><section class="panel" id="events" aria-labelledby="events-title"><h2 id="events-title">Lebensereignisse</h2>{facts_html(connection, "person", person_id, media_root)}</section>
<section class="panel" id="family-events" aria-labelledby="family-events-title"><h2 id="family-events-title">Partnerschaft & Hochzeit</h2>{family_events or '<p>Keine gemeinsamen Ereignisse im GEDCOM verzeichnet.</p>'}</section></div>
<section class="panel" id="media" aria-labelledby="media-title"><h2 id="media-title">Medien & Quellen</h2>
{direct_media or '<p>Keine direkt zugeordneten Medien.</p>'}
{f'<h3>Direkte Quellenverweise</h3><div class="citation-clips">{direct_source_links}</div>' if direct_source_links else ''}
<h3>Dokumente zu Lebensereignissen</h3>{fact_media or '<p>Keine weiteren Dokumente zu Lebensereignissen.</p>'}</section>
{f'<section class="panel"><h2>Medien zu Familien</h2>{"".join(family_media)}</section>' if family_media else ''}
<section class="panel"><h2>Notizen</h2>{notes_html(connection, "person", person_id) or '<p>Keine Notizen im GEDCOM.</p>'}</section>
<section class="panel" id="details"><h2>Weitere Angaben</h2>{additional_fields}</section>
<section class="panel" id="relations" aria-labelledby="relations-title"><h2 id="relations-title">Beziehungen</h2>
<p>{link('Familienbaum ansehen →', '/tree/' + quote(person_id))}</p>
<p>{link('Verbindung zu einer anderen Person finden →', '/connections?from=' + quote(person_id))}</p>
{f'<h3>Paten und weitere Beziehungen</h3>{association_links}' if association_links else ''}</section>'''
    content += f'</div>{relation_rail("Kinder", children, "children", "desktop-children")}</div>'
    return layout(person["name"], content)


def family_graph(connection):
    graph = {}

    def connect(first, second, relation, reverse):
        if first and second and first != second:
            graph.setdefault(first, []).append((second, relation))
            graph.setdefault(second, []).append((first, reverse))

    for family in connection.execute("SELECT * FROM families"):
        parents = [family[column] for column in ("husband_id", "wife_id") if family[column]]
        children = [row[0] for row in connection.execute("SELECT person_id FROM children WHERE family_id=?", (family["id"],))]
        if len(parents) == 2:
            connect(parents[0], parents[1], "Partner von", "Partner von")
        for parent_id in parents:
            for child_id in children:
                connect(parent_id, child_id, "Elternteil von", "Kind von")
        for index, child_id in enumerate(children):
            for sibling_id in children[index + 1:]:
                connect(child_id, sibling_id, "Geschwister von", "Geschwister von")
    return graph


def connection_path(graph, origin, destination):
    queue = deque([origin])
    previous = {origin: None}
    while queue:
        current = queue.popleft()
        if current == destination:
            path = []
            while previous[current] is not None:
                prior, relation = previous[current]
                path.append((current, relation))
                current = prior
            return [(origin, "Start")] + list(reversed(path))
        for neighbor, relation in graph.get(current, []):
            if neighbor not in previous:
                previous[neighbor] = (current, relation)
                queue.append(neighbor)
    return []


def connections_page(connection, origin, destination, query):
    origin_person = connection.execute("SELECT * FROM people WHERE id=?", (origin,)).fetchone() if origin else None
    destination_person = connection.execute("SELECT * FROM people WHERE id=?", (destination,)).fetchone() if destination else None
    candidates = []
    if query:
        candidates = connection.execute("SELECT * FROM people WHERE name LIKE ? ORDER BY name LIMIT 25", (f'%{query[:100]}%',)).fetchall()
    path_html = ""
    if origin_person and destination_person:
        path = connection_path(family_graph(connection), origin, destination)
        people = {person_id: connection.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
                  for person_id, _ in path}
        path_html = '<section class="panel"><h2>Verbindungsweg</h2>' + (
            '<ol class="connection-path">' + ''.join(
                f'<li>{escape(relation)}: {person_link(people[person_id])}</li>' for person_id, relation in path
            ) + '</ol>' if path else '<p>Keine Verbindung im importierten Baum gefunden.</p>') + '</section>'
    choice_links = [person_link(person) + ' · ' + link('Weg zeigen',
                    '/connections?from=' + quote(origin) + '&to=' + quote(person['id'])) for person in candidates]
    content = f'''<h1>Personen verbinden</h1><p>Wähle eine zweite Person. Der kürzeste Weg zeigt die im GEDCOM erfassten Beziehungen.</p>
<section class="panel"><h2>Ausgangspunkt</h2><p>{person_link(origin_person) if origin_person else 'Bitte zuerst eine Personenseite öffnen.'}</p></section>
<form class="search panel" action="/connections" method="get"><label for="connection-search">Zielperson suchen</label>
<input type="hidden" name="from" value="{escape(origin, quote=True)}"><div><input id="connection-search" name="q" type="search" value="{escape(query[:100], quote=True)}"><button>Suchen</button></div></form>
{path_html}<section class="panel"><h2>Person auswählen</h2>{list_items(choice_links)}</section>'''
    return layout("Personen verbinden", content)


def tree_branches(connection, person_id, person_name, depth, ancestors):
    displayed = 0
    truncated = False
    generations = {}

    def branch(current_id, current_name, generation, path):
        nonlocal displayed, truncated
        if generation >= depth:
            return ""
        if ancestors:
            relatives = connection.execute(
                "SELECT DISTINCT people.* FROM people JOIN families ON "
                "people.id=families.husband_id OR people.id=families.wife_id "
                "JOIN children ON children.family_id=families.id "
                "WHERE children.person_id=? ORDER BY people.name", (current_id,),
            ).fetchall()
        else:
            relatives = connection.execute(
                "SELECT DISTINCT people.* FROM people JOIN children ON children.person_id=people.id "
                "JOIN families ON families.id=children.family_id "
                "WHERE families.husband_id=? OR families.wife_id=? ORDER BY people.name",
                (current_id, current_id),
            ).fetchall()
        entries = []
        for relative in relatives:
            if displayed >= 250:
                truncated = True
                break
            displayed += 1
            relative_id = relative["id"]
            generations.setdefault(generation + 1, []).append((relative, current_name))
            continuation = branch(relative_id, relative["name"], generation + 1,
                                  path | {relative_id}) if relative_id not in path else ""
            entries.append(f'<li><span class="generation">Generation {generation + 1}:</span> '
                           f'{person_link(relative)}{continuation}</li>')
        relation = "Eltern" if ancestors else "Kinder"
        return (f'<ul class="relation-list" aria-label="{relation} von {escape(current_name, quote=True)}">'
                + ''.join(entries) + '</ul>') if entries else ""

    return branch(person_id, person_name, 1, {person_id}), truncated, generations


def generation_bands(generations, ancestors):
    labels = {2: "Eltern" if ancestors else "Kinder", 3: "Großeltern" if ancestors else "Enkel"}
    bands = []
    for number in sorted(generations, reverse=ancestors):
        entries = generations[number]
        cards = []
        for person, related_name in entries:
            initials = "".join(part[0] for part in person["name"].split()[:2]).upper()
            relationship = "Elternteil von" if ancestors else "Kind von"
            cards.append(f'<li><a class="generation-card" href="/person/{quote(person["id"])}">'
                         f'<span class="person-initials" aria-hidden="true">{escape(initials)}</span>'
                         f'<span class="card-copy"><strong>{escape(person["name"])}</strong>'
                         f'<span>{relationship} {escape(related_name)}</span></span></a></li>')
        title = labels.get(number, "Vorfahren" if ancestors else "Nachkommen")
        columns = min(len(cards), 4)
        bands.append(f'<section class="generation-band band-count-{columns}" aria-label="{title}, Generation {number}">'
                     f'<h3>{title} <span>Generation {number}</span></h3>'
                     f'<ul class="generation-grid band-count-{columns}">'
                     + ''.join(cards) + '</ul></section>')
    return ''.join(bands)


def tree_page(connection, person_id, depth=3):
    person = connection.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not person:
        return None
    depth = min(max(depth, 2), 5)
    partners = connection.execute(
        "SELECT DISTINCT people.* FROM people JOIN families ON "
        "(people.id=families.husband_id AND families.wife_id=?) OR "
        "(people.id=families.wife_id AND families.husband_id=?) ORDER BY people.name", (person_id, person_id)
    ).fetchall()
    ancestors, ancestors_truncated, ancestor_generations = tree_branches(connection, person_id, person["name"], depth, True)
    descendants, descendants_truncated, descendant_generations = tree_branches(connection, person_id, person["name"], depth, False)
    truncation = ('<p class="muted">Diese Ansicht zeigt höchstens 250 Personen je Richtung. '
                  'Öffne eine Person weiter außen als neuen Ausgangspunkt.</p>') if ancestors_truncated or descendants_truncated else ''
    initials = "".join(part[0] for part in person["name"].split()[:2]).upper()
    content = f'''<div class="tree-page"><p class="back">{link('← Zur Person', '/person/' + quote(person_id))}</p>
<header class="tree-toolbar"><div><p class="eyebrow">Familienlinien</p><h1>Familienbaum</h1>
<p>Vorfahren und Nachkommen der Ausgangsperson.</p></div>
<form class="tree-controls" action="/tree/{quote(person_id)}" method="get"><label for="depth">Generationen</label>
<select id="depth" name="depth">{''.join(f'<option value="{number}"{" selected" if number == depth else ""}>{number}</option>' for number in range(2, 6))}</select>
<button type="submit">Anzeigen</button></form></header>
{truncation}<div class="generation-map"><section class="generation-group" aria-labelledby="ancestors-title">
<h2 id="ancestors-title">Vorfahren</h2>{generation_bands(ancestor_generations, True) or '<p>Keine Vorfahren verknüpft.</p>'}</section>
<section class="focus-person" aria-labelledby="focus-title"><span class="person-initials" aria-hidden="true">{escape(initials)}</span>
<div><p class="eyebrow">Ausgangsperson</p><h2 id="focus-title">{person_link(person)}</h2>
{('<p>Partner: ' + ', '.join(person_link(member) for member in partners) + '</p>') if partners else ''}</div></section>
<section class="generation-group" aria-labelledby="descendants-title"><h2 id="descendants-title">Nachkommen</h2>
{generation_bands(descendant_generations, False) or '<p>Keine Nachkommen verknüpft.</p>'}</section></div>
<details class="relation-details"><summary>Familienlinien als verschachtelte Liste</summary>
<h2>Vorfahren</h2>{ancestors or '<p>Keine Vorfahren verknüpft.</p>'}
<h2>Nachkommen</h2>{descendants or '<p>Keine Nachkommen verknüpft.</p>'}</details></div>'''
    return layout("Familienbaum", content)


def sources_page(connection, query):
    term = query.strip()[:100]
    sources = connection.execute(
        "SELECT * FROM sources WHERE title LIKE ? COLLATE NOCASE ORDER BY title LIMIT 100", (f"%{term}%",)
    ).fetchall()
    count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    linked = connection.execute("SELECT COUNT(DISTINCT source_id) FROM source_archive_links").fetchone()[0]
    cited = connection.execute("SELECT COUNT(DISTINCT source_id) FROM citations").fetchone()[0]
    content = f'''<h1>GEDCOM-Quellen</h1><p>{count} Quelleneinträge aus dem Export. {linked} mit Archivdatei verknüpft; {cited} bei Lebensereignissen zitiert.
Dateizuordnung und historische Beweiskraft sind verschieden.</p>
<form class="search panel" action="/sources" method="get"><label for="source-search">Quelle suchen</label>
<div><input id="source-search" name="q" type="search" value="{escape(term, quote=True)}"><button>Suchen</button></div></form>
<section class="panel"><h2>Quellenliste</h2>{list_items([link(source['title'], f'/source/{quote(source["id"])}') for source in sources])}</section>'''
    return layout("GEDCOM-Quellen", content)


def event_owner(connection, fact):
    if fact["owner_type"] == "person":
        person = connection.execute("SELECT * FROM people WHERE id=?", (fact["owner_id"],)).fetchone()
        return person_link(person)
    family = connection.execute("SELECT * FROM families WHERE id=?", (fact["owner_id"],)).fetchone()
    if not family:
        return "Unbekannte Familie"
    members = [connection.execute("SELECT * FROM people WHERE id=?", (family[column],)).fetchone()
               for column in ("husband_id", "wife_id") if family[column]]
    return " und ".join(person_link(member) for member in members) or "Unbekannte Familie"


def event_page(connection, fact_id, media_root=None):
    fact = connection.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
    if not fact:
        return None
    place_label = ", ".join(place_parts(fact["place"] or ""))[:500]
    has_coordinates = fact["latitude"] is not None and fact["longitude"] is not None
    map_query = (f'{fact["latitude"]:.6f},{fact["longitude"]:.6f}' if has_coordinates else place_label)
    fields = [("Datum", fact["date_text"]), ("Ort", format_place(fact["place"] or "")),
              ("Genauer Ort", fact["address"]), ("Angabe", fact["value"])]
    place_record = connection.execute("SELECT record_id FROM places WHERE name=? ORDER BY record_id LIMIT 1",
                                      (fact["place"],)).fetchone() if fact["place"] else None
    details = "".join(f'<dt>{label}</dt><dd>{escape(value)}'
                      + (f' · {link("Ortsdatensatz", "/place/" + str(place_record["record_id"]))}'
                         if label == "Ort" and place_record else '')
                      + ('<br><a href="#map">Karte zum Ort ansehen ↓</a>' if label == "Ort" and map_query else '')
                      + '</dd>' for label, value in fields if value)
    citations = citations_for(connection, "fact", str(fact_id))
    media = media_for(connection, "fact", str(fact_id), media_root)
    map_section = (f'<section class="panel event-map" id="map" aria-labelledby="map-title"><h2 id="map-title">Karte zum Ort</h2>'
                   f'<p class="map-place">{escape(format_place(fact["place"]))}</p>'
                   + ('<p>Koordinaten aus dem GEDCOM; ihre Genauigkeit ist nicht geprüft.</p>' if has_coordinates else '<p>Keine Koordinaten im GEDCOM; die Karte sucht nach dem Ortsnamen.</p>')
                   + '<p>Die Karte wird erst auf Wunsch geladen. Dabei werden die Ortsdaten an Google Maps übermittelt.</p>'
                   f'<button type="button" class="load-map" data-map-query="{escape(map_query, quote=True)}" data-map-label="{escape(place_label, quote=True)}">Karte laden</button>'
                   f'<div class="map-container"></div>'
                   f'</section><script src="/static/map.js" defer></script>') if map_query else ""
    content = f'''<div class="event-detail"><p class="back">{link('← Zu den Ereignissen', '/events')}</p>
<section class="person-hero"><p class="eyebrow">Ereignis</p><h1 class="title-icon">{event_icon(fact['kind'])}{escape(fact['kind'])}</h1>
<p>Betroffene Person oder Familie: {event_owner(connection, fact)} · {original_record_link(connection, fact["owner_id"])}</p></section>
<section class="panel"><h2>Angaben</h2><dl>{details or '<dt>Weitere Angaben</dt><dd>Keine im GEDCOM.</dd>'}</dl></section>{map_section}
<section class="panel"><h2>Notizen</h2>{notes_html(connection, "fact", str(fact_id)) or '<p>Keine Notizen im GEDCOM.</p>'}</section>
<section class="panel" id="sources"><h2>Quellen und Medien</h2><h3>GEDCOM-Quellenverweise</h3>{citations_html(connection, citations, media_root)}
<h3>Angehängte Medien</h3>{media or '<p>Keine Medien angehängt. Das ist unabhängig von formalen Quellenverweisen.</p>'}</section></div>'''
    return layout(fact["kind"], content)


def events_page(connection, query, page):
    term = query.strip()[:100]
    page = min(max(page, 1), 10000)
    pattern = f"%{term}%"
    filter_sql = "WHERE kind LIKE ? OR date_text LIKE ? OR place LIKE ? OR value LIKE ?"
    values = (pattern,) * 4
    count = connection.execute(f"SELECT COUNT(*) FROM facts {filter_sql}", values).fetchone()[0]
    facts = connection.execute(
        f"SELECT facts.*, (SELECT COUNT(*) FROM citations WHERE fact_id=facts.id) AS citation_count "
        f"FROM facts {filter_sql} ORDER BY id DESC LIMIT 50 OFFSET ?", (*values, (page - 1) * 50)
    ).fetchall()
    entries = [f'{event_icon(fact["kind"])}{link(fact["kind"], "/event/" + str(fact["id"]))} · '
               f'{escape(fact["date_text"] or "ohne Datum")} · {event_owner(connection, fact)} '
               + (citation_marker(f'/event/{fact["id"]}#sources', f'{fact["citation_count"]} Quelle(n) zu {fact["kind"]} anzeigen')
                  if fact["citation_count"] else '') for fact in facts]
    previous = link("← Vorherige", f'/events?q={quote(term)}&page={page - 1}') if page > 1 else ""
    following = link("Nächste →", f'/events?q={quote(term)}&page={page + 1}') if page * 50 < count else ""
    content = f'''<h1>Ereignisse</h1><p>{count} Einträge gefunden.</p>
<form class="search panel" action="/events" method="get"><label for="event-search">Ereignisse suchen</label>
<div><input id="event-search" name="q" type="search" value="{escape(term, quote=True)}"><button>Suchen</button></div></form>
<section class="panel"><h2>Ergebnisse</h2>{list_items(entries)}<nav class="pagination" aria-label="Ergebnisseiten">{previous} {following}</nav></section>'''
    return layout("Ereignisse", content)


def source_page(connection, source_id, media_root=None):
    source = connection.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not source:
        return None
    original = connection.execute("SELECT id FROM export_records WHERE tag='SOUR' AND xref=?", (source_id,)).fetchone()
    extra_fields = export_tree(connection, original["id"], {"TITL", "AUTH", "PUBL", "TEXT", "NOTE", "OBJE", "REPO"}) if original else ""
    cited_facts = connection.execute(
        "SELECT facts.* FROM facts JOIN citations ON citations.fact_id=facts.id "
        "WHERE citations.source_id=? ORDER BY facts.id", (source_id,)
    ).fetchall()
    directly_linked = connection.execute(
        "SELECT people.* FROM people JOIN record_citations ON record_citations.owner_id=people.id "
        "WHERE record_citations.owner_type='person' AND record_citations.source_id=? ORDER BY people.name",
        (source_id,),
    ).fetchall()
    archive_links = connection.execute(
        "SELECT source_archive_links.*, archive_files.relative_path, archive_files.size_bytes "
        "FROM source_archive_links JOIN archive_files ON archive_files.id=source_archive_links.archive_file_id "
        "WHERE source_archive_links.source_id=? ORDER BY archive_files.relative_path, source_archive_links.page",
        (source_id,),
    ).fetchall()
    archive_entries = []
    for item in archive_links:
        page = item["page"]
        document_route = f'/document/{item["archive_file_id"]}' + (f'#page={page}' if page else "")
        status = "Dateizuordnung geprüft" if item["status"] == "verified" else "Dateizuordnung vorgeschlagen, noch nicht geprüft"
        details = f'<p>{escape(status)}' + (f' · Seite {page}' if page else "") + '</p>'
        if item["note"]:
            details += f'<p>{escape(item["note"])}</p>'
        if item["transcription"]:
            details += f'<details><summary>Lesbarer Text</summary><p class="transcription">{escape(item["transcription"])}</p></details>'
        archive_entries.append(f'{link(item["relative_path"], document_route)} · '
                               f'{link("Dateidetails", "/archive-file/" + str(item["archive_file_id"]))}{details}')
    fields = [("Urheber", source["author"]), ("Veröffentlichung", source["publication"]), ("Notiz", source["notes"])]
    metadata = "".join(f'<dt>{label}</dt><dd>{escape(value)}</dd>' for label, value in fields if value)
    repositories = connection.execute(
        "SELECT repositories.*, source_repositories.call_number FROM source_repositories "
        "LEFT JOIN repositories ON repositories.id=source_repositories.repository_id "
        "WHERE source_repositories.source_id=? ORDER BY repositories.name", (source_id,),
    ).fetchall()
    repository_items = [escape(item["name"] or "Unbekanntes Archiv")
                        + (" · Signatur: " + escape(item["call_number"]) if item["call_number"] else "")
                        + (" · " + escape(item["address"]) if item["address"] else "") for item in repositories]
    content = f'''<p class="back">{link('← Zu den Quellen', '/sources')}</p><h1 class="title-icon">{icon("document")}{escape(source['title'])}</h1>
<p class="muted">GEDCOM-ID: {escape(source_id)} · Archivzuordnungen und ihr Prüfstatus stehen unten. {original_record_link(connection, source_id)}</p>
<section class="panel"><h2>Quellenangaben</h2><dl>{metadata or '<dt>Metadaten</dt><dd>Keine weiteren Angaben im GEDCOM.</dd>'}</dl></section>
<section class="panel"><h2>Archiv oder Repositorium</h2>{list_items(repository_items)}</section>
<section class="panel"><h2>Quellennotizen</h2>{notes_html(connection, "source", source_id) or '<p>Keine Notizen im GEDCOM.</p>'}</section>
{f'<section class="panel"><h2>Weitere Angaben aus dem Export</h2>{extra_fields}</section>' if extra_fields else ''}
<section class="panel"><h2>Verknüpfte Medien</h2>{media_for(connection, "source", source_id, media_root) or '<p>Keine Medien verknüpft.</p>'}</section>
<section class="panel"><h2>Archivdokumente</h2>{list_items(archive_entries) if archive_entries else '<p>Noch keine Zuordnung zum Quellenarchiv geprüft oder eingetragen.</p>'}</section>
<section class="panel"><h2>Belegte Ereignisse</h2>{list_items([link(fact['kind'], '/event/' + str(fact['id'])) + ' · ' + event_owner(connection, fact) for fact in cited_facts])}</section>
<section class="panel"><h2>Direkt verknüpfte Personen</h2>{list_items([person_link(person) for person in directly_linked])}</section>'''
    return layout(source["title"], content)


def archive_page(connection, query, page):
    term = query.strip()[:100]
    current_page = min(max(page, 1), 10000)
    count = connection.execute("SELECT COUNT(*) FROM archive_files WHERE relative_path LIKE ?", (f"%{term}%",)).fetchone()[0]
    files = connection.execute(
        "SELECT * FROM archive_files WHERE relative_path LIKE ? ORDER BY relative_path LIMIT 50 OFFSET ?",
        (f"%{term}%", (current_page - 1) * 50),
    ).fetchall()
    items = [link(file["relative_path"], f'/document/{file["id"]}') + ' · ' +
             link('Details', f'/archive-file/{file["id"]}') for file in files]
    previous = link("← Vorherige", f'/archive?q={quote(term)}&page={current_page - 1}') if current_page > 1 else ""
    following = link("Nächste →", f'/archive?q={quote(term)}&page={current_page + 1}') if current_page * 50 < count else ""
    content = f'''<h1>Quellenarchiv</h1><p>{count} Dokumente gefunden. Originale bleiben unverändert auf dem privaten Speicher.
Die App bewertet historische Aussagen nicht automatisch.</p>
<form class="search panel" action="/archive" method="get"><label for="archive-search">Dateinamen suchen</label>
<div><input id="archive-search" name="q" type="search" value="{escape(term, quote=True)}"><button>Suchen</button></div></form>
<section class="panel"><h2>Dokumente</h2><p class="muted">Seite {current_page}</p>{list_items(items)}
<nav class="pagination" aria-label="Ergebnisseiten">{previous} {following}</nav></section>'''
    return layout("Quellenarchiv", content)


def archive_file_page(connection, file_id):
    file = connection.execute("SELECT * FROM archive_files WHERE id=?", (file_id,)).fetchone()
    if not file:
        return None
    metadata = json.loads(file["metadata_json"]) if file["metadata_json"] else {}
    fields = [("Archivpfad", file["relative_path"]), ("Dateigröße", f'{file["size_bytes"]:,} Bytes'),
              ("Dateityp", file["mime_type"])] + [(key, str(value)) for key, value in metadata.items()]
    details = "".join(f'<dt>{escape(label)}</dt><dd>{escape(value)}</dd>' for label, value in fields)
    sources = connection.execute(
        "SELECT sources.id, sources.title, source_archive_links.page, source_archive_links.status "
        "FROM source_archive_links JOIN sources ON sources.id=source_archive_links.source_id "
        "WHERE source_archive_links.archive_file_id=? ORDER BY sources.title", (file_id,)
    ).fetchall()
    source_items = [link(source["title"], "/source/" + quote(source["id"]))
                    + (f' · Seite {source["page"]}' if source["page"] else "")
                    + (' · Dateizuordnung geprüft' if source["status"] == "verified" else ' · Zuordnung offen')
                    for source in sources]
    content = f'''<p class="back">{link('← Zum Archiv', '/archive')}</p><h1>Archivdatei</h1>
<section class="panel"><h2>Original</h2><p>{link('Datei öffnen', '/document/' + str(file_id))}</p><dl>{details}</dl></section>
<section class="panel"><h2>Verknüpfte Quellen</h2>{list_items(source_items)}</section>'''
    return layout("Archivdatei", content)


class Handler(BaseHTTPRequestHandler):
    database_path = None
    archive_root = None
    media_root = None
    featured_person_id = None
    password_hash = None
    failed_logins = {}
    failed_logins_lock = Lock()

    def authorized(self):
        if not self.password_hash:
            return True
        address = self.client_address[0]
        now = time.monotonic()
        with self.failed_logins_lock:
            failures = [value for value in self.failed_logins.get(address, []) if now - value < 300]
            self.failed_logins[address] = failures
            blocked = len(failures) >= 10
        header = self.headers.get("Authorization", "")
        valid = False
        if not blocked and header.startswith("Basic ") and len(header) < 1024:
            try:
                decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
                username, password = decoded.split(":", 1)
                valid = username == "stammbaum" and verify_password(password, self.password_hash)
            except (binascii.Error, UnicodeDecodeError, ValueError):
                pass
        if valid:
            with self.failed_logins_lock:
                self.failed_logins.pop(address, None)
            return True
        with self.failed_logins_lock:
            self.failed_logins.setdefault(address, []).append(now)
        self.send_response(429 if blocked else 401)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("WWW-Authenticate", 'Basic realm="Stammbaum", charset="UTF-8"')
        self.end_headers()
        self.wfile.write("Anmeldung erforderlich.\n".encode("utf-8"))
        return False

    def send_page(self, body, status=200, content_type="text/html; charset=utf-8"):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; frame-src https://maps.google.com https://www.google.com; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
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
        if not self.authorized():
            return
        parsed = urlsplit(self.path)
        route = parsed.path
        parameters = parse_qs(parsed.query)
        if route == "/static/style.css":
            return self.send_page(STYLE, content_type="text/css; charset=utf-8")
        if route == "/static/map.js":
            return self.send_page(MAP_SCRIPT, content_type="application/javascript; charset=utf-8")
        try:
            with closing(database(self.database_path)) as connection:
                if route == "/":
                    body = overview(connection, parameters.get("q", [""])[0], self.featured_person_id, self.media_root,
                                    parameters.get("place", [""])[0], parameters.get("year", [""])[0],
                                    parameters.get("evidence", [""])[0])
                elif route == "/sources":
                    body = sources_page(connection, parameters.get("q", [""])[0])
                elif route in ("/export", "/places"):
                    try:
                        page = int(parameters.get("page", ["1"])[0])
                    except ValueError:
                        page = 1
                    if route == "/export":
                        body = export_page(connection, parameters.get("q", [""])[0], parameters.get("tag", [""])[0], page)
                    else:
                        body = places_page(connection, parameters.get("q", [""])[0], page)
                elif route == "/events":
                    try:
                        page = int(parameters.get("page", ["1"])[0])
                    except ValueError:
                        page = 1
                    body = events_page(connection, parameters.get("q", [""])[0], page)
                elif route == "/connections":
                    body = connections_page(connection, parameters.get("from", [""])[0],
                                            parameters.get("to", [""])[0], parameters.get("q", [""])[0])
                elif route == "/archive":
                    try:
                        page = int(parameters.get("page", ["1"])[0])
                    except ValueError:
                        page = 1
                    body = archive_page(connection, parameters.get("q", [""])[0], page)
                elif re.fullmatch(r"/person/[A-Za-z0-9_-]+", route):
                    body = person_page(connection, route.rsplit("/", 1)[1], self.media_root)
                elif re.fullmatch(r"/export-record/[0-9]+", route):
                    body = export_record_page(connection, int(route.rsplit("/", 1)[1]))
                elif re.fullmatch(r"/place/[0-9]+", route):
                    body = place_page(connection, int(route.rsplit("/", 1)[1]))
                elif re.fullmatch(r"/tree/[A-Za-z0-9_-]+", route):
                    try:
                        depth = int(parameters.get("depth", ["3"])[0])
                    except ValueError:
                        depth = 3
                    body = tree_page(connection, route.rsplit("/", 1)[1], depth)
                elif re.fullmatch(r"/source/[A-Za-z0-9_-]+", route):
                    body = source_page(connection, route.rsplit("/", 1)[1], self.media_root)
                elif re.fullmatch(r"/event/[0-9]+", route):
                    body = event_page(connection, int(route.rsplit("/", 1)[1]), self.media_root)
                elif re.fullmatch(r"/archive-file/[0-9]+", route):
                    body = archive_file_page(connection, int(route.rsplit("/", 1)[1]))
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
    parser.add_argument("--password-hash-file", help="Enable HTTP Basic authentication using a private password hash file")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args()
    Handler.database_path = Path(arguments.database).expanduser()
    Handler.archive_root = arguments.archive_root
    Handler.media_root = arguments.media_root
    Handler.featured_person_id = arguments.featured_person_id
    if arguments.password_hash_file:
        Handler.password_hash = Path(arguments.password_hash_file).read_text(encoding="utf-8").strip()
        if not Handler.password_hash.startswith("pbkdf2_sha256:600000:"):
            parser.error("Password hash file is invalid")
    server = ThreadingHTTPServer((arguments.host, arguments.port), Handler)
    print(f"Listening on http://{arguments.host}:{arguments.port}", flush=True)
    server.serve_forever()
