import test from "node:test";
import assert from "node:assert/strict";

import { renderMethodPanel } from "../js/panels/method-panel.js";

test("renderMethodPanel renders a generic table from a panel spec path", () => {
  const document = createTestDocument();
  const host = document.createElement("div");
  const result = {
    band_power_summary: {
      band: { min_hz: 8, max_hz: 13 },
      channels: [
        { channel: "Cz", power: 0.427318 },
        { channel: "Pz", power: 0.314159 },
      ],
      mean_power: 0.3707385,
      top_channel: { channel: "Cz", power: 0.427318 },
    },
  };

  const panel = renderMethodPanel(host, {
    document,
    method: { id: "band_power_summary", name: "Band Power Summary" },
    panelSpec: {
      id: "band_power_summary",
      title: "Band Power Summary",
      kind: "table",
      field: "band_power_summary.channels",
    },
    result,
  });

  assert.equal(panel.querySelector("h2").textContent, "Band Power Summary");
  assert.equal(panel.querySelector("[data-method-panel-status]").textContent, "2 rows");
  assert.deepEqual(
    Array.from(panel.querySelector("thead").querySelectorAll("th")).map((node) => node.textContent),
    ["channel", "power"],
  );
  assert.deepEqual(
    Array.from(panel.querySelectorAll("tbody tr")).map((row) => {
      return Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent);
    }),
    [
      ["Cz", "0.4273"],
      ["Pz", "0.3142"],
    ],
  );
  assert.equal(host.children.length, 1);
});

test("renderMethodPanel renders heatmap_table rows and cells from MEA-like rate output", () => {
  const document = createTestDocument();
  const host = document.createElement("div");
  const result = {
    spike_detect: {
      rates: [
        { electrode: "E01", rate_hz: 5.0 },
        { electrode: "E02", rate_hz: 2.5 },
        { electrode: "E03", rate_hz: 0.0 },
      ],
    },
  };

  renderMethodPanel(host, {
    document,
    method: { id: "spike_detect_rates", name: "Spike Detect Firing Rates" },
    panelSpec: {
      id: "spike_detect_rates",
      title: "Spike Detect Firing Rates",
      kind: "heatmap_table",
      field: "spike_detect.rates",
    },
    result,
  });

  const table = host.querySelector("table");
  assert.ok(table, "Expected a table for heatmap_table");
  assert.deepEqual(
    Array.from(table.querySelectorAll("thead tr th")).map((node) => node.textContent),
    ["electrode", "rate_hz"],
  );
  assert.deepEqual(
    Array.from(table.querySelectorAll("tbody tr")).map((row) => {
      return Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent);
    }),
    [
      ["E01", "5"],
      ["E02", "2.5000"],
      ["E03", "0"],
    ],
  );
});

test("renderMethodPanel renders timeline segments from MEA-like timeline output", () => {
  const document = createTestDocument();
  const host = document.createElement("div");
  const result = {
    network_burst: {
      timeline: [
        { start_sec: 0.12, end_sec: 0.37, spike_count: 5 },
        { start_sec: 0.9, end_sec: 1.42, spike_count: 3 },
      ],
    },
  };

  renderMethodPanel(host, {
    document,
    method: { id: "network_burst_timeline", name: "Network Burst Timeline" },
    panelSpec: {
      id: "network_burst_timeline",
      title: "Network Burst Timeline",
      kind: "timeline",
      field: "network_burst.timeline",
    },
    result,
  });

  const timeline = host.querySelector("table");
  assert.ok(timeline, "Expected a timeline table");
  assert.deepEqual(
    Array.from(timeline.querySelectorAll("tr")).length,
    3,
    "Expected header row + two segments",
  );
  assert.deepEqual(
    Array.from(timeline.querySelectorAll("tbody tr")).map((row) => {
      return Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent);
    }),
    [
      ["0.1200", "0.3700", "5"],
      ["0.9000", "1.4200", "3"],
    ],
  );
});

test("renderMethodPanel renders matrix panels as NxN grids", () => {
  const document = createTestDocument();
  const host = document.createElement("div");
  const result = {
    electrode_connectivity: {
      matrix: [
        [1.0, 0.6, 0.2],
        [0.6, 1.0, 0.1],
        [0.2, 0.1, 1.0],
      ],
    },
  };

  renderMethodPanel(host, {
    document,
    method: { id: "electrode_connectivity_matrix", name: "Electrode Connectivity Matrix" },
    panelSpec: {
      id: "electrode_connectivity_matrix",
      title: "Electrode Connectivity Matrix",
      kind: "matrix",
      field: "electrode_connectivity.matrix",
    },
    result,
  });

  const matrix = host.querySelector("table");
  assert.ok(matrix, "Expected a matrix table");
  assert.equal(matrix.querySelectorAll("tbody tr").length, 3);
  assert.deepEqual(Array.from(matrix.querySelectorAll("tbody tr")).map((row) => row.querySelectorAll("td").length), [3, 3, 3]);
});

test("renderMethodPanel renders key-value output when the panel field is scalar", () => {
  const document = createTestDocument();
  const host = document.createElement("div");

  renderMethodPanel(host, {
    document,
    panelSpec: {
      id: "mean_power",
      title: "Mean Power",
      kind: "metric",
      field: "band_power_summary.mean_power",
    },
    result: {
      band_power_summary: {
        mean_power: 0.3707385,
      },
    },
  });

  assert.equal(host.querySelector("h2").textContent, "Mean Power");
  assert.match(host.textContent, /0\.3707/);
});

test("renderMethodPanel shows a useful empty state for missing panel fields", () => {
  const document = createTestDocument();
  const host = document.createElement("div");

  renderMethodPanel(host, {
    document,
    panelSpec: {
      id: "missing",
      title: "Missing Output",
      kind: "table",
      field: "band_power_summary.missing",
    },
    result: {
      band_power_summary: {
        channels: [],
      },
    },
  });

  assert.match(host.textContent, /No data returned for band_power_summary\.missing/);
});

function createTestDocument() {
  class TestNode {
    constructor(tagName) {
      this.tagName = tagName.toUpperCase();
      this.children = [];
      this.parentNode = null;
      this.attributes = new Map();
      this.ownerDocument = document;
      this._textContent = "";
      this.className = "";
    }

    append(...children) {
      children.flat().forEach((child) => {
        const node = typeof child === "string" ? document.createTextNode(child) : child;
        node.parentNode = this;
        this.children.push(node);
      });
    }

    replaceChildren(...children) {
      this.children = [];
      this._textContent = "";
      this.append(...children);
    }

    setAttribute(name, value) {
      this.attributes.set(name, String(value));
      if (name === "class") this.className = String(value);
    }

    getAttribute(name) {
      return this.attributes.get(name) ?? null;
    }

    querySelector(selector) {
      return this.querySelectorAll(selector)[0] ?? null;
    }

    querySelectorAll(selector) {
      const selectors = selector.split(/\s+/);
      return collect(this).filter((node) => matchesSelectorChain(node, selectors));
    }

    get textContent() {
      return this._textContent + this.children.map((child) => child.textContent).join("");
    }

    set textContent(value) {
      this.children = [];
      this._textContent = String(value);
    }
  }

  class TestTextNode {
    constructor(text) {
      this.text = text;
      this.children = [];
      this.parentNode = null;
    }

    get textContent() {
      return this.text;
    }

    set textContent(value) {
      this.text = String(value);
    }
  }

  const document = {
    createElement(tagName) {
      return new TestNode(tagName);
    },
    createTextNode(text) {
      return new TestTextNode(text);
    },
  };
  return document;
}

function collect(root) {
  const nodes = [];
  for (const child of root.children ?? []) {
    nodes.push(child);
    nodes.push(...collect(child));
  }
  return nodes;
}

function matchesSelectorChain(node, selectors) {
  if (!matchesSelector(node, selectors[selectors.length - 1])) return false;
  let current = node.parentNode;
  for (let index = selectors.length - 2; index >= 0; index -= 1) {
    while (current && !matchesSelector(current, selectors[index])) {
      current = current.parentNode;
    }
    if (!current) return false;
    current = current.parentNode;
  }
  return true;
}

function matchesSelector(node, selector) {
  if (!node.tagName) return false;
  const attr = selector.match(/^\[([^=\]]+)(?:=['"]?([^'"\]]+)['"]?)?\]$/);
  if (attr) {
    const value = node.getAttribute(attr[1]);
    return attr[2] == null ? value != null : value === attr[2];
  }
  return node.tagName.toLowerCase() === selector.toLowerCase();
}
