import api = require("@alpininsightsolutions/webmcp");
import InsightUiWebmcp from "@alpininsightsolutions/webmcp";

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
      inputSchema: { type: "object" as const },
    },
  ],
};

interface SearchHandlers {
  search(input: { q: string }): { results: string[] };
}

const handlers: SearchHandlers = {
  search(input) {
    return { results: [input.q] };
  },
};

interface IdOnlyTool {
  id: string;
  description: string;
  inputSchema: { type: "object" };
  execute(input: { q: string }): { ok: true };
}

const idOnly: IdOnlyTool = {
  id: "a_tool",
  description: "Search by id",
  inputSchema: { type: "object" },
  execute() {
    return { ok: true };
  },
};

async function useRuntime(): Promise<void> {
  await api.registerTool(search);
  await api.registerTool(idOnly);
  await api.registerTool({
    id: "a_tool",
    description: "Search by id",
    inputSchema: { type: "object" },
    execute() {
      return { ok: true };
    },
  });
  await api.registerFromManifest(manifest);
  const batch = await api.registerFromManifest(manifest, handlers);
  // @ts-expect-error a tool spec needs id or name
  await api.registerTool({
    description: "missing identifier",
    inputSchema: { type: "object" },
    execute() {
      return { ok: true };
    },
  });
  interface BadHandlers {
    search: string;
  }
  const badHandlers: BadHandlers = { search: "nope" };
  // @ts-expect-error handler properties must be execute functions
  await api.registerFromManifest(manifest, badHandlers);
  // @ts-expect-error exactly one input schema alias is required
  await api.registerTool({
    id: "a_tool",
    description: "missing schema",
    execute() {
      return { ok: true };
    },
  });
  // @ts-expect-error input schema aliases are exclusive
  await api.registerTool({
    name: "a_tool",
    description: "two schemas",
    inputSchema: { type: "object" },
    parameters: { type: "object" },
    execute() {
      return { ok: true };
    },
  });
  await api.registerFromManifest({
    profile: "webpage",
    version: "1",
    tools: [
      {
        name: "Search",
        description: "Search",
        parameters: { type: "object", properties: { q: { type: "string" } } },
        outputSchema: { type: "object" },
      },
    ],
  });
  await api.registerTool({
    id: "a_tool",
    description: "string schema",
    // @ts-expect-error input schemas must use type object
    inputSchema: { type: "string" },
    execute() {
      return { ok: true };
    },
  });
  await api.registerTool({
    id: "a_tool",
    description: "array schema",
    // @ts-expect-error an array is not an input schema
    inputSchema: [],
    execute() {
      return { ok: true };
    },
  });
  // @ts-expect-error output schema aliases are exclusive
  await api.registerTool({
    name: "a_tool",
    description: "two output schemas",
    inputSchema: { type: "object" },
    outputSchema: { type: "object" },
    output_schema: { type: "string" },
    execute() {
      return { ok: true };
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

async function readmeExample(): Promise<void> {
  const status = InsightUiWebmcp.status();
  if (status.supported) {
    await InsightUiWebmcp.registerFromManifest(
      {
        profile: "webpage",
        version: "1",
        tools: [
          {
            id: "search",
            name: "Search",
            description: "Search this page",
            inputSchema: {
              type: "object",
              properties: { q: { type: "string" } },
            },
          },
        ],
      },
      {
        search(input: { q?: string }) {
          return { results: [] };
        },
      },
    );
  }
}

void readmeExample;
