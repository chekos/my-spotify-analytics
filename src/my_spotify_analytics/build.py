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
    <table>
      <thead><tr><th>#</th>{header}</tr></thead>
      <tbody>{''.join(body)}</tbody>
    </table>
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
    source_ref = audit.get("source_ref", "unknown")

    site_dir.mkdir(parents=True, exist_ok=True)
    index_path = site_dir / "index.html"
    db_size_mb = db_path.stat().st_size / 1024 / 1024

    source_breakdown = "".join(
        f"<tr><td>{html.escape(row['source_label'])}</td><td class=\"numeric\">{row['plays']:,}</td></tr>"
        for row in source_rows
    )

    index_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>My Spotify Analytics</title>
  <style>
    :root {{
      --bg: #ffffff;
      --panel: #ffffff;
      --text: #101820;
      --muted: #5f6b7a;
      --line: #d9dee5;
      --soft: #f5f7f9;
      --accent: #1aa34a;
      --accent-dark: #0d7f35;
      --shadow: 0 1px 2px rgba(16, 24, 32, 0.06);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.45;
    }}
    main {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 28px 24px 32px;
    }}
    header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 26px;
    }}
    .brand {{
      display: flex;
      gap: 14px;
      align-items: center;
    }}
    .mark {{
      width: 48px;
      height: 48px;
      border-radius: 50%;
      background: var(--accent);
      display: grid;
      place-items: center;
      color: #fff;
      font-weight: 800;
      letter-spacing: 0;
    }}
    h1 {{
      margin: 0;
      font-size: 32px;
      line-height: 1.1;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 14px;
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
      text-align: right;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 16px;
      margin-bottom: 18px;
    }}
    .metric, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}
    .metric {{
      padding: 18px 20px;
      min-height: 112px;
    }}
    .metric-label {{
      color: var(--accent-dark);
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 28px;
      font-weight: 760;
      letter-spacing: 0;
    }}
    .metric-detail {{
      color: var(--muted);
      margin-top: 6px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1.05fr 1fr 1.1fr;
      gap: 14px;
      align-items: start;
    }}
    .panel {{
      padding: 16px 16px 18px;
      overflow: hidden;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 18px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .bars {{
      height: 340px;
      display: flex;
      align-items: end;
      gap: 12px;
      border-bottom: 1px solid var(--line);
      padding: 30px 4px 0;
    }}
    .bar-item {{
      flex: 1;
      min-width: 28px;
      height: 100%;
      display: grid;
      grid-template-rows: 24px 1fr 26px;
      text-align: center;
      color: var(--muted);
      font-size: 12px;
    }}
    .bar-track {{
      display: flex;
      align-items: end;
      min-height: 0;
    }}
    .bar-fill {{
      width: 100%;
      background: linear-gradient(180deg, #29b85a, #13853c);
      border-radius: 3px 3px 0 0;
    }}
    .bar-value {{
      color: var(--accent-dark);
      font-weight: 700;
    }}
    .bar-label {{
      padding-top: 8px;
      color: var(--text);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th {{
      text-align: left;
      color: #334155;
      font-size: 12px;
      font-weight: 750;
      border-bottom: 1px solid var(--line);
      padding: 8px 8px;
    }}
    td {{
      border-bottom: 1px solid #edf0f3;
      padding: 9px 8px;
      vertical-align: top;
    }}
    .rank {{
      width: 34px;
      color: var(--muted);
    }}
    .numeric {{
      text-align: right;
      font-variant-numeric: tabular-nums;
    }}
    .audit {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 0;
      margin-top: 14px;
    }}
    .audit section {{
      border-right: 1px solid var(--line);
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
    .audit dt {{ color: var(--muted); }}
    .audit dd {{ margin: 0; overflow-wrap: anywhere; }}
    footer {{
      margin-top: 20px;
      color: var(--muted);
      text-align: center;
      font-size: 13px;
    }}
    a {{ color: var(--accent-dark); text-decoration: none; font-weight: 700; }}
    @media (max-width: 1100px) {{
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .grid, .audit {{ grid-template-columns: 1fr; }}
      .audit section {{
        border-right: 0;
        border-bottom: 1px solid var(--line);
        padding: 16px 0;
      }}
      .audit section:last-child {{ border-bottom: 0; }}
    }}
    @media (max-width: 720px) {{
      main {{ padding: 20px 14px; }}
      header {{ display: block; }}
      .meta {{ text-align: left; margin-top: 12px; }}
      .metrics {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 26px; }}
      .bars {{ gap: 4px; overflow-x: visible; }}
      .bar-item {{ min-width: 0; grid-template-rows: 1fr 24px; font-size: 10px; }}
      .bar-value {{ display: none; }}
      table {{ font-size: 12px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="brand">
        <div class="mark">SP</div>
        <div>
          <h1>My Spotify Analytics</h1>
          <div class="subtitle">Personal listening history insights from the canonical public Spotify data.</div>
        </div>
      </div>
      <div class="meta">
        Source ref <strong>{html.escape(source_ref)}</strong><br>
        SQLite build <strong>{db_size_mb:.1f} MB</strong>
      </div>
    </header>

    <section class="metrics">
      {metric_card("Total Plays", f"{summary['events']:,}", f"{active_days:,} active days")}
      {metric_card("Unique Tracks", f"{summary['tracks']:,}", f"{known_tracks:,} with metadata")}
      {metric_card("Unique Artists", f"{summary['artists']:,}", "catalog records")}
      {metric_card("Unique Albums", f"{summary['albums']:,}", "catalog records")}
      {metric_card("Date Range", f"{summary['earliest'][:10]} – {summary['latest'][:10]}", "UTC timestamps")}
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Plays By Year</h2>
        <div class="bars">{bars(years)}</div>
      </div>
      <div class="panel">
        <h2>Top Artists</h2>
        {ranked_table(top_artists, [("artist_name", "Artist"), ("plays", "Plays")])}
      </div>
      <div class="panel">
        <h2>Top Tracks</h2>
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
          <dt>Event hash</dt><dd>{html.escape(event_hash)}</dd>
        </dl>
      </section>
      <section>
        <h2>Source Mix</h2>
        <table><tbody>{source_breakdown}</tbody></table>
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
      Built from <a href="https://github.com/chekos/my-spotify-data">my-spotify-data</a>.
      Generated with Python and SQLite for GitHub Pages.
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
