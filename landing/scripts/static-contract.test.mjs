import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const landingDirectory = join(fileURLToPath(new URL("..", import.meta.url)));
const outputDirectory = join(landingDirectory, "dist");

async function readOutput(file) {
  return readFile(join(outputDirectory, file), "utf8");
}

test("landing ships precompiled browser assets without runtime Babel", async () => {
  const [index, docs, appBundle, docsBundle, vercelConfig, manifest] = await Promise.all([
    readOutput("index.html"),
    readOutput("docs.html"),
    readOutput("trace-app.js"),
    readOutput("trace-docs.js"),
    readFile(join(landingDirectory, "vercel.json"), "utf8"),
    readFile(join(outputDirectory, "prepared-examples.v1.json"), "utf8"),
  ]);

  for (const document of [index, docs]) {
    assert.doesNotMatch(document, /@babel\/standalone|text\/babel/i);
  }
  assert.match(index, /\/static\/trace-app\.js/);
  assert.match(index, /hls\.js@1\.6\.16\/dist\/hls\.min\.js/);
  assert.match(index, /integrity="sha384-5E8B0pTlZZJMabWpC0fyYf6OUpe15jJij34BqBAh4NXoHAlLNOjCPRrwtOXOQFAn"/);
  assert.match(docs, /\/static\/trace-docs\.js/);
  assert.match(appBundle, /\/\* src\/app\.jsx \*\//);
  assert.match(appBundle, /\/\* src\/PreparedExamples\.jsx \*\//);
  assert.match(appBundle, /\/\* src\/Handoff\.jsx \*\//);
  assert.match(appBundle, /browser never captures your screen/);
  assert.match(docsBundle, /\/\* src\/Docs\.jsx \*\//);
  assert.deepEqual(
    JSON.parse(vercelConfig).rewrites.find(({ source }) => source === "/favicon.ico"),
    { source: "/favicon.ico", destination: "/favicons/favicon-32.png" },
  );
  new Function(appBundle);
  new Function(docsBundle);
  assert.equal(JSON.parse(manifest).version, 1);
});

test("hosted handoff is functional and keeps capture on the desktop", async () => {
  const [handoff, postRoute, getRoute, config] = await Promise.all([
    readFile(join(landingDirectory, "src/Handoff.jsx"), "utf8"),
    readFile(join(landingDirectory, "api/handoffs.mjs"), "utf8"),
    readFile(join(landingDirectory, "api/handoffs/[token].mjs"), "utf8"),
    readFile(join(landingDirectory, "vercel.json"), "utf8"),
  ]);
  assert.match(handoff, /fetch\("\/api\/handoffs"/);
  assert.match(handoff, /Local repository path/);
  assert.match(handoff, /value stays in your browser/);
  assert.match(postRoute, /idempotency-key/);
  assert.match(getRoute, /verifyHandoff/);
  assert.deepEqual(JSON.parse(config).regions, ["iad1"]);
});

test("prepared examples are complete, labelled, and stream original public outputs", async () => {
  const manifestSource = await readFile(join(landingDirectory, "prepared-examples.v1.json"), "utf8");
  const manifest = JSON.parse(manifestSource);
  const kinds = manifest.examples.map((example) => example.kind).sort();

  assert.equal(manifest.version, 1);
  assert.deepEqual(kinds, ["Bug fix", "Feature", "Refactor"]);
  assert.equal(new Set(manifest.examples.map((example) => example.id)).size, 3);
  assert.doesNotMatch(manifestSource, /api[_-]?key|token/i);

  for (const example of manifest.examples) {
    assert.equal(example.chapters.length, 3);
    assert.ok(example.chapters.every(({ start, end }) => Number.isFinite(start) && Number.isFinite(end) && start < end));
    assert.match(example.source.note, /public|synthetic/i);
    assert.ok(example.evidence.text.length > 30);
    assert.ok(example.transcript.text.length > 30 && example.transcript.citation.length > 4);
    assert.ok(example.qa.question.length > 10 && example.qa.answer.length > 30);
  }

  const feature = manifest.examples.find(({ kind }) => kind === "Feature");
  const bug = manifest.examples.find(({ kind }) => kind === "Bug fix");
  const refactor = manifest.examples.find(({ kind }) => kind === "Refactor");
  assert.match(feature.media.src, /^https:\/\/play\.videodb\.io\/v1\/.+\.m3u8$/);
  assert.match(bug.media.src, /^https:\/\/play\.videodb\.io\/v1\/.+\.m3u8$/);
  assert.match(feature.media.rights_note, /does not copy or redistribute/i);
  assert.match(bug.media.rights_note, /does not copy or redistribute/i);
  assert.equal(refactor.media.status, "unavailable");
  assert.match(refactor.media.message, /interactive timeline and evidence panel/i);
});

test("landing copy reports the supported vendor and CLI counts consistently", async () => {
  const [hero, commands] = await Promise.all([
    readFile(join(landingDirectory, "src/Hero.jsx"), "utf8"),
    readFile(join(landingDirectory, "src/Commands.jsx"), "utf8"),
  ]);

  assert.match(hero, /twenty-four API calls/);
  assert.match(hero, /CLI commands[\s\S]*>15</);
  assert.match(hero, /capture · index · inspect · generate · review/);
  assert.match(commands, /Seven core verbs\. One pipeline\./);
  assert.match(commands, /fifteen commands in total/i);
  assert.match(commands, /name: "trace contribution-map"/);
  assert.equal((commands.match(/name: "trace /g) ?? []).length, 7);
});

test("mobile cards and command tabs contain wide command text", async () => {
  const styles = await readFile(join(landingDirectory, "styles.css"), "utf8");

  assert.match(styles, /\.cmd-tabs\s*\{[\s\S]*?min-width:\s*0;[\s\S]*?max-width:\s*100%;[\s\S]*?overflow-x:\s*auto;/);
  assert.match(styles, /\.cmd-tab\s*\{[\s\S]*?flex:\s*0 0 auto;/);
  assert.match(styles, /\.install-step\s*\{\s*min-width:\s*0;/);
  assert.match(styles, /\.install-code\s*\{[\s\S]*?min-width:\s*0;[\s\S]*?max-width:\s*100%;[\s\S]*?overflow-x:\s*auto;/);
  assert.match(styles, /@media \(max-width:\s*600px\)\s*\{[\s\S]*?:root\s*\{\s*--page-pad:\s*32px;/);
  assert.match(styles, /@media \(max-width:\s*380px\)\s*\{[\s\S]*?:root\s*\{\s*--page-pad:\s*20px;/);
  assert.match(styles, /\.prepared-picker\s*\{[\s\S]*?grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(styles, /@media \(max-width:\s*700px\)\s*\{[\s\S]*?\.prepared-picker\s*\{\s*grid-template-columns:\s*1fr;/);
});
