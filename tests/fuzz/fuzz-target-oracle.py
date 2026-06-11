#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
for package in ("adapters", "backend", "core", "sdk", "sorting"):
    src = REPO_ROOT / "packages" / package / "src"
    if src.exists():
        sys.path.insert(0, str(src))
for package in ("contracts",):
    package_path = REPO_ROOT / package / "src"
    if package_path.exists():
        sys.path.insert(0, str(package_path))

from fastapi.testclient import TestClient
from neuromouse_adapters import read_mea
from neuromouse_backend.app import create_app
from neuromouse_backend.storage import InMemoryBackendStore, SQLiteBackendStore
from neuromouse_contract import DatasetValidationError, validate_dataset
from neuromouse_core.method_registry import MethodRegistry
from neuromouse_sdk import Method, OutputField, OutputSpec
from neuromouse_sorting import (
    MEARecording,
    OutputField as SortingOutputField,
    SorterOutputSpec,
    SpikeSorterRegistry,
    SortedUnit,
    SortingResult,
)
from neuromouse_sorting.spikeinterface_adapter import SpikeInterfaceSorter


def _coerce_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _coerce_jsonable(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_coerce_jsonable(child) for child in value]
    if isinstance(value, tuple):
        return [_coerce_jsonable(child) for child in value]
    return value


def _run_json_target(target: str, payload: dict[str, Any]) -> dict[str, Any]:
    handlers = {
        "mea": run_mea_case,
        "run-engine": run_run_engine_case,
        "backend-jobs": run_backend_case,
        "sorter-seam": run_sorter_seam_case,
    }
    handler = handlers.get(target)
    if handler is None:
        raise ValueError(f"unknown target {target!r}")
    return handler(payload)


def _safe_case_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raise TypeError("case payload must be a JSON object")


def run_mea_case(payload: dict[str, Any]) -> dict[str, Any]:
    suffix = str(payload.get("suffix", "csv")).lstrip(".").lower()
    header = payload.get("header")
    if not isinstance(header, list):
        header = ["time_sec", "A", "B"]
    rows = payload.get("rows")
    if not isinstance(rows, list):
        rows = [["0", "1", "2"]]

    with tempfile.TemporaryDirectory() as directory:
        file_path = Path(directory) / f"fuzz.{suffix}"
        body = ""
        if suffix == "csv":
            body = ",".join(str(cell) for cell in header) + "\n"
            for row in rows[:64]:
                if isinstance(row, list):
                    body += ",".join(str(cell) for cell in row) + "\n"
        else:
            body = "\n".join(",".join(str(cell) for cell in row) for row in rows[:32]) if rows else ""
            body = "".join(ch for ch in body if ch.isprintable() or ch == "\n")
        file_path.write_text(body, encoding="utf-8")

        try:
            dataset = read_mea(file_path)
        except Exception as exc:
            return {
                "outcome": "read_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

    try:
        validate_dataset(dataset)
    except Exception as exc:
        return {
            "outcome": "validation_failed",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    meta = dataset.get("meta", {})
    return {
        "outcome": "ok",
        "channels": len(meta.get("channels", [])),
        "declared_channels": int(meta.get("n_channels", 0)),
        "layout": _safe_meta_entry(meta.get("mea", {})).get("layout"),
        "analysis_by": meta.get("analysis_by"),
        "modality": meta.get("modality"),
    }


def _safe_meta_entry(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _valid_dataset() -> dict[str, Any]:
    channels = ("C0", "C1")
    return {
        "meta": {"channels": list(channels), "n_channels": len(channels)},
        "welch_psd": {
            "frequencies": [8.0, 10.0, 12.0],
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


def _build_dataset(case_mode: str, seed: int = 0) -> dict[str, Any]:
    dataset = _valid_dataset()
    if case_mode == "valid":
        return dataset
    if case_mode == "missing_meta":
        return {"welch_psd": dataset["welch_psd"]}
    if case_mode == "missing_channels":
        payload = copy.deepcopy(dataset)
        payload["meta"]["channels"] = []
        payload["meta"]["n_channels"] = 0
        return payload
    if case_mode == "bad_channel_count":
        payload = copy.deepcopy(dataset)
        payload["meta"]["n_channels"] = "x"
        return payload
    if case_mode == "bad_channel_name":
        payload = copy.deepcopy(dataset)
        payload["meta"]["channels"] = [""]
        payload["meta"]["n_channels"] = 1
        return payload
    return dataset


def _build_output_for_output_fields(fields: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in fields:
        if not isinstance(path, str) or not path:
            continue
        parts = [part for part in path.split(".") if part]
        current = result
        for part in parts[:-1]:
            next_node = current.setdefault(part, {})
            if not isinstance(next_node, dict):
                next_node = {}
                current[part] = next_node
            current = next_node
        if parts:
            current[parts[-1]] = 1
    return result


def run_run_engine_case(payload: dict[str, Any]) -> dict[str, Any]:
    @dataclass
    class Params:
        scale: float = 1.0

    class Method:
        name = payload.get("method_name", "random_scalar")
        version = str(payload.get("method_version", "1.0.0"))
        params_type = Params if payload.get("params_type") != "invalid" else int
        required_inputs = tuple(payload.get("required_inputs") or ("meta.channels",))
        output = OutputSpec(
            fields=tuple(
                OutputField(path) for path in (payload.get("output_fields") or ("analysis.value",))
            )
        )

        def compute(self, dataset, params):  # noqa: ANN001, ANN401
            compute_mode = payload.get("compute_mode", "ok")
            if compute_mode == "none":
                return None
            if compute_mode == "non_mapping":
                return ["not", "a", "mapping"]
            if compute_mode == "missing":
                return {"other": {"value": 0}}
            if compute_mode == "raise":
                raise RuntimeError("method.compute failure")
            if compute_mode == "bad_map":
                return {"analysis": []}
            if compute_mode == "invalid":
                return {"analysis": {"value": {"nested": True}}}
            return _build_output_for_output_fields(list(payload.get("output_fields") or ("analysis.value",)))

    registry = MethodRegistry()
    outcome: dict[str, Any] = {}

    try:
        registry.register(Method())
        outcome["register"] = {"ok": True}
    except Exception as exc:
        return {
            "register": {
                "ok": False,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        }

    dataset = _build_dataset(str(payload.get("dataset_mode", "valid")), seed=int(payload.get("seed", 0)))
    params = payload.get("params")

    if payload.get("run", True):
        try:
            result = registry.run(str(payload.get("method_name", "random_scalar")), dataset, params=params)
            outcome["run"] = {
                "ok": True,
                "has_output": isinstance(result.result, dict),
                "method_name": result.method_name,
                "result": _coerce_jsonable(result.result),
            }
        except Exception as exc:
            outcome["run"] = {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}

    if payload.get("run_result", True):
        try:
            seed = int(payload.get("seed", 7))
            run_result = registry.run_result(
                dataset,
                str(payload.get("method_name", "random_scalar")),
                params=params,
                seed=seed,
                dataset_version=payload.get("dataset_version", "unversioned"),
                dataset_lineage=payload.get("dataset_lineage"),
                use_cache=bool(payload.get("use_cache", True)),
            )
            if payload.get("verify", False):
                manifest = run_result.manifest.to_jsonable()
                tampered = copy.deepcopy(dataset)
                if payload.get("tamper_manifest", False):
                    tampered["meta"] = {"channels": ["X"]}
                verified = registry.verify_reproduction(manifest, tampered if payload.get("tamper_manifest", False) else dataset)
                outcome["verify"] = {"ok": True, "output_hash": verified.manifest.output_hash}
            else:
                outcome["run_result"] = {
                    "ok": True,
                    "run_id": run_result.manifest.run_id,
                    "output_hash": run_result.manifest.output_hash,
                }
        except Exception as exc:
            outcome["run_result"] = {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}

    return outcome


def run_backend_case(payload: dict[str, Any]) -> dict[str, Any]:
    store_mode = str(payload.get("store", "memory"))
    if store_mode == "sqlite":
        temp_db = tempfile.NamedTemporaryFile(prefix="backend-fuzz-", suffix=".sqlite3", delete=True)
        temp_db.close()
        store = SQLiteBackendStore(temp_db.name)
    else:
        store = InMemoryBackendStore()

    app = create_app(store=store)
    client = TestClient(app)

    dataset_mode = str(payload.get("dataset_mode", "valid"))
    case_job_mode = str(payload.get("job_mode", "valid"))
    session_name = payload.get("session_name", "fuzz")
    if dataset_mode == "missing_dataset":
        session_payload: dict[str, Any] = {"name": session_name}
    elif dataset_mode == "invalid_dataset":
        session_payload = {"name": session_name, "dataset": {}}
    elif dataset_mode == "bad_channels":
        payload_dataset = _valid_dataset()
        payload_dataset["meta"]["channels"] = []
        payload_dataset["meta"]["n_channels"] = 0
        session_payload = {"name": session_name, "dataset": payload_dataset}
    else:
        session_payload = {"name": session_name, "dataset": _valid_dataset()}

    create_session = _safe_request(client.post, "/sessions", session_payload)

    summary: dict[str, Any] = {"session": create_session}
    session_id = None
    if create_session.get("ok") and create_session.get("status") == 201:
        session_id = create_session["json"].get("id")
        summary["session_snapshot"] = copy.deepcopy(create_session["json"])

    if case_job_mode == "skip":
        return summary

    method_id = payload.get("method_id", "band_power_summary")
    params = payload.get("job_params")
    use_session = session_id if str(payload.get("job_session", "created")) != "missing" else "missing-session"
    job_target = f"/sessions/{use_session}/jobs"
    create_job = _safe_request(
        client.post,
        job_target,
        {"method_id": method_id, "params": params},
    )
    summary["job"] = create_job

    if create_job.get("ok") and create_job.get("status") == 201:
        job_id = create_job["json"].get("id")
        summary["job"] = {"id": job_id, **create_job}
        summary["get_job"] = _safe_request(client.get, f"/jobs/{job_id}", None)
    else:
        summary["get_job"] = _safe_request(client.get, "/jobs/not-found", None)

    if session_id:
        summary["get_session"] = _safe_request(client.get, f"/sessions/{session_id}", None)
    else:
        summary["get_session"] = _safe_request(client.get, "/sessions/not-found", None)

    return summary


def _safe_request(method, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    try:
        if payload is None:
            response = method(path)
        else:
            response = method(path, json=payload)
    except Exception as exc:
        return {"ok": False, "transport": "exception", "error_type": type(exc).__name__, "error_message": str(exc)}

    response_json: Any
    try:
        response_json = response.json()
    except Exception:
        response_json = None

    return {
        "ok": response is not None and response.status_code < 600,
        "status": response.status_code,
        "json": _coerce_jsonable(response_json),
        "text": None if response is None else (response.text[:2048] if response.text is not None else None),
    }


def run_sorter_seam_case(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action", "registry-run")

    try:
        recording = _make_recording(payload)
    except Exception as exc:
        return {
            "register": {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}
        }

    if action == "spikeinterface":
        sorter_name = str(payload.get("sorter_name", ""))
        try:
            sorter = SpikeInterfaceSorter(sorter_name)
        except Exception as exc:
            return {
                "register": {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}
            }

        try:
            result = sorter.sort(recording, payload.get("sorter_params", {"sorter_params": {}}))
            return {
                "register": {"ok": True, "name": sorter.name},
                "run": {
                    "ok": True,
                    "result": {"units": len(result.units), "metadata_keys": list(result.metadata)},
                },
            }
        except Exception as exc:
            return {
                "register": {"ok": True, "name": sorter.name},
                "run": {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)},
            }

    @dataclass(frozen=True)
    class SorterParams:
        output: int = 0

    class Sorter:
        name = str(payload.get("sorter_name", "fuzz_sorter"))
        version = str(payload.get("sorter_version", "1.0.0"))
        params_type = SorterParams if str(payload.get("params_type", "valid")) != "bad" else int
        output = SorterOutputSpec(
            fields=tuple(
                SortingOutputField(path) for path in (payload.get("output_fields") or ("units", "metadata.sorter"))
            )
        )

        def sort(self, recording: MEARecording, params: SorterParams) -> SortingResult:
            mode = str(payload.get("sort_mode", "ok"))
            if mode == "wrong_type":
                return 123  # type: ignore[return-value]
            if mode == "missing":
                return SortingResult(units=(), metadata={"other": "value"})
            if mode == "raise":
                raise RuntimeError("sorter failed")
            if mode == "ok" or mode == "non_deterministic":
                return _build_sorting_result(list(payload.get("output_fields") or ("units", "metadata.sorter")))
            return SortingResult(units=(), metadata={})

    registry = SpikeSorterRegistry()
    try:
        sorter = Sorter()
        registry.register(sorter)
        summary: dict[str, Any] = {"register": {"ok": True, "name": sorter.name}}
    except Exception as exc:
        return {"register": {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}}

    try:
        run_result = registry.run(sorter.name, recording)
        summary["run"] = {
            "ok": True,
            "has_output": isinstance(run_result.result, SortingResult),
            "n_units": len(run_result.result.units),
        }
    except Exception as exc:
        summary["run"] = {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}

    return summary


def _make_recording(payload: dict[str, Any]) -> MEARecording | dict[str, Any]:
    mode = payload.get("recording_mode", "valid")
    if mode == "mapping_invalid":
        return {"channels": [], "sampling_rate_hz": -10.0, "traces": ()}
    if mode == "non_numeric_rate":
        return {"channels": ("A",), "sampling_rate_hz": "nan", "traces": [[1, 2, 3]]}
    if mode == "mismatched":
        return MEARecording(channels=("A", "B"), sampling_rate_hz=1_000.0, traces=((1, 2), (3, 4, 5)))
    if mode == "empty":
        return MEARecording(channels=("A",), sampling_rate_hz=1_000.0, traces=((),))

    return MEARecording(
        channels=("MEA-1", "MEA-2"),
        sampling_rate_hz=1_000.0,
        traces=(
            (0.0, 0.1, 0.2, 0.3),
            (0.0, -0.1, 0.2, 0.0),
        ),
        metadata={"fixture": "fuzzer"},
    )


def _build_sorting_result(output_fields: list[str]) -> SortingResult:
    metadata: dict[str, Any] = {}
    for field in output_fields:
        if field == "units":
            continue
        if field.startswith("metadata."):
            key = field.split(".", maxsplit=1)[1]
            metadata[key] = 1
        elif field.startswith("metadata_"):
            metadata[field] = 1

    units = (
        (
            SortedUnit(
                unit_id="unit-1",
                channel="MEA-1",
                spike_sample_indexes=(1,),
                spike_times_sec=(0.001,),
            ),
        )
        if "units" in output_fields
        else ()
    )
    return SortingResult(units=units, metadata=metadata)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fuzz-case oracle")
    parser.add_argument("--target", required=True, choices=["mea", "run-engine", "backend-jobs", "sorter-seam"])
    parser.add_argument("--case", required=True, help="JSON case payload")
    args = parser.parse_args()

    try:
        payload = _safe_case_payload(json.loads(args.case))
        result = _run_json_target(args.target, payload)
        payload["input_target"] = args.target
        print(json.dumps(_coerce_jsonable({"ok": True, "target": args.target, "result": result}), sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "target": args.target,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback": traceback.format_exc(),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
