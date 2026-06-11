export function renderMethodPanel(target, {
  document: providedDocument = target?.ownerDocument ?? globalThis.document,
  method = {},
  panelSpec,
  result,
} = {}) {
  if (!target) throw new Error("renderMethodPanel requires a target");
  if (!providedDocument) throw new Error("renderMethodPanel requires a document");
  const panel = buildMethodPanel({
    document: providedDocument,
    method,
    panelSpec,
    result,
  });
  target.replaceChildren(panel);
  return panel;
}

export function buildMethodPanel({
  document: providedDocument = globalThis.document,
  method = {},
  panelSpec,
  result,
} = {}) {
  if (!providedDocument) throw new Error("buildMethodPanel requires a document");
  const spec = normalizePanelSpec(panelSpec, method);
  const value = getPath(result, spec.field);
  const body = element(providedDocument, "div", { className: "panel-body" });
  const status = element(providedDocument, "span", { "data-method-panel-status": "" }, statusText(value, spec));

  if (value == null) {
    body.append(element(
      providedDocument,
      "p",
      { className: "empty-comparison" },
      `No data returned for ${spec.field}.`,
    ));
  } else if (Array.isArray(value)) {
    body.append(renderTable(providedDocument, value, spec));
  } else if (isPlainObject(value)) {
    body.append(renderKeyValueGrid(providedDocument, value));
  } else {
    body.append(element(providedDocument, "strong", { className: "method-panel-value" }, formatValue(value)));
  }

  return element(providedDocument, "section", {
    className: "panel panel-method panel-collapsible is-expanded",
    "data-method-panel": spec.id,
    "aria-labelledby": `${spec.id}-title`,
  },
  element(providedDocument, "div", { className: "panel-head" },
    element(providedDocument, "div", {},
      element(providedDocument, "h2", { id: `${spec.id}-title` }, spec.title),
      element(providedDocument, "p", {}, spec.description || method.description || "Backend method result"),
    ),
    status,
  ),
  body);
}

function renderTable(document, rows, spec) {
  if (!rows.length) {
    return element(document, "p", { className: "empty-comparison" }, "No rows returned.");
  }
  const columns = normalizeColumns(spec.columns, rows);
  return element(document, "div", { className: "method-table-wrap" },
    element(document, "table", { className: "method-table" },
      element(document, "thead", {},
        element(document, "tr", {}, columns.map((column) => {
          return element(document, "th", { scope: "col" }, column.label ?? column.key);
        })),
      ),
      element(document, "tbody", {}, rows.map((row) => {
        return element(document, "tr", {}, columns.map((column) => {
          return element(document, "td", {}, formatValue(getPath(row, column.key)));
        }));
      })),
    ),
  );
}

function renderKeyValueGrid(document, value) {
  return element(document, "div", { className: "workbench-metrics" },
    Object.entries(value).map(([key, entry]) => {
      return element(document, "div", { className: "metric-tile" },
        element(document, "span", {}, key),
        element(document, "strong", {}, formatValue(entry)),
      );
    }),
  );
}

function normalizeColumns(columns, rows) {
  if (Array.isArray(columns) && columns.length) {
    return columns.map((column) => {
      if (typeof column === "string") return { key: column, label: column };
      return { key: column.key ?? column.field ?? column.path, label: column.label ?? column.title };
    }).filter((column) => column.key);
  }
  const keys = new Set();
  rows.forEach((row) => {
    if (!isPlainObject(row)) return;
    Object.keys(row).forEach((key) => keys.add(key));
  });
  return Array.from(keys).map((key) => ({ key, label: key }));
}

function normalizePanelSpec(panelSpec, method) {
  const methodId = method.id ?? method.name ?? "method_result";
  const id = panelSpec?.id ?? methodId;
  return {
    id,
    title: panelSpec?.title ?? method.name ?? titleFromId(id),
    kind: panelSpec?.kind ?? "table",
    field: panelSpec?.field ?? panelSpec?.path ?? methodId,
    columns: panelSpec?.columns,
    description: panelSpec?.description ?? method.description ?? "",
  };
}

function statusText(value, spec) {
  if (value == null) return "No output";
  if (Array.isArray(value)) return `${value.length} row${value.length === 1 ? "" : "s"}`;
  if (isPlainObject(value)) return `${Object.keys(value).length} field${Object.keys(value).length === 1 ? "" : "s"}`;
  return spec.kind === "metric" ? "Metric" : "Result";
}

function element(document, name, attrs = {}, ...children) {
  const node = document.createElement(name);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "className") node.className = value;
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, value);
  });
  children.flat().forEach((child) => {
    if (child == null) return;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  });
  return node;
}

function getPath(value, path) {
  if (!path) return value;
  return String(path).split(".").reduce((current, part) => {
    if (current == null) return undefined;
    if (Array.isArray(current) && /^\d+$/.test(part)) return current[Number(part)];
    return current[part];
  }, value);
}

function formatValue(value) {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return String(value);
    if (Number.isInteger(value)) return String(value);
    if (Math.abs(value) >= 100) return value.toFixed(2);
    return value.toFixed(4);
  }
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (isPlainObject(value)) {
    return Object.entries(value).map(([key, entry]) => `${key}: ${formatValue(entry)}`).join(", ");
  }
  return String(value);
}

function isPlainObject(value) {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function titleFromId(id) {
  return String(id).replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
