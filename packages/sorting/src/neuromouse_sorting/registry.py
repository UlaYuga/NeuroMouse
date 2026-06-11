from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, cast

from neuromouse_sorting.models import MEARecording, OutputField, SorterOutputSpec, SortingResult

ParamsT = TypeVar("ParamsT")


class SpikeSorter(Protocol[ParamsT]):
    name: str
    version: str
    params_type: type[ParamsT]
    output: SorterOutputSpec

    def sort(self, recording: MEARecording, params: ParamsT) -> SortingResult:
        ...


class SpikeSorterRegistryError(ValueError):
    """Base error for spike sorter registry failures."""


class SpikeSorterDeclarationError(SpikeSorterRegistryError):
    """Raised when a sorter declaration is incomplete or malformed."""


class SpikeSorterLookupError(SpikeSorterRegistryError):
    """Raised when a registered sorter cannot be found."""


class SpikeSorterExecutionError(SpikeSorterRegistryError):
    """Raised when a sorter input or output violates its declaration."""


@dataclass(frozen=True)
class SorterRun:
    sorter_name: str
    output_spec: SorterOutputSpec
    result: SortingResult


class SpikeSorterRegistry:
    def __init__(self) -> None:
        self._sorters: dict[str, SpikeSorter[Any]] = {}

    def register(self, sorter: SpikeSorter[Any]) -> SpikeSorter[Any]:
        name = _validate_sorter(sorter)
        if name in self._sorters:
            raise SpikeSorterDeclarationError(f"sorter already registered: {name}")
        self._sorters[name] = sorter
        return sorter

    def lookup(self, name: str) -> SpikeSorter[Any]:
        key = _normalize_name(name)
        try:
            return self._sorters[key]
        except KeyError as exc:
            raise SpikeSorterLookupError(f"unknown sorter: {name}") from exc

    def run(
        self,
        name: str,
        recording: MEARecording | Mapping[str, Any],
        params: Mapping[str, Any] | Any | None = None,
    ) -> SorterRun:
        sorter = self.lookup(name)
        recording_model = _recording_model(recording)
        typed_params = build_params(sorter.params_type, params)
        try:
            result = sorter.sort(recording_model, typed_params)
        except SpikeSorterRegistryError:
            raise
        except Exception as exc:
            raise SpikeSorterExecutionError(f"sorter {sorter.name!r} failed: {exc}") from exc

        if not isinstance(result, SortingResult):
            raise SpikeSorterExecutionError(f"sorter {sorter.name!r} returned a non-SortingResult")
        for field in sorter.output.fields:
            if not has_field_path(result, field.path):
                raise SpikeSorterExecutionError(
                    f"sorter {sorter.name!r} did not produce declared output field {field.path!r}"
                )

        return SorterRun(
            sorter_name=_normalize_name(sorter.name),
            output_spec=sorter.output,
            result=result,
        )


_default_registry = SpikeSorterRegistry()


def register(sorter: SpikeSorter[Any]) -> SpikeSorter[Any]:
    return _default_registry.register(sorter)


def lookup(name: str) -> SpikeSorter[Any]:
    return _default_registry.lookup(name)


def run(
    name: str,
    recording: MEARecording | Mapping[str, Any],
    params: Mapping[str, Any] | Any | None = None,
) -> SorterRun:
    return _default_registry.run(name, recording, params=params)


def build_params(params_type: type[ParamsT], params: ParamsT | Mapping[str, Any] | None) -> ParamsT:
    if params is None:
        return params_type()
    try:
        if isinstance(params, params_type):
            return params
    except TypeError:
        pass
    if isinstance(params, Mapping):
        model_validate = getattr(params_type, "model_validate", None)
        params_mapping = dict(cast(Mapping[str, Any], params))
        if callable(model_validate):
            return model_validate(params_mapping)
        return params_type(**params_mapping)
    raise SpikeSorterExecutionError(f"Expected {params_type.__name__} or mapping params")


def has_field_path(value: Any, path: str) -> bool:
    if not _is_well_formed_path(path):
        return False
    marker = object()
    return _get_field_path(value, path, marker) is not marker


def _validate_sorter(sorter: SpikeSorter[Any]) -> str:
    name = _normalize_name(getattr(sorter, "name", None))

    version = getattr(sorter, "version", None)
    if not isinstance(version, str) or not version.strip():
        raise SpikeSorterDeclarationError("sorter.version must be a non-empty string")

    params_type = getattr(sorter, "params_type", None)
    if not isinstance(params_type, type):
        raise SpikeSorterDeclarationError("sorter.params_type must be a type")

    output = getattr(sorter, "output", None)
    if not isinstance(output, SorterOutputSpec):
        raise SpikeSorterDeclarationError("sorter.output must be a SorterOutputSpec")
    if not output.fields:
        raise SpikeSorterDeclarationError("sorter.output.fields must declare at least one field")
    for field in output.fields:
        if not isinstance(field, OutputField):
            raise SpikeSorterDeclarationError(
                "sorter.output.fields must contain OutputField values"
            )
        _validate_path(field.path, "sorter.output.fields")

    if not callable(getattr(sorter, "sort", None)):
        raise SpikeSorterDeclarationError("sorter.sort must be callable")
    return name


def _recording_model(recording: MEARecording | Mapping[str, Any]) -> MEARecording:
    if isinstance(recording, MEARecording):
        return recording
    if isinstance(recording, Mapping):
        return MEARecording(**recording)
    raise SpikeSorterExecutionError("recording must be an MEARecording or mapping")


def _normalize_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise SpikeSorterDeclarationError("sorter.name must be a non-empty string")
    return name.strip()


def _validate_path(path: Any, owner: str) -> None:
    if not isinstance(path, str) or not _is_well_formed_path(path):
        raise SpikeSorterDeclarationError(f"{owner} contains malformed field path {path!r}")


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
