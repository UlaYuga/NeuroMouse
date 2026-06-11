import test from "node:test";

import { loadDatasetFiles, loadZip } from "../../js/loader.js";
import { validateData } from "../../js/sources/static-source.js";
import { cleanError, compactError, runFuzzUntilDry } from "./fuzz-harness.mjs";
import {
  installJSZipGlobal,
  makeMalformedZipFiles,
  makeValidZipFiles,
  malformedZipArb,
  validZipArb,
} from "./zip-fixtures.mjs";
import { shapeRepro } from "./data-fixtures.mjs";

installJSZipGlobal();

test("property: valid CSV ZIP imports convert to canonical datasets", async () => {
  await runFuzzUntilDry({
    name: "loader.valid-csv-zip",
    arbitrary: validZipArb,
    async check(sample, findings) {
      const files = await makeValidZipFiles(sample);

      let result;
      try {
        result = await loadDatasetFiles(files);
      } catch (error) {
        findings.add("valid-import-uncaught-throw", {
          mode: sample.mode,
          shape: shapeRepro(sample.shape),
          error: compactError(error),
        });
        return;
      }

      if (result.errors.length > 0 || result.datasets.length !== 1) {
        findings.add("valid-import-rejected", {
          mode: sample.mode,
          shape: shapeRepro(sample.shape),
          datasetCount: result.datasets.length,
          errors: result.errors,
        });
        return;
      }

      try {
        validateData(result.datasets[0].data);
      } catch (error) {
        findings.add("valid-import-produced-invalid-data", {
          mode: sample.mode,
          shape: shapeRepro(sample.shape),
          error: compactError(error),
        });
      }

      if (sample.mode === "combined") {
        try {
          const direct = await loadZip(files[0]);
          validateData(direct);
        } catch (error) {
          findings.add("valid-loadZip-combined-rejected", {
            shape: shapeRepro(sample.shape),
            error: compactError(error),
          });
        }
      }
    },
  });
});

test("property: malformed CSV ZIP imports are rejected without escaping loader errors", async () => {
  await runFuzzUntilDry({
    name: "loader.malformed-csv-zip",
    arbitrary: malformedZipArb,
    async check(sample, findings) {
      const { files, repro } = await makeMalformedZipFiles(sample);

      let result;
      try {
        result = await loadDatasetFiles(files);
      } catch (error) {
        findings.add(`import-uncaught-throw:${sample.mutation}:${error?.name ?? typeof error}`, {
          repro,
          error: compactError(error),
        });
        return;
      }

      if (result.datasets.length > 0 || result.errors.length === 0) {
        findings.add(`import-silent-accept:${sample.mutation}`, {
          repro,
          datasetCount: result.datasets.length,
          errors: result.errors,
        });
      }

      if (files.length === 1) {
        try {
          await loadZip(files[0]);
          findings.add(`loadZip-silent-accept:${sample.mutation}`, {
            repro,
          });
        } catch (error) {
          if (!cleanError(error)) {
            findings.add(`loadZip-unclean-rejection:${sample.mutation}:${error?.name ?? typeof error}`, {
              repro,
              error: compactError(error),
            });
          }
        }
      }
    },
  });
});
