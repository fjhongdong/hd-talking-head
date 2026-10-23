#!/usr/bin/env node
import {createHash} from "node:crypto";
import {copyFile, mkdir, readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";

const runtimeRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const upstreamRoot = path.resolve(runtimeRoot, "..", "upstream");
const outputRoot = path.join(runtimeRoot, "qualification-fixtures");
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

const hostSource = path.join(upstreamRoot, "demos", "_lib", "dh-host.webm");
const hostBytes = await readFile(hostSource);
if (sha256(hostBytes) !== "02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af") {
  throw new Error("qualification presenter fixture identity mismatch");
}

const samplesSource = path.join(upstreamRoot, "demos", "_lib", "sfx-samples.js");
const samplesText = await readFile(samplesSource, "utf8");
const prefix = "window.SFX_SAMPLES = ";
const start = samplesText.indexOf(prefix);
const end = samplesText.lastIndexOf(";");
if (start < 0 || end <= start) throw new Error("upstream SFX sample table is invalid");
const samples = JSON.parse(samplesText.slice(start + prefix.length, end));
const clickBytes = Buffer.from(samples.click ?? "", "base64");
if (sha256(clickBytes) !== "dcb764a9be9ac69e64c8a4736513d019ce270dd9e62ffea311a8abfa0efb8e60") {
  throw new Error("qualification click fixture identity mismatch");
}
const uiPopBytes = Buffer.from(samples["pk:ui-pop"] ?? "", "base64");
if (sha256(uiPopBytes) !== "e19e3e04563c470068ee8fd179fb4d0ac2a6e51724cb60fd2e92237c456eacd4") {
  throw new Error("qualification UI pop fixture identity mismatch");
}
const markerBytes = Buffer.from(samples["pk:text-marker-pen-line"] ?? "", "base64");
if (sha256(markerBytes) !== "3bb80d474f1b1ca2a03bb63f43f36338f164a1201e1f6bf95e0a1c00a74cc744") {
  throw new Error("qualification marker fixture identity mismatch");
}
const mechLockBytes = Buffer.from(samples["pk:mech-lock-quick"] ?? "", "base64");
if (sha256(mechLockBytes) !== "2ec67a68f9c13bdb75f5fdfb6aacac4d76eba048d16795754c473b08bb5a9182") {
  throw new Error("qualification mechanical lock fixture identity mismatch");
}
const swooshBytes = Buffer.from(samples["pk:transition-wind-swoosh-short"] ?? "", "base64");
if (sha256(swooshBytes) !== "61918d34661288c794664885f97674e22694f5ef01be815ee6ad33c8c14a7d89") {
  throw new Error("qualification wind swoosh fixture identity mismatch");
}
const oceanSource = path.join(upstreamRoot, "demos", "_lib", "media", "v-ocean.webm");
const typingSource = path.join(upstreamRoot, "demos", "_lib", "media", "v-typing.webm");
const oceanBytes = await readFile(oceanSource);
const typingBytes = await readFile(typingSource);
if (sha256(oceanBytes) !== "27a5027a92f74e8de594e3fe9653857fd705e9fc05cea38fd8e96341c2d5cd45" ||
    sha256(typingBytes) !== "b314d507fbe21e9f9588ea216722861cc9423e66722a46396f6529f0d6816c5f") {
  throw new Error("qualification scene video fixture identity mismatch");
}
const calloutLaptopSource = path.join(upstreamRoot, "demos", "_lib", "media", "p-0.jpg");
const calloutDeskSource = path.join(upstreamRoot, "demos", "_lib", "media", "p-60.jpg");
const calloutLaptopBytes = await readFile(calloutLaptopSource);
const calloutDeskBytes = await readFile(calloutDeskSource);
if (sha256(calloutLaptopBytes) !== "d91b8db3ded913eac99572c2752aaec64b9aef1b37cdbb9be0ae58c0e0336af7" ||
    sha256(calloutDeskBytes) !== "ddb49dc09886c023888ff53bcb2608fcb8f270645c0c09811016ad9ccec80e65") {
  throw new Error("qualification callout image fixture identity mismatch");
}
const impactBytes = Buffer.from(samples["pk:impact-hit-fast-exciting"] ?? "", "base64");
if (sha256(impactBytes) !== "a4853ac0fec244fc92934f129953252c885007249e79db02171cb41a9c018f00") {
  throw new Error("qualification impact fixture identity mismatch");
}
const deepWhooshBytes = Buffer.from(samples["pk:impact-impact-deep-whoosh"] ?? "", "base64");
if (sha256(deepWhooshBytes) !== "9aa95b3ad01c1f3ebb7b260c6d6cd346bf4a8f2f7b03298b046e108e8f5c93d4") {
  throw new Error("qualification deep whoosh fixture identity mismatch");
}

await mkdir(outputRoot, {recursive: true});
await copyFile(hostSource, path.join(outputRoot, "alt-block-lines-host.webm"));
await copyFile(oceanSource, path.join(outputRoot, "shape-wipe-ocean.webm"));
await copyFile(typingSource, path.join(outputRoot, "shape-wipe-typing.webm"));
await copyFile(calloutLaptopSource, path.join(outputRoot, "callout-laptop.jpg"));
await copyFile(calloutDeskSource, path.join(outputRoot, "callout-desk.jpg"));
await writeFile(path.join(outputRoot, "talkcraft-click.mp3"), clickBytes);
await writeFile(path.join(outputRoot, "talkcraft-ui-pop.mp3"), uiPopBytes);
await writeFile(path.join(outputRoot, "talkcraft-text-marker-pen-line.mp3"), markerBytes);
await writeFile(path.join(outputRoot, "talkcraft-mech-lock-quick.mp3"), mechLockBytes);
await writeFile(path.join(outputRoot, "talkcraft-impact-hit-fast-exciting.mp3"), impactBytes);
await writeFile(path.join(outputRoot, "talkcraft-impact-deep-whoosh.mp3"), deepWhooshBytes);
await writeFile(path.join(outputRoot, "talkcraft-wind-swoosh-short.mp3"), swooshBytes);
process.stdout.write(`${JSON.stringify({presenter_sha256: sha256(hostBytes), ocean_sha256: sha256(oceanBytes), typing_sha256: sha256(typingBytes), callout_laptop_sha256: sha256(calloutLaptopBytes), callout_desk_sha256: sha256(calloutDeskBytes), click_sha256: sha256(clickBytes), ui_pop_sha256: sha256(uiPopBytes), marker_sha256: sha256(markerBytes), mech_lock_sha256: sha256(mechLockBytes), impact_sha256: sha256(impactBytes), deep_whoosh_sha256: sha256(deepWhooshBytes), swoosh_sha256: sha256(swooshBytes)})}\n`);
