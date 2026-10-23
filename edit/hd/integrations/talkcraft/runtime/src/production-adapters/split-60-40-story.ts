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
  const [presenter, subjectVideo] = brief.media;
  if (brief.card_id !== "split-60-40-story" || duration !== 173 || brief.media.length !== 2 || stagedMedia.length !== 2 ||
      stagedMedia.some((item, index) => item.mediaRef !== `media-${index}`) ||
      brief.media.some((item) => !Number.isInteger(item.width) || !Number.isInteger(item.height) || item.width <= 0 || item.height <= 0) ||
      presenter.source_kind !== "presenter" || !/\.(?:mov|webm)$/i.test(presenter.job_path) || presenter.fps !== 24 || presenter.start_frame !== 0 || presenter.end_frame !== duration ||
      subjectVideo.source_kind !== "local_material" || !/\.(?:mov|mp4|webm)$/i.test(subjectVideo.job_path) || subjectVideo.fps !== 24 || subjectVideo.start_frame !== 0 || subjectVideo.end_frame !== duration ||
      typeof brief.text.display !== "string" || brief.text.display.length < 2 || brief.text.display.length > 12 ||
      subtitle === null || subtitle.length < 2 || subtitle.length > 18 || brief.text.spoken !== subtitle || events[0].frame < 0 || events[0].frame >= duration ||
      !new Set(["apple-dark", "apple-light"]).has(brief.style.theme)) {
    throw new Error("[PRODUCTION_INPUT_INVALID] split-60-40-story production input is invalid");
  }
  return {cardId: brief.card_id, raw: {title: brief.text.display, subtitle, accent: brief.style.theme === "apple-dark" ? "#007AFF" : "#FF375F"}, durationInFrames: duration,
    sceneInputs: [
      {slot: "presenter", kind: "presenter-alpha", src: stagedMedia[0].publicSrc, width: presenter.width, height: presenter.height},
      {slot: "subject-video", kind: "video-cover", src: stagedMedia[1].publicSrc, width: subjectVideo.width, height: subjectVideo.height},
    ]};
};

export default adapt;
