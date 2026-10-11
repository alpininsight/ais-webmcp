"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const helper = fs.realpathSync(
  path.resolve(
    __dirname,
    "../../src/ais_webmcp/assets/register.js",
  ),
);
for (const entry of require("../fixtures/cross-layer.json")) {
  test("cross-layer " + entry.name, async () => {
    const calls = [];
    globalThis.document = {
      modelContext: { registerTool: async (tool) => calls.push(tool) },
    };
    delete require.cache[helper];
    const api = require(helper);
    const result = await api.registerFromManifest(entry.manifest, {
      probe: async () => "ok",
    });
    assert.equal(result.registered, Number(entry.register));
    assert.equal(calls.length, Number(entry.register));
    if (entry.register)
      assert.equal(calls[0].inputSchema.properties.value.type, "string");
    api.dispose();
    delete globalThis.document;
  });
}
test("malformed execute input never reaches handler", async () => {
  let execute;
  let calls = 0;
  globalThis.document = {
    modelContext: {
      registerTool: async (tool) => {
        execute = tool.execute;
      },
    },
  };
  delete require.cache[helper];
  const api = require(helper);
  await api.registerTool({
    id: "probe",
    name: "Probe",
    description: "Probe",
    inputSchema: { type: "object" },
    execute: () => calls++,
  });
  for (const input of ["{", "[]", [], null, 42])
    await assert.rejects(() => execute(input));
  assert.equal(calls, 0);
  api.dispose();
  delete globalThis.document;
});

test("late rejection of a replaced registration keeps the new lifecycle", async () => {
  let rejectOld;
  let count = 0;
  globalThis.document = {
    modelContext: {
      registerTool: async () => {
        count++;
        if (count === 1)
          await new Promise((_, reject) => {
            rejectOld = reject;
          });
      },
    },
  };
  delete require.cache[helper];
  const api = require(helper);
  const spec = {
    id: "probe",
    name: "Probe",
    description: "Probe",
    inputSchema: { type: "object" },
    execute: () => "ok",
  };
  const old = api.registerTool(spec);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal((await api.registerTool(spec)).ok, true);
  rejectOld(new Error("old registration failed"));
  assert.equal((await old).ok, false);
  assert.equal(api.dispose(), 1);
  delete globalThis.document;
});
