export type ProductionBrief = {
  card_id: string;
  text: {display: string; spoken: string};
  frame_scope: {global_start_frame: number; global_end_frame: number};
  events: Array<{anchor_id: string; type: string; frame: number; payload: unknown}>;
  media: Array<{
    source_kind: string;
    width: number;
    height: number;
    fps: number;
    start_frame: number;
    end_frame: number;
    job_path: string;
  }>;
  style: {theme: string};
};

export type StagedMedia = {mediaRef: string; publicSrc: string};

export type ProductionSceneInput = {
  slot: string;
  kind: "presenter-on-white" | "presenter-alpha" | "video-cover" | "image-contain";
  src: string;
  width: number;
  height: number;
};

export type ProductionProps = {
  cardId: string;
  raw: unknown;
  durationInFrames: number;
  sceneInputs: Array<ProductionSceneInput>;
};

export type ProductionInputAdapter = (
  brief: ProductionBrief,
  stagedMedia: ReadonlyArray<StagedMedia>,
) => ProductionProps;

export const textPayload = (value: unknown): string | null => {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const text = (value as {text?: unknown}).text;
  return typeof text === "string" ? text : null;
};

const exactIdentity = (value: unknown): {role: string} | null => {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  if (Object.keys(value).sort().join(",") !== "role") return null;
  const role = (value as {role?: unknown}).role;
  return typeof role === "string" ? {role} : null;
};

export const presenterIdentityAdapter = (cardId: string, duration: number): ProductionInputAdapter => (
  brief: ProductionBrief,
  stagedMedia: ReadonlyArray<StagedMedia>,
) => {
  const durationInFrames = brief.frame_scope.global_end_frame - brief.frame_scope.global_start_frame;
  const identityEvents = brief.events.filter((event) => event.type === "data" && exactIdentity(event.payload) !== null);
  const identity = identityEvents.length === 1 ? exactIdentity(identityEvents[0].payload) : null;
  const presenter = brief.media[0];
  if (
    brief.card_id !== cardId || durationInFrames !== duration ||
    identity === null || identity.role !== brief.text.spoken ||
    brief.text.display.length < 2 || brief.text.display.length > 12 ||
    identity.role.length < 2 || identity.role.length > 18 ||
    identityEvents[0].frame < 0 || identityEvents[0].frame >= durationInFrames ||
    brief.media.length !== 1 || stagedMedia.length !== 1 || stagedMedia[0].mediaRef !== "media-0" ||
    presenter.source_kind !== "presenter" || !/\.(?:mov|webm)$/i.test(presenter.job_path) ||
    presenter.fps !== 24 || presenter.start_frame !== 0 || presenter.end_frame !== durationInFrames ||
    !new Set(["apple-dark", "apple-light"]).has(brief.style.theme)
  ) {
    throw new Error(`[PRODUCTION_INPUT_INVALID] ${cardId} production input is invalid`);
  }
  return {
    cardId,
    raw: {
      title: brief.text.display,
      subtitle: identity.role,
      accent: brief.style.theme === "apple-dark" ? "#007AFF" : "#FF375F",
    },
    durationInFrames,
    sceneInputs: [{
      slot: "presenter",
      kind: "presenter-alpha",
      src: stagedMedia[0].publicSrc,
      width: presenter.width,
      height: presenter.height,
    }],
  };
};

export const buildParallelItemsProductionProps: ProductionInputAdapter = (
  brief: ProductionBrief,
  stagedMedia: ReadonlyArray<StagedMedia>,
): ProductionProps => {
  if (brief.card_id !== "parallel-items-with-host") {
    throw new Error("[PRODUCTION_MAPPING_UNAVAILABLE] card production input mapping is unavailable");
  }
  const durationInFrames = brief.frame_scope.global_end_frame - brief.frame_scope.global_start_frame;
  const subtitle = brief.events.find((event) => event.type === "text" && textPayload(event.payload) !== null);
  const subtitleText = subtitle ? textPayload(subtitle.payload) : null;
  const [presenter, ...items] = brief.media;
  if (
    durationInFrames !== 530 || brief.media.length !== 4 || stagedMedia.length !== 4 ||
    stagedMedia.some((item, index) => item.mediaRef !== `media-${index}`) ||
    presenter.source_kind !== "presenter" ||
    !/\.(?:mov|webm)$/i.test(presenter.job_path) || presenter.fps !== 24 ||
    presenter.start_frame !== 0 || presenter.end_frame !== durationInFrames ||
    items.some((item) => item.source_kind !== "local_material" ||
      !/\.(?:jpe?g|png|webp)$/i.test(item.job_path) || item.fps !== 24 ||
      item.start_frame !== 0 || item.end_frame !== durationInFrames) ||
    typeof brief.text.display !== "string" || brief.text.display.length < 2 || brief.text.display.length > 12 ||
    subtitleText === null || subtitleText.length < 2 || subtitleText.length > 18 ||
    brief.text.spoken !== subtitleText ||
    !new Set(["apple-dark", "apple-light"]).has(brief.style.theme)
  ) {
    throw new Error("[PRODUCTION_INPUT_INVALID] parallel-items-with-host production input is invalid");
  }
  const accent = brief.style.theme === "apple-dark" ? "#007AFF" : "#FF375F";
  return {
    cardId: brief.card_id,
    raw: {title: brief.text.display, subtitle: subtitleText, accent},
    durationInFrames,
    sceneInputs: [{
      slot: "presenter",
      kind: "presenter-alpha",
      src: stagedMedia[0].publicSrc,
      width: brief.media[0].width,
      height: brief.media[0].height,
    }, ...items.map((item, index) => ({
      slot: `item-${index + 1}`,
      kind: "image-contain" as const,
      src: stagedMedia[index + 1].publicSrc,
      width: item.width,
      height: item.height,
    }))],
  };
};

// Compatibility name for the original single-card unit contract.
export const buildProductionProps = buildParallelItemsProductionProps;
