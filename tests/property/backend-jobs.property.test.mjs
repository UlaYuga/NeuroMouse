import test from "node:test";

import { runFuzzUntilDry } from "./fuzz-harness.mjs";
import fc from "fast-check";
import { runPythonTarget } from "./python-fuzz-runner.mjs";

test("property: backend session and job lifecycle rejects malformed input without crashing", async () => {
  await runFuzzUntilDry({
    name: "backend-jobs.fuzz.property",
    baseCases: Number(process.env.PROPERTY_BASE_CASES ?? 64),
    maxCases: Number(process.env.PROPERTY_MAX_CASES ?? 512),
    dryRuns: Number(process.env.PROPERTY_DRY_RUNS ?? 2),
    seed: Number(process.env.PROPERTY_SEED ?? 0x7a11),
    arbitrary: fc.record({
      store: fc.constantFrom("memory", "sqlite"),
      session_name: fc.string({ minLength: 0, maxLength: 12 }),
      dataset_mode: fc.constantFrom("valid", "invalid_dataset", "bad_channels", "missing_dataset"),
      job_mode: fc.constantFrom("valid", "missing_session", "skip"),
      method_id: fc.oneof(
        fc.constant("band_power_summary"),
        fc.string({ minLength: 0, maxLength: 16 }),
      ),
      job_session: fc.constantFrom("created", "missing"),
      job_params: fc.oneof(
        fc.constant({}),
        fc.dictionary(fc.string({ minLength: 0, maxLength: 6 }), fc.integer({ min: -5, max: 5 })),
        fc.integer({ min: 0, max: 10 }),
        fc.string({ minLength: 0, maxLength: 10 }),
        fc.boolean(),
        fc.array(fc.integer({ min: -3, max: 3 })),
      ),
    }),
    async check(sample, findings) {
      const result = runPythonTarget("backend-jobs", sample);
      if (!result.ok) {
        findings.add(`backend-transport-${result.transport}`, {
          payload: sample,
          error: result.stderr ?? result.errorType,
        });
        return;
      }

      const payload = result.payload?.result;
      if (!payload) {
        findings.add("backend-no-result", { payload: sample });
        return;
      }

      checkResponse("session", payload.session, findings, sample);
      checkResponse("job", payload.job, findings, sample);
      checkResponse("get_job", payload.get_job, findings, sample);
      checkResponse("get_session", payload.get_session, findings, sample);
    },
  });
});

function checkResponse(label, response, findings, payload) {
  if (!response || typeof response !== "object") {
    return;
  }

  const status = response.status;
  if (!Number.isInteger(status) || status < 100 || status >= 600) {
    findings.add(`${label}-status-invalid`, {
      payload,
      status,
      detail: response,
    });
    return;
  }

  if (status === 404) {
    return;
  }

  if (status >= 500) {
    findings.add(`${label}-5xx`, {
      payload,
      status,
      detail: response,
    });
  }

  if (status === 201 && (!response.json || typeof response.json.id !== "string")) {
    findings.add(`${label}-id-missing`, {
      payload,
      status,
      detail: response,
    });
  }
}
