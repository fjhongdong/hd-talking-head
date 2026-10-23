import type {ProductionInputAdapter} from "../production-input";

const exactText = (value: unknown): string | null => {
  if (value === null || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join(",") !== "text") return null;
  const text = (value as {text?: unknown}).text;
  return typeof text === "string" ? text : null;
};

const adapt: ProductionInputAdapter = (brief, stagedMedia) => {
  const duration = brief.frame_scope.global_end_frame - brief.frame_scope.global_start_frame;
  const events = brief.events.filter((event) => event.type === "text" && exactText(event.payload) !== null);
  const subtitle = events.length === 1 ? exactText(events[0].payload) : null;
  const [presenter, ...images] = brief.media;
  if (brief.card_id !== "stack-fan-out" || duration !== 163 || brief.media.length !== 6 || stagedMedia.length !== 6 ||
      stagedMedia.some((item, index) => item.mediaRef !== `media-${index}`) ||
      brief.media.some((item) => !Number.isInteger(item.width) || !Number.isInteger(item.height) || item.width <= 0 || item.height <= 0) ||
      presenter.source_kind !== "presenter" || !/\.(?:mov|webm)$/i.test(presenter.job_path) || presenter.fps !== 24 || presenter.start_frame !== 0 || presenter.end_frame !== duration ||
      images.some((item) => item.source_kind !== "local_material" || !/\.(?:jpe?g|png|webp)$/i.test(item.job_path) || item.fps !== 24 || item.start_frame !== 0 || item.end_frame !== duration) ||
      typeof brief.text.display !== "string" || brief.text.display.length < 2 || brief.text.display.length > 12 ||
      subtitle === null || subtitle.length < 2 || subtitle.length > 18 || brief.text.spoken !== subtitle || events[0].frame < 0 || events[0].frame >= duration ||
      !new Set(["apple-dark", "apple-light"]).has(brief.style.theme)) {
    throw new Error("[PRODUCTION_INPUT_INVALID] stack-fan-out production input is invalid");
  }
  return {cardId: brief.card_id, raw: {title: brief.text.display, subtitle, accent: brief.style.theme === "apple-dark" ? "#007AFF" : "#FF375F"}, durationInFrames: duration,
    sceneInputs: [
      {slot: "presenter", kind: "presenter-alpha", src: stagedMedia[0].publicSrc, width: presenter.width, height: presenter.height},
      ...images.map((item, index) => ({slot: `item-${index + 1}`, kind: "image-contain" as const, src: stagedMedia[index + 1].publicSrc, width: item.width, height: item.height})),
    ]};
};

export default adapt;
