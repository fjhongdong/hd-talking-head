import type {ProductionInputAdapter, ProductionSceneInput} from "../production-input";

const CARD_ID = "x-follow-card";
const DURATION = 144;
const RAW_KEYS = ["accent","subtitle","title"];
const PRIMARY_PATH = ["title"];
type SlotSpec = {slot: string; kind: ProductionSceneInput["kind"]; width: number; height: number};
const SLOTS: readonly SlotSpec[] = [{"slot":"presenter","kind":"presenter-alpha","width":540,"height":600}];
const HEX = /^#[0-9a-f]{6}$/i;
const SAFE_MEDIA_SRC = /^production\/[0-9a-f]{64}\.(?:jpe?g|mov|mp4|png|webm|webp)$/i;
const BLOCKED_KEY = /^(?:adapterVersion|entrypoint|fd|media|publicSrc|qualificationId|sceneInputs|sha256|src|url)$/i;

const exact = (value: unknown, keys: readonly string[]) =>
  value !== null && typeof value === "object" && !Array.isArray(value) &&
  Object.keys(value).sort().join(",") === [...keys].sort().join(",");

const safeJson = (value: unknown, depth = 0): boolean => {
  if (depth > 5) return false;
  if (typeof value === "string") return value.trim().length > 0 && Array.from(value).length <= 160;
  if (typeof value === "number") return Number.isFinite(value) && Math.abs(value) <= 1_000_000;
  if (typeof value === "boolean") return true;
  if (Array.isArray(value)) return value.length > 0 && value.length <= 12 && value.every((item) => safeJson(item, depth + 1));
  if (value === null || typeof value !== "object") return false;
  const entries = Object.entries(value);
  return entries.length > 0 && entries.length <= 12 &&
    entries.every(([key, item]) => !BLOCKED_KEY.test(key) && safeJson(item, depth + 1));
};

const colorsAreValid = (value: unknown): boolean => {
  if (Array.isArray(value)) return value.every(colorsAreValid);
  if (value === null || typeof value !== "object") return true;
  return Object.entries(value).every(([key, item]) =>
    !/(?:accent|canvas|color|ink|outline)$/i.test(key) ||
    (typeof item === "string" && HEX.test(item))
  ) && Object.values(value).every(colorsAreValid);
};

const rectsAreValid = (value: unknown): boolean => {
  if (Array.isArray(value)) return value.every(rectsAreValid);
  if (value === null || typeof value !== "object") return true;
  for (const [key, item] of Object.entries(value)) {
    if (key === "targetBox" || key === "labelRect") {
      if (!exact(item, ["height", "width", "x", "y"])) return false;
      const rect = item as Record<string, unknown>;
      const numbers = [rect.x, rect.y, rect.width, rect.height];
      if (!numbers.every((n) => typeof n === "number" && Number.isFinite(n)) ||
          Number(rect.x) < 0 || Number(rect.y) < 0 || Number(rect.width) <= 0 || Number(rect.height) <= 0 ||
          Number(rect.x) + Number(rect.width) > 1200 || Number(rect.y) + Number(rect.height) > 750) return false;
    }
    if (!rectsAreValid(item)) return false;
  }
  return true;
};

const atPath = (value: unknown, path: readonly string[]): unknown =>
  path.reduce<unknown>((current, key) => {
    if (Array.isArray(current) && /^\d+$/.test(key)) return current[Number(key)];
    if (current !== null && typeof current === "object") return (current as Record<string, unknown>)[key];
    return undefined;
  }, value);

const validMedium = (medium: any, spec: SlotSpec) => {
  if (!medium || medium.fps !== 24 || medium.start_frame !== 0 || medium.end_frame !== DURATION ||
      medium.width !== spec.width || medium.height !== spec.height || typeof medium.job_path !== "string") return false;
  if (spec.kind === "presenter-alpha" || spec.kind === "presenter-on-white") return medium.source_kind === "presenter" && /\.(?:mov|webm)$/i.test(medium.job_path);
  if (spec.kind === "image-contain") return medium.source_kind === "local_material" && /\.(?:jpe?g|png|webp)$/i.test(medium.job_path);
  return medium.source_kind === "local_material" && /\.(?:mov|mp4|webm)$/i.test(medium.job_path);
};

const adapt: ProductionInputAdapter = (brief, stagedMedia) => {
  const duration = brief.frame_scope.global_end_frame - brief.frame_scope.global_start_frame;
  const event = brief.events[0];
  const payload = event?.payload;
  const raw = exact(payload, ["raw"]) ? (payload as {raw: unknown}).raw : null;
  const primary = atPath(raw, PRIMARY_PATH);
  if (brief.card_id !== CARD_ID || duration !== DURATION || brief.frame_scope.global_start_frame < 0 ||
      brief.events.length !== 1 || !exact(event, ["anchor_id", "frame", "payload", "type"]) ||
      event?.type !== "data" || !Number.isInteger(event?.frame) || Number(event?.frame) < 0 || Number(event?.frame) >= DURATION ||
      !exact(raw, RAW_KEYS) || !safeJson(raw) || !colorsAreValid(raw) || !rectsAreValid(raw) ||
      typeof primary !== "string" || brief.text.display !== primary ||
      typeof brief.text.spoken !== "string" || brief.text.spoken.trim().length < 2 || Array.from(brief.text.spoken).length > 120 ||
      !new Set(["apple-dark", "apple-light"]).has(brief.style.theme) ||
      brief.media.length !== SLOTS.length || stagedMedia.length !== SLOTS.length ||
      stagedMedia.some((item, index) => item.mediaRef !== `media-${index}` || !SAFE_MEDIA_SRC.test(item.publicSrc)) ||
      brief.media.some((medium, index) => !validMedium(medium, SLOTS[index]))) {
    throw new Error(`[PRODUCTION_INPUT_INVALID] ${CARD_ID} production input is invalid`);
  }
  return {
    cardId: CARD_ID,
    raw,
    durationInFrames: DURATION,
    sceneInputs: SLOTS.map((spec, index): ProductionSceneInput => ({
      slot: spec.slot,
      kind: spec.kind,
      src: stagedMedia[index].publicSrc,
      width: spec.width,
      height: spec.height,
    })),
  };
};

export default adapt;
