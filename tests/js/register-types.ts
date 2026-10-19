import api = require("@alpininsightsolutions/webmcp");

interface SearchTool {
  name: string;
  description: string;
  inputSchema: { type: "object"; properties: { q: { type: "string" } } };
  execute(input: { q: string }): { results: string[] };
}

const search: SearchTool = {
  name: "search",
  description: "Search the page",
  inputSchema: { type: "object", properties: { q: { type: "string" } } },
  execute(input) {
    return { results: [input.q] };
  },
};

const manifest = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  profile: "webpage",
  version: "1",
  anchors: ["top"],
  notes: ["starter"],
  tools: [
    {
      name: "Search the page",
      description: "Search the page",
      id: "search",
      inputSchema: { type: "object" },
    },
  ],
};

async function useRuntime(): Promise<void> {
  await api.registerTool(search);
  const batch = await api.registerFromManifest(manifest, {
    search(input: { q: string }) {
      return { results: [input.q] };
    },
  });
  const failure = batch.errors[0];
  if (failure) {
    // @ts-expect-error manifest-level errors do not include ok
    const unchecked: boolean = failure.ok;
    void unchecked;
  }
  if (failure && "ok" in failure) {
    const flagged: boolean = failure.ok;
    void flagged;
  }
}

void useRuntime;
void api.version;
