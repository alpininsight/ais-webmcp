/** Browser runtime shipped as `@alpininsightsolutions/webmcp`. */
export interface WebmcpStatus {
  supported: boolean;
  modelContext: boolean;
  registerTool: boolean;
  originTrialMeta: boolean | null;
  reason: string;
}

export interface WebmcpToolResult {
  ok: boolean;
  name?: string;
  error?: string;
}

declare const api: {
  isSupported(): boolean;
  status(): WebmcpStatus;
  onToolActivated(
    listener: EventListener,
    options?: AddEventListenerOptions | boolean,
  ): () => void;
  onToolCancel(
    listener: EventListener,
    options?: AddEventListenerOptions | boolean,
  ): () => void;
  registerTool(
    spec: Record<string, unknown>,
    options?: { signal?: AbortSignal },
  ): Promise<WebmcpToolResult>;
  registerFromManifest(
    manifest: { profile: string; version: string; tools: unknown[] },
    handlers?: Record<
      string,
      (input: unknown, options?: { signal?: AbortSignal }) => unknown
    >,
    options?: { signal?: AbortSignal },
  ): Promise<{
    registered: number;
    results: WebmcpToolResult[];
    errors: WebmcpToolResult[];
  }>;
  registerDefaults(): Promise<number>;
  unregister(name: string): boolean;
  dispose(): number;
  readonly version: string;
};

export = api;
