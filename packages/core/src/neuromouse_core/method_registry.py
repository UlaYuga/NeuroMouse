from __future__ import annotations

import copy
import hashlib
import json
import platform as platform_module
import random
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from importlib import metadata
from typing import Any

import numpy as np
import scipy

from neuromouse_contract import Dataset, validate_dataset
from neuromouse_sdk import Method, OutputField, OutputSpec, PanelSpec, build_params


class MethodRegistryError(ValueError):
    """Base error for method registry failures."""


class MethodDeclarationError(MethodRegistryError):
    """Raised when a method declaration is incomplete or malformed."""


class MethodLookupError(MethodRegistryError):
    """Raised when a registered method cannot be found."""


class MethodExecutionError(MethodRegistryError):
    """Raised when declared inputs or outputs do not match runtime data."""


class ReproductionVerificationError(MethodRegistryError):
    """Raised when a run manifest cannot be reproduced against an input dataset."""


RUN_MANIFEST_SCHEMA_VERSION = "neuromouse.run-manifest.v1"
DEFAULT_DATASET_VERSION = "unversioned"


@dataclass(frozen=True)
class MethodRun:
    method_name: str
    output_spec: OutputSpec
    result: Mapping[str, Any]


@dataclass(frozen=True)
class RunProvenance:
    method_name: str
    method_version: str
    params: Mapping[str, Any]
    input_hash: str
    input_version: str | int
    input_lineage: tuple[str, ...]
    seed: int
    versions: Mapping[str, str]


@dataclass(frozen=True)
class RunManifest:
    schema_version: str
    run_id: str
    dataset: Mapping[str, Any]
    method: Mapping[str, Any]
    seed: int
    library_versions: Mapping[str, str]
    platform: Mapping[str, str]
    output_hash: str

    @classmethod
    def from_components(
        cls,
        *,
        dataset_content_hash: str,
        dataset_version: str | int,
        dataset_lineage: Sequence[str] | None,
        method_id: str,
        method_version: str,
        params: Mapping[str, Any] | Any,
        seed: int,
        library_versions: Mapping[str, str],
        platform: Mapping[str, str],
        output_hash: str,
    ) -> RunManifest:
        payload = _manifest_payload(
            dataset_content_hash=dataset_content_hash,
            dataset_version=dataset_version,
            dataset_lineage=dataset_lineage,
            method_id=method_id,
            method_version=method_version,
            params=params,
            seed=seed,
            library_versions=library_versions,
            platform=platform,
            output_hash=output_hash,
        )
        return cls(run_id=_manifest_run_id(payload), **payload)

    @classmethod
    def from_jsonable(cls, payload: Mapping[str, Any]) -> RunManifest:
        if not isinstance(payload, Mapping):
            raise MethodExecutionError("run manifest must be a mapping")
        if payload.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
            raise MethodExecutionError("unsupported run manifest schema_version")
        dataset = _required_mapping(payload, "dataset")
        method = _required_mapping(payload, "method")
        manifest = cls.from_components(
            dataset_content_hash=_required_str(dataset, "content_hash"),
            dataset_version=dataset.get("version", DEFAULT_DATASET_VERSION),
            dataset_lineage=dataset.get("lineage", ()),
            method_id=_required_str(method, "id"),
            method_version=_required_str(method, "version"),
            params=method.get("params", {}),
            seed=_required_int(payload, "seed"),
            library_versions=_required_mapping(payload, "library_versions"),
            platform=_required_mapping(payload, "platform"),
            output_hash=_required_str(payload, "output_hash"),
        )
        supplied_run_id = _required_str(payload, "run_id")
        if supplied_run_id != manifest.run_id:
            raise MethodExecutionError("run manifest run_id does not match its contents")
        return manifest

    def to_jsonable(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "dataset": self.dataset,
                "method": self.method,
                "seed": self.seed,
                "library_versions": self.library_versions,
                "platform": self.platform,
                "output_hash": self.output_hash,
            }
        )


@dataclass(frozen=True)
class RunResult:
    output: Mapping[str, Any]
    provenance: RunProvenance
    manifest: RunManifest


@dataclass(frozen=True)
class RunCacheKey:
    method_name: str
    method_version: str
    params_hash: str
    input_hash: str
    input_version: str | int
    input_lineage: tuple[str, ...]
    seed: int


class MethodRegistry:
    def __init__(self) -> None:
        self._methods: dict[str, Method[Any]] = {}
        self._run_cache: dict[RunCacheKey, RunResult] = {}

    def register(self, method: Method[Any]) -> Method[Any]:
        name = _validate_method(method)
        if name in self._methods:
            raise MethodDeclarationError(f"method already registered: {name}")
        self._methods[name] = method
        return method

    def lookup(self, name: str) -> Method[Any]:
        key = _normalize_name(name)
        try:
            return self._methods[key]
        except KeyError as exc:
            raise MethodLookupError(f"unknown method: {name}") from exc

    def run(
        self,
        name: str,
        dataset: Dataset | Mapping[str, Any],
        params: Mapping[str, Any] | Any | None = None,
    ) -> MethodRun:
        method = self.lookup(name)
        dataset_model = _dataset_model(dataset)
        typed_params = build_params(method.params_type, params)
        result = self._execute(method, dataset_model, typed_params)
        return MethodRun(
            method_name=_normalize_name(method.name),
            output_spec=method.output,
            result=result,
        )

    def run_result(
        self,
        dataset: Dataset | Mapping[str, Any],
        name: str,
        params: Mapping[str, Any] | Any | None = None,
        *,
        seed: int,
        dataset_version: str | int = DEFAULT_DATASET_VERSION,
        dataset_lineage: Sequence[str] | None = None,
        use_cache: bool = True,
    ) -> RunResult:
        method = self.lookup(name)
        dataset_model = _dataset_model(dataset)
        typed_params = build_params(method.params_type, params)
        method_name = _normalize_name(method.name)
        method_version = _method_version(method)
        params_payload = _jsonable(typed_params)
        input_hash = content_hash(dataset_model)
        input_version = _normalize_dataset_version(dataset_version)
        input_lineage = _normalize_dataset_lineage(dataset_lineage)
        cache_key = RunCacheKey(
            method_name=method_name,
            method_version=method_version,
            params_hash=_hash_jsonable(params_payload),
            input_hash=input_hash,
            input_version=input_version,
            input_lineage=input_lineage,
            seed=_validate_seed(seed),
        )
        if use_cache and cache_key in self._run_cache:
            return copy.deepcopy(self._run_cache[cache_key])

        with _seeded(cache_key.seed):
            output = _jsonable(self._execute(method, dataset_model, typed_params))
        versions = _runtime_versions()
        platform = _runtime_platform()
        output_hash = _hash_jsonable(output)
        manifest = RunManifest.from_components(
            dataset_content_hash=input_hash,
            dataset_version=input_version,
            dataset_lineage=input_lineage,
            method_id=method_name,
            method_version=method_version,
            params=params_payload,
            seed=cache_key.seed,
            library_versions=versions,
            platform=platform,
            output_hash=output_hash,
        )
        result = RunResult(
            output=output,
            provenance=RunProvenance(
                method_name=method_name,
                method_version=method_version,
                params=params_payload,
                input_hash=input_hash,
                input_version=input_version,
                input_lineage=input_lineage,
                seed=cache_key.seed,
                versions=versions,
            ),
            manifest=manifest,
        )
        if use_cache:
            self._run_cache[cache_key] = copy.deepcopy(result)
        return copy.deepcopy(result)

    def verify_reproduction(
        self,
        manifest: RunManifest | Mapping[str, Any],
        dataset: Dataset | Mapping[str, Any],
    ) -> RunResult:
        manifest_model = _manifest_model(manifest)
        dataset_hash = content_hash(dataset)
        manifest_hash = manifest_model.dataset["content_hash"]
        if dataset_hash != manifest_hash:
            raise ReproductionVerificationError(
                f"input hash mismatch: expected {manifest_hash}, got {dataset_hash}"
            )

        result = self.run_result(
            dataset,
            manifest_model.method["id"],
            manifest_model.method["params"],
            seed=manifest_model.seed,
            dataset_version=manifest_model.dataset["version"],
            dataset_lineage=manifest_model.dataset["lineage"],
            use_cache=False,
        )
        if result.manifest.output_hash != manifest_model.output_hash:
            raise ReproductionVerificationError(
                "output hash mismatch: "
                f"expected {manifest_model.output_hash}, got {result.manifest.output_hash}"
            )
        if result.manifest.run_id != manifest_model.run_id:
            raise ReproductionVerificationError(
                f"run-id mismatch: expected {manifest_model.run_id}, got {result.manifest.run_id}"
            )
        return result

    def _execute(
        self,
        method: Method[Any],
        dataset_model: Dataset,
        typed_params: Any,
    ) -> Mapping[str, Any]:
        for path in method.required_inputs:
            if not has_field_path(dataset_model, path):
                raise MethodExecutionError(
                    f"method {method.name!r} requires missing input field {path!r}"
                )

        try:
            result = method.compute(dataset_model, typed_params)
        except MethodRegistryError:
            raise
        except Exception as exc:
            raise MethodExecutionError(f"method {method.name!r} failed: {exc}") from exc

        if not isinstance(result, Mapping):
            raise MethodExecutionError(f"method {method.name!r} returned a non-mapping result")
        for field in method.output.fields:
            if not has_field_path(result, field.path):
                raise MethodExecutionError(
                    f"method {method.name!r} did not produce declared output field {field.path!r}"
                )
        return result


_default_registry = MethodRegistry()


def register(method: Method[Any]) -> Method[Any]:
    return _default_registry.register(method)


def lookup(name: str) -> Method[Any]:
    return _default_registry.lookup(name)


def run_method(
    name: str,
    dataset: Dataset | Mapping[str, Any],
    params: Mapping[str, Any] | Any | None = None,
) -> MethodRun:
    return _default_registry.run(name, dataset, params=params)


def run(
    dataset: Dataset | Mapping[str, Any],
    method_name: str,
    params: Mapping[str, Any] | Any | None = None,
    *,
    seed: int,
    dataset_version: str | int = DEFAULT_DATASET_VERSION,
    dataset_lineage: Sequence[str] | None = None,
) -> RunResult:
    return _default_registry.run_result(
        dataset,
        method_name,
        params=params,
        seed=seed,
        dataset_version=dataset_version,
        dataset_lineage=dataset_lineage,
    )


def verify_reproduction(
    manifest: RunManifest | Mapping[str, Any],
    dataset: Dataset | Mapping[str, Any],
) -> RunResult:
    return _default_registry.verify_reproduction(manifest, dataset)


def content_hash(dataset: Dataset | Mapping[str, Any]) -> str:
    return _hash_jsonable(_dataset_model(dataset).model_dump(mode="json"))


def output_hash(output: Mapping[str, Any]) -> str:
    return _hash_jsonable(_jsonable(output))


def has_field_path(value: Any, path: str) -> bool:
    if not _is_well_formed_path(path):
        return False
    marker = object()
    return _get_field_path(value, path, marker) is not marker


def _validate_method(method: Method[Any]) -> str:
    name = _normalize_name(getattr(method, "name", None))
    required_inputs = getattr(method, "required_inputs", None)
    if isinstance(required_inputs, str) or not isinstance(required_inputs, tuple):
        raise MethodDeclarationError("method.required_inputs must be a tuple of field paths")
    for path in required_inputs:
        _validate_path(path, "method.required_inputs")

    params_type = getattr(method, "params_type", None)
    if not isinstance(params_type, type):
        raise MethodDeclarationError("method.params_type must be a type")

    output = getattr(method, "output", None)
    if not isinstance(output, OutputSpec):
        raise MethodDeclarationError("method.output must be an OutputSpec")
    if not output.fields:
        raise MethodDeclarationError("method.output.fields must declare at least one field")
    for field in output.fields:
        if not isinstance(field, OutputField):
            raise MethodDeclarationError("method.output.fields must contain OutputField values")
        _validate_path(field.path, "method.output.fields")
    _validate_panel(output.panel, output.fields)
    if not callable(getattr(method, "compute", None)):
        raise MethodDeclarationError("method.compute must be callable")
    return name


def _validate_panel(panel: PanelSpec | None, fields: tuple[OutputField, ...]) -> None:
    if panel is None:
        return
    if not isinstance(panel, PanelSpec):
        raise MethodDeclarationError("method.output.panel must be a PanelSpec or None")
    for attr in ("id", "title", "kind"):
        if not isinstance(getattr(panel, attr), str) or not getattr(panel, attr).strip():
            raise MethodDeclarationError(f"method.output.panel.{attr} must be a non-empty string")
    _validate_path(panel.field, "method.output.panel.field")
    field_paths = {field.path for field in fields}
    if panel.field not in field_paths:
        raise MethodDeclarationError(
            "method.output.panel.field must reference a declared output field"
        )


def _normalize_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise MethodDeclarationError("method.name must be a non-empty string")
    return name.strip()


def _validate_path(path: Any, owner: str) -> None:
    if not isinstance(path, str) or not _is_well_formed_path(path):
        raise MethodDeclarationError(f"{owner} contains malformed field path {path!r}")


def _is_well_formed_path(path: str) -> bool:
    parts = path.split(".")
    return bool(path) and all(parts) and parts == [part.strip() for part in parts]


def _get_field_path(value: Any, path: str, missing: object) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return missing
            current = current[part]
        else:
            if not hasattr(current, part):
                return missing
            current = getattr(current, part)
        if current is None:
            return missing
    return current


def _dataset_model(dataset: Dataset | Mapping[str, Any]) -> Dataset:
    return dataset if isinstance(dataset, Dataset) else validate_dataset(dataset)


def _method_version(method: Method[Any]) -> str:
    version = getattr(method, "version", "0.0.0")
    if not isinstance(version, str) or not version.strip():
        raise MethodDeclarationError("method.version must be a non-empty string")
    return version.strip()


def _validate_seed(seed: int) -> int:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise MethodExecutionError("seed must be an integer")
    if seed < 0 or seed >= 2**32:
        raise MethodExecutionError("seed must be between 0 and 2**32 - 1")
    return seed


def _manifest_model(manifest: RunManifest | Mapping[str, Any]) -> RunManifest:
    return manifest if isinstance(manifest, RunManifest) else RunManifest.from_jsonable(manifest)


def _manifest_payload(
    *,
    dataset_content_hash: str,
    dataset_version: str | int,
    dataset_lineage: Sequence[str] | None,
    method_id: str,
    method_version: str,
    params: Mapping[str, Any] | Any,
    seed: int,
    library_versions: Mapping[str, str],
    platform: Mapping[str, str],
    output_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "dataset": {
            "content_hash": _validate_digest(dataset_content_hash, "dataset_content_hash"),
            "version": _normalize_dataset_version(dataset_version),
            "lineage": list(_normalize_dataset_lineage(dataset_lineage)),
        },
        "method": {
            "id": _normalize_name(method_id),
            "version": _normalize_non_empty_str(method_version, "method_version"),
            "params": _jsonable(params),
        },
        "seed": _validate_seed(seed),
        "library_versions": _normalize_str_mapping(library_versions, "library_versions"),
        "platform": _normalize_str_mapping(platform, "platform"),
        "output_hash": _validate_digest(output_hash, "output_hash"),
    }


def _manifest_run_id(payload: Mapping[str, Any]) -> str:
    return _hash_jsonable(payload)


def _normalize_dataset_version(version: str | int) -> str | int:
    if isinstance(version, bool):
        raise MethodExecutionError("dataset_version must be a string or integer")
    if isinstance(version, int):
        if version < 0:
            raise MethodExecutionError("dataset_version integer must be non-negative")
        return version
    if isinstance(version, str) and version.strip():
        return version.strip()
    raise MethodExecutionError("dataset_version must be a non-empty string or integer")


def _normalize_dataset_lineage(lineage: Sequence[str] | None) -> tuple[str, ...]:
    if lineage is None:
        return ()
    if isinstance(lineage, str) or not isinstance(lineage, Sequence):
        raise MethodExecutionError("dataset_lineage must be a sequence of strings")
    normalized: list[str] = []
    for entry in lineage:
        if not isinstance(entry, str) or not entry.strip():
            raise MethodExecutionError("dataset_lineage entries must be non-empty strings")
        normalized.append(entry.strip())
    return tuple(normalized)


def _normalize_str_mapping(value: Mapping[str, Any], owner: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise MethodExecutionError(f"{owner} must be a mapping")
    normalized: dict[str, str] = {}
    for key, child in value.items():
        if not isinstance(key, str) or not key.strip():
            raise MethodExecutionError(f"{owner} keys must be non-empty strings")
        if not isinstance(child, str) or not child.strip():
            raise MethodExecutionError(f"{owner} values must be non-empty strings")
        normalized[key.strip()] = child.strip()
    return normalized


def _validate_digest(value: Any, owner: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise MethodExecutionError(f"{owner} must be a 64-character SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise MethodExecutionError(f"{owner} must be a SHA-256 hex digest") from exc
    return value.lower()


def _normalize_non_empty_str(value: Any, owner: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MethodExecutionError(f"{owner} must be a non-empty string")
    return value.strip()


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise MethodExecutionError(f"run manifest {key} must be a mapping")
    return value


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MethodExecutionError(f"run manifest {key} must be a non-empty string")
    return value.strip()


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise MethodExecutionError(f"run manifest {key} must be an integer")
    return value


@contextmanager
def _seeded(seed: int) -> Any:
    numpy_state = np.random.get_state()
    random_state = random.getstate()
    try:
        np.random.seed(seed)
        random.seed(seed)
        yield
    finally:
        np.random.set_state(numpy_state)
        random.setstate(random_state)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(child) for child in value]
    return json.loads(_canonical_json(value).decode("utf-8"))


def _hash_jsonable(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MethodExecutionError(
            f"run output/provenance data must be JSON-serializable: {exc}"
        ) from exc


def _runtime_versions() -> dict[str, str]:
    return {
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "neuromouse_contract": _package_version("neuromouse-contract"),
        "neuromouse_core": _package_version("neuromouse-core"),
        "neuromouse_sdk": _package_version("neuromouse-sdk"),
    }


def _runtime_platform() -> dict[str, str]:
    return {
        "python": platform_module.python_version(),
        "python_implementation": platform_module.python_implementation(),
        "system": platform_module.system(),
        "release": platform_module.release(),
        "machine": platform_module.machine(),
        "platform": platform_module.platform(),
    }


def _package_version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "0.0.0"
