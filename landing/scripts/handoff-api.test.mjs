import assert from "node:assert/strict";
import test from "node:test";

process.env.TRACE_HANDOFF_SECRET = "trace-test-secret-that-is-longer-than-thirty-two-bytes";

const [{ default: createHandler }, { default: readHandler }] = await Promise.all([
  import("../api/handoffs.mjs"),
  import("../api/handoffs/[token].mjs"),
]);

function createRequest(body, key = "trace-contract-001") {
  return new Request("https://trace-videodb.vercel.app/api/handoffs", {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": key },
    body: JSON.stringify(body),
  });
}

test("signed handoffs are idempotent, retrievable, and explicit about the boundary", async () => {
  const first = await createHandler.fetch(createRequest({ platform: "macos", live: true, microphone: false }));
  const second = await createHandler.fetch(createRequest({ platform: "macos", live: true, microphone: false }));
  assert.equal(first.status, 201);
  assert.equal(second.status, 201);
  const firstBody = await first.json();
  const secondBody = await second.json();
  assert.equal(firstBody.url, secondBody.url);
  assert.equal(firstBody.browserCaptures, false);
  assert.equal(firstBody.credentialsAccepted, false);
  assert.match(firstBody.commands.startTemplate, /--live --no-mic/);

  const read = await readHandler.fetch(new Request(firstBody.url));
  assert.equal(read.status, 200);
  const readBody = await read.json();
  assert.equal(readBody.id, firstBody.id);
  assert.match(readBody.boundary, /Native capture/);
});

test("handoff endpoints reject invalid bodies, methods, and signatures", async () => {
  const invalid = await createHandler.fetch(createRequest({ platform: "linux", live: true, microphone: true }, "trace-contract-002"));
  assert.equal(invalid.status, 400);
  const wrongMethod = await createHandler.fetch(new Request("https://trace-videodb.vercel.app/api/handoffs"));
  assert.equal(wrongMethod.status, 405);
  const tampered = await readHandler.fetch(new Request("https://trace-videodb.vercel.app/api/handoffs/not-a-token"));
  assert.equal(tampered.status, 404);
});
