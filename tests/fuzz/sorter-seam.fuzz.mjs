import fc from "fast-check";
import { runPythonTarget } from "./fuzz-runner.mjs";

const seed = Number(process.env.FUZZ_SEED ?? 0x73a);
const baseCases = Number(process.env.FUZZ_BASE_CASES ?? 64);
const maxCases = Number(process.env.FUZZ_MAX_CASES ?? 512);
const dryTarget = Number(process.env.FUZZ_DRY_ROUNDS ?? 2);

const cleanClasses = new Set([
  "SpikeSorterDeclarationError",
  "SpikeSorterExecutionError",
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
const adapterNameArb = fc.string({ minLength: 0, maxLength: 16 });

const caseArb = fc.record({
  action: actionArb,
  sorter_name: sorterNameArb,
  sorter_version: fc.string({ minLength: 1, maxLength: 8 }),
  params_type: paramsModeArb,
  output_fields: outputFieldsArb,
  sort_mode: sorterModeArb,
  recording_mode: recordingModeArb,
  spikeinterface_sorter_name: adapterNameArb,
  sorter_params: fc.record({ output: fc.integer({ min: 0, max: 5 }) }),
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
    const result = runPythonTarget("sorter-seam", sample);
    if (!result.ok) {
      record(`python-${result.transport ?? "error"}`, sample, result);
      continue;
    }
    const payload = result.payload?.result;
    if (!payload) {
      record("sorter-seam-no-result", sample, result.payload);
      continue;
    }

    if (!payload.register) {
      record("sorter-seam-no-register", sample, payload);
      continue;
    }

    if (!payload.register.ok) {
      if (!cleanClasses.has(payload.register.error_type)) {
        record(`sorter-register-${payload.register.error_type}`, sample, payload.register);
      }
      continue;
    }

    if (payload.run && !payload.run.ok && !cleanClasses.has(payload.run.error_type)) {
      record(`sorter-run-${payload.run.error_type}`, sample, payload.run);
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
  `[fuzz] target=sorter-seam seed=${seed} runs=${runs} baseCases=${baseCases} maxCases=${maxCases} total=${totalCases} dry=${dryRuns}/${dryTarget}`,
);
if (findings.size > 0) {
  console.error("sorter-seam fuzz findings:");
  for (const [key, value] of findings.entries()) {
    console.error(` - ${key}: ${value}`);
  }
  process.exitCode = 1;
}

function record(className, sample, detail) {
  if (!findings.has(className)) {
    findings.set(className, 0);
    console.error(`[fuzz:sorter] first:${className} sample=${JSON.stringify(sample)} detail=${JSON.stringify(detail)}`);
  }
  findings.set(className, findings.get(className) + 1);
}

