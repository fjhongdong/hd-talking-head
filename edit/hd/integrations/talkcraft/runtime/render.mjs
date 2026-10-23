#!/usr/bin/env node
import {createHash} from "node:crypto";
import {constants as fsConstants} from "node:fs";
import {chmod, copyFile, lstat, mkdir, mkdtemp, readFile, readdir, realpath, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {pathToFileURL} from "node:url";

const EXPECTED_MANIFEST_SHA256 = "3914bb75ece129a1c0cdbe20352580de7ec8f73cfc2028bbb3c586d2565315bd";
const MANIFEST_NAME = "closure-manifest.json";
const REGISTRY_NAME = "card-registry.json";
const HASH = /^[0-9a-f]{64}$/;
const CARD_ARTIFACT = /^[a-z][a-z0-9-]{0,63}\.(?:tsx|contract\.json)$/;
const CASE_FILE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$/;
const ASSET_ID = /^[a-z][a-z0-9-]{0,63}$/;

const fail = (message) => {
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
};

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

const runtimeRootArgument = (argv) => {
  const indices = argv.flatMap((value, index) => value === "--runtime-root" ? [index] : []);
  if (indices.length !== 1 || indices[0] + 1 >= argv.length) {
    throw new Error("runtime root is required exactly once");
  }
  const value = argv[indices[0] + 1];
  if (!path.isAbsolute(value) || path.normalize(value) !== value) {
    throw new Error("runtime root must be canonical absolute");
  }
  return value;
};

const safeRelative = (value) => {
  if (typeof value !== "string" || value.length === 0 || value.includes("\\")) return false;
  const parts = value.split("/");
  return !path.posix.isAbsolute(value) && parts.every((part) => part && part !== "." && part !== "..");
};

const fileStamp = (value) => [
  value.dev, value.ino, value.mode, value.size, value.mtimeMs, value.ctimeMs,
].join(":");

const snapshotBusinessRegistry = async (root, snapshot) => {
  const source = path.join(root, REGISTRY_NAME);
  const before = await lstat(source);
  if (!before.isFile() || before.isSymbolicLink() || before.size <= 0 || before.size > 4 * 1024 * 1024) {
    throw new Error("TalkCraft registry snapshot is invalid");
  }
  const bytes = await readFile(source);
  const after = await lstat(source);
  if (bytes.length !== before.size || fileStamp(before) !== fileStamp(after)) {
    throw new Error("TalkCraft registry changed while snapshotting");
  }
  await writeFile(path.join(snapshot, REGISTRY_NAME), bytes, {flag: "wx"});
};

const snapshotCardModules = async (root, snapshot) => {
  const sourceRoot = path.join(root, "src", "cards");
  const sourceRootInfo = await lstat(sourceRoot);
  if (!sourceRootInfo.isDirectory() || sourceRootInfo.isSymbolicLink()) {
    throw new Error("TalkCraft card module directory is invalid");
  }
  const names = (await readdir(sourceRoot)).filter((name) => name.endsWith(".tsx") || name.endsWith(".contract.json")).sort();
  if (names.length > 216 || names.some((name) => !CARD_ARTIFACT.test(name))) {
    throw new Error("TalkCraft card module directory is invalid");
  }
  const moduleIds = names.filter((name) => name.endsWith(".tsx")).map((name) => name.slice(0, -4));
  const contractIds = names.filter((name) => name.endsWith(".contract.json")).map((name) => name.slice(0, -14));
  if (JSON.stringify(moduleIds) !== JSON.stringify(contractIds)) throw new Error("TalkCraft card module and contract sets differ");
  const targetRoot = path.join(snapshot, "src", "cards");
  await mkdir(targetRoot, {recursive: true});
  for (const name of names) {
    const source = path.join(sourceRoot, name);
    const before = await lstat(source);
    if (!before.isFile() || before.isSymbolicLink() || before.size <= 0 || before.size > 1024 * 1024) {
      throw new Error(`TalkCraft card module is invalid: ${name}`);
    }
    const bytes = await readFile(source);
    const after = await lstat(source);
    if (bytes.length !== before.size || fileStamp(before) !== fileStamp(after)) {
      throw new Error(`TalkCraft card module changed while snapshotting: ${name}`);
    }
    await writeFile(path.join(targetRoot, name), bytes, {flag: "wx"});
  }
};

const snapshotProductionAdapters = async (root, snapshot) => {
  const sourceRoot = path.join(root, "src", "production-adapters");
  const names = (await readdir(sourceRoot)).filter((name) => name.endsWith(".ts")).sort();
  if (names.length < 1 || names.length > 109 || names.some((name) => !/^[a-z][a-z0-9-]{0,63}\.ts$/.test(name))) {
    throw new Error("TalkCraft production adapter directory is invalid");
  }
  const targetRoot = path.join(snapshot, "src", "production-adapters");
  await mkdir(targetRoot, {recursive: true});
  for (const name of names) {
    const source = path.join(sourceRoot, name);
    const before = await lstat(source);
    if (!before.isFile() || before.isSymbolicLink() || before.size <= 0 || before.size > 128 * 1024) {
      throw new Error(`TalkCraft production adapter is invalid: ${name}`);
    }
    const bytes = await readFile(source);
    const after = await lstat(source);
    if (bytes.length !== before.size || fileStamp(before) !== fileStamp(after)) {
      throw new Error(`TalkCraft production adapter changed while snapshotting: ${name}`);
    }
    await writeFile(path.join(targetRoot, name), bytes, {flag: "wx"});
  }
};

const snapshotQualificationCases = async (root, snapshot) => {
  const sourceRoot = path.join(root, "qualification-cases");
  const names = (await readdir(sourceRoot)).filter((name) => name.endsWith(".json")).sort();
  if (names.length > 108 || names.some((name) => !CASE_FILE.test(name))) {
    throw new Error("TalkCraft qualification cases directory is invalid");
  }
  const targetRoot = path.join(snapshot, "qualification-cases");
  await mkdir(targetRoot, {recursive: true});
  for (const name of names) {
    const source = path.join(sourceRoot, name);
    const before = await lstat(source);
    if (!before.isFile() || before.isSymbolicLink() || before.size <= 0 || before.size > 1024 * 1024) {
      throw new Error(`TalkCraft qualification cases are invalid: ${name}`);
    }
    const bytes = await readFile(source);
    const after = await lstat(source);
    if (bytes.length !== before.size || fileStamp(before) !== fileStamp(after)) {
      throw new Error(`TalkCraft qualification cases changed while snapshotting: ${name}`);
    }
    await writeFile(path.join(targetRoot, name), bytes, {flag: "wx"});
  }
};

const snapshotQualificationFixtures = async (root, snapshot) => {
  const manifestPath = path.join(root, "qualification-fixtures.json");
  const manifestBytes = await readFile(manifestPath);
  const manifest = JSON.parse(manifestBytes.toString("utf8"));
  if (manifest?.schema_version !== "talkcraft-qualification-fixtures/v2" || !Array.isArray(manifest.assets) || manifest.assets.length < 1 || manifest.assets.length > 216) {
    throw new Error("TalkCraft qualification fixture manifest is invalid");
  }
  const assetIds = new Set();
  const publicPaths = new Set();
  for (const asset of manifest.assets) {
    const hasDimensions = asset?.kind === "image" || asset?.kind === "video-alpha";
    const expectedKeys = hasDimensions ? "asset_id,height,kind,public_path,sha256,source,width" : "asset_id,kind,public_path,sha256,source";
    if (asset === null || typeof asset !== "object" || Object.keys(asset).sort().join(",") !== expectedKeys ||
        !ASSET_ID.test(asset.asset_id) || assetIds.has(asset.asset_id) || !safeRelative(asset.source) || !safeRelative(asset.public_path) ||
        !new Set(["audio", "image", "video", "video-alpha"]).has(asset.kind) || !asset.public_path.startsWith("qualification/") || publicPaths.has(asset.public_path) || !HASH.test(asset.sha256) ||
        (hasDimensions && (!Number.isInteger(asset.width) || !Number.isInteger(asset.height) || asset.width <= 0 || asset.height <= 0))) {
      throw new Error("TalkCraft qualification fixture record is invalid");
    }
    assetIds.add(asset.asset_id);
    publicPaths.add(asset.public_path);
    const source = path.join(root, ...asset.source.split("/"));
    const before = await lstat(source);
    if (!before.isFile() || before.isSymbolicLink() || before.size <= 0 || before.size > 32 * 1024 * 1024) {
      throw new Error(`TalkCraft qualification fixture is invalid: ${asset.asset_id}`);
    }
    const bytes = await readFile(source);
    const after = await lstat(source);
    if (bytes.length !== before.size || fileStamp(before) !== fileStamp(after) || sha256(bytes) !== asset.sha256) {
      throw new Error(`TalkCraft qualification fixture identity mismatch: ${asset.asset_id}`);
    }
    const destination = path.join(snapshot, "public", ...asset.public_path.split("/"));
    await mkdir(path.dirname(destination), {recursive: true});
    await writeFile(destination, bytes, {flag: "wx"});
  }
  await writeFile(path.join(snapshot, "qualification-fixtures.json"), manifestBytes, {flag: "wx"});
};

const snapshotRuntime = async (root) => {
  const resolved = await realpath(root);
  const rootInfo = await lstat(root);
  if (resolved !== root || !rootInfo.isDirectory() || rootInfo.isSymbolicLink()) {
    throw new Error("runtime root identity is invalid");
  }
  const manifestBytes = await readFile(path.join(root, MANIFEST_NAME));
  if (sha256(manifestBytes) !== EXPECTED_MANIFEST_SHA256 || !HASH.test(EXPECTED_MANIFEST_SHA256)) {
    throw new Error("runtime closure manifest identity mismatch");
  }
  const manifest = JSON.parse(manifestBytes.toString("utf8"));
  if (
    manifest?.schema_version !== "talkcraft-runtime-closure/v1" ||
    manifest?.platform?.os !== process.platform ||
    manifest?.platform?.arch !== process.arch ||
    manifest?.runtime_versions?.node !== process.versions.node ||
    !Array.isArray(manifest.files) || manifest.files.length === 0
  ) {
    throw new Error("runtime closure manifest contract is invalid");
  }
  const names = new Set();
  const snapshot = await mkdtemp(path.join(tmpdir(), "talkcraft-runtime-"));
  try {
    for (const record of manifest.files) {
      if (
        record === null || typeof record !== "object" ||
        Object.keys(record).sort().join(",") !== "mode,path,sha256" ||
        !safeRelative(record.path) || names.has(record.path) ||
        !HASH.test(record.sha256) || !Number.isInteger(record.mode) ||
        record.mode < 0 || record.mode > 0o777
      ) {
        throw new Error("runtime closure file record is invalid");
      }
      names.add(record.path);
      const source = path.join(root, ...record.path.split("/"));
      const sourceInfo = await lstat(source);
      if (!sourceInfo.isFile() || sourceInfo.isSymbolicLink()) {
        throw new Error(`runtime closure source is invalid: ${record.path}`);
      }
      const destination = path.join(snapshot, ...record.path.split("/"));
      await mkdir(path.dirname(destination), {recursive: true});
      try {
        await copyFile(source, destination, fsConstants.COPYFILE_FICLONE_FORCE);
      } catch {
        await copyFile(source, destination, fsConstants.COPYFILE_FICLONE);
      }
      await chmod(destination, record.mode);
      const copied = await readFile(destination);
      if (sha256(copied) !== record.sha256) {
        throw new Error(`runtime closure file identity mismatch: ${record.path}`);
      }
    }
    if (!names.has("render-core.mjs") || !names.has("card-dispatch.mjs") || !names.has("src/index.tsx") || !names.has("package-lock.json")) {
      throw new Error("runtime closure is incomplete");
    }
    if (names.has(REGISTRY_NAME)) throw new Error("business registry must not be part of the common runtime closure");
    await snapshotBusinessRegistry(root, snapshot);
    await snapshotCardModules(root, snapshot);
    await snapshotProductionAdapters(root, snapshot);
    await snapshotQualificationCases(root, snapshot);
    await snapshotQualificationFixtures(root, snapshot);
    return snapshot;
  } catch (error) {
    await rm(snapshot, {recursive: true, force: true});
    throw error;
  }
};

const main = async () => {
  const argv = process.argv.slice(2);
  const liveRoot = runtimeRootArgument(argv);
  const snapshot = await snapshotRuntime(liveRoot);
  try {
    const core = await import(pathToFileURL(path.join(snapshot, "render-core.mjs")).href);
    if (typeof core.run !== "function") throw new Error("verified runtime core is invalid");
    const snapshotArgv = argv.map((value, index) => argv[index - 1] === "--runtime-root" ? snapshot : value);
    await core.run(snapshotArgv, {runtimeRoot: snapshot});
  } finally {
    await rm(snapshot, {recursive: true, force: true});
  }
};

main().catch((error) => fail(error instanceof Error ? error.message : "TalkCraft render failed"));
