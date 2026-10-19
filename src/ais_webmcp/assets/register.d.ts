/**
 * Browser runtime shipped as `@alpininsightsolutions/webmcp`.
 *
 * The runtime is one CommonJS export (`module.exports = InsightUiWebmcp`).
 * Public types live on that same export so `export =` is valid under
 * `skipLibCheck: false`.
 */
declare const InsightUiWebmcp: {
  isSupported(): boolean;
  status(): InsightUiWebmcp.WebmcpStatus;
  onToolActivated(
    listener: EventListener,
    options?: AddEventListenerOptions | boolean,
  ): () => void;
  onToolCancel(
    listener: EventListener,
    options?: AddEventListenerOptions | boolean,
  ): () => void;
  registerTool(
    spec: InsightUiWebmcp.WebmcpToolSpec,
    options?: { signal?: AbortSignal },
  ): Promise<InsightUiWebmcp.WebmcpToolResult>;
  registerFromManifest<
    Handlers extends InsightUiWebmcp.WebmcpHandlerMap<Handlers>,
  >(
    manifest: InsightUiWebmcp.WebmcpManifest,
    handlers?: Handlers,
    options?: { signal?: AbortSignal },
  ): Promise<InsightUiWebmcp.WebmcpManifestRegistration>;
  registerDefaults(): Promise<number>;
  unregister(name: string): boolean;
  dispose(): number;
  readonly version: string;
};

declare namespace InsightUiWebmcp {
  interface WebmcpStatus {
    supported: boolean;
    modelContext: boolean;
    registerTool: boolean;
    originTrialMeta: boolean | null;
    reason: string;
  }

  interface WebmcpAnnotations {
    readOnlyHint?: boolean;
    consequentialHint?: boolean;
    untrustedContentHint?: boolean;
    debugging?: boolean;
  }

  /**
   * `input` is `any` so a named tool interface can use its own input type.
   * The runtime still passes an object.
   */
  type WebmcpExecute = (
    input: any,
    options?: { signal?: AbortSignal },
  ) => unknown;

  /**
   * Known handler ids only. A named interface does not need a string index
   * signature; each of its properties must be an execute function.
   */
  type WebmcpHandlerMap<Handlers> = {
    [ToolId in keyof Handlers]: WebmcpExecute;
  };

  interface WebmcpToolFields {
    description: string;
    execute: WebmcpExecute;
    title?: string;
    consequential?: boolean;
    enabled?: boolean;
    group?: string;
    annotations?: WebmcpAnnotations;
  }

  /**
   * `validInputSchema` accepts only a non-array schema whose `type` is
   * `"object"`. Other JSON Schema keywords stay open.
   */
  interface WebmcpObjectInputSchema {
    type: "object";
    [keyword: string]: unknown;
  }

  /**
   * The runtime registers a tool only when exactly one input-schema alias
   * is set.
   */
  type WebmcpInputSchema =
    | {
        inputSchema: WebmcpObjectInputSchema;
        parameters?: never;
        input_schema?: never;
      }
    | {
        parameters: WebmcpObjectInputSchema;
        inputSchema?: never;
        input_schema?: never;
      }
    | {
        input_schema: WebmcpObjectInputSchema;
        inputSchema?: never;
        parameters?: never;
      };

  /**
   * `validJsonSchemaObject` accepts a non-array object. Arrays satisfy
   * `object`, so this uses a string index signature. At most one
   * output-schema alias. Omitting both stays valid.
   */
  type WebmcpJsonSchemaObject = { [keyword: string]: unknown };

  type WebmcpOutputSchema =
    | { outputSchema?: WebmcpJsonSchemaObject; output_schema?: never }
    | { output_schema?: WebmcpJsonSchemaObject; outputSchema?: never };

  /** The runtime uses `id` when it is set, and otherwise `name`. */
  type WebmcpToolSpec = WebmcpToolFields &
    WebmcpInputSchema &
    WebmcpOutputSchema &
    ({ id: string; name?: string } | { name: string; id?: string });

  interface WebmcpManifestToolBase {
    name: string;
    description: string;
    id?: string;
    title?: string;
    group?: string;
    annotations?: WebmcpAnnotations;
  }

  /**
   * The manifest schema requires `enabled` when `consequential` is true.
   * `enabled: false` remains valid.
   */
  type WebmcpManifestToolFields = WebmcpManifestToolBase &
    (
      | { consequential?: false; enabled?: boolean }
      | { consequential: true; enabled: boolean }
    );

  type WebmcpManifestTool = WebmcpManifestToolFields &
    WebmcpInputSchema &
    WebmcpOutputSchema;

  /** Top-level fields accepted by the manifest schema. */
  interface WebmcpManifest {
    profile: string;
    version: string;
    tools: readonly WebmcpManifestTool[];
    $schema?: string;
    anchors?: readonly string[];
    notes?: readonly string[];
  }

  interface WebmcpToolResult {
    ok: boolean;
    name?: string;
    error?: string;
  }

  /** Prevalidation failure. These entries have no `ok` property. */
  interface WebmcpManifestError {
    error: string;
  }

  interface WebmcpManifestRegistration {
    registered: number;
    results: WebmcpToolResult[];
    errors: readonly (WebmcpToolResult | WebmcpManifestError)[];
  }
}

export = InsightUiWebmcp;
