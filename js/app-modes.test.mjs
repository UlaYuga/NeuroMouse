import test from "node:test";
import assert from "node:assert/strict";

import { resolveAppModes } from "./app-modes.js";

test("resolveAppModes keeps backend mode explicit but enables private methods on normal app", () => {
  assert.deepEqual(resolveAppModes(new URLSearchParams("")), {
    backendMode: false,
    privateMethodsMode: true,
  });
  assert.deepEqual(resolveAppModes(new URLSearchParams("backend=1")), {
    backendMode: true,
    privateMethodsMode: false,
  });
});

test("resolveAppModes allows private method auto-surface to be disabled for smoke runs", () => {
  assert.deepEqual(resolveAppModes(new URLSearchParams("privateMethods=0")), {
    backendMode: false,
    privateMethodsMode: false,
  });
  assert.deepEqual(resolveAppModes(new URLSearchParams("backend=0")), {
    backendMode: false,
    privateMethodsMode: true,
  });
});
