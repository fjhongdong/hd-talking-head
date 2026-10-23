import {mediaTimeAtGlobalFrame, type MediaClock} from "./time-domain";

export type VerifiedCfrMedia = {
  mediaId: string;
  src: string;
  fps: number;
  frameCount: number;
};

export const resolveCfrPlaybackSeek = ({
  clock,
  media,
  globalFrame,
  outputFrame,
  compositionFps,
}: {
  clock: MediaClock;
  media: VerifiedCfrMedia;
  globalFrame: number;
  outputFrame: number;
  compositionFps: number;
}) => {
  if (!Number.isInteger(outputFrame) || outputFrame < 0) throw new Error("playback output frame is invalid");
  if (clock.playbackRate !== 1) throw new Error("[MEDIA_RATE_UNSUPPORTED] playback bridge currently requires rate 1");
  if (
    media.mediaId !== clock.mediaId || typeof media.src !== "string" || media.src.length === 0 ||
    !Number.isInteger(media.fps) || media.fps < 1 || media.fps !== clock.mediaFps ||
    !Number.isInteger(media.frameCount) || media.frameCount < 1
  ) throw new Error("[MEDIA_FIXTURE_IDENTITY_MISMATCH] verified media differs from the clock");
  if (clock.source.end > media.frameCount) throw new Error("[MEDIA_SOURCE_RANGE_INVALID] source range exceeds the verified media");
  if (globalFrame < clock.timeline.start || globalFrame >= clock.timeline.end) {
    throw new Error("[GLOBAL_FRAME_OUTSIDE_MEDIA_TIMELINE] global frame is outside the media timeline");
  }
  const trimNumerator = clock.source.start * compositionFps;
  if (!Number.isSafeInteger(trimNumerator) || trimNumerator % clock.mediaFps !== 0) {
    throw new Error("[SOURCE_START_NOT_COMPOSITION_FRAME_ALIGNED] source start cannot map exactly to the composition clock");
  }
  const mediaTime = mediaTimeAtGlobalFrame(clock, globalFrame, compositionFps);
  const elapsedTimelineFrames = globalFrame - clock.timeline.start;
  return {
    sequenceFrom: outputFrame - elapsedTimelineFrames,
    trimBefore: trimNumerator / clock.mediaFps,
    sourceFrame: mediaTime.sourceFrame,
    sourceSeconds: mediaTime.sourceSeconds,
  };
};
