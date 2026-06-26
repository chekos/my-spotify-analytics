from __future__ import annotations

import argparse
import html
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


Json = dict[str, Any]


def load_jsonl(path: Path) -> list[Json]:
    rows = []
    with path.open() as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def parse_year(value: str) -> str:
    return value[:4]


def parse_date(value: str) -> str:
    return value[:10]


def source_label(sources: list[str]) -> str:
    if "my-esporifai_spotify_account_export" in sources and any(
        source.endswith("api_recently_played") for source in sources
    ):
        return "export+api"
    if "my-esporifai_spotify_account_export" in sources:
        return "export"
    return "api"


def artist_display(track: Json, artists_by_id: dict[str, Json]) -> str:
    artist_ids = track.get("artist_ids") or []
    if isinstance(artist_ids, str):
        artist_ids = [artist_ids]
    names = [
        artists_by_id.get(artist_id, {}).get("name")
        for artist_id in artist_ids[:3]
        if artist_id
    ]
    names = [name for name in names if name]
    return " & ".join(names) if names else "Unknown"


def build_database(data_dir: Path, db_path: Path) -> dict[str, Any]:
    events = load_jsonl(data_dir / "listening_events.jsonl")
    tracks = load_jsonl(data_dir / "track_catalog.jsonl")
    albums = load_jsonl(data_dir / "album_catalog.jsonl")
    artists = load_jsonl(data_dir / "artist_catalog.jsonl")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(db_path)
    con.execute("pragma journal_mode=off")
    con.execute("pragma synchronous=off")
    con.executescript(
        """
        create table listening_events (
          played_at text not null,
          played_date text not null,
          played_year text not null,
          track_id text not null,
          source_label text not null,
          sources_json text not null,
          primary key (played_at, track_id)
        );

        create table tracks (
          id text primary key,
          name text,
          album_id text,
          primary_artist_id text,
          artist_ids_json text not null,
          metadata_status text not null,
          duration_ms integer,
          explicit integer,
          popularity integer,
          raw_json text not null
        );

        create table albums (
          id text primary key,
          name text,
          release_date text,
          raw_json text not null
        );

        create table artists (
          id text primary key,
          name text,
          raw_json text not null
        );
        """
    )

    con.executemany(
        """
        insert into listening_events
        (played_at, played_date, played_year, track_id, source_label, sources_json)
        values (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                event["played_at"],
                parse_date(event["played_at"]),
                parse_year(event["played_at"]),
                event["track_id"],
                source_label(event.get("sources", [])),
                json.dumps(event.get("sources", []), sort_keys=True),
            )
            for event in events
        ],
    )

    con.executemany(
        """
        insert into tracks
        (id, name, album_id, primary_artist_id, artist_ids_json, metadata_status,
         duration_ms, explicit, popularity, raw_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                track["id"],
                track.get("name"),
                track.get("album_id"),
                (track.get("artist_ids") or [None])[0]
                if isinstance(track.get("artist_ids"), list)
                else track.get("artist_ids"),
                json.dumps(track.get("artist_ids") or [], sort_keys=True),
                track.get("metadata_status", "missing"),
                track.get("duration_ms"),
                int(track["explicit"]) if isinstance(track.get("explicit"), bool) else None,
                track.get("popularity"),
                json.dumps(track, ensure_ascii=False, sort_keys=True),
            )
            for track in tracks
        ],
    )

    con.executemany(
        "insert into albums (id, name, release_date, raw_json) values (?, ?, ?, ?)",
        [
            (
                album["id"],
                album.get("name"),
                album.get("release_date"),
                json.dumps(album, ensure_ascii=False, sort_keys=True),
            )
            for album in albums
        ],
    )

    con.executemany(
        "insert into artists (id, name, raw_json) values (?, ?, ?)",
        [
            (
                artist["id"],
                artist.get("name"),
                json.dumps(artist, ensure_ascii=False, sort_keys=True),
            )
            for artist in artists
        ],
    )

    con.executescript(
        """
        create index idx_events_track_id on listening_events(track_id);
        create index idx_events_year on listening_events(played_year);
        create index idx_tracks_artist on tracks(primary_artist_id);

        create view plays_by_year as
        select played_year, count(*) as plays
        from listening_events
        group by played_year
        order by played_year;

        create view top_tracks as
        select
          t.id,
          coalesce(t.name, t.id) as track_name,
          coalesce(a.name, 'Unknown') as artist_name,
          count(*) as plays
        from listening_events e
        left join tracks t on t.id = e.track_id
        left join artists a on a.id = t.primary_artist_id
        group by t.id, track_name, artist_name
        order by plays desc, track_name asc;

        create view top_artists as
        select
          a.id,
          coalesce(a.name, 'Unknown') as artist_name,
          count(*) as plays
        from listening_events e
        left join tracks t on t.id = e.track_id
        left join artists a on a.id = t.primary_artist_id
        group by a.id, artist_name
        order by plays desc, artist_name asc;
        """
    )
    con.commit()

    audit_path = data_dir / "audit" / "canonical_data_audit.json"
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else {}
    return {
        "db_path": db_path,
        "events": len(events),
        "tracks": len(tracks),
        "albums": len(albums),
        "artists": len(artists),
        "missing_tracks": sum(1 for track in tracks if track.get("metadata_status") == "missing"),
        "earliest": events[0]["played_at"] if events else None,
        "latest": events[-1]["played_at"] if events else None,
        "audit": audit,
    }


def query_rows(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    return list(con.execute(sql, params))


def metric_card(label: str, value: str, detail: str) -> str:
    return f"""
    <section class="metric">
      <div class="metric-label">{html.escape(label)}</div>
      <div class="metric-value">{html.escape(value)}</div>
      <div class="metric-detail">{html.escape(detail)}</div>
    </section>
    """


def display_source_label(value: str) -> str:
    labels = {
        "api": "API",
        "export": "Account Export",
        "export+api": "Export + API",
    }
    return labels.get(value, value.replace("_", " ").title())


def display_coverage_source(value: str) -> str:
    labels = {
        "my-esporifai_recent_history": "Recent history mirror",
        "my-esporifai_spotify_account_export": "Account export",
        "my-spotify-data_api_recently_played": "Canonical API history",
        "spotify-git-scraping_api_recently_played": "Original API scraper",
    }
    return labels.get(value, value.replace("_", " ").title())


def bars(rows: list[sqlite3.Row]) -> str:
    max_value = max([row["plays"] for row in rows], default=1)
    items = []
    for row in rows:
        height = max(6, round((row["plays"] / max_value) * 100))
        items.append(
            f"""
            <div class="bar-item">
              <div class="bar-value">{row['plays']:,}</div>
              <div class="bar-track"><div class="bar-fill" style="height:{height}%"></div></div>
              <div class="bar-label">{html.escape(row['played_year'])}</div>
            </div>
            """
        )
    return "\n".join(items)


def ranked_table(rows: list[sqlite3.Row], columns: list[tuple[str, str]]) -> str:
    header = "".join(f"<th>{html.escape(label)}</th>" for _key, label in columns)
    body = []
    for index, row in enumerate(rows, start=1):
        cells = [f"<td class=\"rank\">{index}</td>"]
        for key, _label in columns:
            value = row[key]
            if key == "plays":
                cells.append(f"<td class=\"numeric\">{int(value):,}</td>")
            else:
                cells.append(f"<td>{html.escape(str(value or 'Unknown'))}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th>{header}</tr></thead>
        <tbody>{''.join(body)}</tbody>
      </table>
    </div>
    """


def render_site(db_path: Path, site_dir: Path, summary: dict[str, Any]) -> Path:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    years = query_rows(con, "select played_year, plays from plays_by_year")
    top_tracks = query_rows(con, "select track_name, artist_name, plays from top_tracks limit 15")
    top_artists = query_rows(con, "select artist_name, plays from top_artists limit 15")
    source_rows = query_rows(
        con,
        """
        select source_label, count(*) as plays
        from listening_events
        group by source_label
        order by plays desc
        """,
    )

    active_days = con.execute("select count(distinct played_date) from listening_events").fetchone()[0]
    known_tracks = summary["tracks"] - summary["missing_tracks"]
    audit = summary.get("audit", {})
    event_hash = audit.get("union", {}).get("event_set_hash", "unknown")
    event_hash_display = (
        f"{event_hash[:12]}...{event_hash[-12:]}" if len(event_hash) > 28 else event_hash
    )
    source_ref = audit.get("source_ref", "unknown")

    site_dir.mkdir(parents=True, exist_ok=True)
    index_path = site_dir / "index.html"
    db_size_mb = db_path.stat().st_size / 1024 / 1024
    source_total = sum(row["plays"] for row in source_rows) or 1
    coverage_checks = audit.get("coverage_checks", [])

    source_breakdown_rows = []
    for row in source_rows:
        source_width = round((row["plays"] / source_total) * 100)
        if row["plays"]:
            source_width = max(2, source_width)
        source_breakdown_rows.append(
            f"""
        <tr>
          <td>{html.escape(display_source_label(row['source_label']))}</td>
          <td>
            <div class="source-meter" aria-hidden="true">
              <span style="width:{source_width}%"></span>
            </div>
          </td>
          <td class="numeric">{row['plays']:,}</td>
        </tr>
        """
        )
    source_breakdown = "".join(source_breakdown_rows)
    coverage_breakdown = "".join(
        f"""
        <tr>
          <td>{html.escape(display_coverage_source(check.get('source', 'unknown')))}</td>
          <td class="numeric">{check.get('source_events', 0):,}</td>
          <td class="coverage-pass">missing {check.get('missing_count', 0):,}</td>
        </tr>
        """
        for check in coverage_checks
    )

    index_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>My Spotify Analytics</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg width='64' height='64' viewBox='0 0 64 64' xmlns='http://www.w3.org/2000/svg'%3E%3Crect width='64' height='64' rx='32' fill='%23F7F5F1'/%3E%3Ccircle cx='32' cy='32' r='24' fill='none' stroke='%23E8DAC6' stroke-width='3'/%3E%3Ctext x='32' y='37' text-anchor='middle' font-family='monospace' font-size='14' fill='%23B7410E'%3ESP%3C/text%3E%3C/svg%3E">
  <style>
    @import url("https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap");

    :root {{
      --c-paper: #F7F5F1;
      --c-ember: #B7410E;
      --c-ember-dark: #9E3A0D;
      --c-joy-ember: #D65A2F;
      --c-ink: #111111;
      --c-ink-secondary: #2D2D2D;
      --c-ink-tertiary: #4A4A4A;
      --c-dust: #E8DAC6;
      --c-dust-soft: #EFE5D8;
      --c-sky: #A7D8DE;
      --c-process: #6C7B7F;
      --font-display: "Playfair Display", Georgia, "Times New Roman", serif;
      --font-body: "Inter", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
      --shadow-soft: 0 1px 2px rgba(17, 17, 17, 0.04);
      --shadow-lift: 0 8px 24px rgba(17, 17, 17, 0.10);
      --shadow-ember: 0 4px 12px rgba(183, 65, 14, 0.15);
      --ease: cubic-bezier(0.25, 0.46, 0.45, 0.94);
    }}
    * {{ box-sizing: border-box; }}
    html {{ background: var(--c-paper); }}
    body {{
      margin: 0;
      background: var(--c-paper);
      color: var(--c-ink);
      font-family: var(--font-body);
      font-size: 14px;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      z-index: -1;
      opacity: 0.55;
      pointer-events: none;
      background-image: url("data:image/svg+xml,%3Csvg width='48' height='48' viewBox='0 0 48 48' xmlns='http://www.w3.org/2000/svg'%3E%3Ccircle cx='24' cy='24' r='1' fill='%23E8DAC6'/%3E%3C/svg%3E");
      background-size: 48px 48px;
    }}
    main {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 36px 28px 28px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.8fr);
      gap: 28px;
      align-items: stretch;
      margin-bottom: 22px;
    }}
    .hero-copy {{
      min-height: 260px;
      border: 1px solid var(--c-dust);
      border-radius: 8px;
      background: rgba(247, 245, 241, 0.92);
      box-shadow: var(--shadow-soft);
      padding: 30px 32px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .brand-row {{
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 30px;
    }}
    .mark {{
      position: relative;
      width: 58px;
      height: 58px;
      border-radius: 50%;
      border: 2px solid var(--c-dust);
      background: var(--c-paper);
      display: grid;
      place-items: center;
      color: var(--c-ember);
      font-family: var(--font-mono);
      font-size: 13px;
      font-weight: 500;
      letter-spacing: 0;
      transition: transform 300ms var(--ease), border-color 300ms var(--ease);
    }}
    .mark::before,
    .mark::after {{
      content: "";
      position: absolute;
      width: 13px;
      height: 13px;
      border-radius: 50%;
      background: var(--c-paper);
    }}
    .mark::before {{ top: 5px; right: -3px; }}
    .mark::after {{ bottom: 5px; left: -4px; }}
    .mark:hover {{
      border-color: var(--c-ember);
      transform: rotate(5deg);
    }}
    .eyebrow {{
      margin: 0 0 4px;
      color: var(--c-process);
      font-family: var(--font-mono);
      font-size: 12px;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .brand-note {{
      margin: 0;
      color: var(--c-ink-tertiary);
      font-size: 13px;
    }}
    h1 {{
      margin: 0;
      font-family: var(--font-display);
      font-size: 46px;
      line-height: 1.1;
      font-weight: 600;
      letter-spacing: 0;
    }}
    .lead {{
      max-width: 62ch;
      margin: 14px 0 0;
      color: var(--c-ink-secondary);
      font-size: 17px;
      line-height: 1.65;
    }}
    .hero-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 26px;
      align-items: center;
    }}
    .btn-primary,
    .chevron-link {{
      min-height: 42px;
      display: inline-flex;
      align-items: center;
      text-decoration: none;
      font-weight: 600;
    }}
    .btn-primary {{
      min-width: 158px;
      justify-content: center;
      padding: 0 20px;
      border-radius: 999px;
      color: var(--c-paper);
      background: var(--c-ember);
      box-shadow: none;
      transition: transform 300ms var(--ease), background 300ms var(--ease), box-shadow 300ms var(--ease);
    }}
    .btn-primary:hover {{
      background: var(--c-ember-dark);
      box-shadow: var(--shadow-ember);
      transform: translateY(-1px);
    }}
    .chevron-link {{
      color: var(--c-ink);
      border-bottom: 1px solid var(--c-dust);
      padding: 0 0 2px;
      min-height: auto;
      transition: color 300ms var(--ease), border-color 300ms var(--ease);
    }}
    .chevron-link::after {{
      content: "->";
      margin-left: 8px;
      color: var(--c-ember);
      transition: transform 300ms var(--ease);
    }}
    .chevron-link:hover {{
      color: var(--c-ember);
      border-color: var(--c-ember);
    }}
    .chevron-link:hover::after {{ transform: translateX(2px); }}
    .build-panel {{
      border: 1px solid var(--c-ink);
      border-radius: 8px;
      background: var(--c-ink);
      color: var(--c-paper);
      padding: 24px;
      box-shadow: var(--shadow-lift);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 260px;
    }}
    .build-panel h2 {{
      color: var(--c-paper);
      margin-bottom: 18px;
    }}
    .status-line {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: rgba(247, 245, 241, 0.82);
      font-family: var(--font-mono);
      font-size: 12px;
    }}
    .status-light {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--c-joy-ember);
      box-shadow: 0 0 0 0 rgba(214, 90, 47, 0.46);
      animation: emberPulse 1.4s ease-in-out infinite;
    }}
    .build-list {{
      display: grid;
      gap: 12px;
      margin: 20px 0 0;
      padding: 0;
      list-style: none;
    }}
    .build-list li {{
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      gap: 16px;
      padding-top: 12px;
      border-top: 1px solid rgba(247, 245, 241, 0.16);
    }}
    .build-list span {{
      color: rgba(247, 245, 241, 0.58);
    }}
    .build-list strong {{
      font-weight: 500;
      overflow-wrap: anywhere;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 14px;
      margin-bottom: 14px;
    }}
    .metric, .panel {{
      background: rgba(247, 245, 241, 0.96);
      border: 1px solid var(--c-dust);
      border-radius: 8px;
      box-shadow: var(--shadow-soft);
      transition: border-color 300ms var(--ease), transform 300ms var(--ease), box-shadow 300ms var(--ease);
    }}
    .metric:hover,
    .panel:hover {{
      border-color: var(--c-ember);
      box-shadow: var(--shadow-lift);
      transform: translateY(-1px);
    }}
    .metric {{
      padding: 18px;
      min-height: 118px;
    }}
    .metric-label {{
      color: var(--c-ember);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0;
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-family: var(--font-display);
      font-size: 28px;
      font-weight: 600;
      letter-spacing: 0;
      line-height: 1.1;
    }}
    .metric-detail {{
      color: var(--c-ink-tertiary);
      margin-top: 6px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(320px, 1.05fr) minmax(260px, 0.9fr) minmax(360px, 1.1fr);
      gap: 14px;
      align-items: start;
    }}
    .panel {{
      padding: 18px;
      overflow: hidden;
    }}
    h2 {{
      margin: 0 0 14px;
      font-family: var(--font-display);
      font-size: 22px;
      font-weight: 600;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .panel-subtitle {{
      margin: -8px 0 14px;
      color: var(--c-ink-tertiary);
      font-size: 13px;
    }}
    .bars {{
      height: 330px;
      display: flex;
      align-items: end;
      gap: 10px;
      border-bottom: 1px solid var(--c-dust);
      padding: 28px 4px 0;
    }}
    .bar-item {{
      flex: 1;
      min-width: 28px;
      height: 100%;
      display: grid;
      grid-template-rows: 48px 1fr 26px;
      text-align: center;
      color: var(--c-ink-tertiary);
      font-size: 12px;
    }}
    .bar-track {{
      display: flex;
      align-items: end;
      min-height: 0;
    }}
    .bar-fill {{
      width: 100%;
      background: var(--c-ember);
      border-radius: 3px 3px 0 0;
      border: 1px solid rgba(17, 17, 17, 0.10);
    }}
    .bar-value {{
      color: var(--c-ember);
      font-family: var(--font-mono);
      font-size: 10px;
      font-weight: 500;
      justify-self: center;
      letter-spacing: 0;
      line-height: 1;
      writing-mode: vertical-rl;
    }}
    .bar-label {{
      padding-top: 8px;
      color: var(--c-ink);
      font-family: var(--font-mono);
    }}
    .table-wrap {{ overflow-x: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th {{
      text-align: left;
      color: var(--c-process);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0;
      text-transform: uppercase;
      border-bottom: 1px solid var(--c-dust);
      padding: 8px 8px;
    }}
    td {{
      border-bottom: 1px solid var(--c-dust-soft);
      padding: 9px 8px;
      vertical-align: top;
    }}
    tbody tr:last-child td {{ border-bottom: 0; }}
    .rank {{
      width: 34px;
      color: var(--c-ink-tertiary);
      font-family: var(--font-mono);
    }}
    .numeric {{
      text-align: right;
      font-variant-numeric: tabular-nums;
      font-family: var(--font-mono);
    }}
    .audit {{
      display: grid;
      grid-template-columns: 0.9fr 1fr 1.1fr 0.9fr;
      gap: 0;
      margin-top: 14px;
    }}
    .audit section {{
      border-right: 1px solid var(--c-dust);
      padding: 0 18px;
    }}
    .audit section:first-child {{ padding-left: 0; }}
    .audit section:last-child {{ border-right: 0; padding-right: 0; }}
    .audit dl {{
      display: grid;
      grid-template-columns: minmax(120px, 1fr) 1.3fr;
      gap: 8px 16px;
      margin: 0;
    }}
    .audit dt {{
      color: var(--c-ink-tertiary);
      font-family: var(--font-mono);
      font-size: 12px;
    }}
    .audit dd {{ margin: 0; overflow-wrap: anywhere; }}
    .source-meter {{
      width: 100%;
      height: 8px;
      border-radius: 999px;
      background: var(--c-dust);
      overflow: hidden;
      margin-top: 4px;
    }}
    .source-meter span {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: var(--c-ember);
    }}
    .coverage-pass {{
      color: var(--c-ember);
      font-family: var(--font-mono);
      font-size: 12px;
      white-space: nowrap;
    }}
    footer {{
      margin-top: 14px;
      border-radius: 8px;
      background: var(--c-ink);
      color: rgba(247, 245, 241, 0.78);
      padding: 18px 22px;
      font-size: 13px;
    }}
    footer a {{
      color: var(--c-paper);
      text-decoration: none;
      border-bottom: 1px solid rgba(247, 245, 241, 0.36);
    }}
    footer a:hover {{ border-color: var(--c-joy-ember); color: var(--c-joy-ember); }}
    @keyframes emberPulse {{
      0% {{ box-shadow: 0 0 0 0 rgba(214, 90, 47, 0.46); }}
      70% {{ box-shadow: 0 0 0 9px rgba(214, 90, 47, 0); }}
      100% {{ box-shadow: 0 0 0 0 rgba(214, 90, 47, 0); }}
    }}
    @media (max-width: 1100px) {{
      main {{ padding: 26px 18px; }}
      .hero {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .grid, .audit {{ grid-template-columns: 1fr; }}
      .audit section {{
        border-right: 0;
        border-bottom: 1px solid var(--c-dust);
        padding: 16px 0;
      }}
      .audit section:last-child {{ border-bottom: 0; }}
    }}
    @media (max-width: 720px) {{
      main {{ padding: 20px 14px; }}
      .hero-copy, .build-panel {{ padding: 20px; }}
      .brand-row {{ align-items: flex-start; margin-bottom: 22px; }}
      .metrics {{ grid-template-columns: 1fr; }}
      .grid {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 34px; }}
      .bars {{ gap: 4px; overflow-x: visible; }}
      .bar-item {{ min-width: 0; grid-template-rows: 1fr 24px; font-size: 10px; }}
      .bar-value {{ display: none; }}
      table {{ font-size: 12px; }}
      .build-list li {{ grid-template-columns: 1fr; gap: 3px; }}
      .hero-links {{ align-items: stretch; flex-direction: column; }}
      .btn-primary {{ width: 100%; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      *, *::before, *::after {{
        animation-duration: 1ms !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
        transition-duration: 200ms !important;
        transform: none !important;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="hero">
      <div class="hero-copy">
        <div>
          <div class="brand-row">
            <div class="mark" aria-label="Spotify analytics mark">SP</div>
            <div>
              <p class="eyebrow">Canonical listening data</p>
              <p class="brand-note">Git history -> SQLite -> Pages</p>
            </div>
          </div>
          <h1>My Spotify Analytics</h1>
          <p class="lead">A warmer view into the canonical Spotify archive: account export, API history, and metadata preserved as a stable public dataset.</p>
        </div>
        <div class="hero-links">
          <a class="btn-primary" href="https://github.com/chekos/my-spotify-data">Open canonical data</a>
          <a class="chevron-link" href="https://github.com/chekos/my-spotify-analytics">View analytics source</a>
        </div>
      </div>
      <aside class="build-panel" aria-label="Build metadata">
        <div>
          <div class="status-line"><span class="status-light" aria-hidden="true"></span>canonical pipeline verified</div>
          <h2>Data Provenance</h2>
        </div>
        <ul class="build-list">
          <li><span>Source ref</span><strong>{html.escape(source_ref)}</strong></li>
          <li><span>SQLite</span><strong>{db_size_mb:.1f} MB generated artifact</strong></li>
          <li><span>Event hash</span><strong>{html.escape(event_hash[:16])}</strong></li>
        </ul>
      </aside>
    </header>

    <section class="metrics">
      {metric_card("Total Plays", f"{summary['events']:,}", f"{active_days:,} active days")}
      {metric_card("Unique Tracks", f"{summary['tracks']:,}", f"{known_tracks:,} with metadata")}
      {metric_card("Unique Artists", f"{summary['artists']:,}", "catalog records")}
      {metric_card("Unique Albums", f"{summary['albums']:,}", "catalog records")}
      {metric_card("Date Range", f"{summary['earliest'][:10]} - {summary['latest'][:10]}", "UTC timestamps")}
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Plays By Year</h2>
        <p class="panel-subtitle">Long-range listening volume from the canonical event stream.</p>
        <div class="bars">{bars(years)}</div>
      </div>
      <div class="panel">
        <h2>Top Artists</h2>
        <p class="panel-subtitle">Primary artist attribution from catalog records.</p>
        {ranked_table(top_artists, [("artist_name", "Artist"), ("plays", "Plays")])}
      </div>
      <div class="panel">
        <h2>Top Tracks</h2>
        <p class="panel-subtitle">Most repeated tracks across API and account export history.</p>
        {ranked_table(top_tracks, [("track_name", "Track"), ("artist_name", "Artist"), ("plays", "Plays")])}
      </div>
    </section>

    <section class="panel audit">
      <section>
        <h2>Data Source</h2>
        <dl>
          <dt>Events</dt><dd>{summary['events']:,}</dd>
          <dt>Tracks</dt><dd>{summary['tracks']:,}</dd>
          <dt>Missing metadata</dt><dd>{summary['missing_tracks']:,}</dd>
          <dt>Event hash</dt><dd title="{html.escape(event_hash)}">{html.escape(event_hash_display)}</dd>
        </dl>
      </section>
      <section>
        <h2>Source Mix</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Source</th><th>Share</th><th>Plays</th></tr></thead>
            <tbody>{source_breakdown}</tbody>
          </table>
        </div>
      </section>
      <section>
        <h2>Coverage</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Input</th><th>Events</th><th>Status</th></tr></thead>
            <tbody>{coverage_breakdown}</tbody>
          </table>
        </div>
      </section>
      <section>
        <h2>Database</h2>
        <dl>
          <dt>Format</dt><dd>SQLite</dd>
          <dt>Tables</dt><dd>listening_events, tracks, albums, artists</dd>
          <dt>Views</dt><dd>plays_by_year, top_tracks, top_artists</dd>
          <dt>Generated output</dt><dd>not committed to main</dd>
        </dl>
      </section>
    </section>

    <footer>
      Built from <a href="https://github.com/chekos/my-spotify-data">my-spotify-data</a> with Python and SQLite. Generated artifacts stay out of main.
    </footer>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return index_path


def build(data_dir: Path, db_path: Path, site_dir: Path) -> dict[str, Any]:
    summary = build_database(data_dir, db_path)
    index_path = render_site(db_path, site_dir, summary)
    summary["index_path"] = index_path
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Spotify analytics SQLite DB and Pages site.")
    parser.add_argument("--data-dir", default=Path("../my-spotify-data/data"))
    parser.add_argument("--db-path", default=Path("build/spotify.db"))
    parser.add_argument("--site-dir", default=Path("site"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build(Path(args.data_dir), Path(args.db_path), Path(args.site_dir))
    print(
        json.dumps(
            {
                "events": summary["events"],
                "tracks": summary["tracks"],
                "artists": summary["artists"],
                "albums": summary["albums"],
                "missing_tracks": summary["missing_tracks"],
                "db_path": str(summary["db_path"]),
                "index_path": str(summary["index_path"]),
            },
            indent=2,
        )
    )
