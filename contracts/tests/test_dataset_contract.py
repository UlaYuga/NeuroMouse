from __future__ import annotations

import copy
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from neuromouse_contract import (
    Dataset,
    DatasetValidationError,
    emit_dataset_schema,
    validate_dataset,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = REPO_ROOT / "datasets" / "golden" / "data.json"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schema" / "dataset.schema.json"
STATIC_SOURCE_PATH = REPO_ROOT / "js" / "sources" / "static-source.js"


Mutation = tuple[str, Callable[[dict[str, Any]], None], str]


def load_golden() -> dict[str, Any]:
    with GOLDEN_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def minimal_dataset(channel_count: int = 2) -> dict[str, Any]:
    channels = [f"C{i}" for i in range(channel_count)]
    return {
        "meta": {"channels": channels, "n_channels": channel_count},
        "welch_psd": {
            "frequencies": [1.0, 2.0, 3.0],
            "psd": [[0.1, 0.2, 0.3] for _ in channels],
        },
        "centroid": {
            "time_relative": [0.0, 0.5],
            "values": [[8.0, 8.5] for _ in channels],
        },
        "geometry": {
            "time": [0.0, 0.5],
            "centroid": [[8.0, 8.5] for _ in channels],
            "spread": [[1.0, 1.1] for _ in channels],
            "entropy": [[0.6, 0.7] for _ in channels],
            "flatness": [[0.2, 0.3] for _ in channels],
            "edge95": [[24.0, 24.5] for _ in channels],
            "alpha_relative_power": [[0.3, 0.31] for _ in channels],
            "area_normalized_psd": {
                "frequencies": [1.0, 2.0, 3.0],
                "psd": [[0.01, 0.02, 0.03] for _ in channels],
            },
        },
        "channel_summary": [
            {
                "channel": channel,
                "hemisphere": "",
                "region": "unknown",
                "has_clear_alpha_peak": False,
                "alpha_relative_power": 0.3,
                "spectral_centroid_hz": 8.0,
                "spectral_spread_hz": 1.0,
                "spectral_entropy": 0.6,
                "spectral_flatness": 0.2,
                "edge95_hz": 24.0,
                "alpha_peak_frequency_hz": 10.0,
                "sliding_alpha_relative_mean": 0.29,
            }
            for channel in channels
        ],
    }


def _drop_meta_channels(data: dict[str, Any]) -> None:
    data["meta"].pop("channels")


def _empty_meta_channels(data: dict[str, Any]) -> None:
    data["meta"]["channels"] = []


def _string_meta_channels(data: dict[str, Any]) -> None:
    data["meta"]["channels"] = "Fp1"


def _missing_welch_frequencies(data: dict[str, Any]) -> None:
    data["welch_psd"].pop("frequencies")


def _string_welch_frequencies(data: dict[str, Any]) -> None:
    data["welch_psd"]["frequencies"] = "1,2,3"


def _string_welch_psd(data: dict[str, Any]) -> None:
    data["welch_psd"]["psd"] = "not rows"


def _mismatch_welch_rows(data: dict[str, Any]) -> None:
    data["welch_psd"]["psd"] = data["welch_psd"]["psd"][:-1]


def _missing_centroid_time(data: dict[str, Any]) -> None:
    data["centroid"].pop("time_relative")


def _string_centroid_values(data: dict[str, Any]) -> None:
    data["centroid"]["values"] = "not rows"


def _mismatch_centroid_rows(data: dict[str, Any]) -> None:
    data["centroid"]["values"] = data["centroid"]["values"][:-1]


def _missing_geometry_time(data: dict[str, Any]) -> None:
    data["geometry"].pop("time")


def _string_geometry_time(data: dict[str, Any]) -> None:
    data["geometry"]["time"] = "0,1,2"


MUTATION_CASES: list[Mutation] = [
    (
        "drop meta.channels",
        _drop_meta_channels,
        "data.json must contain a non-empty meta.channels array",
    ),
    (
        "empty meta.channels",
        _empty_meta_channels,
        "data.json must contain a non-empty meta.channels array",
    ),
    (
        "meta.channels is not an array",
        _string_meta_channels,
        "data.json must contain a non-empty meta.channels array",
    ),
    (
        "drop welch_psd.frequencies",
        _missing_welch_frequencies,
        "data.json is missing welch_psd arrays",
    ),
    (
        "welch_psd.frequencies is not an array",
        _string_welch_frequencies,
        "data.json is missing welch_psd arrays",
    ),
    (
        "welch_psd.psd is not an array",
        _string_welch_psd,
        "data.json is missing welch_psd arrays",
    ),
    (
        "welch_psd.psd row count mismatch",
        _mismatch_welch_rows,
        "welch_psd.psd has 1 channel rows but meta.channels lists 2",
    ),
    (
        "drop centroid.time_relative",
        _missing_centroid_time,
        "data.json is missing centroid arrays",
    ),
    (
        "centroid.values is not an array",
        _string_centroid_values,
        "data.json is missing centroid arrays",
    ),
    (
        "centroid.values row count mismatch",
        _mismatch_centroid_rows,
        "centroid.values has 1 channel rows but meta.channels lists 2",
    ),
    (
        "drop geometry.time",
        _missing_geometry_time,
        "data.json is missing geometry.time",
    ),
    (
        "geometry.time is not an array",
        _string_geometry_time,
        "data.json is missing geometry.time",
    ),
]


def finite_float_values(
    min_value: float | None = None, max_value: float | None = None
) -> st.SearchStrategy[float]:
    return st.floats(
        min_value=min_value,
        max_value=max_value,
        allow_nan=False,
        allow_infinity=False,
        width=32,
    )


def channel_major_rows(channel_count: int, width: int) -> st.SearchStrategy[list[list[float]]]:
    return st.lists(
        st.lists(finite_float_values(), min_size=width, max_size=width),
        min_size=channel_count,
        max_size=channel_count,
    )


@st.composite
def valid_dataset_objects(draw: st.DrawFn) -> dict[str, Any]:
    channels = draw(
        st.lists(
            st.text(min_size=1, max_size=12).filter(lambda value: value.strip() != ""),
            min_size=1,
            max_size=12,
            unique=True,
        )
    )
    channel_count = len(channels)
    frequencies = draw(st.lists(finite_float_values(), min_size=1, max_size=16))
    centroid_time = draw(st.lists(finite_float_values(), min_size=1, max_size=16))
    geometry_time = draw(st.lists(finite_float_values(), min_size=0, max_size=16))

    return {
        "meta": {
            "channels": channels,
            "n_channels": channel_count,
            "segment_duration_sec": draw(st.none() | finite_float_values(min_value=0.0)),
            "sampling_rate_analysis_hz": draw(st.none() | finite_float_values(min_value=1.0)),
            "welch_window_sec": draw(st.none() | finite_float_values(min_value=0.0)),
            "welch_overlap_fraction": draw(
                st.none() | finite_float_values(min_value=0.0, max_value=1.0)
            ),
            "sliding_window_sec": draw(st.none() | finite_float_values(min_value=0.0)),
            "sliding_step_sec": draw(st.none() | finite_float_values(min_value=0.0)),
            "source": draw(st.none() | st.text(max_size=24)),
            "analysis_by": draw(st.none() | st.text(max_size=24)),
        },
        "welch_psd": {
            "frequencies": frequencies,
            "psd": draw(channel_major_rows(channel_count, len(frequencies))),
        },
        "centroid": {
            "time_relative": centroid_time,
            "values": draw(channel_major_rows(channel_count, len(centroid_time))),
        },
        "geometry": {
            "time": geometry_time,
            "centroid": draw(st.none() | channel_major_rows(channel_count, len(geometry_time))),
            "spread": draw(st.none() | channel_major_rows(channel_count, len(geometry_time))),
            "entropy": draw(st.none() | channel_major_rows(channel_count, len(geometry_time))),
            "flatness": draw(st.none() | channel_major_rows(channel_count, len(geometry_time))),
            "edge95": draw(st.none() | channel_major_rows(channel_count, len(geometry_time))),
            "alpha_relative_power": draw(
                st.none() | channel_major_rows(channel_count, len(geometry_time))
            ),
        },
        "channel_summary": [
            {
                "channel": channel,
                "hemisphere": draw(st.sampled_from(["L", "R", "M", ""])),
                "region": draw(st.text(max_size=16)),
                "has_clear_alpha_peak": draw(st.booleans()),
                "alpha_relative_power": draw(finite_float_values()),
                "spectral_centroid_hz": draw(finite_float_values()),
                "spectral_spread_hz": draw(finite_float_values()),
                "spectral_entropy": draw(finite_float_values()),
                "spectral_flatness": draw(finite_float_values()),
                "edge95_hz": draw(finite_float_values()),
                "alpha_peak_frequency_hz": draw(st.none() | finite_float_values()),
                "sliding_alpha_relative_mean": draw(st.none() | finite_float_values()),
            }
            for channel in channels
        ],
    }


def mutated_fixture(mutation: Mutation, source: dict[str, Any] | None = None) -> dict[str, Any]:
    data = copy.deepcopy(source or minimal_dataset())
    mutation[1](data)
    return data


def python_acceptance(data: dict[str, Any]) -> tuple[bool, str]:
    try:
        validate_dataset(data)
    except Exception as exc:  # noqa: BLE001 - parity test needs the actual public decision.
        return False, str(exc)
    return True, ""


def write_js_validator(tmp_path: Path) -> Path:
    script = tmp_path / "validate-data.mjs"
    script.write_text(
        """
const staticSourceUrl = process.argv[2];
const { validateData } = await import(staticSourceUrl);
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) {
  input += chunk;
}
try {
  validateData(JSON.parse(input));
  process.stdout.write("ACCEPT");
} catch (error) {
  process.stderr.write(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
""".lstrip(),
        encoding="utf-8",
    )
    return script


def js_acceptance(script: Path, data: dict[str, Any]) -> tuple[bool, str]:
    result = subprocess.run(
        ["node", str(script), STATIC_SOURCE_PATH.as_uri()],
        input=json.dumps(data),
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0, result.stderr


def test_golden_dataset_loads_with_zero_validation_errors() -> None:
    dataset = validate_dataset(load_golden())

    assert isinstance(dataset, Dataset)
    assert len(dataset.meta.channels) == 32


@pytest.mark.parametrize(
    ("name", "mutate", "expected_error"), MUTATION_CASES, ids=lambda item: item
)
def test_documented_hard_rule_mutations_are_rejected(
    name: str, mutate: Callable[[dict[str, Any]], None], expected_error: str
) -> None:
    data = minimal_dataset()
    mutate(data)

    with pytest.raises(DatasetValidationError, match=re.escape(expected_error)):
        validate_dataset(data)


@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(valid_dataset_objects())
def test_hypothesis_valid_datasets_pass(data: dict[str, Any]) -> None:
    validate_dataset(data)


@settings(max_examples=500, deadline=None)
@given(valid_dataset_objects(), st.sampled_from(MUTATION_CASES))
def test_hypothesis_targeted_invalid_mutations_reject(
    data: dict[str, Any], mutation: Mutation
) -> None:
    mutated = mutated_fixture(mutation, data)

    with pytest.raises(DatasetValidationError):
        validate_dataset(mutated)


def test_json_schema_file_matches_dataset_model_schema() -> None:
    on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert on_disk == Dataset.model_json_schema()


def test_emit_dataset_schema_writes_schema(tmp_path: Path) -> None:
    target = tmp_path / "dataset.schema.json"

    emit_dataset_schema(target)

    assert json.loads(target.read_text(encoding="utf-8")) == Dataset.model_json_schema()


def test_python_validator_matches_js_validate_data_on_shared_fixture_set(tmp_path: Path) -> None:
    script = write_js_validator(tmp_path)
    fixtures = [
        ("golden", load_golden()),
        ("minimal", minimal_dataset()),
        *[
            (f"mutation: {name}", mutated_fixture((name, mutate, expected_error)))
            for name, mutate, expected_error in MUTATION_CASES
        ],
    ]

    disagreements: list[str] = []
    for name, data in fixtures:
        python_ok, python_message = python_acceptance(data)
        js_ok, js_message = js_acceptance(script, data)
        if python_ok != js_ok:
            disagreements.append(
                f"{name}: python={python_ok} {python_message!r}; js={js_ok} {js_message!r}"
            )

    assert disagreements == []
