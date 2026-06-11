from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import scipy
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import neuromouse_core
import neuromouse_sdk
from neuromouse_core import (
    ReproductionVerificationError,
    RunManifest,
    RunResult,
    register,
    run,
)
from neuromouse_core.method_registry import MethodRegistry
from neuromouse_sdk import OutputField, OutputSpec
from neuromouse_sdk.examples.band_power_summary import band_power_summary

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = ROOT / "datasets" / "golden" / "data.json"
SEED_MAX = (2**32) - 1


@dataclass(frozen=True)
class RandomParams:
    scale: float = 1.0


class RandomScalarMethod:
    name = "random_scalar"
    version = "1.0.0"
    params_type = RandomParams
    required_inputs = ("meta.channels",)
    output = OutputSpec(fields=(OutputField("analysis.value"),), panel=None)

    def __init__(self) -> None:
        self.calls = 0

    def compute(self, dataset: Any, params: RandomParams) -> dict[str, Any]:
        self.calls += 1
        return {
            "analysis": {
                "value": float(np.random.random() * params.scale),
                "n_channels": len(dataset.meta.channels),
            }
        }


class AlternateRandomScalarMethod(RandomScalarMethod):
    name = "random_scalar_alt"


class PublicRunMethod(RandomScalarMethod):
    name = "public_run_engine_method"


def load_golden() -> dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def output_bytes(result: RunResult) -> bytes:
    return json.dumps(result.output, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def test_run_manifest_captures_reproducibility_schema_and_dataset_lineage() -> None:
    registry = MethodRegistry()
    registry.register(RandomScalarMethod())
    dataset = load_golden()

    result = registry.run_result(
        dataset,
        " random_scalar ",
        {"scale": 1.25},
        seed=77,
        dataset_version="golden-v1",
        dataset_lineage=("raw:generation-script@2026-06-11", "contract:canonical-v1"),
    )

    manifest = result.manifest
    payload = manifest.to_jsonable()

    assert isinstance(manifest, RunManifest)
    assert manifest.schema_version == "neuromouse.run-manifest.v1"
    assert len(manifest.run_id) == 64
    assert manifest.dataset == {
        "content_hash": result.provenance.input_hash,
        "version": "golden-v1",
        "lineage": ["raw:generation-script@2026-06-11", "contract:canonical-v1"],
    }
    assert manifest.method == {
        "id": "random_scalar",
        "version": "1.0.0",
        "params": {"scale": 1.25},
    }
    assert manifest.seed == 77
    assert len(manifest.output_hash) == 64
    assert manifest.library_versions["numpy"] == np.__version__
    assert manifest.library_versions["scipy"] == scipy.__version__
    assert manifest.library_versions["neuromouse_core"] == neuromouse_core.__version__
    assert manifest.library_versions["neuromouse_sdk"] == neuromouse_sdk.__version__
    assert payload["platform"]["python"]
    assert payload["platform"]["system"]
    assert result.provenance.input_version == "golden-v1"
    assert result.provenance.input_lineage == (
        "raw:generation-script@2026-06-11",
        "contract:canonical-v1",
    )


def test_run_manifest_repeated_run_has_same_run_id_and_output_hash() -> None:
    registry = MethodRegistry()
    registry.register(RandomScalarMethod())

    first = registry.run_result(
        load_golden(),
        "random_scalar",
        {"scale": 1.5},
        seed=1234,
        dataset_version="golden-v1",
        dataset_lineage=("fixture:golden",),
    )
    second = registry.run_result(
        copy.deepcopy(load_golden()),
        "random_scalar",
        {"scale": 1.5},
        seed=1234,
        dataset_version="golden-v1",
        dataset_lineage=("fixture:golden",),
    )

    assert output_bytes(first) == output_bytes(second)
    assert first.manifest.run_id == second.manifest.run_id
    assert first.manifest.output_hash == second.manifest.output_hash


def test_run_manifest_run_id_changes_when_any_derivation_field_changes() -> None:
    base = RunManifest.from_components(
        dataset_content_hash="a" * 64,
        dataset_version="dataset-v1",
        dataset_lineage=("raw:one",),
        method_id="method-a",
        method_version="1.0.0",
        params={"scale": 1.0},
        seed=7,
        library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
        platform={"python": "3.12", "system": "Darwin"},
        output_hash="b" * 64,
    )

    variants = [
        RunManifest.from_components(
            dataset_content_hash="c" * 64,
            dataset_version="dataset-v1",
            dataset_lineage=("raw:one",),
            method_id="method-a",
            method_version="1.0.0",
            params={"scale": 1.0},
            seed=7,
            library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.12", "system": "Darwin"},
            output_hash="b" * 64,
        ),
        RunManifest.from_components(
            dataset_content_hash="a" * 64,
            dataset_version="dataset-v2",
            dataset_lineage=("raw:one",),
            method_id="method-a",
            method_version="1.0.0",
            params={"scale": 1.0},
            seed=7,
            library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.12", "system": "Darwin"},
            output_hash="b" * 64,
        ),
        RunManifest.from_components(
            dataset_content_hash="a" * 64,
            dataset_version="dataset-v1",
            dataset_lineage=("raw:two",),
            method_id="method-a",
            method_version="1.0.0",
            params={"scale": 1.0},
            seed=7,
            library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.12", "system": "Darwin"},
            output_hash="b" * 64,
        ),
        RunManifest.from_components(
            dataset_content_hash="a" * 64,
            dataset_version="dataset-v1",
            dataset_lineage=("raw:one",),
            method_id="method-b",
            method_version="1.0.0",
            params={"scale": 1.0},
            seed=7,
            library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.12", "system": "Darwin"},
            output_hash="b" * 64,
        ),
        RunManifest.from_components(
            dataset_content_hash="a" * 64,
            dataset_version="dataset-v1",
            dataset_lineage=("raw:one",),
            method_id="method-a",
            method_version="2.0.0",
            params={"scale": 1.0},
            seed=7,
            library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.12", "system": "Darwin"},
            output_hash="b" * 64,
        ),
        RunManifest.from_components(
            dataset_content_hash="a" * 64,
            dataset_version="dataset-v1",
            dataset_lineage=("raw:one",),
            method_id="method-a",
            method_version="1.0.0",
            params={"scale": 2.0},
            seed=7,
            library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.12", "system": "Darwin"},
            output_hash="b" * 64,
        ),
        RunManifest.from_components(
            dataset_content_hash="a" * 64,
            dataset_version="dataset-v1",
            dataset_lineage=("raw:one",),
            method_id="method-a",
            method_version="1.0.0",
            params={"scale": 1.0},
            seed=8,
            library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.12", "system": "Darwin"},
            output_hash="b" * 64,
        ),
        RunManifest.from_components(
            dataset_content_hash="a" * 64,
            dataset_version="dataset-v1",
            dataset_lineage=("raw:one",),
            method_id="method-a",
            method_version="1.0.0",
            params={"scale": 1.0},
            seed=7,
            library_versions={"numpy": "2", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.12", "system": "Darwin"},
            output_hash="b" * 64,
        ),
        RunManifest.from_components(
            dataset_content_hash="a" * 64,
            dataset_version="dataset-v1",
            dataset_lineage=("raw:one",),
            method_id="method-a",
            method_version="1.0.0",
            params={"scale": 1.0},
            seed=7,
            library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.13", "system": "Darwin"},
            output_hash="b" * 64,
        ),
        RunManifest.from_components(
            dataset_content_hash="a" * 64,
            dataset_version="dataset-v1",
            dataset_lineage=("raw:one",),
            method_id="method-a",
            method_version="1.0.0",
            params={"scale": 1.0},
            seed=7,
            library_versions={"numpy": "1", "scipy": "1", "neuromouse_core": "1"},
            platform={"python": "3.12", "system": "Darwin"},
            output_hash="d" * 64,
        ),
    ]

    assert {variant.run_id for variant in variants}.isdisjoint({base.run_id})


def test_verify_reproduction_passes_for_faithful_rerun_and_fails_for_tampered_input() -> None:
    registry = MethodRegistry()
    method = RandomScalarMethod()
    registry.register(method)
    dataset = load_golden()
    result = registry.run_result(
        dataset,
        "random_scalar",
        {"scale": 1.5},
        seed=1234,
        dataset_version="golden-v1",
        dataset_lineage=("fixture:golden",),
    )

    verified = registry.verify_reproduction(result.manifest, copy.deepcopy(dataset))

    assert method.calls == 2
    assert verified.manifest == result.manifest
    assert output_bytes(verified) == output_bytes(result)

    tampered = copy.deepcopy(dataset)
    tampered["meta"]["source"] = "tampered-dataset"
    with pytest.raises(ReproductionVerificationError, match="input hash"):
        registry.verify_reproduction(result.manifest, tampered)


@given(
    scale=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
    seed=st.integers(min_value=0, max_value=SEED_MAX),
    dataset_version=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=12,
    ),
)
@settings(
    max_examples=40,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_run_manifest_property_round_trips_jsonable_payload(
    scale: float,
    seed: int,
    dataset_version: str,
) -> None:
    registry = MethodRegistry()
    registry.register(RandomScalarMethod())

    result = registry.run_result(
        load_golden(),
        "random_scalar",
        {"scale": scale},
        seed=seed,
        dataset_version=dataset_version,
        dataset_lineage=("property:golden",),
    )
    payload = json.loads(json.dumps(result.manifest.to_jsonable()))

    assert RunManifest.from_jsonable(payload) == result.manifest


def test_run_engine_is_seed_deterministic_without_reusing_cache() -> None:
    outputs = []
    for _ in range(20):
        registry = MethodRegistry()
        registry.register(RandomScalarMethod())

        result = registry.run_result(
            load_golden(),
            "random_scalar",
            {"scale": 1.5},
            seed=1234,
        )

        outputs.append(output_bytes(result))

    assert len(set(outputs)) == 1


def test_run_engine_cache_hits_for_identical_content_and_invalidates_each_key_field() -> None:
    dataset = load_golden()
    registry = MethodRegistry()
    method = RandomScalarMethod()
    alt_method = AlternateRandomScalarMethod()
    registry.register(method)
    registry.register(alt_method)

    first = registry.run_result(dataset, "random_scalar", {"scale": 1.5}, seed=1234)
    second = registry.run_result(copy.deepcopy(dataset), "random_scalar", {"scale": 1.5}, seed=1234)

    assert method.calls == 1
    assert output_bytes(first) == output_bytes(second)
    assert first.provenance == second.provenance

    registry.run_result(dataset, "random_scalar", {"scale": 2.0}, seed=1234)
    assert method.calls == 2

    registry.run_result(dataset, "random_scalar", {"scale": 2.0}, seed=4321)
    assert method.calls == 3

    changed_dataset = copy.deepcopy(dataset)
    changed_dataset["meta"]["source"] = "cache-key-invalidation"
    registry.run_result(changed_dataset, "random_scalar", {"scale": 2.0}, seed=4321)
    assert method.calls == 4

    registry.run_result(dataset, "random_scalar_alt", {"scale": 1.5}, seed=1234)
    assert alt_method.calls == 1


def test_run_engine_provenance_records_method_params_input_seed_and_versions() -> None:
    registry = MethodRegistry()
    registry.register(RandomScalarMethod())

    result = registry.run_result(load_golden(), " random_scalar ", {"scale": 1.25}, seed=77)

    assert result.provenance.method_name == "random_scalar"
    assert result.provenance.method_version == "1.0.0"
    assert result.provenance.params == {"scale": 1.25}
    assert result.provenance.seed == 77
    assert len(result.provenance.input_hash) == 64
    assert result.provenance.versions["numpy"] == np.__version__
    assert result.provenance.versions["scipy"] == scipy.__version__
    assert result.provenance.versions["neuromouse_core"] == neuromouse_core.__version__
    assert result.provenance.versions["neuromouse_sdk"] == neuromouse_sdk.__version__


@given(
    scale=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
    seed=st.integers(min_value=0, max_value=SEED_MAX),
)
@settings(
    max_examples=60,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_run_engine_property_caches_random_params_and_seeds(scale: float, seed: int) -> None:
    registry = MethodRegistry()
    method = RandomScalarMethod()
    registry.register(method)
    params = {"scale": scale}

    first = registry.run_result(load_golden(), "random_scalar", params, seed=seed)
    second = registry.run_result(load_golden(), "random_scalar", params, seed=seed)

    assert method.calls == 1
    assert output_bytes(first) == output_bytes(second)
    assert first.provenance == second.provenance

    registry.run_result(load_golden(), "random_scalar", params, seed=(seed + 1) % (SEED_MAX + 1))
    assert method.calls == 2


def test_run_engine_stress_repeats_are_byte_identical() -> None:
    outputs = []
    for _ in range(100):
        registry = MethodRegistry()
        registry.register(RandomScalarMethod())
        result = registry.run_result(load_golden(), "random_scalar", {"scale": 2.5}, seed=2026)
        outputs.append(output_bytes(result))

    assert len(set(outputs)) == 1


def test_run_engine_runs_band_power_summary_on_golden_end_to_end() -> None:
    registry = MethodRegistry()
    registry.register(band_power_summary)

    result = registry.run_result(
        load_golden(),
        "band_power_summary",
        {"min_hz": 8.0, "max_hz": 13.0},
        seed=11,
    )

    summary = result.output["band_power_summary"]
    assert result.provenance.method_name == "band_power_summary"
    assert result.provenance.method_version == band_power_summary.version
    assert result.provenance.params == {"min_hz": 8.0, "max_hz": 13.0}
    assert result.provenance.seed == 11
    assert len(summary["channels"]) == load_golden()["meta"]["n_channels"]
    assert summary["top_channel"]["channel"] in load_golden()["meta"]["channels"]
    assert summary["mean_power"] == pytest.approx(
        sum(row["power"] for row in summary["channels"]) / len(summary["channels"])
    )


def test_public_run_function_uses_the_default_registry() -> None:
    method = PublicRunMethod()
    try:
        register(method)
    except ValueError as exc:
        if "already registered" not in str(exc):
            raise

    result = run(load_golden(), "public_run_engine_method", {"scale": 3.0}, seed=9)

    assert isinstance(result, RunResult)
    assert result.provenance.method_name == "public_run_engine_method"
    assert "analysis" in result.output
