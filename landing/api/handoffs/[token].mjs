import { json, publicPlan, verifyHandoff } from "../_handoff.mjs";

export default {
  fetch(request) {
    if (request.method !== "GET") return json({ error: "Method not allowed" }, 405, { allow: "GET" });
    try {
      const token = decodeURIComponent(new URL(request.url).pathname.split("/").pop() || "");
      const payload = verifyHandoff(token);
      const plan = publicPlan(request, payload);
      return json({ ...plan, url: request.url, cliCommand: plan.cliCommand.replace("__TOKEN__", token) });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Invalid handoff";
      const status = /Expired/.test(message) ? 410 : 404;
      return json({ error: message.slice(0, 180) }, status);
    }
  },
};
