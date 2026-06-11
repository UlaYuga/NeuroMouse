import fc from "fast-check";
import { runPythonTarget } from "./fuzz-runner.mjs";

const seed = Number(process.env.FUZZ_SEED ?? 0x51eed);
const baseCases = Number(process.env.FUZZ_BASE_CASES ?? 64);
const maxCases = Number(process.env.FUZZ_MAX_CASES ?? 512);
const dryTarget = Number(process.env.FUZZ_DRY_ROUNDS ?? 2);

const suffixArb = fc.constantFrom("csv", "txt", "h5", "hdf5", "brw");
const tokenArb = fc.string({ minLength: 0, maxLength: 12 });
const headerArb = fc.array(tokenArb, { minLength: 0, maxLength: 8 });
const rowArb = fc.array(tokenArb, { minLength: 0, maxLength: 8 });
const rowsArb = fc.array(rowArb, { minLength: 0, maxLength: 32 });

const cases = fc.record({
  suffix: suffixArb,
  header: headerArb,
  rows: rowsArb,
});

const summary = new Map();

let totalCases = 0;
let runs = 0;
let dryRuns = 0;
let casesPerRun = baseCases;

while (dryRuns < dryTarget && runs < 8) {
  const before = summary.size;
  const samples = fc.sample(cases, {
    numRuns: casesPerRun,
    seed: seed + runs,
  });

  for (const sample of samples) {
    totalCases += 1;
    const result = runPythonTarget("mea", sample);
    if (!result.ok) {
      record(`python-${result.transport}`, sample, result);
      continue;
    }

    if (!result.payload?.ok || !result.payload.result) {
      record("oracle-unexpected", sample, result);
      continue;
    }

    const outcome = result.payload.result.outcome;
    if (outcome === "ok") {
      if (result.payload.result.channels <= 0 || result.payload.result.declared_channels <= 0) {
        record("mea-valid-missing-channels", sample, result.payload.result);
      }
      continue;
    }

    if (outcome === "validation_failed") {
      if (result.payload.result.error_type !== "DatasetValidationError") {
        record(`mea-validation-${result.payload.result.error_type}`, sample, result.payload.result);
      }
      continue;
    }

    if (outcome === "read_failed") {
      if (!cleanReadFailure(result.payload.result.error_type)) {
        record(`mea-read-${result.payload.result.error_type}`, sample, result.payload.result);
      }
      continue;
    }

    record(`mea-unexpected-${outcome}`, sample, result.payload.result);
  }

  if (summary.size === before) {
    dryRuns += 1;
  } else {
    dryRuns = 0;
  }
  casesPerRun = Math.min(maxCases, casesPerRun * 2);
  runs += 1;
}

console.log(
  `[fuzz] target=mea-adapter seed=${seed} runs=${runs} baseCases=${baseCases} maxCases=${maxCases} total=${totalCases} dry=${dryRuns}/${dryTarget}`,
);
if (summary.size > 0) {
  console.error("MEA adapter fuzz findings:");
  for (const [key, value] of summary.entries()) {
    console.error(` - ${key}: ${value}`);
  }
  process.exitCode = 1;
}

function record(className, sample, detail) {
  if (!summary.has(className)) {
    summary.set(className, 0);
    console.error(`[fuzz:mea] first:${className} sample=${JSON.stringify(sample)} detail=${JSON.stringify(detail)}`);
  }
  summary.set(className, summary.get(className) + 1);
}

function cleanReadFailure(errorType) {
  return (
    errorType === "ValueError" ||
    errorType === "DatasetValidationError" ||
    errorType === "FileNotFoundError" ||
    errorType === "TypeError" ||
    errorType === "UnicodeDecodeError" ||
    errorType === "OSError"
  );
}
