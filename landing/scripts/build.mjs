import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { transformSync } from "@babel/core";
import presetReact from "@babel/preset-react";

const landingDirectory = join(dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = join(landingDirectory, "dist");

const bundles = {
  "trace-app.js": [
    "src/Nav.jsx",
    "src/Hero.jsx",
    "src/Commands.jsx",
    "src/PRWalkthrough.jsx",
    "src/Install.jsx",
    "src/app.jsx",
  ],
  "trace-docs.js": ["src/Nav.jsx", "src/Install.jsx", "src/Docs.jsx"],
};

async function compileSource(sourcePath) {
  const source = await readFile(join(landingDirectory, sourcePath), "utf8");
  const result = transformSync(source, {
    babelrc: false,
    configFile: false,
    filename: sourcePath,
    presets: [[presetReact, { runtime: "classic" }]],
  });

  if (!result?.code) {
    throw new Error(`Could not compile ${sourcePath}`);
  }

  return `/* ${sourcePath} */\n${result.code}`;
}

async function buildBundle(outputName, sourcePaths) {
  const source = await Promise.all(sourcePaths.map(compileSource));
  await writeFile(join(outputDirectory, outputName), `${source.join("\n\n")}\n`);
}

await rm(outputDirectory, { force: true, recursive: true });
await mkdir(outputDirectory, { recursive: true });
await Promise.all([
  cp(join(landingDirectory, "favicons"), join(outputDirectory, "favicons"), { recursive: true }),
  ...["index.html", "docs.html", "styles.css", "logo.png"].map((file) =>
    cp(join(landingDirectory, file), join(outputDirectory, file)),
  ),
]);
await Promise.all(Object.entries(bundles).map(([outputName, sourcePaths]) => buildBundle(outputName, sourcePaths)));
