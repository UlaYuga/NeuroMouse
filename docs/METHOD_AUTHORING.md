# Method Authoring

NeuroMouse methods are small plugins that run against a validated
[`Dataset`](../contracts/src/neuromouse_contract/dataset.py). A method declares the contract
fields it consumes, the output fields it promises to return, and an optional panel hint for
rendering.

Use these two files first:

- full working example:
  [`band_power_summary.py`](../packages/sdk/src/neuromouse_sdk/examples/band_power_summary.py)
- starter template:
  [`method_template.py`](../packages/sdk/templates/method_template.py)

## Author Surface

The SDK method surface is intentionally small:

```python
class MyMethod:
    name = "my_method"
    params_type = MyMethodParams
    required_inputs = ("meta.channels", "welch_psd.frequencies", "welch_psd.psd")
    output = OutputSpec(...)

    def compute(self, dataset: Dataset, params: MyMethodParams) -> dict[str, Any]:
        ...
```

The current primitives live in
[`packages/sdk/src/neuromouse_sdk/method.py`](../packages/sdk/src/neuromouse_sdk/method.py):

- `OutputField(path, description="", unit=None)`
- `PanelSpec(id, title, kind, field)`
- `OutputSpec(fields, panel=None)`
- `Method` protocol
- `build_params()` for dataclass or Pydantic-style params

## Registry Contract

Methods run through
[`MethodRegistry`](../packages/core/src/neuromouse_core/method_registry.py), not by direct
viewer calls. The registry:

- validates the method declaration
- verifies every `required_inputs` field path exists on the dataset
- coerces params into `params_type`
- calls `compute()`
- verifies every declared `output.fields` path exists in the returned mapping
- verifies `output.panel.field` points at one declared output field

That means a method cannot silently depend on missing data and cannot return a shape the UI
has to guess.

## Minimal Workflow

1. Copy [`method_template.py`](../packages/sdk/templates/method_template.py).
2. Rename the class, `name`, and output root key.
3. Define params as a frozen dataclass or Pydantic-compatible type.
4. Declare the exact contract fields in `required_inputs`.
5. Declare every returned field in `OutputSpec`.
6. Add a panel only when the result has a clear table, chart, or summary surface.
7. Register and run through `neuromouse_core.method_registry.MethodRegistry`.
8. Add tests that cover declaration shape, params coercion, output fields, and at least one
   realistic dataset.

## Example Reference

[`band_power_summary`](../packages/sdk/src/neuromouse_sdk/examples/band_power_summary.py)
integrates PSD values across a frequency band. It demonstrates the expected shape:

- params: `BandPowerParams(min_hz=8.0, max_hz=13.0)`
- inputs: `meta.channels`, `welch_psd.frequencies`, `welch_psd.psd`
- outputs: band metadata, per-channel rows, mean power, and top channel
- panel: table over `band_power_summary.channels`

The tests in
[`packages/sdk/tests/test_method_author_api.py`](../packages/sdk/tests/test_method_author_api.py)
and
[`packages/core/tests/test_method_registry.py`](../packages/core/tests/test_method_registry.py)
are the best executable examples of the authoring contract.

## Review Checklist

- Does the method read only declared input paths?
- Does `compute()` return every declared output field?
- Does the output root key match the method name or a clear method namespace?
- Are params typed and deterministic?
- Does the method fail with a clear `ValueError` for invalid scientific settings?
- Is provenance or unit information included when the output would otherwise be ambiguous?
