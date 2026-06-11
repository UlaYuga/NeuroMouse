import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const oracleScript = resolve(import.meta.dirname, "../fuzz/fuzz-target-oracle.py");
const pythonFallback = [process.env.FUZZ_PYTHON || "python3", "python"];

export function runPythonTarget(target, payload) {
  const payloadJson = JSON.stringify(payload);
  const commandError = new Error(`python executable not found: ${pythonFallback.join(", ")}`);

  for (const python of pythonFallback) {
    const processResult = spawnSync(python, [oracleScript, "--target", target, "--case", payloadJson], {
      encoding: "utf8",
      maxBuffer: 4 * 1024 * 1024,
    });

    if (processResult.error) {
      if (processResult.error.code === "ENOENT") {
        continue;
      }
      commandError.message = `${python}: ${processResult.error.message}`;
      break;
    }

    if (processResult.status !== 0 && !processResult.stdout?.trim()) {
      return {
        ok: false,
        status: processResult.status,
        transport: "python-exit",
        python,
        stderr: processResult.stderr?.trim(),
      };
    }

    try {
      const parsed = JSON.parse(processResult.stdout ?? "{}");
      return {
        ok: parsed.ok === true,
        target: parsed.target,
        status: processResult.status,
        python,
        errorType: parsed.error_type,
        payload: parsed,
      };
    } catch (error) {
      return {
        ok: false,
        status: processResult.status,
        transport: "json-parse",
        python,
        stderr: processResult.stderr?.trim(),
      };
    }
  }

  return {
    ok: false,
    transport: "spawn",
    status: -1,
    python: pythonFallback[0],
    stderr: commandError.message,
  };
}
