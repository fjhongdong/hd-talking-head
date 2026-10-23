import React from "react";
import {OffthreadVideo, Sequence, useCurrentFrame} from "remotion";
import {resolveCfrPlaybackSeek, type VerifiedCfrMedia} from "./media-playback";
import type {MediaClock} from "./time-domain";

export const CfrMediaClockVideo: React.FC<{
  clock: MediaClock;
  media: VerifiedCfrMedia;
  globalFrame: number;
  style?: React.CSSProperties;
}> = ({clock, media, globalFrame, style}) => {
  const outputFrame = useCurrentFrame();
  const seek = resolveCfrPlaybackSeek({
    clock,
    media,
    globalFrame,
    outputFrame,
    compositionFps: 24,
  });
  return <Sequence
    from={seek.sequenceFrom}
    durationInFrames={clock.timeline.end - clock.timeline.start}
    layout="none"
  >
    <OffthreadVideo
      src={media.src}
      trimBefore={seek.trimBefore}
      playbackRate={clock.playbackRate}
      muted
      style={style}
    />
  </Sequence>;
};
