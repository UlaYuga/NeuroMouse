import test from "node:test";
import { cleanError, compactError, runFuzzUntilDry } from "./fuzz-harness.mjs";
import fc from "fast-check";
import { runPythonTarget } from "./python-fuzz-runner.mjs";

const suffixArb = fc.constantFrom("csv", "txt", "h5", "hdf5", "brw");
const tokenArb = fc.string({ minLength: 0, maxLength: 12 });
const headerArb = fc.array(tokenArb, { minLength: 0, maxLength: 8 });
const rowArb = fc.array(tokenArb, { minLength: 0, maxLength: 8 });
const rowsArb = fc.array(rowArb, { minLength: 0, maxLength: 16 });

test("property: MEA parser accepts valid outputs and rejects malformed payloads cleanly", async () => {
  await runFuzzUntilDry({
    name: "mea.read_mea",
    baseCases: Number(process.env.PROPERTY_BASE_CASES ?? 64),
    maxCases: Number(process.env.PROPERTY_MAX_CASES ?? 512),
    dryRuns: Number(process.env.PROPERTY_DRY_RUNS ?? 2),
    seed: Number(process.env.PROPERTY_SEED ?? 0x51eed),
    arbitrary: fc.record({
      suffix: suffixArb,
      header: headerArb,
      rows: rowsArb,
    }),
    async check(sample, findings) {
      const result = runPythonTarget("mea", sample);
      if (!result.ok) {
        findings.add(`python-transport:${result.transport ?? "error"}`, {
          payload: sample,
          detail: result.stderr,
        });
        return;
      }

  const resultPayload = result.payload?.result;
  const cleanReadFailures = new Set([
    "ValueError",
    "FileNotFoundError",
    "TypeError",
    "UnicodeDecodeError",
    "OSError",
    "DatasetValidationError",
  ]);

  if (!resultPayload) {
    findings.add("oracle-no-result", sample);
    return;
  }

      if (resultPayload.outcome === "ok") {
        if (resultPayload.channels <= 0 || resultPayload.declared_channels <= 0) {
          findings.add("read-mea-empty-valid-looking", {
            payload: sample,
            detail: resultPayload,
          });
        }
        return;
      }

      if (resultPayload.outcome === "validation_failed" && resultPayload.error_type !== "DatasetValidationError") {
        findings.add(`validation-${resultPayload.error_type}`, {
          payload: sample,
          detail: compactError(new Error(resultPayload.error_message)),
        });
        return;
      }

      if (resultPayload.outcome === "read_failed" && !cleanReadFailures.has(resultPayload.error_type)) {
        findings.add(`read-failed-${resultPayload.error_type}`, {
          payload: sample,
          error: compactError(new Error(resultPayload.error_message)),
        });
      }
    },
  });
});
