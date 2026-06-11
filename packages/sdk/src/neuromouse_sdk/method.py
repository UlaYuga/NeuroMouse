from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from neuromouse_contract import Dataset

ParamsT = TypeVar("ParamsT")


@dataclass(frozen=True)
class OutputField:
    path: str
    description: str = ""
    unit: str | None = None


@dataclass(frozen=True)
class PanelSpec:
    id: str
    title: str
    kind: str
    field: str


@dataclass(frozen=True)
class OutputSpec:
    fields: tuple[OutputField, ...]
    panel: PanelSpec | None = None


class Method(Protocol[ParamsT]):
    name: str
    version: str
    params_type: type[ParamsT]
    required_inputs: tuple[str, ...]
    output: OutputSpec

    def compute(self, dataset: Dataset, params: ParamsT) -> Mapping[str, Any]:
        ...


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
        if callable(model_validate):
            return model_validate(dict(params))
        return params_type(**params)  # ty: ignore[invalid-argument-type]  # Mapping[str,Any] guaranteed by function sig + isinstance guard
    raise TypeError(f"Expected {params_type.__name__} or mapping params")
