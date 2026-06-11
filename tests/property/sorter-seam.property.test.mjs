import test from "node:test";

import { compactError, runFuzzUntilDry } from "./fuzz-harness.mjs";
import fc from "fast-check";
import { runPythonTarget } from "./python-fuzz-runner.mjs";

const cleanClasses = new Set([
  "SpikeSorterDeclarationError",
  "SpikeSorterExecutionError",
  "SpikeSorterLookupError",
  "TypeError",
  "ValueError",
  "RuntimeError",
]);

const actionArb = fc.constantFrom("registry-run", "spikeinterface");
const pathArb = fc.oneof(
  fc.constantFrom("units", "metadata.sorter", "metadata.version", "metadata.n_units", "", "meta.", ".bad", "metadata."),
  fc.string({ minLength: 1, maxLength: 14 }),
);
const outputFieldsArb = fc.array(pathArb, { minLength: 0, maxLength: 4, unique: true });
const sorterModeArb = fc.constantFrom("ok", "wrong_type", "missing", "raise");
const paramsModeArb = fc.constantFrom("valid", "bad");
const sorterNameArb = fc.string({ minLength: 0, maxLength: 12 });
const recordingModeArb = fc.constantFrom("valid", "mismatched", "mapping_invalid", "non_numeric_rate", "empty");

test("property: sorter seam handles malformed seam inputs and adapter/runtime failures", async () => {
  await runFuzzUntilDry({
    name: "sorter-seam.fuzz.property",
    baseCases: Number(process.env.PROPERTY_BASE_CASES ?? 64),
    maxCases: Number(process.env.PROPERTY_MAX_CASES ?? 512),
    dryRuns: Number(process.env.PROPERTY_DRY_RUNS ?? 2),
    seed: Number(process.env.PROPERTY_SEED ?? 0x73a),
    arbitrary: fc.record({
      action: actionArb,
      sorter_name: sorterNameArb,
      sorter_version: fc.string({ minLength: 1, maxLength: 8 }),
      params_type: paramsModeArb,
      output_fields: outputFieldsArb,
      sort_mode: sorterModeArb,
      recording_mode: recordingModeArb,
      sorter_params: fc.oneof(
        fc.constant({ sorter_params: {} }),
        fc.constant({ sorter_params: { output: 1 } }),
        fc.string(),
        fc.integer({ min: -2, max: 5 }),
      ),
      spikeinterface_sorter_name: fc.string({ minLength: 0, maxLength: 16 }),
    }),
    async check(sample, findings) {
      const result = runPythonTarget("sorter-seam", sample);
      if (!result.ok) {
        if (result.payload?.error_type && !cleanClasses.has(result.payload.error_type)) {
          findings.add(`python-${result.payload.error_type}`, {
            payload: sample,
            detail: compactError(new Error(result.payload.error_message)),
          });
        }
        return;
      }

      const payload = result.payload?.result;
      if (!payload) {
        findings.add("sorter-seam-no-result", { payload: sample });
        return;
      }

      if (!payload.register) {
        findings.add("sorter-seam-no-register", {
          payload: sample,
          detail: payload,
        });
        return;
      }

      if (!payload.register.ok) {
        if (!cleanClasses.has(payload.register.error_type)) {
          findings.add(`sorter-register-${payload.register.error_type}`, {
            payload: sample,
            detail: payload.register,
          });
        }
        return;
      }

      if (payload.run && !payload.run.ok && payload.run.error_type && !cleanClasses.has(payload.run.error_type)) {
        findings.add(`sorter-run-${payload.run.error_type}`, {
          payload: sample,
          detail: payload.run,
        });
      }
    },
  });
});
