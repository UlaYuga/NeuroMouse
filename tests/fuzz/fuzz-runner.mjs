import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

export const ORACLE_PATH = resolve(import.meta.dirname, "fuzz-target-oracle.py");
const PYTHON_COMMANDS = [process.env.FUZZ_PYTHON || "python3", "python"];

export function runPythonTarget(target, payload) {
  const payloadJson = JSON.stringify(payload);
  const errors = [];
  for (const python of PYTHON_COMMANDS) {
    const result = spawnSync(python, [ORACLE_PATH, "--target", target, "--case", payloadJson], {
      encoding: "utf8",
      maxBuffer: 4 * 1024 * 1024,
    });

    if (result.error) {
      if (result.error.code === "ENOENT") {
        continue;
      }
      return {
        ok: false,
        transport: "spawn",
        python,
        status: -1,
        error: String(result.error),
      };
    }

    if (!result.stdout && result.status !== 0) {
      return {
        ok: false,
        transport: "empty-output",
        python,
        status: result.status,
        stderr: String(result.stderr ?? ""),
      };
    }

    if (result.status !== 0) {
      return {
        ok: false,
        transport: "exit-non-zero",
        python,
        status: result.status,
        stdout: result.stdout?.trim(),
        stderr: result.stderr?.trim(),
      };
    }

    try {
      const parsed = JSON.parse(result.stdout);
      return {
        ok: true,
        status: 0,
        payload: parsed,
        python,
      };
    } catch (error) {
      return {
        ok: false,
        transport: "json-parse",
        python,
        status: 0,
        stderr: `Could not parse oracle output: ${error.message}`,
      };
    }
  }

  errors.push("python command not available");
  return {
    ok: false,
    transport: "spawn",
    python: PYTHON_COMMANDS[0],
    status: -1,
    stderr: errors.join("; "),
  };
}

