from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from my_spotify_analytics.build import build, load_jsonl


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


class BuildAnalyticsTest(unittest.TestCase):
    def test_build_creates_sqlite_and_static_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            write_jsonl(
                data / "listening_events.jsonl",
                [
                    {
                        "played_at": "2024-01-01T00:00:00Z",
                        "track_id": "track-1",
                        "sources": ["my-spotify-data_api_recently_played"],
                    },
                    {
                        "played_at": "2024-01-02T00:00:00Z",
                        "track_id": "track-1",
                        "sources": ["my-esporifai_spotify_account_export"],
                    },
                ],
            )
            write_jsonl(
                data / "track_catalog.jsonl",
                [
                    {
                        "id": "track-1",
                        "name": "Track One",
                        "artist_ids": ["artist-1"],
                        "metadata_status": "complete",
                    }
                ],
            )
            write_jsonl(data / "album_catalog.jsonl", [])
            write_jsonl(
                data / "artist_catalog.jsonl",
                [{"id": "artist-1", "name": "Artist One"}],
            )
            (data / "audit").mkdir()
            (data / "audit" / "canonical_data_audit.json").write_text(
                json.dumps(
                    {
                        "source_ref": "origin/main",
                        "union": {"event_set_hash": "abc123"},
                    }
                )
            )

            summary = build(data, root / "build" / "spotify.db", root / "site")

            self.assertEqual(2, summary["events"])
            self.assertTrue((root / "build" / "spotify.db").exists())
            self.assertTrue((root / "site" / "index.html").exists())
            index_html = (root / "site" / "index.html").read_text()
            self.assertIn("My Spotify Analytics", index_html)
            self.assertIn("--c-paper: #F7F5F1", index_html)
            self.assertIn("Data Provenance", index_html)
            self.assertIn("Coverage", index_html)

            con = sqlite3.connect(root / "build" / "spotify.db")
            self.assertEqual(
                2,
                con.execute("select plays from top_tracks where id = 'track-1'").fetchone()[0],
            )

    def test_load_jsonl_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.jsonl"
            path.write_text('{"a": 1}\n\n{"a": 2}\n')
            self.assertEqual([{"a": 1}, {"a": 2}], load_jsonl(path))


if __name__ == "__main__":
    unittest.main()
