import { json } from "./_handoff.mjs";

export default {
  fetch() {
    return json({
      ok: true,
      service: "trace-handoff",
      captureRuntime: "desktop-only",
      browserCapture: false,
      provider: "VideoDB Capture SDK",
    });
  },
};
