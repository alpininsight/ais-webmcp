/**
 * Contract tests for register.js against a mock document.modelContext.
 * Run: node --test tests/js/register.test.js
 */
"use strict";

const { describe, it, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const REGISTER_JS = require("node:fs").realpathSync(
  path.resolve(
    __dirname,
    "../../src/ais_webmcp/assets/register.js",
  ),
);

/**
 * Load a fresh copy of register.js with an injected mock modelContext.
 * @param {object|null} modelContext
 */
function loadHelper(modelContext) {
  // Drop cached module so each test gets a clean IIFE + Map state.
  delete require.cache[REGISTER_JS];
  globalThis.document = { modelContext };
  // Ensure window is undefined so the IIFE binds to globalThis.
  const hadWindow = Object.prototype.hasOwnProperty.call(globalThis, "window");
  const prevWindow = globalThis.window;
  try {
    // eslint-disable-next-line no-global-assign
    delete globalThis.window;
  } catch (_e) {
    globalThis.window = undefined;
  }
  const api = require(REGISTER_JS);
  if (hadWindow) {
    globalThis.window = prevWindow;
  }
  return api;
}

function makeMockContext(opts) {
  opts = opts || {};
  const tools = new Map();
  const registerCalls = [];

  const ctx = {
    registerCalls,
    tools,
    registerTool(tool, options) {
      registerCalls.push({ tool, options });
      if (typeof opts.onRegister === "function") {
        return opts.onRegister(tool, options, tools);
      }
      return new Promise((resolve, reject) => {
        if (opts.rejectWith) {
          reject(opts.rejectWith);
          return;
        }
        const signal = options && options.signal;
        const entry = {
          name: tool.name,
          title: tool.title || "",
          description: tool.description,
          inputSchema: tool.inputSchema,
          annotations: tool.annotations,
          execute: tool.execute,
        };
        if (signal) {
          if (signal.aborted) {
            // Already aborted — do not keep the tool.
            resolve();
            return;
          }
          signal.addEventListener(
            "abort",
            () => {
              tools.delete(tool.name);
            },
            { once: true },
          );
        }
        tools.set(tool.name, entry);
        resolve();
      });
    },
    async getTools() {
      return Array.from(tools.values()).sort((a, b) =>
        a.name < b.name ? -1 : a.name > b.name ? 1 : 0,
      );
    },
  };
  return ctx;
}

describe("InsightUiWebmcp registerTool contract", () => {
  afterEach(() => {
    delete require.cache[REGISTER_JS];
    delete globalThis.document;
    delete globalThis.InsightUiWebmcp;
  });

  it("maps id→name and human name→title with annotations.consequentialHint", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    const result = await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll or navigate the page to a named section anchor.",
      inputSchema: {
        type: "object",
        properties: { section: { type: "string" } },
        required: ["section"],
      },
      consequential: true,
      enabled: true,
      execute: async () => "ok",
    });

    assert.equal(result.ok, true);
    assert.equal(result.name, "go_to_section");
    assert.equal(ctx.registerCalls.length, 1);

    const { tool, options } = ctx.registerCalls[0];
    assert.equal(tool.name, "go_to_section");
    assert.equal(tool.title, "Go to section");
    assert.equal(
      tool.description,
      "Scroll or navigate the page to a named section anchor.",
    );
    assert.deepEqual(tool.inputSchema.required, ["section"]);
    assert.equal(typeof tool.execute, "function");
    assert.ok(tool.annotations);
    assert.equal(tool.annotations.consequentialHint, true);
    assert.equal("consequential" in tool, false);
    assert.ok(options.signal);
    assert.equal(options.signal instanceof AbortSignal, true);

    const listed = await ctx.getTools();
    assert.equal(listed.length, 1);
    assert.equal(listed[0].name, "go_to_section");
  });

  it("does not assume readOnlyHint when not consequential", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    await api.registerTool({
      inputSchema: { type: "object" },
      id: "list_sections",
      name: "List sections",
      description: "List available page section anchors on this host.",
      execute: async () => [],
    });

    const { tool } = ctx.registerCalls[0];
    assert.equal(tool.annotations.readOnlyHint, false);
    assert.equal(tool.annotations.consequentialHint, undefined);
    assert.equal("consequential" in tool, false);
  });

  it("passes through untrustedContentHint on annotations", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    await api.registerTool({
      inputSchema: { type: "object" },
      id: "get_section",
      name: "Get section",
      description: "Return the text content of a named section.",
      annotations: { untrustedContentHint: true, readOnlyHint: true },
      execute: async () => "text",
    });

    const { tool } = ctx.registerCalls[0];
    assert.equal(tool.annotations.untrustedContentHint, true);
    assert.equal(tool.annotations.readOnlyHint, true);
  });

  it("passes through annotations.debugging when the host sets it explicitly (#9)", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    await api.registerTool({
      inputSchema: { type: "object" },
      id: "inspect_dom_snapshot",
      name: "Inspect DOM snapshot",
      description: "DevTools-only snapshot helper.",
      annotations: { debugging: true, readOnlyHint: true },
      execute: async () => null,
    });

    const { tool } = ctx.registerCalls[0];
    assert.equal(tool.annotations.debugging, true);
    assert.equal(tool.annotations.readOnlyHint, true);
  });

  it("rejects unknown annotation keys including typos of debugging", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    const result = await api.registerTool({
      inputSchema: { type: "object" },
      id: "inspect_dom_snapshot",
      name: "Inspect",
      description: "Dev only.",
      annotations: { debuging: true, readOnlyHint: true },
      execute: async () => null,
    });

    assert.equal(result.ok, false);
    assert.match(result.error, /annotation/i);
    assert.equal(ctx.registerCalls.length, 0);
  });

  it("rejects tools without execute and does not call registerTool", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    const result = await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
    });

    assert.equal(result.ok, false);
    assert.match(result.error, /execute/i);
    assert.equal(ctx.registerCalls.length, 0);
  });

  it("rejects invisible or control characters in names and descriptions", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const cases = [
      { description: "Hello\u200bworld" },
      { description: "Hello\u202eworld" },
      { description: "Hello\u2065world" },
      { description: "Hello\u{E0001}world" },
      { title: "Probe\u200b" },
      { id: "pro\u0007be", name: "Probe" },
    ];
    for (const extra of cases) {
      const result = await api.registerTool({
        inputSchema: { type: "object" },
        id: "probe",
        name: "Probe",
        description: "Visible description.",
        execute: async () => "ok",
        ...extra,
      });
      assert.equal(result.ok, false, JSON.stringify(extra));
      assert.match(result.error, /invisible or control/i);
    }
    assert.equal(ctx.registerCalls.length, 0);

    const accented = await api.registerTool({
      inputSchema: { type: "object" },
      id: "probe",
      name: "Probe",
      description: "Liste des cafés.",
      execute: async () => "ok",
    });
    assert.equal(accented.ok, true);
  });

  it("rejects every Unicode format character in descriptions", async () => {
    const format = /\p{Cf}/u;
    const chars = [];
    for (let cp = 0; cp <= 0x10ffff; cp++) {
      if (cp >= 0xd800 && cp <= 0xdfff) continue;
      const ch = String.fromCodePoint(cp);
      if (format.test(ch)) chars.push(ch);
    }
    assert.ok(chars.includes("\u0600"));
    assert.ok(chars.includes("\u06dd"));

    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    for (const ch of chars) {
      const description = `Hello${ch}world`;
      const result = await api.registerTool({
        inputSchema: { type: "object" },
        id: "probe",
        name: "Probe",
        description,
        execute: async () => "ok",
      });
      const code = ch.codePointAt(0).toString(16).toUpperCase();
      assert.equal(result.ok, false, `U+${code}`);
      assert.match(result.error, /invisible or control/i, `U+${code}`);
    }
    assert.equal(ctx.registerCalls.length, 0);

    const cubeRoot = await api.registerTool({
      inputSchema: { type: "object" },
      id: "probe",
      name: "Probe",
      description: "Hello\u0606world",
      execute: async () => "ok",
    });
    assert.equal(cubeRoot.ok, true);
  });

  it("rejects control and format characters before trimming the description", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const cases = ["hello\n", "\thello", "hello\uFEFF", "\uFEFFhello"];
    for (const description of cases) {
      const result = await api.registerTool({
        inputSchema: { type: "object" },
        id: "probe",
        name: "Probe",
        description,
        execute: async () => "ok",
      });
      assert.equal(result.ok, false, JSON.stringify(description));
      assert.match(result.error, /invisible or control/i);
    }
    assert.equal(ctx.registerCalls.length, 0);

    const padded = await api.registerTool({
      inputSchema: { type: "object" },
      id: "probe",
      name: "Probe",
      description: "  hello  ",
      execute: async () => "ok",
    });
    assert.equal(padded.ok, true);
    assert.equal(ctx.tools.get("probe").description, "hello");
  });

  it("rejects empty description", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    const result = await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "   ",
      execute: async () => "ok",
    });

    assert.equal(result.ok, false);
    assert.match(result.error, /description/i);
    assert.equal(ctx.registerCalls.length, 0);
  });

  it("rejects invalid tool name with spaces (human label must be title)", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    const result = await api.registerTool({
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => "ok",
    });

    assert.equal(result.ok, false);
    assert.match(result.error, /name must match/i);
    assert.equal(ctx.registerCalls.length, 0);
  });

  it("awaits registerTool Promise and does not count rejection as success", async () => {
    const ctx = makeMockContext({
      rejectWith: new Error("browser rejected registration"),
    });
    const api = loadHelper(ctx);

    const result = await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => "ok",
    });

    assert.equal(result.ok, false);
    assert.match(result.error, /browser rejected registration/);
    assert.equal(ctx.registerCalls.length, 1);
    const listed = await ctx.getTools();
    assert.equal(listed.length, 0);
  });

  it("unregister via AbortSignal removes the tool from getTools()", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    const ok = await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => "ok",
    });
    assert.equal(ok.ok, true);
    assert.equal((await ctx.getTools()).length, 1);

    assert.equal(api.unregister("go_to_section"), true);
    assert.equal((await ctx.getTools()).length, 0);
  });

  it("dispose aborts all registration signals", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    await api.registerTool({
      inputSchema: { type: "object" },
      id: "a_tool",
      description: "A",
      execute: async () => 1,
    });
    await api.registerTool({
      inputSchema: { type: "object" },
      id: "b_tool",
      description: "B",
      execute: async () => 2,
    });
    assert.equal((await ctx.getTools()).length, 2);
    assert.equal(api.dispose(), 2);
    assert.equal((await ctx.getTools()).length, 0);
  });

  it("never calls unregisterTool on modelContext", async () => {
    const ctx = makeMockContext();
    let unregisterCalled = false;
    ctx.unregisterTool = function () {
      unregisterCalled = true;
    };
    const api = loadHelper(ctx);

    await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => "ok",
    });
    api.unregister("go_to_section");
    assert.equal(unregisterCalled, false);
  });

  it("registerFromManifest only registers tools with handlers and reports errors", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    const summary = await api.registerFromManifest(
      {
        profile: "webpage",
        version: "1",
        tools: [
          {
            inputSchema: { type: "object" },
            id: "go_to_section",
            inputSchema: { type: "object" },
            name: "Go to section",
            description: "Scroll to section.",
          },
          {
            inputSchema: { type: "object" },
            id: "subscribe_newsletter",
            name: "Subscribe newsletter",
            description: "Subscribe an email.",
            consequential: true,
            enabled: true,
          },
          {
            inputSchema: { type: "object" },
            id: "list_sections",
            name: "List sections",
            description: "List sections.",
          },
        ],
      },
      {
        go_to_section: async ({ section }) => section,
        subscribe_newsletter: async ({ email }) => email,
      },
    );

    assert.equal(summary.registered, 2);
    assert.equal(summary.errors.length, 1);
    assert.equal(summary.errors[0].name, "list_sections");
    assert.match(summary.errors[0].error, /execute/i);

    const listed = await ctx.getTools();
    assert.deepEqual(listed.map((t) => t.name).sort(), [
      "go_to_section",
      "subscribe_newsletter",
    ]);
    const sub = listed.find((t) => t.name === "subscribe_newsletter");
    assert.equal(sub.annotations.consequentialHint, true);
    assert.equal("consequential" in sub, false);
  });

  it("execute wrapper passes object input and signal through to handler", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    let seenInput;
    let seenSignal;

    await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async (input, { signal }) => {
        seenInput = input;
        seenSignal = signal;
        return "done";
      },
    });

    const { tool } = ctx.registerCalls[0];
    const ac = new AbortController();
    const out = await tool.execute(
      { section: "contact" },
      { signal: ac.signal },
    );
    assert.equal(out, "done");
    assert.deepEqual(seenInput, { section: "contact" });
    assert.equal(seenSignal, ac.signal);
  });

  it("isSupported is false without document.modelContext", () => {
    const api = loadHelper(null);
    assert.equal(api.isSupported(), false);
  });

  it("targets document.modelContext only (no navigator fallback used)", async () => {
    // Getter-only navigator must not be read; registration stays on document.
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      get() {
        throw new Error("navigator is getter-only and must not be read");
      },
    });
    try {
      const ctx = makeMockContext();
      const api = loadHelper(ctx);
      await api.registerTool({
        inputSchema: { type: "object" },
        id: "ok_tool",
        description: "ok",
        execute: async () => "ok",
      });
      assert.equal(ctx.registerCalls.length, 1);
    } finally {
      delete globalThis.navigator;
    }
  });

  it("reports a missing browser API instead of succeeding", async () => {
    const api = loadHelper({});
    const result = await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => "ok",
    });
    assert.equal(result.ok, false);
    assert.match(result.error, /unavailable/i);
  });

  it("counts a synchronous registerTool throw as failure", async () => {
    const ctx = makeMockContext({
      onRegister() {
        throw new Error("sync registration failed");
      },
    });
    const api = loadHelper(ctx);
    const result = await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => "ok",
    });
    assert.equal(result.ok, false);
    assert.match(result.error, /sync registration failed/);
  });

  it("does not keep a tool when the external signal is already aborted", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const ac = new AbortController();
    ac.abort();
    const result = await api.registerTool(
      {
        inputSchema: { type: "object" },
        id: "go_to_section",
        inputSchema: { type: "object" },
        name: "Go to section",
        description: "Scroll to section.",
        execute: async () => "ok",
      },
      { signal: ac.signal },
    );
    assert.equal(result.ok, false);
    assert.match(result.error, /aborted/i);
    assert.equal((await ctx.getTools()).length, 0);
  });

  it("replacing a pending registration aborts the previous signal", async () => {
    const signals = [];
    const resolvers = [];
    const ctx = makeMockContext({
      onRegister(tool, options, tools) {
        signals.push(options.signal);
        return new Promise((resolve) => {
          resolvers.push(() => {
            if (!options.signal.aborted) {
              tools.set(tool.name, {
                name: tool.name,
                annotations: tool.annotations,
                execute: tool.execute,
              });
            }
            resolve();
          });
        });
      },
    });
    const api = loadHelper(ctx);
    const spec = {
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => "ok",
    };
    const first = api.registerTool(spec);
    const second = api.registerTool(spec);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(signals.length, 2);
    assert.equal(signals[0].aborted, true);
    assert.equal(signals[1].aborted, false);
    resolvers.forEach((finish) => finish());
    const firstResult = await first;
    const secondResult = await second;
    assert.equal(firstResult.ok, false);
    assert.match(firstResult.error, /aborted/i);
    assert.equal(secondResult.ok, true);
    assert.equal((await ctx.getTools()).length, 1);
  });

  it("parses a JSON string defensively and warns once", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    let seen;
    try {
      await api.registerTool({
        inputSchema: { type: "object" },
        id: "go_to_section",
        name: "Go to section",
        description: "Scroll to section.",
        execute: async (input) => {
          seen = input;
          return "done";
        },
      });
      const { tool } = ctx.registerCalls[0];
      const out = await tool.execute('{"section":"contact"}');
      assert.equal(out, "done");
      assert.deepEqual(seen, { section: "contact" });
      await tool.execute('{"section":"about"}');
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /plain object/);
      assert.equal(warnings[0].includes("contact"), false);
    } finally {
      console.warn = previous;
    }
  });

  it("propagates a handler rejection and a synchronous throw", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => {
        throw new Error("handler failed");
      },
    });
    const rejected = ctx.registerCalls[0].tool;
    await assert.rejects(
      () => rejected.execute({ section: "contact" }),
      (err) => err && err.message === "handler failed",
    );

    await api.registerTool({
      inputSchema: { type: "object" },
      id: "list_sections",
      name: "List sections",
      description: "List sections.",
      execute: () => {
        throw new Error("sync handler");
      },
    });
    const thrown = ctx.registerCalls[1].tool;
    await assert.rejects(
      () => thrown.execute({}),
      (err) => err && err.message === "sync handler",
    );
  });

  it("rejects execute for Promise.reject() with no reason", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    await api.registerTool({
      inputSchema: { type: "object" },
      id: "reject_bare",
      name: "Reject bare",
      description: "Reject with no reason.",
      execute: () => Promise.reject(),
    });
    const { tool } = ctx.registerCalls[0];
    await assert.rejects(
      () => tool.execute({}),
      (err) => err === undefined,
    );
  });

  it("rejects execute for Promise.reject(null)", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    await api.registerTool({
      inputSchema: { type: "object" },
      id: "reject_null",
      name: "Reject null",
      description: "Reject with null.",
      execute: () => Promise.reject(null),
    });
    const { tool } = ctx.registerCalls[0];
    await assert.rejects(
      () => tool.execute({}),
      (err) => err === null,
    );
  });

  it("rejects execute when the handler throws undefined", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    await api.registerTool({
      inputSchema: { type: "object" },
      id: "throw_undefined",
      name: "Throw undefined",
      description: "Throw undefined synchronously.",
      execute: () => {
        throw undefined;
      },
    });
    const { tool } = ctx.registerCalls[0];
    await assert.rejects(
      () => tool.execute({}),
      (err) => err === undefined,
    );
  });

  it("rejects execute immediately when its signal is already aborted", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => "ok",
    });
    const { tool } = ctx.registerCalls[0];
    const ac = new AbortController();
    ac.abort();
    await assert.rejects(
      () => tool.execute({ section: "contact" }, { signal: ac.signal }),
      (err) => err && err.name === "AbortError",
    );
  });

  it("rejects in-flight execute on abort and ignores a later success", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    let resolveHandler;
    await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      name: "Go to section",
      description: "Scroll to section.",
      execute: () =>
        new Promise((resolve) => {
          resolveHandler = resolve;
        }),
    });
    const { tool } = ctx.registerCalls[0];
    const ac = new AbortController();
    const pending = tool.execute(
      { section: "contact" },
      { signal: ac.signal },
    );
    ac.abort();
    resolveHandler("scrolled");
    await assert.rejects(
      () => pending,
      (err) => err && err.name === "AbortError",
    );
  });

  it("reference go_to_section does not scroll after its execute signal aborts", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    let started;
    const startedPromise = new Promise((resolve) => {
      started = resolve;
    });
    let scrolled = false;
    await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      name: "Go to section",
      description: "Scroll to section.",
      execute: (input, { signal }) =>
        new Promise((resolve, reject) => {
          started();
          const timer = setTimeout(() => {
            if (signal && signal.aborted) {
              reject(Object.assign(new Error("The operation was aborted."), { name: "AbortError" }));
              return;
            }
            scrolled = true;
            resolve({ section: input.section, navigated: true });
          }, 30);
          if (signal) {
            signal.addEventListener(
              "abort",
              () => {
                clearTimeout(timer);
              },
              { once: true },
            );
          }
        }),
    });
    const { tool } = ctx.registerCalls[0];
    const ac = new AbortController();
    const pending = tool.execute(
      { section: "contact" },
      { signal: ac.signal },
    );
    await startedPromise;
    ac.abort();
    await assert.rejects(
      () => pending,
      (err) => err && err.name === "AbortError",
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(scrolled, false);
  });

  it("unregister does not abort an in-flight execute signal", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    let seenSignal;
    let release;
    const started = new Promise((resolve) => {
      release = resolve;
    });
    await api.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: (input, { signal }) => {
        seenSignal = signal;
        release();
        return new Promise((resolve) => {
          setTimeout(() => resolve("finished"), 20);
        });
      },
    });
    const { tool } = ctx.registerCalls[0];
    const execSignal = new AbortController();
    const pending = tool.execute(
      { section: "contact" },
      { signal: execSignal.signal },
    );
    await started;
    assert.equal(api.unregister("go_to_section"), true);
    assert.equal(seenSignal.aborted, false);
    assert.equal(await pending, "finished");
    assert.equal((await ctx.getTools()).length, 0);
  });

  it("a second init has its own controller map and dispose is idempotent", async () => {
    const ctx = makeMockContext();
    const first = loadHelper(ctx);
    await first.registerTool({
      inputSchema: { type: "object" },
      id: "go_to_section",
      inputSchema: { type: "object" },
      name: "Go to section",
      description: "Scroll to section.",
      execute: async () => "ok",
    });
    const second = loadHelper(ctx);
    assert.equal(second.dispose(), 0);
    assert.equal((await ctx.getTools()).length, 1);
    assert.equal(first.dispose(), 1);
    assert.equal(first.dispose(), 0);
    assert.equal((await ctx.getTools()).length, 0);
  });

  it("shared lifecycle abort unregisters every manifest tool (htmx/turbo cleanup)", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const lifecycle = new AbortController();
    const summary = await api.registerFromManifest(
      {
        profile: "webpage",
        version: "1",
        tools: [
          {
            inputSchema: { type: "object" },
            id: "list_sections",
            name: "List sections",
            description: "List sections.",
          },
          {
            inputSchema: { type: "object" },
            id: "go_to_section",
            name: "Go to section",
            description: "Scroll to section.",
          },
        ],
      },
      {
        list_sections: async () => [],
        go_to_section: async () => "ok",
      },
      { signal: lifecycle.signal },
    );
    assert.equal(summary.registered, 2);
    lifecycle.abort();
    assert.equal((await ctx.getTools()).length, 0);
    // Helper map still tracks controllers until dispose; second dispose is a no-op.
    assert.equal(api.dispose(), 2);
    assert.equal(api.dispose(), 0);
  });

  it("does not register subscribe_newsletter by default", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    assert.equal(await api.registerDefaults(), 0);
    assert.equal(ctx.registerCalls.length, 0);

    const summary = await api.registerFromManifest(
      {
        profile: "webpage",
        version: "1",
        tools: [
          {
            inputSchema: { type: "object" },
            id: "list_sections",
            name: "List sections",
            description: "List sections.",
          },
          {
            inputSchema: { type: "object" },
            id: "subscribe_newsletter",
            name: "Subscribe newsletter",
            description: "Subscribe an email.",
            consequential: true,
            enabled: false,
          },
          {
            inputSchema: { type: "object" },
            id: "go_to_section",
            name: "Go to section",
            description: "Scroll to section.",
          },
        ],
      },
      {
        list_sections: async () => [],
        go_to_section: async () => "ok",
      },
    );
    assert.equal(summary.registered, 2);
    const names = (await ctx.getTools()).map((tool) => tool.name);
    assert.equal(names.includes("subscribe_newsletter"), false);
    assert.ok(
      summary.errors.some((err) => err.name === "subscribe_newsletter"),
    );
  });

  it("forwards outputSchema and the output_schema alias", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const outputSchema = {
      type: "object",
      properties: { sections: { type: "array", items: { type: "string" } } },
    };
    const result = await api.registerTool({
      id: "list_sections",
      description: "List sections",
      inputSchema: { type: "object", properties: {} },
      outputSchema,
      execute: async () => ({ sections: [] }),
    });
    assert.equal(result.ok, true);
    assert.deepEqual(ctx.registerCalls[0].tool.outputSchema, outputSchema);

    const alias = await api.registerTool({
      id: "list_sections",
      description: "List sections",
      inputSchema: { type: "object", properties: {} },
      output_schema: { type: "string" },
      execute: async () => "ok",
    });
    assert.equal(alias.ok, true);
    assert.deepEqual(ctx.registerCalls[1].tool.outputSchema, { type: "string" });
  });

  it("registers a tool that omits outputSchema", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const result = await api.registerTool({
      id: "list_sections",
      description: "List sections",
      inputSchema: { type: "object", properties: {} },
      execute: async () => [],
    });
    assert.equal(result.ok, true);
    assert.equal("outputSchema" in ctx.registerCalls[0].tool, false);
  });

  it("returns ok false for a circular output schema", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const outputSchema = { type: "object" };
    outputSchema.properties = { self: outputSchema };
    const result = await api.registerTool({
      id: "list_sections",
      description: "List sections",
      inputSchema: { type: "object", properties: {} },
      outputSchema,
      execute: async () => ({}),
    });
    assert.equal(result.ok, false);
    assert.match(result.error, /output schema/i);
    assert.equal(ctx.registerCalls.length, 0);
  });

  it("rejects an invalid or ambiguous output schema", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const base = {
      id: "list_sections",
      description: "List sections",
      inputSchema: { type: "object", properties: {} },
      execute: async () => ({}),
    };
    const invalid = await api.registerTool({
      ...base,
      outputSchema: { type: "object", required: "nope" },
    });
    assert.equal(invalid.ok, false);
    assert.match(invalid.error, /output schema/i);

    const arraySchema = await api.registerTool({ ...base, outputSchema: [] });
    assert.equal(arraySchema.ok, false);
    assert.match(arraySchema.error, /output schema/i);

    const both = await api.registerTool({
      ...base,
      outputSchema: { type: "object" },
      output_schema: { type: "string" },
    });
    assert.equal(both.ok, false);
    assert.match(both.error, /outputSchema/);
    assert.equal(ctx.registerCalls.length, 0);
  });

  it("registerFromManifest copies outputSchema onto the registered tool", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const summary = await api.registerFromManifest(
      {
        profile: "webpage",
        version: "1",
        tools: [
          {
            id: "probe",
            name: "Probe",
            description: "Contract probe",
            inputSchema: {
              type: "object",
              properties: { value: { type: "string" } },
            },
            outputSchema: {
              type: "object",
              properties: { ok: { type: "boolean" } },
            },
          },
        ],
      },
      { probe: async () => ({ ok: true }) },
    );
    assert.equal(summary.registered, 1);
    assert.equal(summary.errors.length, 0);
    assert.equal(ctx.registerCalls[0].tool.outputSchema.properties.ok.type, "boolean");
  });

  it("passes the outputSchema object through unchanged", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const outputSchema = {
      type: "object",
      properties: { ok: { type: "boolean" } },
    };
    const result = await api.registerTool({
      id: "probe",
      description: "Probe",
      inputSchema: { type: "object", properties: {} },
      outputSchema,
      execute: async () => ({ ok: true }),
    });
    assert.equal(result.ok, true);
    assert.equal(ctx.registerCalls.length, 1);
    assert.equal(ctx.registerCalls[0].tool.outputSchema, outputSchema);
  });

  it("retries without outputSchema when the browser rejects that member", async () => {
    const ctx = makeMockContext({
      onRegister(tool) {
        if (Object.prototype.hasOwnProperty.call(tool, "outputSchema")) {
          throw new TypeError("Unexpected property outputSchema");
        }
      },
    });
    const api = loadHelper(ctx);
    const outputSchema = {
      type: "object",
      properties: { ok: { type: "boolean" } },
    };
    const first = await api.registerTool({
      id: "probe",
      description: "Probe",
      inputSchema: { type: "object", properties: {} },
      outputSchema,
      execute: async () => ({ ok: true }),
    });
    assert.equal(first.ok, true);
    assert.equal(ctx.registerCalls.length, 2);
    assert.equal(ctx.registerCalls[0].tool.outputSchema, outputSchema);
    assert.equal("outputSchema" in ctx.registerCalls[1].tool, false);
    assert.equal(
      ctx.registerCalls[1].tool.execute,
      ctx.registerCalls[0].tool.execute,
    );

    const second = await api.registerTool({
      id: "other",
      description: "Other",
      inputSchema: { type: "object", properties: {} },
      outputSchema: { type: "string" },
      execute: async () => "ok",
    });
    assert.equal(second.ok, true);
    assert.equal(ctx.registerCalls.length, 3);
    assert.equal("outputSchema" in ctx.registerCalls[2].tool, false);
  });

  it("retries when registerTool rejects the outputSchema member", async () => {
    const ctx = makeMockContext({
      onRegister(tool) {
        if (Object.prototype.hasOwnProperty.call(tool, "outputSchema")) {
          return Promise.reject(
            new TypeError("outputSchema is not a valid dictionary member"),
          );
        }
      },
    });
    const api = loadHelper(ctx);
    const outputSchema = { type: "string" };
    const result = await api.registerTool({
      id: "probe",
      description: "Probe",
      inputSchema: { type: "object", properties: {} },
      outputSchema,
      execute: async () => "ok",
    });
    assert.equal(result.ok, true);
    assert.equal(ctx.registerCalls.length, 2);
    assert.equal(ctx.registerCalls[0].tool.outputSchema, outputSchema);
    assert.equal("outputSchema" in ctx.registerCalls[1].tool, false);
  });

  it("surfaces the retry error when registration without outputSchema also fails", async () => {
    const ctx = makeMockContext({
      onRegister(tool) {
        if (Object.prototype.hasOwnProperty.call(tool, "outputSchema")) {
          throw new TypeError("Unexpected property outputSchema");
        }
        throw new Error("retry registration failed");
      },
    });
    const api = loadHelper(ctx);
    const result = await api.registerTool({
      id: "probe",
      description: "Probe",
      inputSchema: { type: "object", properties: {} },
      outputSchema: { type: "string" },
      execute: async () => "ok",
    });
    assert.equal(result.ok, false);
    assert.equal(ctx.registerCalls.length, 2);
    assert.equal(ctx.registerCalls[0].tool.outputSchema.type, "string");
    assert.equal("outputSchema" in ctx.registerCalls[1].tool, false);
    assert.equal(result.error, "retry registration failed");
  });

  it("does not retry Chrome's invalid output schema TypeError", async () => {
    const ctx = makeMockContext({
      onRegister() {
        return Promise.reject(
          new TypeError("invalid output schema: toJSON() returns undefined"),
        );
      },
    });
    const api = loadHelper(ctx);
    const result = await api.registerTool({
      id: "probe",
      description: "Probe",
      inputSchema: { type: "object", properties: {} },
      outputSchema: { type: "object" },
      execute: async () => ({}),
    });
    assert.equal(result.ok, false);
    assert.equal(ctx.registerCalls.length, 1);
    assert.equal(
      result.error,
      "invalid output schema: toJSON() returns undefined",
    );
  });

  it("does not drop outputSchema when registration fails for another reason", async () => {
    const ctx = makeMockContext({
      onRegister() {
        return Promise.reject(new TypeError("outputSchema is not valid JSON"));
      },
    });
    const api = loadHelper(ctx);
    const invalid = await api.registerTool({
      id: "probe",
      description: "Probe",
      inputSchema: { type: "object", properties: {} },
      outputSchema: { type: "object" },
      execute: async () => ({}),
    });
    assert.equal(invalid.ok, false);
    assert.match(invalid.error, /valid JSON/);
    assert.equal(ctx.registerCalls.length, 1);
    assert.equal(ctx.registerCalls[0].tool.outputSchema.type, "object");

    const other = makeMockContext({
      onRegister() {
        throw new Error("duplicate tool");
      },
    });
    const api2 = loadHelper(other);
    const failed = await api2.registerTool({
      id: "probe",
      description: "Probe",
      inputSchema: { type: "object", properties: {} },
      outputSchema: { type: "string" },
      execute: async () => "ok",
    });
    assert.equal(failed.ok, false);
    assert.match(failed.error, /duplicate tool/);
    assert.equal(other.registerCalls.length, 1);
    assert.equal(other.registerCalls[0].tool.outputSchema.type, "string");
  });

  it("warns for an outputSchema mismatch only when validateOutput is set", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    const outputSchema = {
      type: "object",
      required: ["ok"],
      additionalProperties: false,
      properties: {
        ok: { type: "boolean" },
        items: { type: "array", items: { type: "string" } },
      },
    };
    try {
      await api.registerTool({
        id: "probe",
        description: "Probe",
        inputSchema: { type: "object", properties: {} },
        outputSchema,
        execute: async () => ({ extra: true, items: [1] }),
      });
      const silent = ctx.registerCalls[0].tool;
      const quiet = await silent.execute({});
      assert.deepEqual(quiet, { extra: true, items: [1] });
      assert.equal(warnings.length, 0);

      await api.registerTool(
        {
          id: "probe",
          description: "Probe",
          inputSchema: { type: "object", properties: {} },
          outputSchema,
          execute: async () => ({ extra: true, items: [1] }),
        },
        { validateOutput: true },
      );
      const checked = ctx.registerCalls[1].tool;
      const secret = "do-not-log-this-result";
      const noisy = await checked.execute({});
      assert.deepEqual(noisy, { extra: true, items: [1] });
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /probe/);
      assert.match(warnings[0], /outputSchema/);
      assert.match(warnings[0], /returned anyway/);
      assert.equal(warnings[0].includes(secret), false);
      assert.equal(warnings[0].includes("extra"), false);
      await checked.execute({});
      assert.equal(warnings.length, 1);

      const match = await api.registerTool(
        {
          id: "exact",
          description: "Exact",
          inputSchema: { type: "object", properties: {} },
          outputSchema,
          execute: async () => ({ ok: true, items: ["a"] }),
        },
        { validateOutput: true },
      );
      assert.equal(match.ok, true);
      assert.deepEqual(await ctx.registerCalls[2].tool.execute({}), {
        ok: true,
        items: ["a"],
      });
      assert.equal(warnings.length, 1);
    } finally {
      console.warn = previous;
    }
  });

  it("validateOutput covers type, enum, and $ref limits without rejecting", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "count",
          description: "Count",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { type: "integer", enum: [1, 2] },
          execute: async (input) => input.mode,
        },
        { validateOutput: true },
      );
      const tool = ctx.registerCalls[0].tool;
      assert.equal(await tool.execute({ mode: 1.5 }), 1.5);
      assert.match(warnings[0], /expected integer/);
      assert.match(warnings[0], /not in enum/);
      assert.equal(warnings[0].includes("1.5"), false);
      warnings.length = 0;
      assert.equal(await tool.execute({ mode: 2 }), 2);
      assert.equal(warnings.length, 0);

      await api.registerTool(
        {
          id: "ref_only",
          description: "Ref",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { $ref: "#/$defs/out" },
          execute: async () => "not-checked",
        },
        { validateOutput: true },
      );
      assert.equal(await ctx.registerCalls[1].tool.execute({}), "not-checked");
      assert.equal(warnings.length, 0);
    } finally {
      console.warn = previous;
    }
  });

  function nest(levels, leaf) {
    let node = leaf;
    for (let i = 0; i < levels; i += 1) {
      node = { n: node };
    }
    return node;
  }

  it("warns for additionalProperties false when properties is omitted", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "closed",
          description: "Closed",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { type: "object", additionalProperties: false },
          execute: async (input) => input.value,
        },
        { validateOutput: true },
      );
      const tool = ctx.registerCalls[0].tool;
      assert.deepEqual(await tool.execute({ value: {} }), {});
      assert.equal(warnings.length, 0);
      const extra = { extra: 1 };
      assert.deepEqual(await tool.execute({ value: extra }), extra);
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /additionalProperties does not allow/);
      assert.equal(warnings[0].includes("extra"), false);
    } finally {
      console.warn = previous;
    }
  });

  it("does not warn for patternProperties that additionalProperties allows", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "labels",
          description: "Labels",
          inputSchema: { type: "object", properties: {} },
          outputSchema: {
            type: "object",
            additionalProperties: false,
            patternProperties: { "^x-": { type: "string" } },
          },
          execute: async (input) => input.value,
        },
        { validateOutput: true },
      );
      const tool = ctx.registerCalls[0].tool;
      const valid = { "x-a": "ok" };
      assert.deepEqual(await tool.execute({ value: valid }), valid);
      assert.equal(warnings.length, 0);

      const wrongType = { "x-a": 1 };
      assert.deepEqual(await tool.execute({ value: wrongType }), wrongType);
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /expected string/);
      assert.equal(warnings[0].includes("additionalProperties"), false);

      warnings.length = 0;
      const unexpected = { y: 1 };
      assert.deepEqual(await tool.execute({ value: unexpected }), unexpected);
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /additionalProperties does not allow/);
      assert.equal(warnings[0].includes(".y"), false);
    } finally {
      console.warn = previous;
    }
  });

  it("matches pattern and patternProperties by Unicode code point", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "glyph",
          description: "Glyph",
          inputSchema: { type: "object", properties: {} },
          outputSchema: {
            type: "object",
            additionalProperties: false,
            patternProperties: { "^.$": { type: "string" } },
          },
          execute: async (input) => input.value,
        },
        { validateOutput: true },
      );
      const tool = ctx.registerCalls[0].tool;
      const emoji = { "😀": "ok" };
      assert.deepEqual(await tool.execute({ value: emoji }), emoji);
      assert.equal(warnings.length, 0);
      const two = { ab: "ok" };
      assert.deepEqual(await tool.execute({ value: two }), two);
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /additionalProperties does not allow/);

    } finally {
      console.warn = previous;
    }
  });

  it("does not evaluate a string pattern", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "text",
          description: "Text",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { type: "string", pattern: "^(a+)+$" },
          execute: async () => "a".repeat(28) + "!",
        },
        { validateOutput: true },
      );
      const started = Date.now();
      assert.equal(
        await ctx.registerCalls[0].tool.execute({}),
        "a".repeat(28) + "!",
      );
      assert.ok(Date.now() - started < 200);
      assert.equal(warnings.length, 0);
    } finally {
      console.warn = previous;
    }
  });

  it("skips an invalid pattern instead of warning a mismatch", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "broken_keys",
          description: "Broken key pattern",
          inputSchema: { type: "object", properties: {} },
          outputSchema: {
            type: "object",
            additionalProperties: false,
            patternProperties: { "(": { type: "string" } },
          },
          execute: async () => ({ a: "ok" }),
        },
        { validateOutput: true },
      );
      assert.deepEqual(await ctx.registerCalls[0].tool.execute({}), { a: "ok" });
      assert.deepEqual(await ctx.registerCalls[0].tool.execute({}), { a: "ok" });
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /not checked/);
      assert.equal(warnings[0].includes("additionalProperties"), false);
    } finally {
      console.warn = previous;
    }
  });

  it("applies every matching patternProperties schema and named properties", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "overlap",
          description: "Overlap",
          inputSchema: { type: "object", properties: {} },
          outputSchema: {
            type: "object",
            additionalProperties: false,
            properties: { name: { type: "string" } },
            patternProperties: {
              "^n": { enum: ["ok", "end"] },
              e$: { const: "ok" },
            },
          },
          execute: async (input) => input.value,
        },
        { validateOutput: true },
      );
      const tool = ctx.registerCalls[0].tool;
      assert.deepEqual(await tool.execute({ value: { name: "ok" } }), {
        name: "ok",
      });
      assert.equal(warnings.length, 0);

      assert.deepEqual(await tool.execute({ value: { name: "end" } }), {
        name: "end",
      });
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /does not match const/);
      assert.equal(warnings[0].includes("not in enum"), false);
      assert.equal(warnings[0].includes("expected string"), false);

      warnings.length = 0;
      assert.deepEqual(await tool.execute({ value: { name: "no" } }), {
        name: "no",
      });
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /not in enum/);
      assert.match(warnings[0], /does not match const/);
      assert.equal(warnings[0].includes("expected string"), false);

      warnings.length = 0;
      assert.deepEqual(await tool.execute({ value: { name: 1 } }), { name: 1 });
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /expected string/);
      assert.equal(warnings[0].includes("additionalProperties"), false);
    } finally {
      console.warn = previous;
    }
  });

  it("skips boolean subschemas, items false, and an empty prefixItems", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "bool_schema",
          description: "Boolean subschema",
          inputSchema: { type: "object", properties: {} },
          outputSchema: {
            type: "object",
            additionalProperties: false,
            properties: { a: true },
          },
          execute: async () => ({ a: 1 }),
        },
        { validateOutput: true },
      );
      assert.deepEqual(await ctx.registerCalls[0].tool.execute({}), { a: 1 });
      assert.equal(warnings.length, 0);

      await api.registerTool(
        {
          id: "items_false",
          description: "Items false",
          inputSchema: { type: "object", properties: {} },
          outputSchema: {
            type: "array",
            prefixItems: [{ type: "string" }],
            items: false,
          },
          execute: async () => ["ok", "extra"],
        },
        { validateOutput: true },
      );
      assert.deepEqual(await ctx.registerCalls[1].tool.execute({}), [
        "ok",
        "extra",
      ]);
      assert.equal(warnings.length, 0);

      const emptyPrefix = await api.registerTool(
        {
          id: "empty_prefix",
          description: "Empty prefix",
          inputSchema: { type: "object", properties: {} },
          outputSchema: {
            type: "array",
            prefixItems: [],
            items: { type: "string" },
          },
          execute: async (input) => input.rows,
        },
        { validateOutput: true },
      );
      // Draft 2020-12 schemaArray requires minItems 1, so an empty
      // prefixItems never reaches the result check.
      assert.equal(emptyPrefix.ok, false);
      assert.match(emptyPrefix.error, /output schema/i);
      assert.equal(ctx.registerCalls.length, 2);
      assert.equal(warnings.length, 0);
    } finally {
      console.warn = previous;
    }
  });

  it("checks prefixItems before items and does not warn on a valid tuple", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    const outputSchema = {
      type: "array",
      prefixItems: [{ type: "string" }, { type: "number" }],
      items: { type: "boolean" },
    };
    try {
      await api.registerTool(
        {
          id: "tuple",
          description: "Tuple",
          inputSchema: { type: "object", properties: {} },
          outputSchema,
          execute: async (input) => input.rows,
        },
        { validateOutput: true },
      );
      const tool = ctx.registerCalls[0].tool;
      const valid = ["a", 1, true];
      assert.deepEqual(await tool.execute({ rows: valid }), valid);
      assert.equal(warnings.length, 0);
      assert.deepEqual(await tool.execute({ rows: ["a"] }), ["a"]);
      assert.equal(warnings.length, 0);

      const prefixMismatch = [1, 1, true];
      assert.deepEqual(
        await tool.execute({ rows: prefixMismatch }),
        prefixMismatch,
      );
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /\$\[0\] expected string/);
      assert.equal(warnings[0].includes("$[1]"), false);
      assert.equal(warnings[0].includes("$[2]"), false);

      warnings.length = 0;
      const itemMismatch = ["a", 1, "no"];
      assert.deepEqual(await tool.execute({ rows: itemMismatch }), itemMismatch);
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /\$\[2\] expected boolean/);
      assert.equal(warnings[0].includes("$[0]"), false);

      warnings.length = 0;
      await api.registerTool(
        {
          id: "prefix_only",
          description: "Prefix only",
          inputSchema: { type: "object", properties: {} },
          outputSchema: {
            type: "array",
            prefixItems: [{ type: "string" }, { type: "number" }],
          },
          execute: async () => ["a", 1, "free"],
        },
        { validateOutput: true },
      );
      assert.deepEqual(await ctx.registerCalls[1].tool.execute({}), [
        "a",
        1,
        "free",
      ]);
      assert.equal(warnings.length, 0);
    } finally {
      console.warn = previous;
    }
  });

  it("checks items past the twentieth array element", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "rows",
          description: "Rows",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { type: "array", items: { type: "string" } },
          execute: async (input) => input.rows,
        },
        { validateOutput: true },
      );
      const tool = ctx.registerCalls[0].tool;
      const good = Array.from({ length: 25 }, () => "ok");
      assert.deepEqual(await tool.execute({ rows: good }), good);
      assert.equal(warnings.length, 0);
      const bad = good.slice();
      bad[20] = 1;
      assert.deepEqual(await tool.execute({ rows: bad }), bad);
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /\$\[20\] expected string/);
      assert.equal(warnings[0].includes("1"), false);
    } finally {
      console.warn = previous;
    }
  });

  it("lists at most three paths when more items mismatch", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      await api.registerTool(
        {
          id: "rows",
          description: "Rows",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { type: "array", items: { type: "string" } },
          execute: async (input) => input.rows,
        },
        { validateOutput: true },
      );
      const rows = [0, 1, 2, 3, 4];
      assert.deepEqual(await ctx.registerCalls[0].tool.execute({ rows }), rows);
      assert.equal(warnings.length, 1);
      const listed = warnings[0].match(/\$\[\d+\] expected string/g) || [];
      assert.deepEqual(listed, [
        "$[0] expected string",
        "$[1] expected string",
        "$[2] expected string",
      ]);
      assert.equal(warnings[0].includes("$[3]"), false);
      assert.equal(warnings[0].includes("$[4]"), false);
    } finally {
      console.warn = previous;
    }
  });

  it("does not warn when a deep const or enum value is equal", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    const deep = nest(9, { v: 1 });
    const same = nest(9, { v: 1 });
    try {
      await api.registerTool(
        {
          id: "deep_const",
          description: "Deep const",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { const: deep },
          execute: async () => same,
        },
        { validateOutput: true },
      );
      assert.deepEqual(await ctx.registerCalls[0].tool.execute({}), same);
      assert.equal(warnings.length, 0);

      await api.registerTool(
        {
          id: "deep_enum",
          description: "Deep enum",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { enum: [nest(9, { v: 1 })] },
          execute: async () => nest(9, { v: 1 }),
        },
        { validateOutput: true },
      );
      await ctx.registerCalls[1].tool.execute({});
      assert.equal(warnings.length, 0);

      await api.registerTool(
        {
          id: "shallow",
          description: "Shallow",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { const: { n: 1 }, enum: [{ n: 1 }] },
          execute: async () => ({ n: 2 }),
        },
        { validateOutput: true },
      );
      assert.deepEqual(await ctx.registerCalls[2].tool.execute({}), { n: 2 });
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /does not match const/);
      assert.match(warnings[0], /not in enum/);
    } finally {
      console.warn = previous;
    }
  });

  it("a throwing console.warn does not reject the tool result", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const previous = console.warn;
    console.warn = () => {
      throw new Error("warn failed");
    };
    try {
      await api.registerTool(
        {
          id: "probe",
          description: "Probe",
          inputSchema: { type: "object", properties: {} },
          outputSchema: { type: "string" },
          execute: async () => 1,
        },
        { validateOutput: true },
      );
      assert.equal(await ctx.registerCalls[0].tool.execute({}), 1);
    } finally {
      console.warn = previous;
    }
  });

  it("registerFromManifest forwards validateOutput", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const warnings = [];
    const previous = console.warn;
    console.warn = (...args) => {
      warnings.push(args.map(String).join(" "));
    };
    try {
      const summary = await api.registerFromManifest(
        {
          profile: "webpage",
          version: "1",
          tools: [
            {
              id: "probe",
              name: "Probe",
              description: "Contract probe",
              inputSchema: { type: "object", properties: {} },
              outputSchema: { type: ["string", "null"] },
            },
          ],
        },
        { probe: async () => 4 },
        { validateOutput: true },
      );
      assert.equal(summary.registered, 1);
      assert.equal(await ctx.registerCalls[0].tool.execute({}), 4);
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /expected string\|null/);
      assert.equal(warnings[0].includes("4"), false);
    } finally {
      console.warn = previous;
    }
  });

  it("rejects an invalid tool id", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);
    const result = await api.registerTool({
      inputSchema: { type: "object" },
      id: "not a valid id",
      description: "bad",
      execute: async () => "ok",
    });
    assert.equal(result.ok, false);
    assert.match(result.error, /name must match/i);
    assert.equal(ctx.registerCalls.length, 0);
  });
});

/**
 * Chrome 155+ shape: RegisteredTool.inputSchema is a JS object and
 * executeTool(registeredTool, inputObject) takes the object from getTools(),
 * never a tool name and never a JSON string (EPP 2026-09-10 / 2026-09-11).
 */
describe("InsightUiWebmcp against executeTool(RegisteredTool, object)", () => {
  afterEach(() => {
    delete require.cache[REGISTER_JS];
    delete globalThis.document;
    delete globalThis.InsightUiWebmcp;
  });

  function withExecuteTool(ctx) {
    const registered = new WeakSet();
    const baseGetTools = ctx.getTools;
    ctx.getTools = async function () {
      const listed = await baseGetTools.call(ctx);
      return listed.map((entry) => {
        // RegisteredTool: deep copy of the registration schema, as an object.
        const tool = Object.freeze({
          name: entry.name,
          title: entry.title,
          description: entry.description,
          inputSchema: structuredClone(entry.inputSchema),
          annotations: entry.annotations,
        });
        registered.add(tool);
        return tool;
      });
    };
    ctx.executeTool = async function (tool, input) {
      if (!tool || typeof tool !== "object" || !registered.has(tool)) {
        throw new TypeError("parameter 1 is not of type 'RegisteredTool'");
      }
      if (input !== undefined && (input === null || typeof input !== "object")) {
        throw new TypeError("Failed to parse input");
      }
      const entry = ctx.tools.get(tool.name);
      return entry.execute(structuredClone(input || {}), {
        signal: new AbortController().signal,
      });
    };
    return ctx;
  }

  it("registers inputSchema as an object and executes with an object input", async () => {
    const ctx = withExecuteTool(makeMockContext());
    const api = loadHelper(ctx);
    const schema = {
      type: "object",
      properties: { section: { type: "string", enum: ["trust"] } },
      required: ["section"],
    };
    const seen = [];
    const result = await api.registerTool({
      id: "get_section",
      description: "Return the rendered text of one public section.",
      inputSchema: schema,
      annotations: { readOnlyHint: true },
      execute: async (input, options) => {
        seen.push({ input, options });
        return "section text";
      },
    });
    assert.equal(result.ok, true);

    const { tool: payload } = ctx.registerCalls[0];
    assert.equal(typeof payload.inputSchema, "object");
    assert.deepEqual(payload.inputSchema, schema);

    const [registeredTool] = await ctx.getTools();
    assert.equal(typeof registeredTool.inputSchema, "object");
    assert.deepEqual(registeredTool.inputSchema, schema);

    const output = await ctx.executeTool(registeredTool, { section: "trust" });
    assert.equal(output, "section text");
    assert.equal(seen.length, 1);
    assert.deepEqual(seen[0].input, { section: "trust" });
    assert.equal(seen[0].options.signal instanceof AbortSignal, true);
  });

  it("a tool name or a JSON string is not the executeTool contract", async () => {
    const ctx = withExecuteTool(makeMockContext());
    const api = loadHelper(ctx);
    let calls = 0;
    await api.registerTool({
      id: "list_sections",
      description: "List public section anchors.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
      execute: async () => {
        calls += 1;
        return [];
      },
    });
    const [registeredTool] = await ctx.getTools();

    await assert.rejects(
      ctx.executeTool("list_sections", "{}"),
      /RegisteredTool/,
    );
    await assert.rejects(
      ctx.executeTool(registeredTool, "{}"),
      /Failed to parse input/,
    );
    assert.equal(calls, 0);
    assert.deepEqual(await ctx.executeTool(registeredTool, {}), []);
    assert.equal(calls, 1);
  });
});
