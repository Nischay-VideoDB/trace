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
  const [index, docs, appBundle, docsBundle, vercelConfig] = await Promise.all([
    readOutput("index.html"),
    readOutput("docs.html"),
    readOutput("trace-app.js"),
    readOutput("trace-docs.js"),
    readFile(join(landingDirectory, "vercel.json"), "utf8"),
  ]);

  for (const document of [index, docs]) {
    assert.doesNotMatch(document, /@babel\/standalone|text\/babel/i);
  }
  assert.match(index, /\/static\/trace-app\.js/);
  assert.match(docs, /\/static\/trace-docs\.js/);
  assert.match(appBundle, /\/\* src\/app\.jsx \*\//);
  assert.match(docsBundle, /\/\* src\/Docs\.jsx \*\//);
  assert.deepEqual(
    JSON.parse(vercelConfig).rewrites.find(({ source }) => source === "/favicon.ico"),
    { source: "/favicon.ico", destination: "/favicons/favicon-32.png" },
  );
  new Function(appBundle);
  new Function(docsBundle);
});

test("landing copy reports the supported vendor and CLI counts consistently", async () => {
  const [hero, commands] = await Promise.all([
    readFile(join(landingDirectory, "src/Hero.jsx"), "utf8"),
    readFile(join(landingDirectory, "src/Commands.jsx"), "utf8"),
  ]);

  assert.match(hero, /twenty-four API calls/);
  assert.match(hero, /CLI commands[\s\S]*>7</);
  assert.match(hero, /contribution-map/);
  assert.match(commands, /Seven verbs\. One pipeline\./);
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
});
