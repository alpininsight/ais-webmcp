/**
 * Tool lifecycle subscription contract for InsightUiWebmcp (#7).
 * Events: toolactivated / toolcancel on document.modelContext only
 * (Chrome 156+ / WebMCP PR #245). Run: node --test tests/js/lifecycle.test.js
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
const SOURCE_CJS = fs.realpathSync(
  path.resolve(__dirname, "../../js/register.source.cjs"),
);

/**
 * Minimal EventTarget mock that records add/remove calls.
 */
function makeContext() {
  /** @type {Map<string, Set<Function>>} */
  const listeners = new Map();
  /** @type {Array<{op: string, type: string, listener: Function, options: unknown}>} */
  const calls = [];
  return {
    listeners,
    calls,
    registerTool() {
      return Promise.resolve();
    },
    addEventListener(type, listener, options) {
      calls.push({ op: "add", type, listener, options });
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(listener);
    },
    removeEventListener(type, listener, options) {
      calls.push({ op: "remove", type, listener, options });
      const set = listeners.get(type);
      if (set) set.delete(listener);
    },
    dispatch(type, event) {
      const set = listeners.get(type);
      if (!set) return;
      for (const listener of Array.from(set)) {
        listener(event);
      }
    },
  };
}

/**
 * Load a fresh helper. When a window stub is provided, the IIFE binds to it
 * (see register.js `typeof window !== "undefined" ? window : globalThis`), so
 * document must live on that stub.
 * @param {object} doc
 * @param {object} [windowStub]
 */
function load(doc, windowStub) {
  delete require.cache[REGISTER_JS];
  delete globalThis.InsightUiWebmcp;
  // Leave document on the IIFE global: getModelContext reads it at call time.
  if (windowStub) {
    windowStub.document = doc;
    globalThis.window = windowStub;
    globalThis.document = doc;
  } else {
    delete globalThis.window;
    globalThis.document = doc;
  }
  return require(REGISTER_JS);
}

describe("InsightUiWebmcp tool lifecycle helpers (#7)", () => {
  afterEach(() => {
    delete require.cache[REGISTER_JS];
    delete globalThis.document;
    delete globalThis.InsightUiWebmcp;
    delete globalThis.window;
  });

  it("subscribes toolactivated and toolcancel only on document.modelContext", () => {
    const ctx = makeContext();
    let windowListenerCalls = 0;
    const windowStub = {
      ontoolactivated: undefined,
      ontoolcancel: undefined,
      addEventListener() {
        windowListenerCalls += 1;
        throw new Error("window must not receive lifecycle listeners");
      },
    };
    const api = load({ modelContext: ctx }, windowStub);
    const activated = [];
    const cancelled = [];
    const stopA = api.onToolActivated((event) =>
      activated.push(event.toolName),
    );
    const stopC = api.onToolCancel((event) => cancelled.push(event.toolName));

    assert.equal(typeof stopA, "function");
    assert.equal(typeof stopC, "function");
    assert.deepEqual(
      ctx.calls.map((c) => [c.op, c.type]),
      [
        ["add", "toolactivated"],
        ["add", "toolcancel"],
      ],
    );
    assert.equal(windowListenerCalls, 0);
    assert.equal(windowStub.ontoolactivated, undefined);
    assert.equal(windowStub.ontoolcancel, undefined);

    ctx.dispatch("toolactivated", { toolName: "go_to_section" });
    ctx.dispatch("toolcancel", { toolName: "go_to_section" });
    assert.deepEqual(activated, ["go_to_section"]);
    assert.deepEqual(cancelled, ["go_to_section"]);

    stopA();
    stopC();
    assert.deepEqual(
      ctx.calls.filter((c) => c.op === "remove").map((c) => c.type),
      ["toolactivated", "toolcancel"],
    );
    ctx.dispatch("toolactivated", { toolName: "again" });
    ctx.dispatch("toolcancel", { toolName: "again" });
    assert.deepEqual(activated, ["go_to_section"]);
    assert.deepEqual(cancelled, ["go_to_section"]);
  });

  it("is a no-op when document.modelContext is missing", () => {
    let windowTouched = false;
    const windowStub = {
      addEventListener() {
        windowTouched = true;
        throw new Error("window fallback is forbidden");
      },
    };
    Object.defineProperty(windowStub, "ontoolactivated", {
      set() {
        windowTouched = true;
        throw new Error("must not set window.ontoolactivated");
      },
      get() {
        return undefined;
      },
      configurable: true,
    });
    Object.defineProperty(windowStub, "ontoolcancel", {
      set() {
        windowTouched = true;
        throw new Error("must not set window.ontoolcancel");
      },
      get() {
        return undefined;
      },
      configurable: true,
    });
    const api = load({ modelContext: null }, windowStub);
    const stop = api.onToolActivated(() => {
      throw new Error("listener must not run");
    });
    assert.equal(typeof stop, "function");
    stop();
    api.onToolCancel(() => {})();
    assert.equal(windowTouched, false);
  });

  it("is a no-op when modelContext lacks addEventListener", () => {
    const api = load({
      modelContext: {
        registerTool() {
          return Promise.resolve();
        },
      },
    });
    let called = 0;
    const stop = api.onToolActivated(() => {
      called += 1;
    });
    stop();
    assert.equal(called, 0);
  });

  it("returns a no-op unsubscribe for non-function listeners", () => {
    const ctx = makeContext();
    const api = load({ modelContext: ctx });
    const stop = api.onToolActivated(null);
    assert.equal(typeof stop, "function");
    stop();
    assert.deepEqual(ctx.calls, []);
  });

  it("forwards listener options and tolerates removeEventListener failures", () => {
    const ctx = makeContext();
    let removeThrows = false;
    ctx.removeEventListener = function (type, listener, options) {
      ctx.calls.push({ op: "remove", type, listener, options });
      if (removeThrows) throw new Error("blocked");
      const set = ctx.listeners.get(type);
      if (set) set.delete(listener);
    };
    const api = load({ modelContext: ctx });
    const opts = { once: true };
    const listener = () => {};
    const stop = api.onToolCancel(listener, opts);
    assert.equal(ctx.calls[0].options, opts);
    removeThrows = true;
    stop();
    stop(); // second call must stay safe
    assert.equal(
      ctx.calls.filter((c) => c.op === "remove").length,
      1,
      "unsubscribe must be idempotent",
    );
  });

  it("shipped bundle never assigns window lifecycle handlers or navigator.modelContext", () => {
    const source = fs.readFileSync(SOURCE_CJS, "utf8");
    const built = fs.readFileSync(REGISTER_JS, "utf8");
    // Built asset (comments stripped) must not mention the forbidden surfaces.
    assert.equal(built.includes("window.ontoolactivated"), false);
    assert.equal(built.includes("window.ontoolcancel"), false);
    assert.equal(built.includes("navigator.modelContext"), false);
    // Source must not assign or call through those surfaces (comments may warn).
    assert.equal(/window\.ontoolactivated\s*=/.test(source), false);
    assert.equal(/window\.ontoolcancel\s*=/.test(source), false);
    assert.equal(
      /\bnavigator\.modelContext\.(addEventListener|ontool)/.test(source),
      false,
    );
    for (const blob of [source, built]) {
      assert.match(blob, /toolactivated/);
      assert.match(blob, /toolcancel/);
      assert.match(blob, /onToolActivated/);
      assert.match(blob, /onToolCancel/);
    }
  });

  it("does not invent a second event bus on the helper", () => {
    const ctx = makeContext();
    const api = load({ modelContext: ctx });
    assert.equal(typeof api.addEventListener, "undefined");
    assert.equal(typeof api.dispatchEvent, "undefined");
    assert.equal(typeof api.ontoolactivated, "undefined");
    assert.equal(typeof api.ontoolcancel, "undefined");
  });
});
