from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class MethodRun:
    method_name: str
    output_spec: OutputSpec
    result: Mapping[str, Any]


class MethodRegistry:
    def __init__(self) -> None:
        self._methods: dict[str, Method[Any]] = {}

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
        dataset_model = dataset if isinstance(dataset, Dataset) else validate_dataset(dataset)
        for path in method.required_inputs:
            if not has_field_path(dataset_model, path):
                raise MethodExecutionError(
                    f"method {method.name!r} requires missing input field {path!r}"
                )

        try:
            typed_params = build_params(method.params_type, params)
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
        return MethodRun(
            method_name=_normalize_name(method.name),
            output_spec=method.output,
            result=result,
        )


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
