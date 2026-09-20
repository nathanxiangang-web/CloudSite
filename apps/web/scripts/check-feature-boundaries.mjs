#!/usr/bin/env node

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const MIGRATION_STATUSES = new Set(["skeleton", "partial", "complete"]);

function posix(value) {
  return value.split(path.sep).join("/");
}

function isInside(child, parent) {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function sourceFiles(root) {
  if (!fs.existsSync(root)) return [];
  const result = [];
  const stack = [root];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(full);
      else if (/\.(?:ts|tsx|js|jsx|mjs|mts)$/.test(entry.name)) result.push(full);
    }
  }
  return result;
}

function importsFrom(source) {
  const result = [];
  const patterns = [
    /\b(?:import|export)\s+(?:[^"'\n]*?\s+from\s+)?["']([^"']+)["']/g,
    /\bimport\(\s*["']([^"']+)["']\s*\)/g,
  ];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(source)) !== null) result.push(match[1]);
  }
  return result;
}

function featureTargetFromAlias(specifier) {
  const match = specifier.match(/^@\/features\/([^/]+)(?:\/(.+))?$/);
  if (!match) return null;
  return { feature: match[1], internal: Boolean(match[2]) };
}

function featureTargetFromRelative(file, specifier, featuresRoot) {
  if (!specifier.startsWith(".")) return null;
  const resolved = path.resolve(path.dirname(file), specifier);
  if (!isInside(resolved, featuresRoot)) return null;
  const relative = path.relative(featuresRoot, resolved);
  const parts = relative.split(path.sep).filter(Boolean);
  if (!parts.length) return null;
  const feature = parts[0];
  const rest = parts.slice(1);
  const internal =
    rest.length > 0 &&
    !(rest.length === 1 && /^index(?:\.[^.]+)?$/.test(rest[0]));
  return { feature, internal };
}

export function collectViolations(projectRoot, baselineOverride = null) {
  const srcRoot = path.join(projectRoot, "src");
  const featuresRoot = path.join(srcRoot, "features");
  const uiRoot = path.join(srcRoot, "components", "ui");
  const appRoot = path.join(srcRoot, "app");
  const violations = [];

  if (fs.existsSync(featuresRoot)) {
    for (const entry of fs.readdirSync(featuresRoot, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.name.startsWith("_")) continue;
      const featureRoot = path.join(featuresRoot, entry.name);
      const manifestPath = path.join(featureRoot, "feature.json");
      const publicEntryTs = path.join(featureRoot, "index.ts");
      const publicEntryTsx = path.join(featureRoot, "index.tsx");

      if (!fs.existsSync(manifestPath)) {
        violations.push("features/" + entry.name + "/feature.json is missing");
      } else {
        try {
          const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
          if (manifest.schema_version !== 1) {
            violations.push("features/" + entry.name + "/feature.json schema_version must be 1");
          }
          if (manifest.name !== entry.name) {
            violations.push("features/" + entry.name + "/feature.json name must match directory");
          }
          if (!MIGRATION_STATUSES.has(manifest.migration_status)) {
            violations.push("features/" + entry.name + "/feature.json migration_status is invalid");
          }
          if (manifest.public_entry !== "index.ts" && manifest.public_entry !== "index.tsx") {
            violations.push("features/" + entry.name + "/feature.json public_entry must be index.ts or index.tsx");
          }
        } catch (error) {
          violations.push("features/" + entry.name + "/feature.json is invalid JSON: " + error.message);
        }
      }

      if (!fs.existsSync(publicEntryTs) && !fs.existsSync(publicEntryTsx)) {
        violations.push("features/" + entry.name + " is missing public index.ts/index.tsx");
      }
    }
  }

  const allFiles = sourceFiles(srcRoot);
  for (const file of allFiles) {
    const source = fs.readFileSync(file, "utf8");
    const relativeFile = posix(path.relative(projectRoot, file));
    const inFeatures = isInside(file, featuresRoot);
    const inUi = isInside(file, uiRoot);
    const inApp = isInside(file, appRoot);
    const sourceFeature = inFeatures
      ? path.relative(featuresRoot, file).split(path.sep)[0]
      : null;

    for (const specifier of importsFrom(source)) {
      const target =
        featureTargetFromAlias(specifier) ||
        featureTargetFromRelative(file, specifier, featuresRoot);
      if (!target) continue;

      if (inUi) {
        violations.push(relativeFile + " must not import business feature '" + target.feature + "'");
        continue;
      }

      if (inApp && target.internal) {
        violations.push(relativeFile + " imports internal files from feature '" + target.feature + "'; import its public entry point");
        continue;
      }

      if (inFeatures && sourceFeature !== target.feature && target.internal) {
        violations.push(relativeFile + " imports internals from feature '" + target.feature + "'; cross-feature imports must use the public entry point");
      }
    }
  }

  const baseline = baselineOverride || JSON.parse(
    fs.readFileSync(path.join(projectRoot, "frontend-architecture-baseline.json"), "utf8"),
  );
  const globalsPath = path.join(srcRoot, "app", "globals.css");
  if (fs.existsSync(globalsPath)) {
    const currentBytes = fs.statSync(globalsPath).size;
    if (currentBytes > baseline.globals_css_max_bytes) {
      violations.push(
        "src/app/globals.css grew to " + currentBytes +
        " bytes (baseline max " + baseline.globals_css_max_bytes +
        "); move feature CSS into features/<name>/styles instead",
      );
    }
  }

  return violations;
}

function runSelfTest() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cloudsite-web-arch-"));
  try {
    fs.mkdirSync(path.join(root, "src", "features", "alpha", "views"), { recursive: true });
    fs.mkdirSync(path.join(root, "src", "features", "beta", "internal"), { recursive: true });
    fs.mkdirSync(path.join(root, "src", "app", "demo"), { recursive: true });
    fs.mkdirSync(path.join(root, "src", "components", "ui"), { recursive: true });

    for (const name of ["alpha", "beta"]) {
      fs.writeFileSync(
        path.join(root, "src", "features", name, "feature.json"),
        JSON.stringify({
          schema_version: 1,
          name,
          migration_status: "partial",
          public_entry: "index.ts",
          routes: [],
        }),
      );
      fs.writeFileSync(path.join(root, "src", "features", name, "index.ts"), "export {};\n");
    }

    fs.writeFileSync(
      path.join(root, "src", "features", "alpha", "views", "A.ts"),
      'import "@/features/beta/internal/secret";\n',
    );
    fs.writeFileSync(
      path.join(root, "src", "app", "demo", "page.tsx"),
      'import "@/features/alpha/views/A";\n',
    );
    fs.writeFileSync(
      path.join(root, "src", "components", "ui", "Button.tsx"),
      'import "@/features/alpha";\n',
    );
    fs.writeFileSync(path.join(root, "src", "app", "globals.css"), "12345");

    const violations = collectViolations(root, { globals_css_max_bytes: 4 });
    const expected = [
      "cross-feature imports must use the public entry point",
      "import its public entry point",
      "must not import business feature",
      "globals.css grew",
    ];
    for (const fragment of expected) {
      if (!violations.some((item) => item.includes(fragment))) {
        throw new Error("self-test missing expected violation: " + fragment + "\n" + violations.join("\n"));
      }
    }
    console.log("frontend architecture self-test PASSED (" + violations.length + " deliberate violations detected)");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

function main() {
  if (process.argv.includes("--self-test")) {
    runSelfTest();
    return;
  }
  const projectRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
  const violations = collectViolations(projectRoot);
  if (violations.length) {
    console.error("Frontend architecture gate FAILED:");
    for (const violation of violations) console.error("  - " + violation);
    process.exit(1);
  }
  const baseline = JSON.parse(
    fs.readFileSync(path.join(projectRoot, "frontend-architecture-baseline.json"), "utf8"),
  );
  const globalsBytes = fs.statSync(path.join(projectRoot, "src", "app", "globals.css")).size;
  console.log(
    "Frontend architecture gate PASSED: globals.css=" + globalsBytes +
    "/" + baseline.globals_css_max_bytes + " bytes",
  );
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) main();
