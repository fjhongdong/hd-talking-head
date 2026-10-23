import React from "react";
import {AbsoluteFill, useCurrentFrame} from "remotion";
import contract from "../scene-foundation-contract.json";
import {Backdrop} from "./visual-foundations";
import {SceneFoundation, type SceneLayout, useSceneTheme} from "./scene-foundations";

export type SceneProbeProps = {sourceFrames: number[]; durationInFrames?: number};

const WorldContent: React.FC<{variant: number}> = ({variant}) => {
  const theme = useSceneTheme();
  return <>
    <div style={{position: "absolute", left: 150, top: 350, width: 780, height: 980, borderRadius: 64, border: `2px solid ${theme.hairline}`, background: variant === 0 ? "rgba(255,255,255,.78)" : "rgba(39,39,41,.82)"}}/>
    <div style={{position: "absolute", left: 230, top: 470, width: 620, fontSize: 92, lineHeight: 1.04, fontWeight: 800}}>一台相机<br/><span style={{color: theme.accent}}>服务一个主角</span></div>
    <div style={{position: "absolute", left: 230, top: 820, width: 270, height: 300, borderRadius: 40, background: theme.canvas_alt, border: `2px solid ${theme.hairline}`}}/>
    <div style={{position: "absolute", left: 540, top: 820, width: 230, height: 300, borderRadius: 40, background: theme.accent, opacity: 0.82}}/>
  </>;
};

const ScreenText: React.FC = () => {
  const theme = useSceneTheme();
  return <div style={{position: "absolute", left: 92, right: 92, top: 1490, fontSize: 38, lineHeight: 1.3, color: theme.ink_muted, borderTop: `2px solid ${theme.hairline}`, paddingTop: 28}}>文字保持在屏幕空间，不随相机缩放</div>;
};

const layouts: SceneLayout[] = [
  {activeSubjectGroups: 3, heroGroups: 1, demotedGroups: 0, emptyQuadrant: "top-right", textBounds: [{x: 92, y: 1490, width: 896, height: 110}], decorationBounds: [{x: 92, y: 1440, width: 896, height: 2}], presenterSafeZone: {x: 40, y: 980, width: 300, height: 420}},
  {activeSubjectGroups: 3, heroGroups: 1, demotedGroups: 1, emptyQuadrant: "top-left", textBounds: [{x: 92, y: 1490, width: 896, height: 110}], decorationBounds: [{x: 92, y: 1440, width: 896, height: 2}], presenterSafeZone: {x: 760, y: 980, width: 280, height: 420}},
];

export const SceneProbe: React.FC<SceneProbeProps> = ({sourceFrames}) => {
  const outputFrame = useCurrentFrame();
  const variant = Math.min(1, Math.floor(outputFrame / sourceFrames.length));
  const sourceFrame = sourceFrames[outputFrame % sourceFrames.length];
  const preset: "light" | "dark" = variant === 0 ? "light" : "dark";
  const direction: "push" | "pull" = variant === 0 ? "push" : "pull";
  return <SceneFoundation
    sceneId={`scene-probe-${variant}`}
    theme={{preset}}
    camera={{direction, peakScale: 1.05}}
    sourceFrame={sourceFrame}
    durationFrames={contract.probe.duration_frames}
    layout={layouts[variant]}
    background={{
      screen: <Backdrop kind={variant === 0 ? "grid-spot-light" : "mesh-flow-dark"} namespace={`scene-probe-bg-${variant}`} sourceFrame={sourceFrame}/>,
      world: <div style={{position: "absolute", left: 80, top: 250, width: 920, height: 1180, borderRadius: "50%", border: "3px solid rgba(100,140,255,.16)"}}/>,
    }}
    subject={<WorldContent variant={variant}/>} text={<ScreenText/>}
  />;
};
