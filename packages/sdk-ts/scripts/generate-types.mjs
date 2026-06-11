import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { compile } from "json-schema-to-typescript";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(packageRoot, "..", "..");
const schemaPath = resolve(repoRoot, "contracts", "schema", "dataset.schema.json");
const typesPath = resolve(packageRoot, "src", "types.ts");
const schemaModulePath = resolve(packageRoot, "src", "schema.ts");

const schemaText = await readFile(schemaPath, "utf8");
const schema = JSON.parse(schemaText);

const types = await compile(schema, "Dataset", {
  bannerComment:
    "/* eslint-disable */\n" +
    "/* Generated from ../../contracts/schema/dataset.schema.json. Do not edit by hand. */",
  style: {
    semi: true,
    singleQuote: false,
  },
});

const schemaModule =
  "/* eslint-disable */\n" +
  "/* Generated from ../../contracts/schema/dataset.schema.json. Do not edit by hand. */\n" +
  `export const datasetSchema = ${JSON.stringify(schema, null, 2)} as const;\n`;

await mkdir(dirname(typesPath), { recursive: true });
await writeFile(typesPath, `${types.trim()}\n`, "utf8");
await writeFile(schemaModulePath, schemaModule, "utf8");
