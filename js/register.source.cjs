/**
 * Insight UI WebMCP browser helper (MVP).
 *
 * Feature-detects `document.modelContext` (not navigator) and exposes a thin
 * registerTool / registerFromManifest / unregister / status /
 * onToolActivated / onToolCancel API on `window.InsightUiWebmcp`.
 *
 * Spec notes (EPP / document.modelContext only):
 * - `registerTool(tool, { signal })` returns a Promise — always await it.
 * - Unregister by aborting the registration AbortSignal (no unregisterTool()).
 * - Aborting registration does NOT cancel in-flight `execute` calls (Chrome 153+);
 *   cancel execution only via the execute AbortSignal (see issue #8).
 * - Tool payload uses `name` (id) + optional `title` (human label) and
 *   `annotations.*Hint` — never a top-level `consequential` boolean.
 * - `outputSchema` (alias `output_schema`) is optional. When set it must be
 *   one JSON Schema object and is passed to registerTool unchanged
 *   (Chrome 159+). If the browser rejects that member as unsupported, the
 *   tool is registered again without it. Omission still registers; manifest
 *   validation reports that as a low finding. A structurally invalid schema
 *   is rejected before registerTool.
 * - `options.validateOutput === true` compares the execute result to
 *   outputSchema and console.warns on mismatch. The result is never rejected.
 *   The check is off by default and is not a full JSON Schema validator.
 *   Upstream mismatch behavior is still open (webmachinelearning/webmcp#92).
 * - Tool names, titles, and descriptions reject invisible or control
 *   characters. A whitespace-only description is rejected.
 * - Missing readOnlyHint is stored as false only when the tool is not
 *   consequential. That default is not a safety assurance, and missing
 *   destructiveHint or openWorldHint must not be treated as safe.
 * - Tool lifecycle events `toolactivated` / `toolcancel` (handler properties
 *   `ontoolactivated` / `ontoolcancel`) fire on `document.modelContext`
 *   (Chrome 156+ / WebMCP PR #245). Helpers `onToolActivated` / `onToolCancel`
 *   subscribe only there — never on `window` or `navigator.modelContext`.
 *
 * No-op when WebMCP is unavailable so hosts can ship the script unconditionally.
 */
(function (global) {
  "use strict";

  var API_NAME = "InsightUiWebmcp";
  /** @type {Map<string, AbortController>} */
  var controllersByName = new Map();
  // null until a registration shows whether this document accepts outputSchema.
  // true: the member was accepted. false: omit it. Chrome 159+ accepts it.
  // Older WebIDL dictionaries ignore unknown members, so they stay on true
  // after a successful call that included the schema.
  var outputSchemaAccepted = null;
  /** @type {Set<string>} */
  var warnedOutputMismatches = new Set();

  // Tool names: 1..128 chars of [A-Za-z0-9_.-] (WebMCP draft).
  var TOOL_NAME_RE = /^[A-Za-z0-9_.-]{1,128}$/;
  // Cc, Cf, and Cs, plus Default_Ignorable code points whose category is
  // none of those. Property escapes cover the whole Cf set (U+0600, U+06DD,
  // and the rest an explicit BMP list missed).
  var INVISIBLE_OR_CONTROL_RE =
    /[\p{Cc}\p{Cf}\p{Cs}\u034F\u115F\u1160\u17B4\u17B5\u180B-\u180D\u2065\u3164\uFE00-\uFE0F\uFFA0\uFFF0-\uFFF8\u{E0100}-\u{E01EF}]/u;

  function hasInvisibleOrControl(value) {
    return typeof value === "string" && INVISIBLE_OR_CONTROL_RE.test(value);
  }

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

  /**
   * Subscribe to a tool-lifecycle event on document.modelContext only (#7).
   *
   * Event types (Chrome 156+ / WebMCP PR #245):
   * - "toolactivated" — agent started executing a registered tool
   * - "toolcancel" — agent cancelled that execution
   *
   * Never attaches to window or navigator.modelContext. When modelContext is
   * missing or is not an EventTarget, returns a no-op unsubscribe.
   *
   * @param {"toolactivated"|"toolcancel"} type
   * @param {EventListener} listener
   * @param {AddEventListenerOptions|boolean} [options]
   * @returns {function(): void} unsubscribe (safe to call more than once)
   */
  function addToolLifecycleListener(type, listener, options) {
    function noop() {}
    if (type !== "toolactivated" && type !== "toolcancel") {
      return noop;
    }
    if (typeof listener !== "function") {
      return noop;
    }
    var ctx = getModelContext();
    if (!ctx || typeof ctx.addEventListener !== "function") {
      return noop;
    }
    try {
      ctx.addEventListener(type, listener, options);
    } catch (_err) {
      return noop;
    }
    var removed = false;
    return function unsubscribe() {
      if (removed) {
        return;
      }
      removed = true;
      try {
        if (typeof ctx.removeEventListener === "function") {
          ctx.removeEventListener(type, listener, options);
        }
      } catch (_removeErr) {
        /* ignore */
      }
    };
  }

  /**
   * Listen for toolactivated on document.modelContext only (#7).
   * @param {EventListener} listener
   * @param {AddEventListenerOptions|boolean} [options]
   * @returns {function(): void}
   */
  function onToolActivated(listener, options) {
    return addToolLifecycleListener("toolactivated", listener, options);
  }

  /**
   * Listen for toolcancel on document.modelContext only (#7).
   * @param {EventListener} listener
   * @param {AddEventListenerOptions|boolean} [options]
   * @returns {function(): void}
   */
  function onToolCancel(listener, options) {
    return addToolLifecycleListener("toolcancel", listener, options);
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

  var JSON_SCHEMA_TYPES = {
    object: true,
    array: true,
    string: true,
    number: true,
    integer: true,
    boolean: true,
    null: true,
  };

  function sameJson(left, right, depth) {
    if (left === right) {
      return true;
    }
    if (!depth || depth < 0) {
      return false;
    }
    if (left === null || right === null) {
      return false;
    }
    if (typeof left !== "object" || typeof right !== "object") {
      return false;
    }
    var leftArray = Array.isArray(left);
    var rightArray = Array.isArray(right);
    if (leftArray !== rightArray) {
      return false;
    }
    if (leftArray) {
      if (left.length !== right.length) {
        return false;
      }
      for (var i = 0; i < left.length; i++) {
        if (!sameJson(left[i], right[i], depth - 1)) {
          return false;
        }
      }
      return true;
    }
    var keys = Object.keys(left);
    if (keys.length !== Object.keys(right).length) {
      return false;
    }
    for (var k = 0; k < keys.length; k++) {
      if (!Object.prototype.hasOwnProperty.call(right, keys[k])) {
        return false;
      }
      if (!sameJson(left[keys[k]], right[keys[k]], depth - 1)) {
        return false;
      }
    }
    return true;
  }

  /**
   * @returns {boolean|null} null when `type` is not a JSON Schema type we check
   */
  function jsonTypeMatches(type, value) {
    switch (type) {
      case "object":
        return (
          value !== null && typeof value === "object" && !Array.isArray(value)
        );
      case "array":
        return Array.isArray(value);
      case "string":
        return typeof value === "string";
      case "number":
        return typeof value === "number" && Number.isFinite(value);
      case "integer":
        return typeof value === "number" && Number.isInteger(value);
      case "boolean":
        return typeof value === "boolean";
      case "null":
        return value === null;
      default:
        return null;
    }
  }

  function valueMatchesTypes(types, value) {
    var sawKnown = false;
    for (var i = 0; i < types.length; i++) {
      var matched = jsonTypeMatches(types[i], value);
      if (matched === null) {
        continue;
      }
      sawKnown = true;
      if (matched === true) {
        return true;
      }
    }
    return sawKnown ? false : true;
  }

  /**
   * Lightweight outputSchema check. Not Draft 2020-12 instance validation:
   * `$ref`, combinators, pattern, format, ranges, and string length are
   * ignored. Boolean subschemas are ignored. Depth is capped at 8.
   * Messages name schema paths only, never the result value.
   */
  function collectOutputMismatches(schema, value, path, depth, seen, mismatches) {
    if (mismatches.length >= 3 || depth > 8) {
      return;
    }
    if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
      return;
    }
    if (seen.indexOf(schema) >= 0) {
      return;
    }
    seen.push(schema);

    if (
      Object.prototype.hasOwnProperty.call(schema, "const") &&
      !sameJson(schema.const, value, 8)
    ) {
      mismatches.push(path + " does not match const");
    }
    if (Array.isArray(schema.enum)) {
      var inEnum = false;
      for (var e = 0; e < schema.enum.length; e++) {
        if (sameJson(schema.enum[e], value, 8)) {
          inEnum = true;
          break;
        }
      }
      if (!inEnum) {
        mismatches.push(path + " is not in enum");
      }
    }

    var types = schema.type;
    if (typeof types === "string") {
      types = [types];
    }
    if (Array.isArray(types) && types.length && !valueMatchesTypes(types, value)) {
      var declared = [];
      for (var t = 0; t < types.length; t++) {
        if (JSON_SCHEMA_TYPES[types[t]] === true) {
          declared.push(types[t]);
        }
      }
      if (declared.length) {
        mismatches.push(path + " expected " + declared.join("|"));
      }
    }

    var isObject =
      value !== null && typeof value === "object" && !Array.isArray(value);
    if (isObject && Array.isArray(schema.required)) {
      for (var r = 0; r < schema.required.length && mismatches.length < 3; r++) {
        var req = schema.required[r];
        if (
          typeof req === "string" &&
          !Object.prototype.hasOwnProperty.call(value, req)
        ) {
          mismatches.push(path + "." + req + " is required");
        }
      }
    }
    if (
      isObject &&
      schema.additionalProperties === false &&
      schema.properties &&
      typeof schema.properties === "object" &&
      !Array.isArray(schema.properties)
    ) {
      var valueKeys = Object.keys(value);
      for (var a = 0; a < valueKeys.length; a++) {
        if (!Object.prototype.hasOwnProperty.call(schema.properties, valueKeys[a])) {
          mismatches.push(path + " has a property outside outputSchema.properties");
          break;
        }
      }
    }
    if (
      isObject &&
      schema.properties &&
      typeof schema.properties === "object" &&
      !Array.isArray(schema.properties)
    ) {
      var propNames = Object.keys(schema.properties);
      for (var p = 0; p < propNames.length && mismatches.length < 3; p++) {
        if (Object.prototype.hasOwnProperty.call(value, propNames[p])) {
          collectOutputMismatches(
            schema.properties[propNames[p]],
            value[propNames[p]],
            path + "." + propNames[p],
            depth + 1,
            seen,
            mismatches,
          );
        }
      }
    }
    if (
      Array.isArray(value) &&
      schema.items &&
      typeof schema.items === "object" &&
      !Array.isArray(schema.items)
    ) {
      var limit = value.length < 20 ? value.length : 20;
      for (var n = 0; n < limit && mismatches.length < 3; n++) {
        collectOutputMismatches(
          schema.items,
          value[n],
          path + "[" + n + "]",
          depth + 1,
          seen,
          mismatches,
        );
      }
    }

    seen.pop();
  }

  function warnOutputMismatch(name, schema, value) {
    try {
      var mismatches = [];
      collectOutputMismatches(schema, value, "$", 0, [], mismatches);
      if (!mismatches.length) {
        return;
      }
      var summary = mismatches.slice(0, 3).join("; ");
      var key = String(name) + "\0" + summary;
      if (warnedOutputMismatches.has(key)) {
        return;
      }
      warnedOutputMismatches.add(key);
      if (global.console && typeof global.console.warn === "function") {
        global.console.warn(
          "InsightUiWebmcp: tool " +
            JSON.stringify(name) +
            " result does not match outputSchema (" +
            summary +
            "). The result was returned anyway.",
        );
      }
    } catch (_err) {
      /* advisory only */
    }
  }

  /**
   * True when registerTool rejected outputSchema as a dictionary member
   * this browser does not implement. Invalid-schema failures stay visible.
   */
  function outputSchemaMemberRejected(err) {
    var message = err && err.message != null ? String(err.message) : "";
    if (message.indexOf("outputSchema") < 0) {
      return false;
    }
    var rest = message.split("outputSchema").join("");
    if (
      /circular|JSON\.stringify|seriali[sz]e|valid JSON|invalid schema|Unexpected token|Draft/i.test(
        rest,
      )
    ) {
      return false;
    }
    return /unexpected|unknown property|unsupported|not supported|extraneous|not a valid dictionary member/i.test(
      message,
    );
  }

  function toolWithoutOutputSchema(tool) {
    if (!Object.prototype.hasOwnProperty.call(tool, "outputSchema")) {
      return null;
    }
    var copy = Object.assign({}, tool);
    delete copy.outputSchema;
    return copy;
  }

  function toolForBrowser(tool) {
    if (outputSchemaAccepted === false) {
      return toolWithoutOutputSchema(tool) || tool;
    }
    return tool;
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
   * When `outputCheck` is set, a resolved result is compared to outputSchema.
   * A mismatch or a throw inside that check only warns. The resolved value
   * is unchanged.
   *
   * @param {function} handler
   * @param {{name: string, schema: object}|null} outputCheck
   * @returns {function}
   */
  function wrapExecute(handler, outputCheck) {
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
            if (outputCheck) {
              warnOutputMismatch(outputCheck.name, outputCheck.schema, result.value);
            }
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
    take("debugging", src.debugging);

    // Legacy manifest / host field → annotations.consequentialHint
    if (
      typeof annotations.consequentialHint !== "boolean" &&
      typeof spec.consequential === "boolean"
    ) {
      annotations.consequentialHint = spec.consequential;
      hasAny = true;
    }

    // Absence of a consequential hint does not establish read-only behavior.
    // readOnlyHint false here is the cautious default, not an assurance.
    // Missing readOnlyHint, destructiveHint, and openWorldHint must not be
    // treated as safe. This runtime stores side effects as consequentialHint.
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
  function validJsonSchemaObject(schema) {
    if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
      return false;
    }
    // A circular schema makes the meta-schema walker throw RangeError.
    // That is an invalid schema, not an uncaught rejection.
    try {
      return !!validators.validateInputSchema(schema);
    } catch (_err) {
      return false;
    }
  }

  function validInputSchema(schema) {
    return !!(validJsonSchemaObject(schema) && schema.type === "object");
  }

  /**
   * Validate and map a host/manifest tool into a ModelContextTool dictionary.
   * @param {object} spec
   * @param {boolean} [validateOutput] Dev-only result check. Never rejects.
   * @returns {{ ok: true, tool: object, name: string } | { ok: false, error: string, name?: string }}
   */
  function buildToolPayload(spec, validateOutput) {
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
      "debugging",
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
    var outputKeys = ["outputSchema", "output_schema"].filter(function (key) {
      return spec[key] !== undefined;
    });
    if (outputKeys.length > 1) {
      return {
        ok: false,
        error: "at most one of outputSchema or output_schema",
      };
    }
    if (
      outputKeys.length === 1 &&
      !validJsonSchemaObject(spec[outputKeys[0]])
    ) {
      return {
        ok: false,
        error: "output schema must be a valid JSON Schema object",
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
    if (hasInvisibleOrControl(name)) {
      return {
        ok: false,
        error: "tool name contains an invisible or control character",
        name: name,
      };
    }
    if (!TOOL_NAME_RE.test(name)) {
      return {
        ok: false,
        error:
          "tool name must match /^[A-Za-z0-9_.-]{1,128}$/ (use id for name, human text as title)",
        name: name,
      };
    }

    if (typeof spec.description !== "string") {
      return {
        ok: false,
        error: "non-empty description is required",
        name: name,
      };
    }
    // Inspect the raw description. trim() would drop a control or U+FEFF
    // that sits only at an edge and then accept the sanitized text.
    if (hasInvisibleOrControl(spec.description)) {
      return {
        ok: false,
        error: "description contains an invisible or control character",
        name: name,
      };
    }
    var description = spec.description.trim();
    if (!description) {
      return {
        ok: false,
        error: "non-empty description is required",
        name: name,
      };
    }
    if (hasInvisibleOrControl(title)) {
      return {
        ok: false,
        error: "title contains an invisible or control character",
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

    // Same object the host passed. Do not clone or rewrite it.
    var outputSchema =
      outputKeys.length === 1 ? spec[outputKeys[0]] : undefined;
    var tool = {
      name: name,
      description: description,
      execute: wrapExecute(
        spec.execute,
        validateOutput === true && outputSchema
          ? { name: name, schema: outputSchema }
          : null,
      ),
    };
    if (title) {
      tool.title = title;
    }

    var inputSchema = spec.inputSchema || spec.parameters || spec.input_schema;
    if (inputSchema && typeof inputSchema === "object") {
      tool.inputSchema = inputSchema;
    }
    if (outputSchema) {
      tool.outputSchema = outputSchema;
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
   * @param {boolean} [options.validateOutput] Warn when the result misses outputSchema.
   *   Off by default. Never rejects the tool result.
   * @returns {Promise<{ok: boolean, name?: string, error?: string}>}
   */
  function registerTool(spec, options) {
    options = options || {};

    return Promise.resolve().then(function () {
      var built = buildToolPayload(spec, options.validateOutput);
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
      var payload = toolForBrowser(built.tool);

      function registrationError(err, fallback) {
        if (controllersByName.get(built.name) === controller) {
          controllersByName.delete(built.name);
        }
        try {
          controller.abort();
        } catch (_thrown) {
          /* ignore */
        }
        return {
          ok: false,
          name: built.name,
          error: err && err.message ? String(err.message) : fallback,
        };
      }

      function registrationSuccess() {
        if (controller.signal.aborted) {
          if (controllersByName.get(built.name) === controller) {
            controllersByName.delete(built.name);
          }
          return {
            ok: false,
            name: built.name,
            error: "registration aborted before completion",
          };
        }
        return { ok: true, name: built.name };
      }

      // A synchronous throw must not escape as an uncaught rejection.
      function invokeRegister(tool) {
        return new Promise(function (resolve, reject) {
          var pending;
          try {
            pending = ctx.registerTool(tool, registerOpts);
          } catch (err) {
            reject({ err: err, fallback: "registerTool threw" });
            return;
          }
          Promise.resolve(pending).then(resolve, function (err) {
            reject({ err: err, fallback: "registerTool promise rejected" });
          });
        });
      }

      return invokeRegister(payload).then(
        function () {
          if (
            !controller.signal.aborted &&
            Object.prototype.hasOwnProperty.call(payload, "outputSchema")
          ) {
            outputSchemaAccepted = true;
          }
          return registrationSuccess();
        },
        function (failure) {
          var retry = toolWithoutOutputSchema(payload);
          if (!retry || !outputSchemaMemberRejected(failure.err)) {
            return registrationError(failure.err, failure.fallback);
          }
          // Remember before the retry so a later tool does not pay the
          // rejected call. The schema stays on the execute wrapper.
          outputSchemaAccepted = false;
          return invokeRegister(retry).then(
            function () {
              return registrationSuccess();
            },
            function (retryFailure) {
              return registrationError(retryFailure.err, retryFailure.fallback);
            },
          );
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
   * @param {boolean} [options.validateOutput] Passed to each registerTool.
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

          return registerTool(spec, {
            signal: options.signal,
            validateOutput: options.validateOutput,
          }).then(
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
    onToolActivated: onToolActivated,
    onToolCancel: onToolCancel,
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
