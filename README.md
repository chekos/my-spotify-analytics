# my-spotify-analytics

Static GitHub Pages analytics for the public canonical data in
`chekos/my-spotify-data`.

This repo builds generated artifacts from canonical JSONL source data:

- `build/spotify.db`: local SQLite analytics database.
- `site/index.html`: GitHub Pages dashboard.

Generated files are intentionally ignored. Rebuild them from source instead of
committing them to `main`.

## Local Build

From the grouped workspace layout:

```shell
python3 scripts/build_site.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

The default data directory is `../my-spotify-data/data`. Override it with:

```shell
python3 scripts/build_site.py --data-dir /path/to/my-spotify-data/data
```

## Publish

GitHub Actions builds the SQLite database and uploads `site/` as the Pages
artifact. The workflow checks out `chekos/my-spotify-data` as a sibling repo and
does not commit generated files.
