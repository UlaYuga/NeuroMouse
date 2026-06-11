import fc from "fast-check";
import { runPythonTarget } from "./fuzz-runner.mjs";

const seed = Number(process.env.FUZZ_SEED ?? 0x7f00d);
const baseCases = Number(process.env.FUZZ_BASE_CASES ?? 64);
const maxCases = Number(process.env.FUZZ_MAX_CASES ?? 512);
const dryTarget = Number(process.env.FUZZ_DRY_ROUNDS ?? 2);

const cleanClasses = new Set([
  "DatasetValidationError",
  "MethodDeclarationError",
  "MethodExecutionError",
  "MethodLookupError",
  "MethodRegistryError",
  "TypeError",
  "ValueError",
  "RuntimeError",
  "ReproductionVerificationError",
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

const caseArb = fc.record({
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
  params: fc.dictionary(fc.string({ minLength: 0, maxLength: 8 }), fc.integer({ min: 0, max: 3 })),
});

const findings = new Map();
let totalCases = 0;
let runs = 0;
let dryRuns = 0;
let casesPerRun = baseCases;

while (dryRuns < dryTarget && runs < 8) {
  const before = findings.size;
  const samples = fc.sample(caseArb, {
    numRuns: casesPerRun,
    seed: seed + runs,
  });

  for (const sample of samples) {
    totalCases += 1;
    const execution = runPythonTarget("run-engine", sample);
    if (!execution.ok) {
      if (execution.payload?.error_type && !cleanClasses.has(execution.payload.error_type)) {
        record(`python-${execution.payload.error_type}`, sample, execution);
      }
      continue;
    }
    const result = execution.payload.result;
    if (!result) {
      record("run-engine-no-result", sample, execution.payload);
      continue;
    }
    if (result.register && result.register.ok === false) {
      if (!cleanClasses.has(result.register.error_type)) {
        record(`run-engine-register-${result.register.error_type}`, sample, result.register);
      }
      continue;
    }

    for (const key of ["run", "run_result", "verify"]) {
      const stage = result[key];
      if (!stage) {
        continue;
      }
      if (stage.ok === true) {
        continue;
      }
      if (!cleanClasses.has(stage.error_type)) {
        record(`run-engine-${key}-${stage.error_type}`, sample, stage);
      }
    }
  }

  if (findings.size === before) {
    dryRuns += 1;
  } else {
    dryRuns = 0;
  }
  casesPerRun = Math.min(maxCases, casesPerRun * 2);
  runs += 1;
}

console.log(
  `[fuzz] target=run-engine seed=${seed} runs=${runs} baseCases=${baseCases} maxCases=${maxCases} total=${totalCases} dry=${dryRuns}/${dryTarget}`,
);
if (findings.size > 0) {
  console.error("run-engine fuzz findings:");
  for (const [key, value] of findings.entries()) {
    console.error(` - ${key}: ${value}`);
  }
  process.exitCode = 1;
}

function record(className, sample, detail) {
  if (!findings.has(className)) {
    findings.set(className, 0);
    console.error(`[fuzz:run-engine] first:${className} sample=${JSON.stringify(sample)} detail=${JSON.stringify(detail)}`);
  }
  findings.set(className, findings.get(className) + 1);
}
