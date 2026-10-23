#!/usr/bin/env node
import {createHash} from "node:crypto";
import {lstat, readdir, readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUTPUT = path.join(ROOT, "closure-manifest.json");
const INCLUDED_ROOTS = ["node_modules"];
const INCLUDED_FILES = [
  "package.json", "package-lock.json", "runtime-contract.json",
  "card-dispatch.mjs", "render-core.mjs", "foundation-contract.json", "scene-foundation-contract.json", "text-layout-contract.json", "time-domain-contract.json", "determinism-contract.json",
  "src/index.tsx", "src/mechanism-probe.tsx", "src/foundation-probe.tsx",
  "src/visual-foundations.tsx", "src/scene-foundations.tsx", "src/scene-probe.tsx",
  "src/text-layout.tsx", "src/text-layout-probe.tsx",
  "src/time-domain.ts", "src/time-domain-probe.tsx",
  "src/media-playback.ts", "src/media-playback-video.tsx",
  "src/isolation.ts", "src/anime-runtime.ts", "src/anime-bridge.ts", "src/three-bridge.tsx", "src/determinism-probe.tsx",
  "src/production-card-root.tsx", "src/production-input.ts",
  "public/time-domain-cfr-20fps.mp4",
];

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

const collect = async (relative, records) => {
  if (["node_modules/.cache", "node_modules/.remotion"].some((cache) => relative === cache || relative.startsWith(`${cache}/`))) return;
  const absolute = path.join(ROOT, ...relative.split("/"));
  const info = await lstat(absolute);
  if (info.isSymbolicLink()) {
    if (relative.split("/").includes(".bin")) return;
    throw new Error(`unexpected runtime symlink: ${relative}`);
  }
  if (info.isDirectory()) {
    const children = (await readdir(absolute)).sort();
    for (const child of children) await collect(`${relative}/${child}`, records);
    return;
  }
  if (!info.isFile()) throw new Error(`unsupported runtime entry: ${relative}`);
  const bytes = await readFile(absolute);
  records.push({path: relative, sha256: sha256(bytes), mode: info.mode & 0o777});
};

const files = [];
for (const relative of [...INCLUDED_FILES, ...INCLUDED_ROOTS]) await collect(relative, files);
files.sort((left, right) => left.path < right.path ? -1 : left.path > right.path ? 1 : 0);
const identity = {
  schema_version: "talkcraft-runtime-closure/v1",
  platform: {os: process.platform, arch: process.arch},
  runtime_versions: {
    node: process.versions.node,
    react: "18.3.1",
    remotion: "4.0.520",
    typescript: "5.9.2",
  },
  files,
};
const closureId = sha256(Buffer.from(JSON.stringify(identity)));
const manifest = {...identity, closure_id: closureId};
await writeFile(OUTPUT, `${JSON.stringify(manifest, null, 2)}\n`, {flag: "w"});
const bytes = await readFile(OUTPUT);
process.stdout.write(`${JSON.stringify({path: OUTPUT, files: files.length, closure_id: closureId, sha256: sha256(bytes)})}\n`);
