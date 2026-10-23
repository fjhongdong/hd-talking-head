import {createHash} from "node:crypto";
import {lstat, readFile} from "node:fs/promises";
import path from "node:path";

const HASH = /^[0-9a-f]{64}$/;
const CARD_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const ROLES = new Set(["annotation", "camera", "overlay", "scene", "transition"]);
const LAYERS = new Set(["annotation", "base", "inset", "overlay"]);
const ENTRYPOINT_PREFIX = "edit/hd/integrations/talkcraft/runtime/src/cards/";
const INPUT_ADAPTER_PREFIX = "src/production-adapters/";
const MAX_REGISTRY_BYTES = 4 * 1024 * 1024;
const MAX_BRIEF_BYTES = 1024 * 1024;

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

const fail = (code, message) => {
  throw new Error(`[${code}] ${message}`);
};

const objectWithKeys = (value, keys) => {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && actual.every((key, index) => key === [...keys].sort()[index]);
};

const readBounded = async (file, maximum, label) => {
  let bytes;
  try {
    bytes = await readFile(file);
  } catch {
    fail("INPUT_UNAVAILABLE", `${label} is unreadable`);
  }
  if (bytes.length === 0 || bytes.length > maximum) {
    fail("INPUT_UNAVAILABLE", `${label} size is invalid`);
  }
  return bytes;
};

const parseObject = (bytes, code, label) => {
  let value;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    fail(code, `${label} is not valid JSON`);
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(code, `${label} must be an object`);
  }
  return value;
};

export const validateRegistrySnapshot = (bytes, expectedBinding) => {
  const registry = parseObject(bytes, "REGISTRY_CONTRACT_INVALID", "registry snapshot");
  if (
    !objectWithKeys(expectedBinding, ["sha256", "version"]) ||
    typeof expectedBinding.version !== "string" || expectedBinding.version.length === 0 ||
    !HASH.test(expectedBinding.sha256) ||
    registry.schema_version !== "talkcraft-card-registry/v1" ||
    registry.registry_version !== expectedBinding.version ||
    sha256(bytes) !== expectedBinding.sha256 ||
    !Array.isArray(registry.cards) || registry.cards.length !== 108
  ) {
    fail("REGISTRY_BINDING_MISMATCH", "registry identity or cardinality differs from the brief");
  }

  const cards = new Map();
  for (const card of registry.cards) {
    if (
      !objectWithKeys(card, ["card_id", "category", "production", "upstream"]) ||
      !CARD_ID.test(card.card_id) || cards.has(card.card_id) ||
      typeof card.category !== "string" || card.category.length === 0 ||
      card.production === null || typeof card.production !== "object" || Array.isArray(card.production)
    ) {
      fail("REGISTRY_CONTRACT_INVALID", "registry card identities are invalid or duplicated");
    }
    const production = card.production;
    if (
      !objectWithKeys(production, [
        "adapter_version", "derived_entrypoint", "implementation_sha256",
        "input_adapter_sha256", "layer_roles", "production_role", "qualification_id", "status",
      ]) ||
      !ROLES.has(production.production_role) ||
      !Array.isArray(production.layer_roles) || production.layer_roles.length === 0 ||
      new Set(production.layer_roles).size !== production.layer_roles.length ||
      production.layer_roles.some((role) => !LAYERS.has(role))
    ) {
      fail("REGISTRY_CONTRACT_INVALID", `production metadata is invalid for ${card.card_id}`);
    }
    const identity = [
      production.derived_entrypoint, production.implementation_sha256,
      production.input_adapter_sha256, production.adapter_version, production.qualification_id,
    ];
    if (production.status === "pending_portrait_adapter") {
      if (identity.some((value) => value !== null)) {
        fail("REGISTRY_CONTRACT_INVALID", `pending card ${card.card_id} claims an implementation identity`);
      }
    } else if (production.status === "qualified") {
      if (
        typeof production.derived_entrypoint !== "string" ||
        !HASH.test(production.implementation_sha256) ||
        !HASH.test(production.input_adapter_sha256) ||
        typeof production.adapter_version !== "string" || production.adapter_version.length === 0 ||
        !HASH.test(production.qualification_id)
      ) {
        fail("REGISTRY_CONTRACT_INVALID", `qualified card ${card.card_id} lacks an implementation identity`);
      }
    } else {
      fail("REGISTRY_CONTRACT_INVALID", `production status is invalid for ${card.card_id}`);
    }
    cards.set(card.card_id, card);
  }
  return {registry, cards};
};

export const resolveProductionCard = async ({briefPath, registryPath, runtimeRoot}) => {
  if (!path.isAbsolute(briefPath)) fail("INPUT_UNAVAILABLE", "brief path must be absolute");
  const briefBytes = await readBounded(briefPath, MAX_BRIEF_BYTES, "production brief");
  const brief = parseObject(briefBytes, "UNSUPPORTED_BRIEF_KIND", "production brief");
  if (brief.schema_version !== "talkcraft-production-brief/v1") {
    fail("UNSUPPORTED_BRIEF_KIND", "only a single TalkCraft production brief is supported");
  }
  if (!CARD_ID.test(brief.card_id ?? "") || !objectWithKeys(brief.registry, ["sha256", "version"])) {
    fail("REGISTRY_BINDING_MISMATCH", "brief registry binding is invalid");
  }

  const registryBytes = await readBounded(registryPath, MAX_REGISTRY_BYTES, "registry snapshot");
  const validated = validateRegistrySnapshot(registryBytes, brief.registry);
  const card = validated.cards.get(brief.card_id);
  if (card === undefined) fail("UNKNOWN_CARD_ID", `unknown card_id: ${brief.card_id}`);
  const production = card.production;
  if (production.status !== "qualified") {
    fail("CARD_NOT_QUALIFIED", `card is pending portrait qualification: ${brief.card_id}`);
  }

  const expectedEntrypoint = `${ENTRYPOINT_PREFIX}${brief.card_id}.tsx`;
  const render = brief.render;
  if (
    render === null || typeof render !== "object" || Array.isArray(render) ||
    render.entrypoint !== production.derived_entrypoint ||
    render.implementation_sha256 !== production.implementation_sha256 ||
    render.adapter_version !== production.adapter_version ||
    render.qualification_id !== production.qualification_id
  ) {
    fail("IMPLEMENTATION_IDENTITY_MISMATCH", "brief render identity differs from the qualified card");
  }
  if (production.derived_entrypoint !== expectedEntrypoint) {
    fail("IMPLEMENTATION_UNAVAILABLE", "qualified card entrypoint is outside the per-card implementation directory");
  }
  const frameScope = brief.frame_scope;
  const renderDuration = render.duration_frames;
  if (
    frameScope === null || typeof frameScope !== "object" || Array.isArray(frameScope) ||
    !Number.isInteger(frameScope.global_start_frame) || !Number.isInteger(frameScope.global_end_frame) ||
    !Number.isInteger(renderDuration) || frameScope.global_start_frame < 0 ||
    frameScope.global_end_frame <= frameScope.global_start_frame ||
    renderDuration !== frameScope.global_end_frame - frameScope.global_start_frame ||
    renderDuration > 720
  ) {
    fail("IMPLEMENTATION_IDENTITY_MISMATCH", "brief render duration differs from its frame scope");
  }
  const targetKind = brief.execution_target?.kind;
  const expectedTargetKind = production.production_role === "transition" ? "boundary" : "component";
  if (targetKind !== expectedTargetKind) {
    fail("IMPLEMENTATION_IDENTITY_MISMATCH", "card role differs from its execution target");
  }

  const modulePath = path.join(runtimeRoot, "src", "cards", `${brief.card_id}.tsx`);
  let moduleInfo;
  try {
    moduleInfo = await lstat(modulePath);
  } catch {
    fail("IMPLEMENTATION_UNAVAILABLE", `card implementation is missing: ${brief.card_id}`);
  }
  if (!moduleInfo.isFile() || moduleInfo.isSymbolicLink()) {
    fail("IMPLEMENTATION_UNAVAILABLE", `card implementation is not a regular file: ${brief.card_id}`);
  }
  const moduleBytes = await readBounded(modulePath, MAX_BRIEF_BYTES, "card implementation");
  if (sha256(moduleBytes) !== production.implementation_sha256) {
    fail("IMPLEMENTATION_IDENTITY_MISMATCH", `card implementation changed: ${brief.card_id}`);
  }
  const inputAdapterPath = path.join(runtimeRoot, ...`${INPUT_ADAPTER_PREFIX}${brief.card_id}.ts`.split("/"));
  let inputAdapterInfo;
  try {
    inputAdapterInfo = await lstat(inputAdapterPath);
  } catch {
    fail("IMPLEMENTATION_UNAVAILABLE", `production input adapter is missing: ${brief.card_id}`);
  }
  if (!inputAdapterInfo.isFile() || inputAdapterInfo.isSymbolicLink()) {
    fail("IMPLEMENTATION_UNAVAILABLE", `production input adapter is not a regular file: ${brief.card_id}`);
  }
  const inputAdapterBytes = await readBounded(inputAdapterPath, 128 * 1024, "production input adapter");
  if (sha256(inputAdapterBytes) !== production.input_adapter_sha256) {
    fail("IMPLEMENTATION_IDENTITY_MISMATCH", `production input adapter changed: ${brief.card_id}`);
  }
  return {brief, briefSha256: sha256(briefBytes), card, modulePath, inputAdapterPath};
};
