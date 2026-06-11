from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

EXPECTED_DANDI_COLUMNS = (
    "identifier",
    "version",
    "name",
    "asset_count",
    "size_bytes",
    "url",
)

MISSING_CANONICAL_FIELDS = (
    "real channel names",
    "sampling rate",
    "raw or windowed signal samples",
    "Welch frequency axis",
    "Welch PSD values",
    "centroid time axis and values",
    "sliding geometry metrics",
    "per-channel summary metrics",
)

CATALOG_CHANNEL = "DANDI catalog"


def ingest_dandi(csv_path: str | Path) -> dict[str, Any]:
    """Ingest a DANDI dandiset metadata CSV into a documented canonical subset.

    The current concrete input, ``data/dandi-kinematic-dandisets.csv``, is a DANDI
    search/export table. It does not contain neural samples, channel names, time axes,
    frequencies, or spectral metrics. The returned object therefore satisfies the
    viewer's hard ``data.json`` container rules with one metadata pseudo-channel and
    carries the real dandiset rows under the ``dandi`` extension key.
    """

    rows, source_columns = _read_rows(csv_path)
    missing_columns = [column for column in EXPECTED_DANDI_COLUMNS if column not in source_columns]
    normalized_rows = sorted((_normalize_row(row) for row in rows), key=_row_sort_key)

    return {
        "meta": {
            "channels": [CATALOG_CHANNEL],
            "n_channels": 1,
            "source": "DANDI kinematic dandisets tabular export",
            "analysis_by": "neuromouse-adapters.ingest_dandi",
            "source_files": {"dandi_csv": "caller supplied CSV"},
            "notes": [
                "Partial metadata-only ingest: this CSV lists DANDI dandisets and does not "
                "contain neural samples, channel names, frequencies, time axes, or "
                "per-channel spectral metrics."
            ],
        },
        "welch_psd": {"frequencies": [], "psd": [[]]},
        "centroid": {"time_relative": [], "values": [[]]},
        "geometry": {"time": []},
        "channel_summary": [
            {
                "channel": CATALOG_CHANNEL,
                "hemisphere": "",
                "region": "metadata",
                "has_clear_alpha_peak": False,
            }
        ],
        "dandi": {
            "schema": "neuromouse-dandi-catalog-v1",
            "source_columns": source_columns,
            "missing_columns": missing_columns,
            "missing_canonical_fields": list(MISSING_CANONICAL_FIELDS),
            "summary": _summarize(normalized_rows),
            "rows": normalized_rows,
        },
    }


def _read_rows(csv_path: str | Path) -> tuple[list[dict[str, str | None]], list[str]]:
    path = Path(csv_path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        source_columns = list(reader.fieldnames or [])
        return list(reader), source_columns


def _normalize_row(row: dict[str, str | None]) -> dict[str, str | int | None]:
    return {
        "identifier": _clean_text(row.get("identifier")),
        "version": _clean_text(row.get("version")),
        "name": _clean_text(row.get("name")),
        "asset_count": _clean_int(row.get("asset_count")),
        "size_bytes": _clean_int(row.get("size_bytes")),
        "url": _clean_text(row.get("url")),
    }


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _clean_int(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _row_sort_key(row: dict[str, str | int | None]) -> tuple[str, str, str, str]:
    return (
        str(row.get("identifier") or ""),
        str(row.get("version") or ""),
        str(row.get("name") or ""),
        str(row.get("url") or ""),
    )


def _summarize(rows: list[dict[str, str | int | None]]) -> dict[str, int | None]:
    asset_counts = [row["asset_count"] for row in rows if isinstance(row["asset_count"], int)]
    sizes = [row["size_bytes"] for row in rows if isinstance(row["size_bytes"], int)]
    return {
        "dandiset_count": len(rows),
        "known_asset_count_rows": len(asset_counts),
        "known_size_bytes_rows": len(sizes),
        "total_asset_count": sum(asset_counts) if asset_counts else None,
        "total_size_bytes": sum(sizes) if sizes else None,
    }
