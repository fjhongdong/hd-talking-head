import contract from "../time-domain-contract.json";

export type FrameRange = {start: number; end: number};
export type TimeScope = {
  fps: 24;
  chunkId: string;
  spanId: string;
  sceneId: string;
  chunk: FrameRange;
  span: FrameRange;
  scene: FrameRange;
};
export type Anchor = {id: string; sceneFrame: number};
export type MediaClock = {
  mediaId: string;
  sourceTimebase: "cfr";
  timeline: FrameRange;
  source: FrameRange;
  mediaFps: number;
  playbackRate: number;
};

const finite = (value: number) => Number.isFinite(value);
const integerFrame = (value: number) => Number.isInteger(value) && value >= 0;
const validRange = (range: FrameRange) => integerFrame(range.start) && integerFrame(range.end) && range.end > range.start;
const contains = (outer: FrameRange, inner: FrameRange) => outer.start <= inner.start && inner.end <= outer.end;

export const validateTimeScope = (scope: TimeScope) => {
  if (scope.fps !== contract.timeline_fps) throw new Error("timeline fps must be 24");
  if (![scope.chunkId, scope.spanId, scope.sceneId].every((value) => /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value))) {
    throw new Error("time scope identities are invalid");
  }
  if (![scope.chunk, scope.span, scope.scene].every(validRange)) throw new Error("time scope ranges must be positive half-open integer frames");
  if (!contains(scope.span, scope.chunk) || !contains(scope.span, scope.scene)) {
    throw new Error("chunk and scene ranges must be contained by the span");
  }
};

export const secondsToFrame = (seconds: number, fps = contract.timeline_fps) => {
  if (!finite(seconds) || seconds < 0 || !finite(fps) || fps <= 0) throw new Error("seconds-to-frame input is invalid");
  const scaled = seconds * fps;
  if (!finite(scaled) || !Number.isSafeInteger(Math.floor(scaled)) || !Number.isSafeInteger(Math.ceil(scaled))) {
    throw new Error("seconds-to-frame result is outside the safe integer range");
  }
  const lower = Math.floor(scaled);
  const fraction = scaled - lower;
  const result = fraction < 0.5 ? lower : fraction > 0.5 ? lower + 1 : lower % 2 === 0 ? lower : lower + 1;
  return Object.is(result, -0) ? 0 : result;
};

export const frameToSeconds = (frame: number, fps: number) => {
  if (!integerFrame(frame) || !finite(fps) || fps <= 0) throw new Error("frame-to-seconds input is invalid");
  return frame / fps;
};

export const timeAtGlobalFrame = (scope: TimeScope, globalFrame: number) => {
  validateTimeScope(scope);
  if (!integerFrame(globalFrame) || globalFrame < scope.chunk.start || globalFrame >= scope.chunk.end) {
    throw new Error("global frame is outside the output chunk");
  }
  return {
    outputFrame: globalFrame - scope.chunk.start,
    globalTimelineFrame: globalFrame,
    globalTimelineSeconds: frameToSeconds(globalFrame, scope.fps),
    spanLocalFrame: globalFrame - scope.span.start,
    sceneLocalFrame: globalFrame - scope.scene.start,
    sceneActive: globalFrame >= scope.scene.start && globalFrame < scope.scene.end,
  };
};

export const globalFrameAtOutput = (scope: TimeScope, outputFrame: number) => {
  validateTimeScope(scope);
  if (!integerFrame(outputFrame) || outputFrame >= scope.chunk.end - scope.chunk.start) {
    throw new Error("output frame is outside the chunk");
  }
  return scope.chunk.start + outputFrame;
};

const validateAnchors = (scope: TimeScope, anchors: Anchor[]) => {
  const sceneDuration = scope.scene.end - scope.scene.start;
  const ids = new Set<string>();
  let previous = -1;
  for (const anchor of anchors) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(anchor.id) || ids.has(anchor.id)) {
      throw new Error("anchor identities must be safe and unique");
    }
    if (!integerFrame(anchor.sceneFrame) || anchor.sceneFrame >= sceneDuration || anchor.sceneFrame < previous) {
      throw new Error("anchor frames must be ordered inside the scene");
    }
    ids.add(anchor.id);
    previous = anchor.sceneFrame;
  }
};

export const resolveAnchor = (scope: TimeScope, anchors: Anchor[], anchorId: string) => {
  validateTimeScope(scope);
  validateAnchors(scope, anchors);
  const anchor = anchors.find((item) => item.id === anchorId);
  if (anchor === undefined) throw new Error("unknown time anchor");
  const globalTimelineFrame = scope.scene.start + anchor.sceneFrame;
  return {
    anchorId,
    sceneLocalFrame: anchor.sceneFrame,
    spanLocalFrame: globalTimelineFrame - scope.span.start,
    globalTimelineFrame,
    globalTimelineSeconds: frameToSeconds(globalTimelineFrame, scope.fps),
  };
};

export const mediaTimeAtGlobalFrame = (clock: MediaClock | null | undefined, globalFrame: number, timelineFps = contract.timeline_fps) => {
  if (clock === null || clock === undefined) throw new Error("[MEDIA_TIMELINE_MAPPING_REQUIRED] media timeline mapping is required");
  if (
    !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(clock.mediaId) || clock.sourceTimebase !== "cfr" ||
    !validRange(clock.timeline) || !validRange(clock.source) ||
    !finite(clock.mediaFps) || clock.mediaFps <= 0 || !finite(clock.playbackRate) || clock.playbackRate <= 0 ||
    timelineFps !== contract.timeline_fps
  ) {
    throw new Error("media clock requires explicit valid timeline/source ranges and media fps");
  }
  const timelineFrames = clock.timeline.end - clock.timeline.start;
  const sourceFrames = clock.source.end - clock.source.start;
  const expectedSourceFrames = timelineFrames / timelineFps * clock.playbackRate * clock.mediaFps;
  if (Math.abs(expectedSourceFrames - sourceFrames) > 1e-9) {
    throw new Error("media source range differs from the explicit timeline and playback rate");
  }
  if (!integerFrame(globalFrame) || globalFrame < clock.timeline.start || globalFrame >= clock.timeline.end) {
    throw new Error("global frame is outside the media timeline range");
  }
  const sourceFrame = clock.source.start + (globalFrame - clock.timeline.start) / timelineFps * clock.playbackRate * clock.mediaFps;
  return {
    mediaId: clock.mediaId,
    globalTimelineFrame: globalFrame,
    sourceFrame,
    sourceSeconds: sourceFrame / clock.mediaFps,
    playbackRate: clock.playbackRate,
  };
};
