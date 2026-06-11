import fc from "fast-check";
import { runPythonTarget } from "./fuzz-runner.mjs";

const seed = Number(process.env.FUZZ_SEED ?? 0x7a11);
const baseCases = Number(process.env.FUZZ_BASE_CASES ?? 64);
const maxCases = Number(process.env.FUZZ_MAX_CASES ?? 512);
const dryTarget = Number(process.env.FUZZ_DRY_ROUNDS ?? 2);

const findings = new Map();
const validMethods = fc.constantFrom("band_power_summary", "missing_method", "");
const storeArb = fc.constantFrom("memory", "sqlite");
const datasetModeArb = fc.constantFrom("valid", "invalid_dataset", "bad_channels", "missing_dataset");
const jobModeArb = fc.constantFrom("valid", "missing_session", "skip");
const sessionNameArb = fc.string({ minLength: 0, maxLength: 12 });
const paramsArb = fc.oneof(
  fc.constant({}),
  fc.dictionary(fc.string({ minLength: 1, maxLength: 8 }), fc.double({ min: -1, max: 20 })),
  fc.integer({ min: -2, max: 10 }),
  fc.string({ min: 0, max: 10 }),
  fc.array(fc.integer({ min: -5, max: 5 }), { minLength: 1, maxLength: 3 }),
  fc.boolean(),
  fc.integer({ min: 0, max: 10 }),
);

const caseArb = fc.record({
  store: storeArb,
  session_name: sessionNameArb,
  dataset_mode: datasetModeArb,
  job_mode: jobModeArb,
  method_id: validMethods,
  job_session: fc.constantFrom("created", "missing"),
  job_params: paramsArb,
});

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
    const result = runPythonTarget("backend-jobs", sample);
    if (!result.ok) {
      record(`backend-transport-${result.transport ?? "error"}`, sample, result);
      continue;
    }

    const payload = result.payload?.result;
    if (!payload) {
      record("backend-no-result", sample, result.payload);
      continue;
    }

    checkResponse("session", payload.session);
    checkResponse("job", payload.job);
    checkResponse("get_job", payload.get_job);
    checkResponse("get_session", payload.get_session);
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
  `[fuzz] target=backend-jobs seed=${seed} runs=${runs} baseCases=${baseCases} maxCases=${maxCases} total=${totalCases} dry=${dryRuns}/${dryTarget}`,
);
if (findings.size > 0) {
  console.error("backend-jobs fuzz findings:");
  for (const [key, value] of findings.entries()) {
    console.error(` - ${key}: ${value}`);
  }
  process.exitCode = 1;
}

function checkResponse(label, response) {
  if (!response || typeof response !== "object") {
    return;
  }

  if (!Number.isInteger(response.status) || response.status < 100 || response.status >= 600) {
    record(`${label}-status-invalid`, response, response);
    return;
  }

  if (response.status === 404) {
    return;
  }
  if (response.status >= 500) {
    record(`${label}-5xx`, response, response);
  }

    if (response.status === 201) {
      if (!response.json || typeof response.json.id !== "string") {
        record(`${label}-id-missing`, response, response);
      }
    }
}

function record(className, sample, detail) {
  if (!findings.has(className)) {
    findings.set(className, 0);
    console.error(`[fuzz:backend] first:${className} sample=${JSON.stringify(sample)} detail=${JSON.stringify(detail)}`);
  }
  findings.set(className, findings.get(className) + 1);
}
