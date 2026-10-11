/**
 * Browser diagnosis contract for InsightUiWebmcp.status() (#6).
 * Run: node --test tests/js/status.test.js
 */
"use strict";

const { describe, it, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const REGISTER_JS = fs.realpathSync(
  path.resolve(
    __dirname,
    "../../src/ais_webmcp/assets/register.js",
  ),
);
const TOKEN = "OT-TOKEN-DO-NOT-RETURN";

function meta(attrs) {
  return {
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(attrs, name)
        ? attrs[name]
        : null;
    },
  };
}

/**
 * Load a fresh helper against a fake document.
 * @param {object} doc fake document (modelContext, querySelectorAll, ...)
 */
function load(doc) {
  delete require.cache[REGISTER_JS];
  globalThis.document = doc;
  const prevWindow = globalThis.window;
  delete globalThis.window;
  const api = require(REGISTER_JS);
  if (prevWindow !== undefined) globalThis.window = prevWindow;
  return api;
}

function docWith(modelContext, metas) {
  const queries = [];
  return {
    modelContext,
    queries,
    querySelectorAll(selector) {
      queries.push(selector);
      return metas;
    },
  };
}

describe("InsightUiWebmcp.status()", () => {
  afterEach(() => {
    delete require.cache[REGISTER_JS];
    delete globalThis.document;
    delete globalThis.InsightUiWebmcp;
  });

  it("reports no-origin-trial-meta when neither API nor meta exist", () => {
    const api = load(docWith(null, []));
    assert.deepEqual(api.status(), {
      supported: false,
      modelContext: false,
      registerTool: false,
      originTrialMeta: false,
      reason: "no-origin-trial-meta",
    });
  });

  it("reports no-model-context when a meta exists but the API is missing", () => {
    const api = load(
      docWith(null, [
        meta({ "http-equiv": "Content-Security-Policy", content: "x" }),
        meta({ "http-equiv": " Origin-Trial ", content: TOKEN }),
      ]),
    );
    const result = api.status();
    assert.equal(result.reason, "no-model-context");
    assert.equal(result.originTrialMeta, true);
    assert.equal(result.supported, false);
    assert.equal(JSON.stringify(result).includes(TOKEN), false);
  });

  it("treats an empty origin-trial meta as absent", () => {
    const api = load(
      docWith(null, [meta({ "http-equiv": "origin-trial", content: "  " })]),
    );
    assert.equal(api.status().originTrialMeta, false);
    assert.equal(api.status().reason, "no-origin-trial-meta");
  });

  it("reports ok whenever registerTool exists, with or without a meta", () => {
    let registered = 0;
    const ctx = {
      registerTool() {
        registered += 1;
        return Promise.resolve();
      },
    };
    let api = load(docWith(ctx, []));
    assert.deepEqual(api.status(), {
      supported: true,
      modelContext: true,
      registerTool: true,
      originTrialMeta: false,
      reason: "ok",
    });
    api = load(
      docWith(ctx, [meta({ "http-equiv": "origin-trial", content: TOKEN })]),
    );
    assert.equal(api.status().reason, "ok");
    assert.equal(api.status().originTrialMeta, true);
    assert.equal(registered, 0, "status() must not register tools");
    assert.equal(api.status().supported, api.isSupported());
  });

  it("does not count a modelContext without registerTool as supported", () => {
    const api = load(docWith({}, []));
    const result = api.status();
    assert.equal(result.modelContext, true);
    assert.equal(result.registerTool, false);
    assert.equal(result.reason, "no-origin-trial-meta");
  });

  it("returns originTrialMeta null when the DOM cannot be queried", () => {
    let api = load({ modelContext: null });
    assert.equal(api.status().originTrialMeta, null);
    assert.equal(api.status().reason, "no-model-context");
    api = load({
      modelContext: null,
      querySelectorAll() {
        throw new Error("blocked");
      },
    });
    assert.equal(api.status().originTrialMeta, null);
    assert.equal(api.status().reason, "no-model-context");
  });

  it("returns a fresh object each call", () => {
    const api = load(docWith(null, []));
    const first = api.status();
    first.reason = "ok";
    assert.equal(api.status().reason, "no-origin-trial-meta");
  });

  it("never logs while diagnosing", () => {
    const original = { ...console };
    const calls = [];
    for (const level of ["log", "info", "warn", "error", "debug"]) {
      console[level] = (...args) => calls.push(args);
    }
    try {
      const api = load(
        docWith(null, [meta({ "http-equiv": "origin-trial", content: TOKEN })]),
      );
      api.status();
    } finally {
      Object.assign(console, original);
    }
    assert.deepEqual(calls, []);
  });
});
