import csv
import itertools
import json
from pathlib import Path

from neuromouse_adapters.dandi import EXPECTED_DANDI_COLUMNS, ingest_dandi

ROOT = Path(__file__).resolve().parents[3]
DANDI_CSV = ROOT / "data" / "dandi-kinematic-dandisets.csv"
GOLDEN = ROOT / "datasets" / "golden" / "dandi_ingest.json"


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def assert_contract_hard_rules(data: dict) -> None:
    channels = data["meta"]["channels"]
    assert isinstance(channels, list)
    assert channels

    assert isinstance(data["welch_psd"]["frequencies"], list)
    assert isinstance(data["welch_psd"]["psd"], list)
    assert len(data["welch_psd"]["psd"]) == len(channels)

    assert isinstance(data["centroid"]["time_relative"], list)
    assert isinstance(data["centroid"]["values"], list)
    assert len(data["centroid"]["values"]) == len(channels)

    assert isinstance(data["geometry"]["time"], list)


def load_source_rows() -> list[dict[str, str]]:
    with DANDI_CSV.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_variant(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row[column] for column in columns})


def test_dandi_csv_ingests_to_documented_contract_subset() -> None:
    result = ingest_dandi(DANDI_CSV)

    assert_contract_hard_rules(result)
    assert result["meta"]["channels"] == ["DANDI catalog"]
    assert result["meta"]["n_channels"] == 1
    assert result["dandi"]["source_columns"] == list(EXPECTED_DANDI_COLUMNS)
    assert result["dandi"]["missing_columns"] == []
    assert result["dandi"]["summary"] == {
        "dandiset_count": 15,
        "known_asset_count_rows": 15,
        "known_size_bytes_rows": 15,
        "total_asset_count": 5650,
        "total_size_bytes": 14797898131717,
    }
    assert result["dandi"]["rows"][0] == {
        "asset_count": 2,
        "identifier": "000127",
        "name": (
            "Area2_Bump: macaque somatosensory area 2 spiking activity during reaching "
            "with perturbations"
        ),
        "size_bytes": 1823368810,
        "url": "https://dandiarchive.org/dandiset/000127/0.220113.0359",
        "version": "0.220113.0359",
    }
    assert "raw or windowed signal samples" in result["dandi"]["missing_canonical_fields"]


def test_dandi_golden_is_stable_across_runs() -> None:
    first = ingest_dandi(DANDI_CSV)
    second = ingest_dandi(DANDI_CSV)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert first == second
    assert first == golden
    assert stable_json(first) == stable_json(golden)


def test_dandi_ingest_is_invariant_for_row_permutations(tmp_path: Path) -> None:
    rows = load_source_rows()[:4]
    expected = ingest_dandi(DANDI_CSV)
    expected_subset = expected | {
        "dandi": expected["dandi"]
        | {
            "rows": expected["dandi"]["rows"][:4],
            "summary": {
                "dandiset_count": 4,
                "known_asset_count_rows": 4,
                "known_size_bytes_rows": 4,
                "total_asset_count": 771,
                "total_size_bytes": 14690977087,
            },
        }
    }

    for index, permutation in enumerate(itertools.permutations(rows)):
        path = tmp_path / f"permutation_{index}.csv"
        write_variant(path, list(permutation), list(EXPECTED_DANDI_COLUMNS))

        assert ingest_dandi(path) == expected_subset


def test_dandi_ingest_degrades_gracefully_for_missing_columns(tmp_path: Path) -> None:
    rows = load_source_rows()[:3]

    for missing_column in EXPECTED_DANDI_COLUMNS:
        columns = [column for column in EXPECTED_DANDI_COLUMNS if column != missing_column]
        path = tmp_path / f"missing_{missing_column}.csv"
        write_variant(path, rows, columns)

        result = ingest_dandi(path)

        assert_contract_hard_rules(result)
        assert missing_column in result["dandi"]["missing_columns"]
        assert len(result["dandi"]["rows"]) == 3
        assert all(set(row) == set(EXPECTED_DANDI_COLUMNS) for row in result["dandi"]["rows"])
