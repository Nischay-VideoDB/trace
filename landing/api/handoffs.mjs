import { createHandoff, json, publicPlan, validateOptions } from "./_handoff.mjs";

export default {
  async fetch(request) {
    if (request.method !== "POST") return json({ error: "Method not allowed" }, 405, { allow: "POST" });
    const length = Number(request.headers.get("content-length") || 0);
    if (length > 4096) return json({ error: "Request body too large" }, 413);
    try {
      const raw = await request.text();
      if (raw.length > 4096) return json({ error: "Request body too large" }, 413);
      const options = validateOptions(JSON.parse(raw));
      const idempotencyKey = request.headers.get("idempotency-key") || "";
      if (idempotencyKey && !/^[A-Za-z0-9._:-]{8,120}$/.test(idempotencyKey)) {
        return json({ error: "Invalid Idempotency-Key" }, 400);
      }
      const { payload, token } = createHandoff(options, idempotencyKey);
      const plan = publicPlan(request, payload);
      const url = new URL(`/api/handoffs/${token}`, request.url).toString();
      return json({ ...plan, url, cliCommand: plan.cliCommand.replace("__TOKEN__", token) }, 201);
    } catch (error) {
      const message = error instanceof SyntaxError ? "Invalid JSON" : error instanceof Error ? error.message : "Invalid request";
      return json({ error: message.slice(0, 180) }, 400);
    }
  },
};
