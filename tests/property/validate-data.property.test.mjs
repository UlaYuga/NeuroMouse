import test from "node:test";

import { validateData } from "../../js/sources/static-source.js";
import {
  malformedDataArb,
  makeCanonicalData,
  makeMalformedData,
  shapeArb,
  shapeRepro,
} from "./data-fixtures.mjs";
import { cleanError, compactError, runFuzzUntilDry } from "./fuzz-harness.mjs";

test("property: structurally valid canonical datasets validate", async () => {
  await runFuzzUntilDry({
    name: "validateData.valid-canonical",
    arbitrary: shapeArb,
    check(shape, findings) {
      const data = makeCanonicalData(shape);
      try {
        validateData(data);
      } catch (error) {
        findings.add("valid-dataset-rejected", {
          shape: shapeRepro(shape),
          error: compactError(error),
        });
      }
    },
  });
});

test("property: malformed canonical datasets are rejected cleanly", async () => {
  await runFuzzUntilDry({
    name: "validateData.malformed-canonical",
    arbitrary: malformedDataArb,
    check(sample, findings) {
      const data = makeMalformedData(sample);
      try {
        validateData(data);
        findings.add(`silent-accept:${sample.mutation}`, {
          mutation: sample.mutation,
          shape: shapeRepro(sample.shape),
        });
      } catch (error) {
        if (!cleanError(error)) {
          findings.add(`unclean-rejection:${sample.mutation}:${error?.name ?? typeof error}`, {
            mutation: sample.mutation,
            shape: shapeRepro(sample.shape),
            error: compactError(error),
          });
        }
      }
    },
  });
});
