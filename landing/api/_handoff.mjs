import { createHash, createHmac, timingSafeEqual } from "node:crypto";

const VERSION = 1;
const MAX_AGE_SECONDS = 24 * 60 * 60;

function secret() {
  const value = process.env.TRACE_HANDOFF_SECRET;
  if (!value || value.length < 32) throw new Error("TRACE_HANDOFF_SECRET is not configured");
  return value;
}

function encode(value) {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function sign(encoded) {
  return createHmac("sha256", secret()).update(encoded).digest("base64url");
}

export function createHandoff(options, idempotencyKey = "") {
  const now = Math.floor(Date.now() / 1000);
  const issuedAt = idempotencyKey ? Math.floor(now / 3600) * 3600 : now;
  const material = JSON.stringify({ options, idempotencyKey, issuedAt });
  const id = `th_${createHash("sha256").update(material).digest("hex").slice(0, 16)}`;
  const payload = {
    version: VERSION,
    id,
    issuedAt,
    expiresAt: issuedAt + MAX_AGE_SECONDS,
    options,
    browserCaptures: false,
    credentialsAccepted: false,
  };
  const encoded = encode(payload);
  return { payload, token: `${encoded}.${sign(encoded)}` };
}

export function verifyHandoff(token) {
  if (!/^[A-Za-z0-9_-]{40,1600}\.[A-Za-z0-9_-]{43}$/.test(token)) {
    throw new Error("Invalid handoff token");
  }
  const [encoded, supplied] = token.split(".");
  const expected = sign(encoded);
  const suppliedBytes = Buffer.from(supplied);
  const expectedBytes = Buffer.from(expected);
  if (suppliedBytes.length !== expectedBytes.length || !timingSafeEqual(suppliedBytes, expectedBytes)) {
    throw new Error("Invalid handoff signature");
  }
  const payload = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
  const now = Math.floor(Date.now() / 1000);
  if (payload.version !== VERSION || payload.browserCaptures !== false || payload.expiresAt < now) {
    throw new Error("Expired or invalid handoff");
  }
  return payload;
}

export function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "cache-control": "no-store",
      "content-type": "application/json; charset=utf-8",
      "x-content-type-options": "nosniff",
      ...extraHeaders,
    },
  });
}

export function validateOptions(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("JSON object required");
  const platform = value.platform;
  if (platform !== "macos" && platform !== "windows") throw new Error("platform must be macos or windows");
  if (typeof value.live !== "boolean" || typeof value.microphone !== "boolean") {
    throw new Error("live and microphone must be boolean");
  }
  return { platform, live: value.live, microphone: value.microphone };
}

export function publicPlan(request, payload) {
  const origin = new URL(request.url).origin;
  const extra = payload.options.platform === "macos" ? "macos" : "windows";
  return {
    ...payload,
    boundary: "The browser creates setup instructions only. Native capture starts after explicit OS consent on the developer machine.",
    requirements: ["Python 3.12", "uv", "git", `VideoDB Capture SDK for ${payload.options.platform}`],
    commands: {
      install: `git clone https://github.com/Nischay-VideoDB/trace.git && cd trace && uv sync --extra ${extra}`,
      verify: "uv run trace doctor --project /absolute/path/to/repository",
      startTemplate: `uv run trace start --project /absolute/path/to/repository${payload.options.live ? " --live" : ""}${payload.options.microphone ? "" : " --no-mic"}`,
    },
    cliCommand: `uv run trace handoff ${origin}/api/handoffs/__TOKEN__ --project /absolute/path/to/repository`,
  };
}
