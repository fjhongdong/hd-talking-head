import React from "react";
import {AbsoluteFill, staticFile, useCurrentFrame} from "remotion";
import {globalFrameAtOutput, mediaTimeAtGlobalFrame, resolveAnchor, timeAtGlobalFrame, type TimeScope} from "./time-domain";
import {CfrMediaClockVideo} from "./media-playback-video";

export type TimeDomainProbeProps = {globalFrames: number[]; durationInFrames?: number};

const scope: TimeScope = {
  fps: 24,
  chunkId: "chunk-time-probe",
  spanId: "span-time-probe",
  sceneId: "scene-time-probe",
  chunk: {start: 48, end: 96},
  span: {start: 24, end: 144},
  scene: {start: 48, end: 120},
};
const anchors = [
  {id: "opening", sceneFrame: 0},
  {id: "emphasis", sceneFrame: 24},
  {id: "payoff", sceneFrame: 47},
];
const mediaClock = {
  mediaId: "media-time-probe",
  sourceTimebase: "cfr" as const,
  timeline: {start: 48, end: 120},
  source: {start: 30, end: 90},
  mediaFps: 20,
  playbackRate: 1,
};

export const TimeDomainProbe: React.FC<TimeDomainProbeProps> = ({globalFrames}) => {
  const outputFrame = useCurrentFrame();
  const globalFrame = globalFrames[outputFrame];
  const time = timeAtGlobalFrame(scope, globalFrame);
  const roundTrip = globalFrameAtOutput(scope, time.outputFrame);
  const anchor = resolveAnchor(scope, anchors, "emphasis");
  const media = mediaTimeAtGlobalFrame(mediaClock, globalFrame);
  const verifiedMedia = {
    mediaId: "media-time-probe",
    src: staticFile("time-domain-cfr-20fps.mp4"),
    fps: 20,
    frameCount: 90,
  };
  const animationProgress = Math.max(0, Math.min(1, (time.sceneLocalFrame - anchor.sceneLocalFrame) / 24));
  const mediaProgress = (media.sourceFrame - mediaClock.source.start) / (mediaClock.source.end - mediaClock.source.start);
  if (roundTrip !== globalFrame) throw new Error("time-domain output/global round trip failed");
  return <AbsoluteFill style={{background: "#f5f5f7", color: "#1d1d1f", fontFamily: "system-ui", padding: 96}}>
    <div style={{fontSize: 72, fontWeight: 700}}>统一时间域</div>
    <div style={{marginTop: 64, fontSize: 38, lineHeight: 1.5}}>
      global {time.globalTimelineFrame} · span {time.spanLocalFrame} · scene {time.sceneLocalFrame}<br/>
      anchor {anchor.globalTimelineFrame} · media {media.sourceSeconds.toFixed(3)}s @ {mediaClock.mediaFps}fps
    </div>
    <div style={{position: "absolute", left: 96, top: 680, width: 888, height: 80, borderRadius: 40, background: "#e0e0e0"}}>
      <div style={{width: `${animationProgress * 100}%`, height: "100%", borderRadius: 40, background: "#0066cc"}}/>
    </div>
    <div style={{position: "absolute", left: 96, top: 900, width: 888, height: 80, borderRadius: 40, background: "#e0e0e0"}}>
      <div style={{width: `${mediaProgress * 100}%`, height: "100%", borderRadius: 40, background: "#248a3d"}}/>
    </div>
    <div style={{position: "absolute", left: 96, top: 1050, width: 444, height: 790, overflow: "hidden", borderRadius: 32, border: "8px solid #1d1d1f"}}>
      <CfrMediaClockVideo
        clock={mediaClock}
        media={verifiedMedia}
        globalFrame={globalFrame}
        style={{width: "100%", height: "100%", objectFit: "cover"}}
      />
    </div>
    <div style={{position: "absolute", left: 590, top: 1110, width: 390, fontSize: 30, lineHeight: 1.5, color: "#7a7a7a"}}>
      真实 CFR 媒体由同一全局帧取样<br/><br/>当前桥：1× · 20fps · 全 I 帧测试源
    </div>
  </AbsoluteFill>;
};
