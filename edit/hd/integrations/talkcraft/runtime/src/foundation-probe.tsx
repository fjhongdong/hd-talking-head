import React from "react";
import {AbsoluteFill, useCurrentFrame} from "remotion";
import {BACKDROP_KINDS, Backdrop, FRAME_KINDS, ThemeFrame} from "./visual-foundations";

export type FoundationProbeProps = {
  kind: "backdrop" | "frame";
  sourceFrames: number[];
  namespace: string;
  durationInFrames?: number;
};

const SyntheticMedia: React.FC<{sourceFrame: number}> = ({sourceFrame}) => {
  const frame = sourceFrame;
  const x = ((frame * 9) % 900) - 120;
  return <AbsoluteFill style={{background: "linear-gradient(142deg,#10233f,#3876d9 55%,#67e1c1)", color: "white", overflow: "hidden"}}>
    <div style={{position: "absolute", width: 420, height: 420, left: x, top: 210, borderRadius: "50%", background: "rgba(255,255,255,.18)", filter: "blur(12px)"}}/>
    <div style={{position: "absolute", left: 70, right: 70, bottom: 100, fontSize: 54, lineHeight: 1.08, fontWeight: 800}}>真实媒体区域<br/><span style={{fontSize: 25, opacity: 0.72}}>MOVING SOURCE</span></div>
  </AbsoluteFill>;
};

export const FoundationProbe: React.FC<FoundationProbeProps> = ({kind, sourceFrames, namespace}) => {
  const frame = useCurrentFrame();
  const variants = kind === "backdrop" ? BACKDROP_KINDS : FRAME_KINDS;
  const index = Math.min(variants.length - 1, Math.floor(frame / sourceFrames.length));
  const sourceFrame = sourceFrames[frame % sourceFrames.length];
  if (kind === "backdrop") {
    return <Backdrop kind={BACKDROP_KINDS[index] as import("./visual-foundations").BackdropKind} namespace={`${namespace}-${index}`} sourceFrame={sourceFrame}/>;
  }
  const frameKind = FRAME_KINDS[index] as import("./visual-foundations").FrameKind;
  return <AbsoluteFill style={{background: frameKind === "film" ? "#f4f0e8" : "#f1f3f7", alignItems: "center", justifyContent: "center"}}>
    <ThemeFrame kind={frameKind} width={760} height={1040} namespace={`${namespace}-${index}`} sourceFrame={sourceFrame}>
      <SyntheticMedia sourceFrame={sourceFrame}/>
    </ThemeFrame>
  </AbsoluteFill>;
};
