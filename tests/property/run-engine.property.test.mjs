import test from "node:test";

import { cleanError, compactError, runFuzzUntilDry } from "./fuzz-harness.mjs";
import fc from "fast-check";
import { runPythonTarget } from "./python-fuzz-runner.mjs";

const cleanClasses = new Set([
  "DatasetValidationError",
  "MethodDeclarationError",
  "MethodExecutionError",
  "MethodLookupError",
  "MethodRegistryError",
  "ReproductionVerificationError",
  "TypeError",
  "ValueError",
  "RuntimeError",
  "PydanticUndefinedTypeError",
]);

const nameArb = fc.string({ minLength: 0, maxLength: 16 });
const outputFieldArb = fc.oneof(
  fc.constantFrom("analysis.value", "analysis.stats", "analysis.value:bad", "", "metadata", "meta.", ".meta"),
  fc.string({ minLength: 1, maxLength: 12 }),
);
const requiredInputsArb = fc.array(outputFieldArb, { minLength: 0, maxLength: 4 });
const outputFieldsArb = fc.array(outputFieldArb, { minLength: 0, maxLength: 4 });
const datasetModeArb = fc.constantFrom(
  "valid",
  "missing_meta",
  "bad_channel_count",
  "bad_channel_name",
  "missing_channels",
);
const computeModeArb = fc.constantFrom("ok", "non_mapping", "missing", "none", "bad_map", "raise", "invalid");
const paramsTypeArb = fc.constantFrom("valid", "invalid");

test("property: run-engine contract handles malformed method registrations and execution errors", async () => {
  await runFuzzUntilDry({
    name: "run-engine.fuzz.property",
    baseCases: Number(process.env.PROPERTY_BASE_CASES ?? 64),
    maxCases: Number(process.env.PROPERTY_MAX_CASES ?? 512),
    dryRuns: Number(process.env.PROPERTY_DRY_RUNS ?? 2),
    seed: Number(process.env.PROPERTY_SEED ?? 0x7f00d),
    arbitrary: fc.record({
      method_name: nameArb,
      method_version: fc.string({ minLength: 1, maxLength: 8 }),
      required_inputs: requiredInputsArb,
      output_fields: outputFieldsArb,
      compute_mode: computeModeArb,
      params_type: paramsTypeArb,
      dataset_mode: datasetModeArb,
      seed: fc.integer({ min: -5, max: 500 }),
      run: fc.boolean(),
      run_result: fc.boolean(),
      verify: fc.boolean(),
      tamper_manifest: fc.boolean(),
      use_cache: fc.boolean(),
      dataset_lineage: fc.array(fc.string({ minLength: 0, maxLength: 16 }), { minLength: 0, maxLength: 4 }),
      params: fc.oneof(
        fc.constant({}),
        fc.dictionary(fc.string({ minLength: 0, maxLength: 8 }), fc.integer({ min: 0, max: 3 })),
        fc.integer({ min: -5, max: 5 }),
        fc.string({ minLength: 0, maxLength: 16 }),
      ),
    }),
    async check(sample, findings) {
      const result = runPythonTarget("run-engine", sample);
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
        findings.add("run-engine-no-result", { payload: sample });
        return;
      }

      if (payload.register && payload.register.ok === false) {
        if (!cleanClasses.has(payload.register.error_type)) {
          findings.add(`run-engine-register-${payload.register.error_type}`, {
            payload: sample,
            detail: payload.register,
          });
        }
        return;
      }

      for (const key of ["run", "run_result", "verify"]) {
        const stage = payload[key];
        if (!stage) {
          continue;
        }
        if (stage.ok === true) {
          continue;
        }
        if (stage.error_type && !cleanClasses.has(stage.error_type)) {
          findings.add(`run-engine-${key}-${stage.error_type}`, {
            payload: sample,
            error: compactError(new Error(stage.error_message)),
          });
        }
      }
    },
  });
});
