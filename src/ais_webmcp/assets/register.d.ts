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
  registerFromManifest(
    manifest: InsightUiWebmcp.WebmcpManifest,
    handlers?: Readonly<Record<string, InsightUiWebmcp.WebmcpExecute>>,
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

  interface WebmcpToolSpec {
    name: string;
    description: string;
    execute: WebmcpExecute;
    id?: string;
    title?: string;
    inputSchema?: object;
    parameters?: object;
    input_schema?: object;
    outputSchema?: object;
    output_schema?: object;
    consequential?: boolean;
    enabled?: boolean;
    group?: string;
    annotations?: WebmcpAnnotations;
  }

  interface WebmcpManifestTool {
    name: string;
    description: string;
    id?: string;
    title?: string;
    inputSchema?: object;
    parameters?: object;
    input_schema?: object;
    outputSchema?: object;
    output_schema?: object;
    consequential?: boolean;
    enabled?: boolean;
    group?: string;
    annotations?: WebmcpAnnotations;
  }

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
