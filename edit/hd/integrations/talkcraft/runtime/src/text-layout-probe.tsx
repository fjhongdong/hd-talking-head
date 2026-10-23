import React from "react";
import {AbsoluteFill} from "remotion";
import {SceneFoundation, type SceneLayout} from "./scene-foundations";
import {ScreenTextBlock, type TextLayoutSpec} from "./text-layout";

export type TextLayoutProbeMode = "valid" | "overflow" | "presenter" | "world" | "hidden";
export type TextLayoutProbeProps = {mode: TextLayoutProbeMode; durationInFrames?: number};

const presenterSafeZone = {x: 680, y: 1180, width: 320, height: 360};

const specFor = (mode: TextLayoutProbeMode): TextLayoutSpec => {
  const base: TextLayoutSpec = {
    id: `text-layout-${mode}`,
    text: "真实排版测量\nAI workflow 2026",
    plane: "text.screen",
    bounds: {x: 100, y: 1380, width: 520, height: 170},
    maxLines: 2,
    font: {family: '"PingFang SC", "Noto Sans SC", sans-serif', size: 52, weight: 600, lineHeight: 1.35, letterSpacing: 0},
    color: "#1d1d1f",
    align: "left",
    effectOutset: 0,
    overflow: "visible",
  };
  if (mode === "overflow") return {...base, text: "这是一段不允许被截断或自动缩小的真实长文本", bounds: {x: 100, y: 1000, width: 230, height: 60}, maxLines: 1};
  if (mode === "presenter") return {...base, text: "真实文字换行后会进入人物区域因此必须明确失败", bounds: {x: 680, y: 1040, width: 320, height: 130}, maxLines: 4};
  if (mode === "world") return {...base, plane: "background.world" as "text.screen"};
  if (mode === "hidden") return {...base, overflow: "hidden" as "visible"};
  return base;
};

export const TextLayoutProbe: React.FC<TextLayoutProbeProps> = ({mode}) => {
  const spec = specFor(mode);
  const layout: SceneLayout = {
    activeSubjectGroups: 1,
    heroGroups: 0,
    demotedGroups: 0,
    emptyQuadrant: "top-right",
    textBounds: [spec.bounds],
    decorationBounds: [],
    presenterSafeZone,
  };
  return <SceneFoundation
    sceneId={`text-layout-probe-${mode}`}
    theme={{preset: "light"}}
    camera={{direction: "push", peakScale: 1.04}}
    sourceFrame={12}
    durationFrames={48}
    layout={layout}
    background={{screen: <AbsoluteFill style={{background: "#f5f5f7"}}/>, world: null}}
    subject={<div style={{position: "absolute", left: 170, top: 460, width: 420, height: 420, borderRadius: 80, background: "#0066cc"}}/>}
    text={<ScreenTextBlock spec={spec} presenterSafeZone={presenterSafeZone}/>} 
  />;
};
