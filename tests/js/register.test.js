/**
 * Contract tests for register.js against a mock document.modelContext.
 * Run: node --test tests/js/register.test.js
 */
"use strict";

const { describe, it, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const REGISTER_JS = path.resolve(
  __dirname,
  "../../src/insight_ui_webmcp/static/insight_ui_webmcp/js/register.js"
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
            { once: true }
          );
        }
        tools.set(tool.name, entry);
        resolve();
      });
    },
    async getTools() {
      return Array.from(tools.values()).sort((a, b) =>
        a.name < b.name ? -1 : a.name > b.name ? 1 : 0
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
      id: "go_to_section",
      name: "Go to section",
      description: "Scroll or navigate the page to a named section anchor.",
      inputSchema: {
        type: "object",
        properties: { section: { type: "string" } },
        required: ["section"],
      },
      consequential: true,
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
      "Scroll or navigate the page to a named section anchor."
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

  it("sets readOnlyHint by default when not consequential", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    await api.registerTool({
      id: "list_sections",
      name: "List sections",
      description: "List available page section anchors on this host.",
      execute: async () => [],
    });

    const { tool } = ctx.registerCalls[0];
    assert.equal(tool.annotations.readOnlyHint, true);
    assert.equal(tool.annotations.consequentialHint, undefined);
    assert.equal("consequential" in tool, false);
  });

  it("passes through untrustedContentHint on annotations", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    await api.registerTool({
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

  it("rejects tools without execute and does not call registerTool", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    const result = await api.registerTool({
      id: "go_to_section",
      name: "Go to section",
      description: "Scroll to section.",
    });

    assert.equal(result.ok, false);
    assert.match(result.error, /execute/i);
    assert.equal(ctx.registerCalls.length, 0);
  });

  it("rejects empty description", async () => {
    const ctx = makeMockContext();
    const api = loadHelper(ctx);

    const result = await api.registerTool({
      id: "go_to_section",
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
      id: "go_to_section",
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
      id: "go_to_section",
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
      id: "a_tool",
      description: "A",
      execute: async () => 1,
    });
    await api.registerTool({
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
      id: "go_to_section",
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
        tools: [
          {
            id: "go_to_section",
            name: "Go to section",
            description: "Scroll to section.",
          },
          {
            id: "subscribe_newsletter",
            name: "Subscribe newsletter",
            description: "Subscribe an email.",
            consequential: true,
          },
          {
            id: "list_sections",
            name: "List sections",
            description: "List sections.",
          },
        ],
      },
      {
        go_to_section: async ({ section }) => section,
        subscribe_newsletter: async ({ email }) => email,
      }
    );

    assert.equal(summary.registered, 2);
    assert.equal(summary.errors.length, 1);
    assert.equal(summary.errors[0].name, "list_sections");
    assert.match(summary.errors[0].error, /execute/i);

    const listed = await ctx.getTools();
    assert.deepEqual(
      listed.map((t) => t.name).sort(),
      ["go_to_section", "subscribe_newsletter"]
    );
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
      id: "go_to_section",
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
    const out = await tool.execute({ section: "contact" }, { signal: ac.signal });
    assert.equal(out, "done");
    assert.deepEqual(seenInput, { section: "contact" });
    assert.equal(seenSignal, ac.signal);
  });

  it("isSupported is false without document.modelContext", () => {
    const api = loadHelper(null);
    assert.equal(api.isSupported(), false);
  });

  it("targets document.modelContext only (no navigator fallback used)", async () => {
    // Even if navigator.modelContext existed, helper must use document only.
    globalThis.navigator = {
      modelContext: {
        registerTool() {
          throw new Error("must not use navigator.modelContext");
        },
      },
    };
    try {
      const ctx = makeMockContext();
      const api = loadHelper(ctx);
      await api.registerTool({
        id: "ok_tool",
        description: "ok",
        execute: async () => "ok",
      });
      assert.equal(ctx.registerCalls.length, 1);
    } finally {
      delete globalThis.navigator;
    }
  });
});
