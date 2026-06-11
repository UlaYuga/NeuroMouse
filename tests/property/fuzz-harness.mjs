import assert from "node:assert/strict";
import fc from "fast-check";

const DEFAULT_BASE_CASES = 64;
const DEFAULT_MAX_CASES = 512;
const DEFAULT_DRY_RUNS = 3;
const DEFAULT_MAX_RUNS = 8;
const DEFAULT_SEED = 0x691;

export function cleanError(error) {
  return error instanceof Error && error.name === "Error" && error.message.length > 0;
}

export function compactError(error) {
  if (!(error instanceof Error)) {
    return {
      name: typeof error,
      message: String(error),
    };
  }
  return {
    name: error.name,
    message: error.message,
  };
}

export async function runFuzzUntilDry({
  name,
  arbitrary,
  check,
  baseCases = numberFromEnv("PROPERTY_BASE_CASES", DEFAULT_BASE_CASES),
  maxCases = numberFromEnv("PROPERTY_MAX_CASES", DEFAULT_MAX_CASES),
  dryRuns = numberFromEnv("PROPERTY_DRY_RUNS", DEFAULT_DRY_RUNS),
  maxRuns = numberFromEnv("PROPERTY_MAX_RUNS", DEFAULT_MAX_RUNS),
  seed = numberFromEnv("PROPERTY_SEED", DEFAULT_SEED),
}) {
  const findingLog = createFindingLog(name);
  let casesThisRun = baseCases;
  let dryStreak = 0;
  let runCount = 0;
  let totalCases = 0;

  while (dryStreak < dryRuns && runCount < maxRuns) {
    const beforeClasses = findingLog.size;
    const samples = fc.sample(arbitrary, {
      numRuns: casesThisRun,
      seed: seed + runCount,
    });

    for (const sample of samples) {
      await check(sample, findingLog);
    }

    totalCases += samples.length;
    if (findingLog.size === beforeClasses) {
      dryStreak += 1;
    } else {
      dryStreak = 0;
    }

    casesThisRun = Math.min(maxCases, casesThisRun * 2);
    runCount += 1;
  }

  const summary = {
    name,
    totalCases,
    runCount,
    dryStreak,
    dryRuns,
    seed,
    baseCases,
    maxCases,
    findingClasses: findingLog.size,
    findings: findingLog.findings(),
  };

  if (summary.findings.length) {
    console.error(`PROPERTY_FINDINGS ${name}`);
    console.error(JSON.stringify(summary, null, 2));
    assert.fail(`${name}: ${summary.findings.length} distinct property finding(s) over ${totalCases} cases`);
  }

  console.log(`PROPERTY_OK ${name}: ${totalCases} cases, ${dryStreak}/${dryRuns} dry runs, seed ${seed}`);
  return summary;
}

function createFindingLog(name) {
  const byClass = new Map();
  return {
    get size() {
      return byClass.size;
    },
    add(className, detail) {
      const existing = byClass.get(className);
      if (existing) {
        existing.count += 1;
        return;
      }

      const finding = {
        className,
        count: 1,
        firstExample: detail,
      };
      byClass.set(className, finding);
      console.error(`PROPERTY_FINDING ${name} ${className}`);
      console.error(JSON.stringify(finding, null, 2));
    },
    findings() {
      return Array.from(byClass.values()).sort((a, b) => a.className.localeCompare(b.className));
    },
  };
}

function numberFromEnv(name, fallback) {
  const raw = process.env[name];
  if (raw == null || raw === "") return fallback;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}
