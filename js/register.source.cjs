/**
 * Insight UI WebMCP browser helper (MVP).
 *
 * Feature-detects `document.modelContext` (not navigator) and exposes a thin
 * registerTool / registerFromManifest / unregister / status API on
 * `window.InsightUiWebmcp`.
 *
 * Spec notes (EPP / document.modelContext only):
 * - `registerTool(tool, { signal })` returns a Promise — always await it.
 * - Unregister by aborting the registration AbortSignal (no unregisterTool()).
 * - Aborting registration does NOT cancel in-flight `execute` calls (Chrome 153+);
 *   cancel execution only via the execute AbortSignal (see issue #8).
 * - Tool payload uses `name` (id) + optional `title` (human label) and
 *   `annotations.*Hint` — never a top-level `consequential` boolean.
 * - Tool activation callbacks such as `ontoolactivated` live on
 *   `document.modelContext` (Chrome 156+ / PR245), not on navigator.
 *
 * No-op when WebMCP is unavailable so hosts can ship the script unconditionally.
 */
(function (global) {
  "use strict";

  var API_NAME = "InsightUiWebmcp";
  /** @type {Map<string, AbortController>} */
  var controllersByName = new Map();

  // Tool names: 1..128 chars of [A-Za-z0-9_.-] (WebMCP draft).
  var TOOL_NAME_RE = /^[A-Za-z0-9_.-]{1,128}$/;

  function getModelContext() {
    try {
      return global.document && global.document.modelContext
        ? global.document.modelContext
        : null;
    } catch (_err) {
      return null;
    }
  }

  function isSupported() {
    var ctx = getModelContext();
    return !!(ctx && typeof ctx.registerTool === "function");
  }

  /**
   * Whether the page carries a non-empty `<meta http-equiv="origin-trial">`.
   * Only presence is reported; the token value is never read out (#6).
   * A token delivered as an `Origin-Trial` response header is not visible here.
   * @returns {boolean|null} null when the DOM cannot be queried
   */
  function hasOriginTrialMeta() {
    try {
      var doc = global.document;
      if (!doc || typeof doc.querySelectorAll !== "function") {
        return null;
      }
      var metas = doc.querySelectorAll("meta[http-equiv]");
      for (var i = 0; i < metas.length; i++) {
        var meta = metas[i];
        if (!meta || typeof meta.getAttribute !== "function") {
          continue;
        }
        var equiv = String(meta.getAttribute("http-equiv") || "")
          .trim()
          .toLowerCase();
        if (
          equiv === "origin-trial" &&
          String(meta.getAttribute("content") || "").trim()
        ) {
          return true;
        }
      }
      return false;
    } catch (_err) {
      return null;
    }
  }

  /**
   * Read-only browser diagnosis for hosts and developers (#6).
   *
   * Distinguishes the three page-side states the server cannot see:
   * - "ok": `document.modelContext.registerTool` exists (trial or stable API).
   * - "no-origin-trial-meta": API missing and no origin-trial meta on the page.
   * - "no-model-context": API missing although a meta is present (or the DOM
   *   could not be inspected): browser/version, expired or foreign-origin
   *   token, flags, or Permissions-Policy are the next suspects.
   * Never registers tools, never returns or logs the token value.
   * @returns {{supported: boolean, modelContext: boolean, registerTool: boolean,
   *   originTrialMeta: (boolean|null), reason: string}}
   */
  function status() {
    var ctx = getModelContext();
    var canRegister = !!(ctx && typeof ctx.registerTool === "function");
    var meta = hasOriginTrialMeta();
    var reason = "ok";
    if (!canRegister) {
      reason = meta === false ? "no-origin-trial-meta" : "no-model-context";
    }
    return {
      supported: canRegister,
      modelContext: !!ctx,
      registerTool: canRegister,
      originTrialMeta: meta,
      reason: reason,
    };
  }

  var warnedStringInput = false;

  function abortError() {
    var aborted = new Error("The operation was aborted.");
    aborted.name = "AbortError";
    return aborted;
  }

  /**
   * Developer warning only. Never include the input value.
   * Strings are a defensive fallback, not the WebMCP input contract (#8).
   */
  function warnStringInput() {
    if (warnedStringInput) {
      return;
    }
    warnedStringInput = true;
    try {
      if (global.console && typeof global.console.warn === "function") {
        global.console.warn(
          "InsightUiWebmcp: string tool input was parsed defensively; pass a plain object",
        );
      }
    } catch (_warnErr) {
      /* ignore */
    }
  }

  /**
   * Normalize host execute handlers for the WebMCP callback shape (#8).
   *
   * Primary input is a plain object. A JSON string is parsed only as a
   * fallback and warned once. `signal` is forwarded as `{ signal }`.
   * An already-aborted signal rejects before the handler runs. Abort during
   * the handler promise rejects this execute promise with AbortError and
   * drops a later success. Handlers must still observe `signal` before
   * scroll, submit, or fetch; this wrapper cannot undo work they already did.
   * Registration abort does not cancel in-flight execute.
   *
   * @param {function} handler
   * @returns {function}
   */
  function wrapExecute(handler) {
    return function execute(input, options) {
      var opts = options && typeof options === "object" ? options : {};
      var signal = opts.signal;
      var payload = input;

      if (typeof input === "string") {
        try {
          payload = JSON.parse(input);
        } catch (_parseErr) {
          return Promise.reject(new TypeError("invalid JSON input"));
        }
      }
      if (
        payload === null ||
        typeof payload !== "object" ||
        Array.isArray(payload)
      ) {
        return Promise.reject(new TypeError("tool input must be an object"));
      }
      if (typeof input === "string") {
        warnStringInput();
      }

      if (signal && signal.aborted) {
        return Promise.reject(abortError());
      }

      return new Promise(function (resolve, reject) {
        var settled = false;

        // Do not use truthiness of err: Promise.reject() / reject(null) /
        // throw undefined|null|false|0|'' must still reject.
        function finish(result) {
          if (settled) {
            return;
          }
          settled = true;
          if (signal && typeof signal.removeEventListener === "function") {
            signal.removeEventListener("abort", onAbort);
          }
          if (result.ok) {
            resolve(result.value);
          } else {
            reject(result.err);
          }
        }

        function onAbort() {
          finish({ ok: false, err: abortError() });
        }

        if (signal && typeof signal.addEventListener === "function") {
          signal.addEventListener("abort", onAbort, { once: true });
        }

        var pending;
        try {
          pending = handler(payload, { signal: signal });
        } catch (err) {
          finish({ ok: false, err: err });
          return;
        }

        Promise.resolve(pending).then(
          function (value) {
            if (signal && signal.aborted) {
              finish({ ok: false, err: abortError() });
              return;
            }
            finish({ ok: true, value: value });
          },
          function (err) {
            if (signal && signal.aborted) {
              finish({ ok: false, err: abortError() });
              return;
            }
            finish({ ok: false, err: err });
          },
        );
      });
    };
  }

  /**
   * Build annotations from a host/manifest tool spec.
   * Manifest may still carry legacy `consequential`; map it to consequentialHint.
   * @param {object} spec
   * @returns {object|undefined}
   */
  function buildAnnotations(spec) {
    var src =
      spec.annotations && typeof spec.annotations === "object"
        ? spec.annotations
        : {};
    var annotations = {};
    var hasAny = false;

    function take(key, value) {
      if (typeof value === "boolean") {
        annotations[key] = value;
        hasAny = true;
      }
    }

    take("readOnlyHint", src.readOnlyHint);
    take("untrustedContentHint", src.untrustedContentHint);
    take("consequentialHint", src.consequentialHint);

    // Legacy manifest / host field → annotations.consequentialHint
    if (
      typeof annotations.consequentialHint !== "boolean" &&
      typeof spec.consequential === "boolean"
    ) {
      annotations.consequentialHint = spec.consequential;
      hasAny = true;
    }

    // Absence of a consequential hint does not establish read-only behavior.
    if (
      typeof annotations.readOnlyHint !== "boolean" &&
      annotations.consequentialHint !== true
    ) {
      annotations.readOnlyHint = false;
      hasAny = true;
    }

    return hasAny ? annotations : undefined;
  }

  var validators = require("./schema-validator.cjs");
  function validInputSchema(schema) {
    return !!(
      schema &&
      typeof schema === "object" &&
      !Array.isArray(schema) &&
      schema.type === "object" &&
      validators.validateInputSchema(schema)
    );
  }

  /**
   * Validate and map a host/manifest tool into a ModelContextTool dictionary.
   * @param {object} spec
   * @returns {{ ok: true, tool: object, name: string } | { ok: false, error: string, name?: string }}
   */
  function buildToolPayload(spec) {
    if (!spec || typeof spec !== "object") {
      return { ok: false, error: "tool spec must be an object" };
    }

    if (
      Array.isArray(spec) ||
      (spec.enabled !== undefined && typeof spec.enabled !== "boolean") ||
      (spec.consequential !== undefined &&
        typeof spec.consequential !== "boolean")
    ) {
      return { ok: false, error: "invalid tool flags" };
    }
    if (
      spec.annotations !== undefined &&
      (!spec.annotations ||
        typeof spec.annotations !== "object" ||
        Array.isArray(spec.annotations))
    ) {
      return { ok: false, error: "annotations must be an object" };
    }
    var annotationKeys = [
      "readOnlyHint",
      "consequentialHint",
      "untrustedContentHint",
    ];
    if (
      Object.keys(spec.annotations || {}).some(function (key) {
        return (
          annotationKeys.indexOf(key) < 0 ||
          typeof spec.annotations[key] !== "boolean"
        );
      })
    ) {
      return { ok: false, error: "invalid annotation key or value" };
    }
    var schemaKeys = ["inputSchema", "parameters", "input_schema"].filter(
      function (key) {
        return spec[key] !== undefined;
      },
    );
    if (schemaKeys.length !== 1 || !validInputSchema(spec[schemaKeys[0]])) {
      return {
        ok: false,
        error: "exactly one valid object input schema is required",
      };
    }
    var hints = spec.annotations || {};
    var consequential =
      spec.consequential === true || hints.consequentialHint === true;
    if (
      typeof spec.consequential === "boolean" &&
      typeof hints.consequentialHint === "boolean" &&
      spec.consequential !== hints.consequentialHint
    ) {
      return { ok: false, error: "contradictory consequential annotations" };
    }
    if (consequential && hints.readOnlyHint === true) {
      return { ok: false, error: "consequential tool cannot be read-only" };
    }
    if (spec.enabled === false || (consequential && spec.enabled !== true)) {
      return {
        ok: false,
        name: spec.id || spec.name,
        error: "tool is disabled or lacks explicit enable",
      };
    }

    // WebMCP `name` is the stable identifier; human label goes to `title`.
    var name = typeof spec.id === "string" && spec.id ? spec.id : spec.name;
    var title;
    if (typeof spec.title === "string" && spec.title) {
      title = spec.title;
    } else if (
      typeof spec.id === "string" &&
      spec.id &&
      typeof spec.name === "string" &&
      spec.name &&
      spec.name !== spec.id
    ) {
      title = spec.name;
    }

    if (!name || typeof name !== "string") {
      return { ok: false, error: "tool name/id is required", name: name };
    }
    if (!TOOL_NAME_RE.test(name)) {
      return {
        ok: false,
        error:
          "tool name must match /^[A-Za-z0-9_.-]{1,128}$/ (use id for name, human text as title)",
        name: name,
      };
    }

    var description =
      typeof spec.description === "string" ? spec.description.trim() : "";
    if (!description) {
      return {
        ok: false,
        error: "non-empty description is required",
        name: name,
      };
    }

    if (typeof spec.execute !== "function") {
      return {
        ok: false,
        error: "execute handler is required",
        name: name,
      };
    }

    var tool = {
      name: name,
      description: description,
      execute: wrapExecute(spec.execute),
    };
    if (title) {
      tool.title = title;
    }

    var inputSchema = spec.inputSchema || spec.parameters || spec.input_schema;
    if (inputSchema && typeof inputSchema === "object") {
      tool.inputSchema = inputSchema;
    }

    var annotations = buildAnnotations(spec);
    if (annotations) {
      tool.annotations = annotations;
    }

    // Never set top-level consequential — browsers ignore it / it is not WebMCP.
    return { ok: true, tool: tool, name: name };
  }

  /**
   * Register one tool against document.modelContext.
   *
   * @param {object} spec Host tool spec (id/name/title/description/execute/…)
   * @param {object} [options]
   * @param {AbortSignal} [options.signal] Optional external signal; abort unregisters.
   * @returns {Promise<{ok: boolean, name?: string, error?: string}>}
   */
  function registerTool(spec, options) {
    options = options || {};

    return Promise.resolve().then(function () {
      var built = buildToolPayload(spec);
      if (!built.ok) {
        return { ok: false, name: built.name, error: built.error };
      }

      var ctx = getModelContext();
      if (!ctx || typeof ctx.registerTool !== "function") {
        return {
          ok: false,
          name: built.name,
          error: "document.modelContext.registerTool is unavailable",
        };
      }

      // Replace prior registration for the same name (abort old controller).
      var previous = controllersByName.get(built.name);
      if (previous) {
        try {
          previous.abort();
        } catch (_abortErr) {
          /* ignore */
        }
        controllersByName.delete(built.name);
      }

      var controller = new AbortController();
      var external = options.signal;
      if (external) {
        if (external.aborted) {
          controller.abort();
        } else {
          external.addEventListener(
            "abort",
            function () {
              controller.abort();
            },
            { once: true },
          );
        }
      }

      controllersByName.set(built.name, controller);

      var registerOpts = { signal: controller.signal };

      // A synchronous throw must not escape as an uncaught rejection.
      var pending;
      try {
        pending = ctx.registerTool(built.tool, registerOpts);
      } catch (err) {
        controllersByName.delete(built.name);
        try {
          controller.abort();
        } catch (_thrown) {
          /* ignore */
        }
        return {
          ok: false,
          name: built.name,
          error:
            err && err.message ? String(err.message) : "registerTool threw",
        };
      }

      return Promise.resolve(pending).then(
        function () {
          if (controller.signal.aborted) {
            if (controllersByName.get(built.name) === controller)
              controllersByName.delete(built.name);
            return {
              ok: false,
              name: built.name,
              error: "registration aborted before completion",
            };
          }
          return { ok: true, name: built.name };
        },
        function (err) {
          if (controllersByName.get(built.name) === controller)
            controllersByName.delete(built.name);
          try {
            controller.abort();
          } catch (_a) {
            /* ignore */
          }
          return {
            ok: false,
            name: built.name,
            error:
              err && err.message
                ? String(err.message)
                : "registerTool promise rejected",
          };
        },
      );
    });
  }

  /**
   * Unregister a tool by aborting its registration AbortController.
   * Does NOT cancel in-flight execute (per EPP / Chrome 153+).
   * @param {string} name
   * @returns {boolean} true if a controller was aborted
   */
  function unregister(name) {
    if (!name || typeof name !== "string") {
      return false;
    }
    var controller = controllersByName.get(name);
    if (!controller) {
      return false;
    }
    controllersByName.delete(name);
    try {
      controller.abort();
    } catch (_err) {
      return false;
    }
    return true;
  }

  /**
   * Abort all registration signals held by this helper.
   * Does NOT cancel in-flight execute calls.
   * @returns {number} number of tools disposed
   */
  function dispose() {
    var names = Array.from(controllersByName.keys());
    var count = 0;
    for (var i = 0; i < names.length; i++) {
      if (unregister(names[i])) {
        count += 1;
      }
    }
    return count;
  }

  /**
   * Register every tool listed in a prepare-time manifest object.
   * Tools without a matching handler are reported as errors (not registered).
   *
   * @param {object} manifest
   * @param {Array<object>} [manifest.tools]
   * @param {object} [handlers] map of tool id -> execute function
   * @param {object} [options]
   * @param {AbortSignal} [options.signal] shared lifecycle signal for all tools
   * @returns {Promise<{registered: number, results: Array, errors: Array}>}
   */
  function registerFromManifest(manifest, handlers, options) {
    options = options || {};
    handlers = handlers || {};

    if (
      !validators.validateManifest(manifest) ||
      !manifest.profile.trim() ||
      !manifest.version.trim()
    ) {
      return Promise.resolve({
        registered: 0,
        results: [],
        errors: [{ error: "invalid manifest" }],
      });
    }
    var seen = new Set();
    for (var tool of manifest.tools) {
      var token = tool.id || tool.name;
      var checked = buildToolPayload(
        Object.assign({}, tool, { execute: function () {} }),
      );
      if (seen.has(token) || (!checked.ok && tool.enabled !== false)) {
        return Promise.resolve({
          registered: 0,
          results: [],
          errors: [
            { error: seen.has(token) ? "duplicate tool id" : checked.error },
          ],
        });
      }
      // Disabled tools also need consistent annotations and valid schemas.
      if (
        !checked.ok &&
        checked.error !== "tool is disabled or lacks explicit enable"
      ) {
        return Promise.resolve({
          registered: 0,
          results: [],
          errors: [{ error: checked.error }],
        });
      }
      seen.add(token);
    }

    var chain = Promise.resolve({ registered: 0, results: [], errors: [] });

    for (var i = 0; i < manifest.tools.length; i++) {
      (function (tool) {
        chain = chain.then(function (acc) {
          if (!tool || typeof tool !== "object" || Array.isArray(tool)) {
            acc.errors.push({
              ok: false,
              error: "tool spec must be an object",
            });
            return acc;
          }
          var id = tool.id || tool.name;
          var spec = Object.assign({}, tool);
          if (id && typeof handlers[id] === "function") {
            spec.execute = handlers[id];
          }

          return registerTool(spec, { signal: options.signal }).then(
            function (result) {
              acc.results.push(result);
              if (result.ok) {
                acc.registered += 1;
              } else {
                acc.errors.push(result);
              }
              return acc;
            },
          );
        });
      })(manifest.tools[i]);
    }

    return chain;
  }

  /**
   * Default / empty registration hook for hosts that call prepare then
   * wire handlers later. Safe to invoke when WebMCP is missing.
   * @returns {Promise<number>}
   */
  function registerDefaults() {
    return Promise.resolve(0);
  }

  var api = {
    isSupported: isSupported,
    status: status,
    registerTool: registerTool,
    registerFromManifest: registerFromManifest,
    registerDefaults: registerDefaults,
    unregister: unregister,
    dispose: dispose,
    /** @deprecated Use unregister / dispose (AbortSignal). Kept absent intentionally. */
    version: "0.0.0",
  };

  global[API_NAME] = api;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
