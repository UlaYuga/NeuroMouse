import { Ajv, type AnySchemaObject, type ErrorObject } from "ajv";

import { datasetSchema } from "./schema.js";
import type { Dataset } from "./types.js";

export type { Dataset } from "./types.js";

export const DEFAULT_MAX_CHANNELS = 4096;

export type DatasetValidationSource = "schema" | "hard-rule";

export interface DatasetValidationIssue {
  source: DatasetValidationSource;
  path: string;
  message: string;
}

export interface ValidateDatasetOptions {
  maxChannels?: number;
}

export type ValidateDatasetResult =
  | {
      valid: true;
      data: Dataset;
      errors: [];
    }
  | {
      valid: false;
      errors: DatasetValidationIssue[];
    };

const ajv = new Ajv({
  allErrors: true,
  strict: false,
  strictNumbers: false,
});

const validateSchema = ajv.compile(datasetSchema as AnySchemaObject);

export function validateDataset(
  obj: unknown,
  options: ValidateDatasetOptions = {},
): ValidateDatasetResult {
  const maxChannels = resolveMaxChannels(options.maxChannels);
  const errors = [...schemaErrors(obj), ...hardRuleErrors(obj, maxChannels)];

  if (errors.length > 0) {
    return { valid: false, errors };
  }

  return { valid: true, data: obj as Dataset, errors: [] };
}

function schemaErrors(obj: unknown): DatasetValidationIssue[] {
  if (validateSchema(obj)) {
    return [];
  }

  return (validateSchema.errors ?? []).map((error) => ({
    source: "schema",
    path: schemaErrorPath(error),
    message: schemaErrorMessage(error),
  }));
}

function hardRuleErrors(obj: unknown, maxChannels: number): DatasetValidationIssue[] {
  const errors: DatasetValidationIssue[] = [];
  if (!isRecord(obj)) {
    return errors;
  }

  const channels = getPath(obj, ["meta", "channels"]);
  const channelCount = Array.isArray(channels) ? channels.length : undefined;

  if (!Array.isArray(channels) || channels.length === 0) {
    addError(errors, "meta.channels", "meta.channels must be a non-empty array");
  } else if (channels.length > maxChannels) {
    addError(
      errors,
      "meta.channels",
      `meta.channels has ${channels.length} channels but must contain at most ${maxChannels}`,
    );
  }

  const nChannels = getPath(obj, ["meta", "n_channels"]);
  if (nChannels !== undefined && nChannels !== null) {
    if (typeof nChannels !== "number" || !Number.isInteger(nChannels) || nChannels <= 0) {
      addError(errors, "meta.n_channels", "meta.n_channels must be a positive integer");
    } else if (channelCount !== undefined && channelCount > 0 && nChannels !== channelCount) {
      addError(
        errors,
        "meta.n_channels",
        `meta.n_channels (${nChannels}) must equal meta.channels.length (${channelCount})`,
      );
    }
  }

  const frequencies = getPath(obj, ["welch_psd", "frequencies"]);
  const frequencyCount = validateRequiredAxis(errors, "welch_psd.frequencies", frequencies);
  validateFiniteVector(errors, "welch_psd.frequencies", frequencies);

  const psd = getPath(obj, ["welch_psd", "psd"]);
  validateChannelRows(errors, {
    path: "welch_psd.psd",
    rows: psd,
    channelCount,
    expectedWidth: frequencyCount,
    expectedWidthPath: "welch_psd.frequencies",
    checkFiniteValues: true,
  });

  const centroidTime = getPath(obj, ["centroid", "time_relative"]);
  const centroidTimeCount = validateRequiredAxis(
    errors,
    "centroid.time_relative",
    centroidTime,
  );

  const centroidValues = getPath(obj, ["centroid", "values"]);
  validateChannelRows(errors, {
    path: "centroid.values",
    rows: centroidValues,
    channelCount,
    expectedWidth: centroidTimeCount,
    expectedWidthPath: "centroid.time_relative",
    checkFiniteValues: true,
  });

  const geometryTime = getPath(obj, ["geometry", "time"]);
  validateRequiredAxis(errors, "geometry.time", geometryTime);
  validateFiniteVector(errors, "geometry.time", geometryTime);

  const mea = getPath(obj, ["mea"]);
  if (mea !== undefined && mea !== null) {
    if (!isRecord(mea)) {
      addError(errors, "mea", "mea must be an object");
      return errors;
    }

    const samplingRate = mea["sampling_rate_hz"];
    if (typeof samplingRate !== "number" || !Number.isFinite(samplingRate) || samplingRate <= 0) {
      addError(errors, "mea.sampling_rate_hz", "mea.sampling_rate_hz must be a positive finite number");
    }

    const traces = mea["traces"];
    if (!Array.isArray(traces) || traces.length === 0) {
      addError(
        errors,
        "mea.traces",
        "mea.traces must be a non-empty channel-major matrix",
      );
    } else {
  if (channelCount !== undefined && channelCount > 0 && traces.length !== channelCount) {
        addError(
          errors,
          "mea.traces",
          `mea.traces has ${traces.length} channel rows but meta.channels lists ${channelCount}`,
        );
      }
      if (!Array.isArray(traces[0]) || traces[0].length === 0) {
        addError(errors, "mea.traces", "mea.traces[0] must be a non-empty array");
      }
      validateChannelRows(errors, {
        path: "mea.traces",
        rows: traces,
        channelCount: traces.length,
        expectedWidth: (Array.isArray(traces[0]) ? traces[0].length : undefined),
        expectedWidthPath: "trace length",
        checkFiniteValues: true,
      });
    }
  }

  return errors;
}

interface ChannelRowsValidationInput {
  path: string;
  rows: unknown;
  channelCount: number | undefined;
  expectedWidth: number | undefined;
  expectedWidthPath: string;
  checkFiniteValues: boolean;
}

function validateChannelRows(
  errors: DatasetValidationIssue[],
  input: ChannelRowsValidationInput,
): void {
  if (!Array.isArray(input.rows)) {
    return;
  }

  if (
    input.channelCount !== undefined &&
    input.channelCount > 0 &&
    input.rows.length !== input.channelCount
  ) {
    addError(
      errors,
      input.path,
      `${input.path} has ${input.rows.length} channel rows but meta.channels lists ${input.channelCount}`,
    );
  }

  input.rows.forEach((row, rowIndex) => {
    const rowPath = `${input.path}[${rowIndex}]`;
    if (!Array.isArray(row)) {
      addError(errors, rowPath, `${rowPath} must be an array`);
      return;
    }

    if (input.expectedWidth !== undefined && row.length !== input.expectedWidth) {
      addError(
        errors,
        rowPath,
        `${rowPath} must contain ${input.expectedWidth} values to match ${input.expectedWidthPath}`,
      );
    }

    if (input.checkFiniteValues) {
      validateFiniteVector(errors, rowPath, row);
    }
  });
}

function validateRequiredAxis(
  errors: DatasetValidationIssue[],
  path: string,
  axis: unknown,
): number | undefined {
  if (!Array.isArray(axis)) {
    addError(errors, path, `${path} must be a non-empty array`);
    return undefined;
  }

  if (axis.length === 0) {
    addError(errors, path, `${path} must be non-empty`);
  }

  return axis.length;
}

function validateFiniteVector(
  errors: DatasetValidationIssue[],
  path: string,
  values: unknown,
): void {
  if (!Array.isArray(values)) {
    return;
  }

  values.forEach((value, index) => {
    if (typeof value === "number" && !Number.isFinite(value)) {
      const valuePath = `${path}[${index}]`;
      addError(errors, valuePath, `${valuePath} must be a finite number`);
    }
  });
}

function resolveMaxChannels(value: number | undefined): number {
  if (value === undefined) {
    return DEFAULT_MAX_CHANNELS;
  }
  if (!Number.isInteger(value) || value <= 0) {
    throw new RangeError("maxChannels must be a positive integer");
  }
  return value;
}

function addError(errors: DatasetValidationIssue[], path: string, message: string): void {
  errors.push({ source: "hard-rule", path, message });
}

function getPath(value: unknown, path: readonly string[]): unknown {
  let current = value;
  for (const segment of path) {
    if (!isRecord(current)) {
      return undefined;
    }
    current = current[segment];
  }
  return current;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function schemaErrorPath(error: ErrorObject): string {
  const basePath = jsonPointerToPath(error.instancePath);
  if (error.keyword === "required" && typeof error.params.missingProperty === "string") {
    return basePath === "$"
      ? error.params.missingProperty
      : `${basePath}.${error.params.missingProperty}`;
  }
  return basePath;
}

function schemaErrorMessage(error: ErrorObject): string {
  if (error.keyword === "required" && typeof error.params.missingProperty === "string") {
    return `must include required property ${error.params.missingProperty}`;
  }
  return error.message ?? "failed JSON Schema validation";
}

function jsonPointerToPath(pointer: string): string {
  if (pointer === "") {
    return "$";
  }

  return pointer
    .split("/")
    .slice(1)
    .map((segment) => segment.replace(/~1/g, "/").replace(/~0/g, "~"))
    .reduce((path, segment) => {
      if (/^(0|[1-9]\d*)$/.test(segment)) {
        return `${path}[${segment}]`;
      }
      return path === "$" ? segment : `${path}.${segment}`;
    }, "$");
}
