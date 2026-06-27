from __future__ import annotations

import html
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


Json = dict[str, Any]


@dataclass(frozen=True)
class VizPage:
    slug: str
    title: str
    kicker: str
    lead: str
    issue: int

    @property
    def href(self) -> str:
        return f"{self.slug}.html"


PAGES = [
    VizPage(
        "almanac",
        "Listening Almanac",
        "Daily heatmap",
        "Every day in the archive, shaded by play count, with streaks and gaps pulled into view.",
        2,
    ),
    VizPage(
        "midnight-index",
        "Midnight Index",
        "Weekday x hour",
        "A rhythm map for when listening actually happens, with late-night share made explicit.",
        3,
    ),
    VizPage(
        "artist-eras",
        "Artist Eras",
        "Small multiples",
        "Quarter-by-quarter artist arcs that show rises, fades, returns, and current obsessions.",
        4,
    ),
    VizPage(
        "taste-river",
        "Taste River",
        "Genre signal",
        "Short, medium, and long-term top-artist genres rendered as a deliberately caveated signal.",
        5,
    ),
    VizPage(
        "comeback-tracks",
        "Comeback Tracks",
        "Long-gap songs",
        "Tracks that vanished for months or years before resurfacing in the listening record.",
        6,
    ),
    VizPage(
        "streaks",
        "Listening Streaks",
        "Runs and gaps",
        "Continuous listening runs and quiet gaps laid out as a printed timeline.",
        7,
    ),
    VizPage(
        "provenance",
        "Data Provenance",
        "Archive archaeology",
        "The migration story: export, API history, source overlap, and zero-missing coverage checks.",
        8,
    ),
    VizPage(
        "year-covers",
        "Yearly Album Covers",
        "Data artifacts",
        "A deterministic square cover for every year, generated from each year's listening fingerprint.",
        9,
    ),
    VizPage(
        "repetition-map",
        "Repetition Map",
        "Track behavior",
        "Tracks plotted by lifespan, play count, binge intensity, and late-night share.",
        10,
    ),
    VizPage(
        "atlas",
        "Guided Listening Atlas",
        "Visual essay",
        "A curated path through the archive, linking the nine exploratory pages into one story.",
        11,
    ),
]


def escape(value: Any) -> str:
    return html.escape(str(value))


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def date_range(start: date, end: date) -> list[date]:
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def query_rows(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    return list(con.execute(sql, params))


def display_source_label(value: str) -> str:
    return {
        "api": "API",
        "export": "Account Export",
        "export+api": "Export + API",
    }.get(value, value.replace("_", " ").title())


def display_coverage_source(value: str) -> str:
    return {
        "my-esporifai_recent_history": "Recent history mirror",
        "my-esporifai_spotify_account_export": "Account export",
        "my-spotify-data_api_recently_played": "Canonical API history",
        "spotify-git-scraping_api_recently_played": "Original API scraper",
    }.get(value, value.replace("_", " ").title())


def visualization_cards() -> str:
    cards = "\n".join(
        f"""
        <a class="story-card" href="{escape(page.href)}">
          <span>{escape(page.kicker)}</span>
          <strong>{escape(page.title)}</strong>
          <em>{escape(page.lead)}</em>
        </a>
        """
        for page in PAGES
    )
    return f"""
    <section class="panel story-index">
      <div>
        <h2>Listening Atlas</h2>
        <p class="panel-subtitle">Ten exploratory pages inspired by Datawrapper, The Pudding, and Nightingale-style personal data storytelling.</p>
      </div>
      <div class="story-grid">{cards}</div>
    </section>
    """


def common_css() -> str:
    return """
    @import url("https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap");
    :root {
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
      --ease: cubic-bezier(0.25, 0.46, 0.45, 0.94);
    }
    * { box-sizing: border-box; }
    html, body { background: var(--c-paper); color: var(--c-ink); }
    body {
      margin: 0;
      font-family: var(--font-body);
      font-size: 14px;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      z-index: -1;
      opacity: 0.5;
      pointer-events: none;
      background-image: url("data:image/svg+xml,%3Csvg width='48' height='48' viewBox='0 0 48 48' xmlns='http://www.w3.org/2000/svg'%3E%3Ccircle cx='24' cy='24' r='1' fill='%23E8DAC6'/%3E%3C/svg%3E");
      background-size: 48px 48px;
    }
    main { max-width: 1360px; margin: 0 auto; padding: 28px; }
    a { color: inherit; }
    .site-nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 16px;
      align-items: center;
    }
    .site-nav a {
      border: 1px solid var(--c-dust);
      border-radius: 999px;
      padding: 7px 11px;
      text-decoration: none;
      color: var(--c-ink-secondary);
      background: rgba(247, 245, 241, 0.9);
      font-size: 12px;
      transition: border-color 300ms var(--ease), color 300ms var(--ease);
    }
    .site-nav a:hover, .site-nav a.active { color: var(--c-ember); border-color: var(--c-ember); }
    .page-hero {
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.7fr);
      gap: 18px;
      margin-bottom: 14px;
    }
    .hero-copy, .hero-note, .panel {
      border: 1px solid var(--c-dust);
      border-radius: 8px;
      background: rgba(247, 245, 241, 0.96);
      box-shadow: var(--shadow-soft);
    }
    .hero-copy { padding: 28px; min-height: 210px; }
    .hero-note { padding: 22px; background: var(--c-ink); color: var(--c-paper); }
    .eyebrow {
      margin: 0 0 10px;
      color: var(--c-process);
      font-family: var(--font-mono);
      font-size: 12px;
      text-transform: uppercase;
    }
    .hero-note .eyebrow { color: rgba(247, 245, 241, 0.66); }
    h1, h2, h3 { font-family: var(--font-display); line-height: 1.1; letter-spacing: 0; }
    h1 { margin: 0; font-size: 48px; font-weight: 600; }
    h2 { margin: 0 0 12px; font-size: 25px; font-weight: 600; }
    h3 { margin: 0 0 8px; font-size: 20px; font-weight: 600; }
    .lead { margin: 14px 0 0; max-width: 68ch; color: var(--c-ink-secondary); font-size: 17px; line-height: 1.65; }
    .hero-note p, .panel-subtitle { color: var(--c-ink-tertiary); margin: -4px 0 14px; }
    .hero-note p { color: rgba(247, 245, 241, 0.76); }
    .panel { padding: 18px; overflow: hidden; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; align-items: start; }
    .grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .metric-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
    .metric {
      border: 1px solid var(--c-dust);
      border-radius: 8px;
      padding: 16px;
      background: rgba(247, 245, 241, 0.96);
    }
    .metric span { color: var(--c-ember); font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; }
    .metric strong { display: block; margin-top: 6px; font-family: var(--font-display); font-size: 29px; line-height: 1; }
    .metric em { display: block; margin-top: 7px; color: var(--c-ink-tertiary); font-style: normal; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th {
      text-align: left;
      color: var(--c-process);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 500;
      text-transform: uppercase;
      border-bottom: 1px solid var(--c-dust);
      padding: 8px;
    }
    td { border-bottom: 1px solid var(--c-dust-soft); padding: 9px 8px; vertical-align: top; }
    tbody tr:last-child td { border-bottom: 0; }
    .numeric { text-align: right; font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
    .table-wrap { overflow-x: auto; }
    .button-link {
      display: inline-flex;
      align-items: center;
      min-height: 40px;
      padding: 0 16px;
      border-radius: 999px;
      background: var(--c-ember);
      color: var(--c-paper);
      text-decoration: none;
      font-weight: 600;
    }
    .source-meter, .mini-meter {
      height: 8px;
      border-radius: 999px;
      background: var(--c-dust);
      overflow: hidden;
    }
    .source-meter span, .mini-meter span { display: block; height: 100%; background: var(--c-ember); border-radius: inherit; }
    .calendar-year { margin-bottom: 18px; }
    .calendar-grid {
      display: grid;
      grid-template-columns: repeat(53, minmax(5px, 1fr));
      gap: 3px;
    }
    .day-cell {
      aspect-ratio: 1;
      border-radius: 2px;
      border: 1px solid rgba(17,17,17,0.04);
    }
    .matrix { display: grid; grid-template-columns: 70px repeat(24, minmax(18px, 1fr)); gap: 3px; align-items: center; }
    .matrix-label, .hour-label { font-family: var(--font-mono); font-size: 10px; color: var(--c-process); }
    .matrix-cell { aspect-ratio: 1.2; border-radius: 3px; background: var(--c-dust); }
    .era-bars { display: grid; grid-template-columns: repeat(var(--quarters), minmax(4px, 1fr)); gap: 3px; align-items: end; height: 58px; border-bottom: 1px solid var(--c-dust); }
    .era-bars span { display: block; min-height: 2px; background: var(--c-ember); border-radius: 2px 2px 0 0; }
    .timeline { position: relative; height: 16px; background: var(--c-dust); border-radius: 999px; margin: 8px 0; }
    .timeline span { position: absolute; top: 2px; width: 12px; height: 12px; margin-left: -6px; border-radius: 50%; background: var(--c-ember); }
    .strip { display: grid; grid-template-columns: repeat(53, minmax(5px, 1fr)); gap: 3px; }
    .strip span { aspect-ratio: 1; border-radius: 2px; background: var(--c-dust); }
    .strip span.active { background: var(--c-ember); }
    .cover-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; }
    .year-cover {
      min-height: 260px;
      border: 1px solid var(--c-ink);
      border-radius: 8px;
      padding: 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      background: var(--c-paper);
      box-shadow: var(--shadow-soft);
    }
    .cover-bars { display: grid; grid-template-columns: repeat(12, 1fr); gap: 4px; align-items: end; height: 78px; }
    .cover-bars span { display: block; min-height: 8px; background: var(--c-ember); }
    .scatter { width: 100%; height: auto; border: 1px solid var(--c-dust); border-radius: 8px; background: rgba(247,245,241,0.72); }
    .atlas-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .atlas-card {
      border: 1px solid var(--c-dust);
      border-radius: 8px;
      padding: 16px;
      text-decoration: none;
      background: rgba(247,245,241,0.96);
    }
    .atlas-card span { color: var(--c-ember); font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; }
    .atlas-card strong { display: block; margin: 6px 0; font-family: var(--font-display); font-size: 21px; }
    footer { margin-top: 14px; border-radius: 8px; background: var(--c-ink); color: rgba(247,245,241,0.78); padding: 18px 22px; }
    footer a { color: var(--c-paper); }
    @media (max-width: 900px) {
      main { padding: 18px 14px; }
      .page-hero, .grid, .grid.two, .metric-row, .atlas-list { grid-template-columns: 1fr; }
      h1 { font-size: 36px; }
      .calendar-grid, .strip { grid-template-columns: repeat(31, minmax(5px, 1fr)); }
      .matrix { grid-template-columns: 56px repeat(12, minmax(16px, 1fr)); overflow-x: auto; }
      .hour-label:nth-of-type(n+14), .matrix-cell.extra-hour { display: none; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation-duration: 1ms !important; transition-duration: 200ms !important; transform: none !important; }
    }
    """


def page_shell(page: VizPage, content: str, note: str = "") -> str:
    nav = "\n".join(
        f'<a class="{"active" if item.slug == page.slug else ""}" href="{escape(item.href)}">{escape(item.title)}</a>'
        for item in PAGES
    )
    note_html = note or f'<p>Issue #{page.issue} tracks this visualization and the review notes for deciding what stays.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(page.title)} - My Spotify Analytics</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg width='64' height='64' viewBox='0 0 64 64' xmlns='http://www.w3.org/2000/svg'%3E%3Crect width='64' height='64' rx='32' fill='%23F7F5F1'/%3E%3Ccircle cx='32' cy='32' r='24' fill='none' stroke='%23E8DAC6' stroke-width='3'/%3E%3Ctext x='32' y='37' text-anchor='middle' font-family='monospace' font-size='14' fill='%23B7410E'%3ESP%3C/text%3E%3C/svg%3E">
  <style>{common_css()}</style>
</head>
<body>
  <main>
    <nav class="site-nav">
      <a href="index.html">Dashboard</a>
      {nav}
    </nav>
    <header class="page-hero">
      <section class="hero-copy">
        <p class="eyebrow">{escape(page.kicker)}</p>
        <h1>{escape(page.title)}</h1>
        <p class="lead">{escape(page.lead)}</p>
      </section>
      <aside class="hero-note">
        <p class="eyebrow">Prototype page</p>
        {note_html}
        <a class="button-link" href="https://github.com/chekos/my-spotify-analytics/issues/{page.issue}">Open issue #{page.issue}</a>
      </aside>
    </header>
    {content}
    <footer>
      Built from <a href="https://github.com/chekos/my-spotify-data">my-spotify-data</a>. Return to the <a href="index.html">dashboard</a>.
    </footer>
  </main>
</body>
</html>
"""


def metric(label: str, value: Any, detail: str = "") -> str:
    return f"""
    <section class="metric">
      <span>{escape(label)}</span>
      <strong>{escape(value)}</strong>
      <em>{escape(detail)}</em>
    </section>
    """


def table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        cells = []
        for value in row:
            class_name = ' class="numeric"' if isinstance(value, int | float) else ""
            if isinstance(value, int):
                value = f"{value:,}"
            cells.append(f"<td{class_name}>{escape(value)}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f"""
    <div class="table-wrap">
      <table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>
    </div>
    """


def render_visualization_pages(
    data_dir: Path,
    db_path: Path,
    site_dir: Path,
    summary: dict[str, Any],
) -> list[Path]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    events = [dict(row) for row in query_rows(con, "select * from listening_events order by played_at")]
    tracks = {
        row["id"]: dict(row)
        for row in query_rows(
            con,
            """
            select t.id, coalesce(t.name, t.id) as name, t.primary_artist_id,
                   coalesce(a.name, 'Unknown') as artist_name, t.metadata_status
            from tracks t
            left join artists a on a.id = t.primary_artist_id
            """,
        )
    }
    audit = summary.get("audit", {})

    context = {
        "data_dir": data_dir,
        "summary": summary,
        "events": events,
        "tracks": tracks,
        "audit": audit,
    }
    renderers = {
        "almanac": render_almanac,
        "midnight-index": render_midnight_index,
        "artist-eras": render_artist_eras,
        "taste-river": render_taste_river,
        "comeback-tracks": render_comeback_tracks,
        "streaks": render_streaks,
        "provenance": render_provenance,
        "year-covers": render_year_covers,
        "repetition-map": render_repetition_map,
        "atlas": render_atlas,
    }
    paths = []
    for page in PAGES:
        path = site_dir / page.href
        path.write_text(page_shell(page, renderers[page.slug](context)), encoding="utf-8")
        paths.append(path)
    return paths


def event_dates(events: list[Json]) -> list[datetime]:
    return [parse_dt(event["played_at"]) for event in events]


def render_almanac(context: Json) -> str:
    events = context["events"]
    dates = event_dates(events)
    counts = Counter(dt.date() for dt in dates)
    start, end = min(counts), max(counts)
    max_count = max(counts.values(), default=1)
    active_days = len(counts)
    years = []
    for year in range(start.year, end.year + 1):
        year_start = max(date(year, 1, 1), start)
        year_end = min(date(year, 12, 31), end)
        cells = []
        for day in date_range(year_start, year_end):
            count = counts.get(day, 0)
            alpha = 0.08 + (count / max_count) * 0.82 if count else 0.0
            background = f"rgba(183, 65, 14, {alpha:.2f})" if count else "#EFE5D8"
            cells.append(
                f'<span class="day-cell" style="background:{background}" title="{day.isoformat()}: {count:,} plays"></span>'
            )
        years.append(
            f"""
            <section class="panel calendar-year">
              <h2>{year}</h2>
              <p class="panel-subtitle">{sum(counts.get(day, 0) for day in date_range(year_start, year_end)):,} plays across {sum(1 for day in date_range(year_start, year_end) if counts.get(day, 0)):,} active days.</p>
              <div class="calendar-grid">{''.join(cells)}</div>
            </section>
            """
        )
    top_days = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10]
    return f"""
    <section class="metric-row">
      {metric("Date range", f"{start.isoformat()} - {end.isoformat()}", "canonical event dates")}
      {metric("Active days", f"{active_days:,}", "days with at least one play")}
      {metric("Max day", f"{max_count:,}", top_days[0][0].isoformat() if top_days else "none")}
      {metric("Zero-play days", f"{len(date_range(start, end)) - active_days:,}", "inside the archive range")}
    </section>
    <section class="grid two">
      <div>{"".join(years)}</div>
      <aside class="panel">
        <h2>Highest-Play Days</h2>
        {table(["Date", "Plays"], [[day.isoformat(), count] for day, count in top_days])}
      </aside>
    </section>
    """


def render_midnight_index(context: Json) -> str:
    dates = event_dates(context["events"])
    counts = Counter((dt.weekday(), dt.hour) for dt in dates)
    by_hour = Counter(dt.hour for dt in dates)
    max_count = max(counts.values(), default=1)
    night_count = sum(1 for dt in dates if dt.hour in {21, 22, 23, 0, 1, 2})
    night_share = night_count / len(dates) if dates else 0
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hour_headers = "".join(f'<span class="hour-label">{hour}</span>' for hour in range(24))
    rows = [f'<span class="matrix-label"></span>{hour_headers}']
    for weekday in range(7):
        cells = [f'<span class="matrix-label">{weekdays[weekday]}</span>']
        for hour in range(24):
            count = counts.get((weekday, hour), 0)
            alpha = 0.08 + (count / max_count) * 0.82 if count else 0
            extra = " extra-hour" if hour >= 12 else ""
            cells.append(
                f'<span class="matrix-cell{extra}" style="background:rgba(183,65,14,{alpha:.2f})" title="{weekdays[weekday]} {hour}:00 - {count:,} plays"></span>'
            )
        rows.append("".join(cells))
    top_hours = [[f"{hour:02d}:00", count] for hour, count in by_hour.most_common(10)]
    return f"""
    <section class="metric-row">
      {metric("Midnight index", f"{night_share:.1%}", "plays from 21:00 through 02:59 UTC")}
      {metric("Night plays", f"{night_count:,}", "late listening events")}
      {metric("Peak hour", f"{by_hour.most_common(1)[0][0]:02d}:00" if by_hour else "n/a", f"{by_hour.most_common(1)[0][1]:,} plays" if by_hour else "")}
      {metric("Total plays", f"{len(dates):,}", "all canonical events")}
    </section>
    <section class="grid two">
      <div class="panel">
        <h2>Weekday x Hour Heatmap</h2>
        <p class="panel-subtitle">Darker ember means more plays in that weekday-hour bucket.</p>
        <div class="matrix">{''.join(rows)}</div>
      </div>
      <aside class="panel">
        <h2>Top Hours</h2>
        {table(["Hour", "Plays"], top_hours)}
      </aside>
    </section>
    """


def render_artist_eras(context: Json) -> str:
    events = context["events"]
    tracks = context["tracks"]
    quarters = sorted({f"{parse_dt(event['played_at']).year}-Q{((parse_dt(event['played_at']).month - 1) // 3) + 1}" for event in events})
    artist_quarters: dict[str, Counter[str]] = defaultdict(Counter)
    totals = Counter()
    for event in events:
        dt = parse_dt(event["played_at"])
        quarter = f"{dt.year}-Q{((dt.month - 1) // 3) + 1}"
        track = tracks.get(event["track_id"], {})
        artist = track.get("artist_name") or "Unknown"
        artist_quarters[artist][quarter] += 1
        totals[artist] += 1
    top_artists = [artist for artist, _count in totals.most_common(18) if artist != "Unknown"][:12]
    cards = []
    for artist in top_artists:
        values = [artist_quarters[artist].get(quarter, 0) for quarter in quarters]
        max_value = max(values, default=1) or 1
        bars = "".join(f'<span style="height:{max(3, round((value / max_value) * 58))}px" title="{quarter}: {value:,}"></span>' for quarter, value in zip(quarters, values, strict=False))
        peak_index = values.index(max(values)) if values else 0
        cards.append(
            f"""
            <section class="panel">
              <h3>{escape(artist)}</h3>
              <p class="panel-subtitle">{totals[artist]:,} plays. Peak: {escape(quarters[peak_index])}.</p>
              <div class="era-bars" style="--quarters:{len(quarters)}">{bars}</div>
            </section>
            """
        )
    winners = []
    for quarter in quarters[-14:]:
        quarter_counts = Counter({artist: artist_quarters[artist][quarter] for artist in artist_quarters})
        artist, plays = quarter_counts.most_common(1)[0]
        winners.append([quarter, artist, plays])
    return f"""
    <section class="metric-row">
      {metric("Artists shown", len(top_artists), "top named artists")}
      {metric("Quarters", len(quarters), f"{quarters[0]} through {quarters[-1]}" if quarters else "")}
      {metric("Top artist", top_artists[0] if top_artists else "n/a", f"{totals[top_artists[0]]:,} plays" if top_artists else "")}
      {metric("Unknown plays", f"{totals.get('Unknown', 0):,}", "kept separate")}
    </section>
    <section class="grid">
      {''.join(cards)}
    </section>
    <section class="panel">
      <h2>Recent Quarter Winners</h2>
      {table(["Quarter", "Artist", "Plays"], winners)}
    </section>
    """


def load_top_artist_genres(data_dir: Path) -> dict[str, Counter[str]]:
    periods = {
        "short": "top_50_artists_short_term.json",
        "medium": "top_50_artists_medium_term.json",
        "long": "top_50_artists_long_term.json",
    }
    results: dict[str, Counter[str]] = {}
    for period, filename in periods.items():
        path = data_dir / filename
        counter: Counter[str] = Counter()
        if path.exists():
            data = json.loads(path.read_text())
            items = data.get("items", data) if isinstance(data, dict) else data
            for item in items if isinstance(items, list) else []:
                for genre in item.get("genres") or []:
                    counter[genre] += 1
        results[period] = counter
    return results


def render_taste_river(context: Json) -> str:
    genre_counts = load_top_artist_genres(context["data_dir"])
    period_labels = {"short": "Short term", "medium": "Medium term", "long": "Long term"}
    panels = []
    all_genres = Counter()
    for period, counts in genre_counts.items():
        all_genres.update(counts)
        max_value = max(counts.values(), default=1)
        rows = []
        for genre, count in counts.most_common(12):
            width = max(3, round((count / max_value) * 100))
            rows.append(
                f"""
                <tr>
                  <td>{escape(genre)}</td>
                  <td><div class="source-meter"><span style="width:{width}%"></span></div></td>
                  <td class="numeric">{count}</td>
                </tr>
                """
            )
        if not rows:
            rows.append('<tr><td colspan="3">No top-artist genre snapshot is available for this period.</td></tr>')
        panels.append(
            f"""
            <section class="panel">
              <h2>{period_labels[period]}</h2>
              <div class="table-wrap"><table><thead><tr><th>Genre</th><th>Signal</th><th>Artists</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
            </section>
            """
        )
    return f"""
    <section class="metric-row">
      {metric("Genre terms", len(all_genres), "from top-artist snapshots")}
      {metric("Strongest signal", all_genres.most_common(1)[0][0] if all_genres else "n/a", f"{all_genres.most_common(1)[0][1]} appearances" if all_genres else "")}
      {metric("Data scope", "Top 50", "artist snapshots only")}
      {metric("Caveat", "Partial", "not a full catalog taxonomy")}
    </section>
    <section class="grid">{''.join(panels)}</section>
    <section class="panel">
      <h2>Read This As A Signal</h2>
      <p>This page intentionally uses only the available top-artist genre snapshots. It is useful for taste direction, but it should not be treated as complete genre coverage across every catalog artist yet.</p>
    </section>
    """


def render_comeback_tracks(context: Json) -> str:
    events = context["events"]
    tracks = context["tracks"]
    by_track: dict[str, list[datetime]] = defaultdict(list)
    for event in events:
        by_track[event["track_id"]].append(parse_dt(event["played_at"]))
    min_dt = min(parse_dt(event["played_at"]) for event in events)
    max_dt = max(parse_dt(event["played_at"]) for event in events)
    total_days = max((max_dt - min_dt).days, 1)
    comeback_rows = []
    for track_id, plays in by_track.items():
        plays = sorted(plays)
        if len(plays) < 2:
            continue
        gaps = [(plays[index] - plays[index - 1]).days for index in range(1, len(plays))]
        max_gap = max(gaps)
        if max_gap < 180:
            continue
        track = tracks.get(track_id, {})
        comeback_rows.append(
            {
                "track": track.get("name") or track_id,
                "artist": track.get("artist_name") or "Unknown",
                "plays": len(plays),
                "gap": max_gap,
                "first": plays[0],
                "last": plays[-1],
                "dates": plays,
            }
        )
    comeback_rows = sorted(comeback_rows, key=lambda row: (row["gap"], row["plays"]), reverse=True)[:24]
    cards = []
    for row in comeback_rows:
        dots = []
        for played in row["dates"][:18]:
            left = ((played - min_dt).days / total_days) * 100
            dots.append(f'<span style="left:{left:.2f}%" title="{played.date().isoformat()}"></span>')
        cards.append(
            f"""
            <section class="panel">
              <h3>{escape(row['track'])}</h3>
              <p class="panel-subtitle">{escape(row['artist'])}</p>
              <div class="timeline">{''.join(dots)}</div>
              <p><strong>{row['gap']:,} days</strong> between plays. {row['plays']:,} total plays from {row['first'].date().isoformat()} to {row['last'].date().isoformat()}.</p>
            </section>
            """
        )
    return f"""
    <section class="metric-row">
      {metric("Comebacks", len(comeback_rows), "tracks with 180+ day gaps")}
      {metric("Longest gap", f"{comeback_rows[0]['gap']:,} days" if comeback_rows else "n/a", comeback_rows[0]["track"] if comeback_rows else "")}
      {metric("Archive span", f"{min_dt.date().isoformat()} - {max_dt.date().isoformat()}", "used for lifelines")}
      {metric("Dots", "First 18", "plays shown per track")}
    </section>
    <section class="grid">{''.join(cards)}</section>
    """


def streaks_and_gaps(active_days: list[date]) -> tuple[list[list[date]], list[tuple[date, date, int]]]:
    runs: list[list[date]] = []
    gaps: list[tuple[date, date, int]] = []
    current: list[date] = []
    previous: date | None = None
    for day in active_days:
        if previous is None or day == previous + timedelta(days=1):
            current.append(day)
        else:
            if current:
                runs.append(current)
            gap_length = (day - previous).days - 1
            if gap_length > 0:
                gaps.append((previous + timedelta(days=1), day - timedelta(days=1), gap_length))
            current = [day]
        previous = day
    if current:
        runs.append(current)
    return runs, gaps


def render_streaks(context: Json) -> str:
    counts = Counter(parse_dt(event["played_at"]).date() for event in context["events"])
    active_days = sorted(counts)
    runs, gaps = streaks_and_gaps(active_days)
    top_runs = sorted(runs, key=len, reverse=True)[:10]
    top_gaps = sorted(gaps, key=lambda item: item[2], reverse=True)[:10]
    years = []
    for year in range(active_days[0].year, active_days[-1].year + 1):
        year_days = date_range(date(year, 1, 1), date(year, 12, 31))
        cells = "".join(f'<span class="{"active" if day in counts else ""}" title="{day.isoformat()}: {counts.get(day, 0):,}"></span>' for day in year_days)
        years.append(f'<section class="panel"><h2>{year}</h2><div class="strip">{cells}</div></section>')
    return f"""
    <section class="metric-row">
      {metric("Longest streak", f"{len(top_runs[0]):,} days", f"{top_runs[0][0].isoformat()} - {top_runs[0][-1].isoformat()}")}
      {metric("Active days", f"{len(active_days):,}", "with one or more plays")}
      {metric("Largest gap", f"{top_gaps[0][2]:,} days" if top_gaps else "0", f"{top_gaps[0][0].isoformat()} - {top_gaps[0][1].isoformat()}" if top_gaps else "")}
      {metric("Runs", f"{len(runs):,}", "continuous active-day groups")}
    </section>
    <section class="grid two">
      <div>{''.join(years)}</div>
      <aside class="panel">
        <h2>Top Runs</h2>
        {table(["Start", "End", "Days"], [[run[0].isoformat(), run[-1].isoformat(), len(run)] for run in top_runs])}
        <h2>Largest Gaps</h2>
        {table(["Start", "End", "Days"], [[start.isoformat(), end.isoformat(), length] for start, end, length in top_gaps])}
      </aside>
    </section>
    """


def render_provenance(context: Json) -> str:
    audit = context["audit"]
    sources = audit.get("sources", [])
    coverage = audit.get("coverage_checks", [])
    source_counts = Counter(event["source_label"] for event in context["events"])
    source_rows = [[display_source_label(label), count] for label, count in source_counts.most_common()]
    source_sections = []
    for source in sources:
        source_sections.append(
            f"""
            <section class="panel">
              <h3>{escape(display_coverage_source(source.get('name', 'unknown')))}</h3>
              <p class="panel-subtitle">{escape(source.get('repo', 'unknown'))}:{escape(source.get('path', 'unknown'))}</p>
              <p>{source.get('unique_events', 0):,} events, {source.get('unique_tracks', 0):,} tracks, {escape(source.get('earliest'))} to {escape(source.get('latest'))}.</p>
            </section>
            """
        )
    return f"""
    <section class="metric-row">
      {metric("Canonical events", f"{context['summary']['events']:,}", "current generated union")}
      {metric("Source fingerprint", escape(audit.get("source_fingerprint", "unknown")[:14]), "semantic audit")}
      {metric("Coverage checks", len(coverage), "source subsets")}
      {metric("Missing events", sum(check.get("missing_count", 0) for check in coverage), "across audited sources")}
    </section>
    <section class="grid two">
      <div class="panel">
        <h2>Source Mix</h2>
        {table(["Source", "Events"], source_rows)}
      </div>
      <div class="panel">
        <h2>Coverage Checks</h2>
        {table(["Input", "Events", "Missing"], [[display_coverage_source(check.get("source", "unknown")), check.get("source_events", 0), check.get("missing_count", 0)] for check in coverage])}
      </div>
    </section>
    <section class="grid">{''.join(source_sections)}</section>
    """


def render_year_covers(context: Json) -> str:
    events = context["events"]
    tracks = context["tracks"]
    by_year: dict[int, list[Json]] = defaultdict(list)
    for event in events:
        by_year[parse_dt(event["played_at"]).year].append(event)
    max_year_count = max((len(items) for items in by_year.values()), default=1)
    cards = []
    for year, items in sorted(by_year.items()):
        months = Counter(parse_dt(event["played_at"]).month for event in items)
        night_share = sum(1 for event in items if parse_dt(event["played_at"]).hour in {21, 22, 23, 0, 1, 2}) / len(items)
        artist_counts = Counter((tracks.get(event["track_id"], {}).get("artist_name") or "Unknown") for event in items)
        top_artist, top_count = artist_counts.most_common(1)[0]
        source_counts = Counter(event["source_label"] for event in items)
        bars = "".join(f'<span style="height:{max(8, round((months.get(month, 0) / max(months.values(), default=1)) * 78))}px"></span>' for month in range(1, 13))
        cards.append(
            f"""
            <section class="year-cover">
              <div>
                <p class="eyebrow">{len(items):,} plays / {night_share:.0%} late</p>
                <h2>{year}</h2>
                <p>{escape(top_artist)} led the year with {top_count:,} plays.</p>
              </div>
              <div class="cover-bars">{bars}</div>
              <div class="source-meter" title="Share of max yearly volume"><span style="width:{round((len(items) / max_year_count) * 100)}%"></span></div>
              <p class="panel-subtitle">{", ".join(f"{display_source_label(k)} {v:,}" for k, v in source_counts.items())}</p>
            </section>
            """
        )
    return f"""
    <section class="metric-row">
      {metric("Years", len(by_year), "generated covers")}
      {metric("Highest-volume year", max(by_year, key=lambda year: len(by_year[year])) if by_year else "n/a", f"{max_year_count:,} plays")}
      {metric("Latest year", max(by_year) if by_year else "n/a", f"{len(by_year[max(by_year)]):,} plays" if by_year else "")}
      {metric("Encoding", "Deterministic", "month bars, night share, source mix")}
    </section>
    <section class="cover-grid">{''.join(cards)}</section>
    """


def render_repetition_map(context: Json) -> str:
    events = context["events"]
    tracks = context["tracks"]
    by_track: dict[str, list[datetime]] = defaultdict(list)
    for event in events:
        by_track[event["track_id"]].append(parse_dt(event["played_at"]))
    stats = []
    for track_id, plays in by_track.items():
        plays = sorted(plays)
        if len(plays) < 2:
            continue
        lifespan = max((plays[-1] - plays[0]).days, 1)
        by_day = Counter(play.date() for play in plays)
        night_share = sum(1 for play in plays if play.hour in {21, 22, 23, 0, 1, 2}) / len(plays)
        track = tracks.get(track_id, {})
        stats.append(
            {
                "track": track.get("name") or track_id,
                "artist": track.get("artist_name") or "Unknown",
                "plays": len(plays),
                "lifespan": lifespan,
                "binge": max(by_day.values()),
                "night": night_share,
            }
        )
    stats = sorted(stats, key=lambda item: item["plays"], reverse=True)
    sample = stats[:420]
    max_x = max((math.log1p(item["lifespan"]) for item in sample), default=1)
    max_y = max((math.log1p(item["plays"]) for item in sample), default=1)
    circles = []
    for item in sample:
        x = 50 + (math.log1p(item["lifespan"]) / max_x) * 790
        y = 390 - (math.log1p(item["plays"]) / max_y) * 330
        radius = 3 + min(item["binge"], 18) / 4
        alpha = 0.28 + item["night"] * 0.62
        circles.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="rgba(183,65,14,{alpha:.2f})"><title>{escape(item["track"])} - {escape(item["artist"])}: {item["plays"]:,} plays</title></circle>')
    longest_lifespan = max(stats, key=lambda item: item["lifespan"]) if stats else None
    rows = [[item["track"], item["artist"], item["plays"], item["lifespan"], item["binge"], f"{item['night']:.0%}"] for item in stats[:15]]
    svg = f"""
    <svg class="scatter" viewBox="0 0 900 430" role="img" aria-label="Track repetition scatterplot">
      <line x1="50" y1="390" x2="860" y2="390" stroke="#E8DAC6"/>
      <line x1="50" y1="40" x2="50" y2="390" stroke="#E8DAC6"/>
      <text x="50" y="420" font-size="12" fill="#6C7B7F">short lifespan</text>
      <text x="760" y="420" font-size="12" fill="#6C7B7F">long lifespan</text>
      <text x="10" y="55" font-size="12" fill="#6C7B7F">more plays</text>
      {''.join(circles)}
    </svg>
    """
    return f"""
    <section class="metric-row">
      {metric("Tracks plotted", len(sample), "top repeated tracks")}
      {metric("Most played", stats[0]["track"] if stats else "n/a", f"{stats[0]['plays']:,} plays" if stats else "")}
      {metric("Longest lifespan", f"{longest_lifespan['lifespan']:,} days" if longest_lifespan else "n/a", longest_lifespan["track"] if longest_lifespan else "")}
      {metric("Encoding", "x/y/r/alpha", "lifespan, plays, binge, night")}
    </section>
    <section class="panel">
      <h2>Behavior Scatterplot</h2>
      <p class="panel-subtitle">X encodes track lifespan, Y encodes play count, point size encodes same-day binge count, opacity encodes late-night share.</p>
      {svg}
    </section>
    <section class="panel">
      <h2>Most Repeated Tracks</h2>
      {table(["Track", "Artist", "Plays", "Lifespan Days", "Max Day", "Night Share"], rows)}
    </section>
    """


def render_atlas(context: Json) -> str:
    page_cards = "\n".join(
        f"""
        <a class="atlas-card" href="{escape(page.href)}">
          <span>{escape(page.kicker)}</span>
          <strong>{escape(page.title)}</strong>
          <p>{escape(page.lead)}</p>
        </a>
        """
        for page in PAGES
        if page.slug != "atlas"
    )
    summary = context["summary"]
    return f"""
    <section class="metric-row">
      {metric("Events", f"{summary['events']:,}", "canonical listening events")}
      {metric("Tracks", f"{summary['tracks']:,}", "catalog records")}
      {metric("Pages", len(PAGES) - 1, "deep dives plus this guide")}
      {metric("Review mode", "Keep or cut", "each page maps to a GitHub issue")}
    </section>
    <section class="grid two">
      <div class="panel">
        <h2>The Arc</h2>
        <p>Start with the archive shape, move into daily and hourly rhythm, follow artists and genres, then end with memory: streaks, comebacks, and repetition. Each page is intentionally separate so the final site can keep only what earns its space.</p>
      </div>
      <div class="panel">
        <h2>How To Review</h2>
        <p>Open each page, decide whether it tells a real story, then use the linked GitHub issue to keep, refine, or remove it. The implementation is static HTML generated from the canonical data, so pruning pages stays low-risk.</p>
      </div>
    </section>
    <section class="atlas-list">{page_cards}</section>
    """
