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
  const rawValue = getPath(result, spec.field);
  const value = normalizePanelValue(spec, rawValue);
  const body = element(providedDocument, "div", { className: "panel-body" });
  const status = element(providedDocument, "span", { "data-method-panel-status": "" }, statusText(value, spec));

  if (rawValue == null) {
    body.append(element(
      providedDocument,
      "p",
      { className: "empty-comparison" },
      `No data returned for ${spec.field}.`,
    ));
  } else if (spec.kind === "matrix") {
    body.append(renderMatrix(providedDocument, rawValue, spec));
  } else if (spec.kind === "timeline") {
    body.append(renderTimeline(providedDocument, value, spec));
  } else if (spec.kind === "heatmap_table") {
    body.append(renderHeatmapTable(providedDocument, value, spec));
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

function renderHeatmapTable(document, rows, spec) {
  const normalizedRows = normalizeHeatmapRows(rows);
  const columns = normalizeColumns(spec.columns, normalizedRows);
  if (!normalizedRows.length) {
    return element(document, "p", { className: "empty-comparison" }, "No heatmap rows returned.");
  }
  return renderTable(document, normalizedRows, { columns });
}

function renderTimeline(document, segments, spec) {
  if (!Array.isArray(segments) || !segments.length) {
    return element(document, "p", { className: "empty-comparison" }, "No timeline events returned.");
  }
  const columns = normalizeColumns(spec.columns, segments);
  if (!columns.length) {
    columns.push({ key: "start_sec", label: "start_sec" });
    columns.push({ key: "end_sec", label: "end_sec" });
    columns.push({ key: "size", label: "size" });
  }
  return element(document, "table", { className: "method-timeline-table" },
    element(document, "thead", {},
      element(document, "tr", {}, columns.map((column) => {
        return element(document, "th", { scope: "col" }, column.label ?? column.key);
      })),
    ),
    element(document, "tbody", {}, segments.map((segment) => {
      return element(document, "tr", { "data-timeline-segment": "" }, columns.map((column) => {
        return element(document, "td", {}, formatValue(getPath(segment, column.key)));
      }));
    })),
  );
}

function renderMatrix(document, matrix, spec) {
  if (!Array.isArray(matrix) || !matrix.length) {
    return element(document, "p", { className: "empty-comparison" }, "No matrix returned.");
  }
  const rows = matrix.filter(Array.isArray);
  if (!rows.length) {
    return element(document, "p", { className: "empty-comparison" }, "No matrix returned.");
  }
  const columnCount = rows.reduce((max, row) => Math.max(max, row.length), 0);
  const headers = normalizeColumns(spec.columns, Array.isArray(spec.columns) ? spec.columns.map((column) => ({ key: String(column) })) : []);
  return element(document, "div", { className: "method-matrix-wrap" },
    element(document, "table", { className: "method-matrix" },
      headers.length ? element(document, "thead", {},
        element(document, "tr", {},
          headers.map((column) => element(document, "th", { scope: "col" }, column.label ?? column.key)),
        ),
      ) : null,
      element(document, "tbody", {}, rows.map((row) => {
        return element(document, "tr", {}, row.slice(0, columnCount).map((cell) => {
          return element(document, "td", {}, formatValue(cell));
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
  if (spec.kind === "timeline") {
    return Array.isArray(value)
      ? `${value.length} segment${value.length === 1 ? "" : "s"}`
      : "No segments";
  }
  if (spec.kind === "heatmap_table") {
    return `${Array.isArray(value) ? value.length : 0} row${Array.isArray(value) && value.length === 1 ? "" : "s"}`;
  }
  if (Array.isArray(value)) return `${value.length} row${value.length === 1 ? "" : "s"}`;
  if (isPlainObject(value)) return `${Object.keys(value).length} field${Object.keys(value).length === 1 ? "" : "s"}`;
  return spec.kind === "metric" ? "Metric" : "Result";
}

function normalizePanelValue(spec, value) {
  if (spec.kind === "heatmap_table") return normalizeHeatmapRows(value);
  if (spec.kind === "timeline") return Array.isArray(value) ? value : [];
  if (spec.kind === "matrix") return Array.isArray(value) ? value : [];
  return value;
}

function normalizeHeatmapRows(value) {
  if (Array.isArray(value)) return value;
  if (!isPlainObject(value)) return [];
  return Object.entries(value).map(([electrode, entry]) => {
    if (isPlainObject(entry)) {
      return Object.keys(entry).length ? { electrode, ...entry } : { electrode, value: entry };
    }
    return { electrode, value };
  });
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
