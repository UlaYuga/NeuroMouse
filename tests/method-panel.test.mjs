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
