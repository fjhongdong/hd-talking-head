import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./bar-chart-growth.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "bar-chart-growth", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as string[];
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;
export const animationFrames = {title: 7, baseline: 10, bars: [15, 16, 18, 19, 21], conclusion: 28} as const;

type BarChartPrepared = PreparedCard & {
  title: string;
  labels: string[];
  values: number[];
  maxValue: number;
  conclusion: string;
  unit: string;
  source: string;
  accent: string;
  ink: string;
};

const COLOR = /^#[0-9a-fA-F]{6}$/;
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) &&
  Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const length = (value: unknown) => typeof value === "string" ? Array.from(value.trim()).length : 0;
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const lerp = (from: number, to: number, progress: number) => from + (to - from) * progress;
const power2Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 3);
const power3Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 4);
const backOut = (value: number) => {
  const x = clamp01(value) - 1;
  return 1 + 2.4 * x * x * x + 1.4 * x * x;
};
const progress = (frame: number, start: number, duration: number, ease: (value: number) => number) => ease((frame - start) / duration);

export const prepareCard = (raw: unknown, context: CardContext): BarChartPrepared => {
  if (!exactObject(raw, ["accent", "conclusion", "ink", "labels", "maxValue", "source", "title", "unit", "values"])) {
    throw new Error("bar-chart-growth input is invalid");
  }
  const input = raw as Record<string, unknown>;
  if (!Array.isArray(input.labels) || !Array.isArray(input.values) || input.labels.length !== 5 || input.values.length !== 5 ||
      input.labels.some((label) => length(label) < 1 || length(label) > 5) ||
      input.values.some((value) => typeof value !== "number" || !Number.isFinite(value)) ||
      typeof input.maxValue !== "number" || !Number.isFinite(input.maxValue) || input.maxValue <= 0 || input.maxValue > 1e9 ||
      (input.values as number[]).some((value) => value < 0 || value > (input.maxValue as number)) ||
      length(input.title) < 2 || length(input.title) > 10 || length(input.conclusion) < 2 || length(input.conclusion) > 12 ||
      length(input.unit) < 1 || length(input.unit) > 8 || length(input.source) < 2 || length(input.source) > 20) {
    throw new Error("bar-chart-growth content exceeds its approved capacity");
  }
  const values = input.values as number[];
  const rises = values.every((value, index) => index === 0 || value >= values[index - 1]);
  const falls = values.every((value, index) => index === 0 || value <= values[index - 1]);
  if ((!rises && !falls) || values[0] === values[values.length - 1]) throw new Error("bar-chart-growth requires one directional trend");
  if ([input.accent, input.ink].some((color) => typeof color !== "string" || !COLOR.test(color))) throw new Error("bar-chart-growth colors are invalid");
  if (context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames < 80) {
    throw new Error("bar-chart-growth requires 1080x1920@24 and at least 80 frames");
  }
  return {
    title: (input.title as string).trim(), labels: (input.labels as string[]).map((item) => item.trim()), values,
    maxValue: input.maxValue as number, conclusion: (input.conclusion as string).trim(), unit: (input.unit as string).trim(),
    source: (input.source as string).trim(), accent: input.accent as string, ink: input.ink as string,
  };
};

export default function BarChartGrowth({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<BarChartPrepared>) {
  const titleP = progress(animationLocalFrame, animationFrames.title, 5, power2Out);
  const baselineP = progress(animationLocalFrame, animationFrames.baseline, 6, power2Out);
  const conclusionP = progress(animationLocalFrame, animationFrames.conclusion, 5, backOut);
  const chartHeight = 360;
  const maxBarHeight = Math.max(...prepared.values) / prepared.maxValue * chartHeight;
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "transparent", color: prepared.ink, fontFamily: '"PingFang SC", "Hiragino Sans GB", sans-serif'}}>
    <div style={{position: "absolute", left: 122, top: 850, width: 836, height: 930, overflow: "hidden"}}>{sceneInputs.presenter}</div>
    <div data-talkcraft-layout="portrait-stack-data" style={{position: "absolute", left: 96, top: 118, width: 888, height: 674}}>
      <div data-track="title" style={{fontSize: 68, lineHeight: 1.12, fontWeight: 650, letterSpacing: "-0.02em", opacity: titleP}}>{prepared.title}</div>
      <div data-track="unit" style={{position: "absolute", right: 0, top: 26, fontSize: 28, color: "#73737a"}}>单位：{prepared.unit}</div>
      <div data-track="chart" style={{position: "absolute", left: 0, top: 190, width: 888, height: chartHeight}}>
        <div data-track="conclusion" style={{position: "absolute", right: 0, bottom: maxBarHeight + 30, padding: "14px 24px", borderRadius: 18, background: prepared.accent, color: "#ffffff", fontSize: 34, lineHeight: 1, fontWeight: 650, whiteSpace: "nowrap", transformOrigin: "100% 50%", opacity: Math.min(1, conclusionP), transform: `scale(${lerp(0.8, 1, conclusionP)})`}}>{prepared.conclusion}</div>
        <div data-track="bars" style={{position: "absolute", inset: 0, display: "flex", alignItems: "flex-end", justifyContent: "space-between"}}>
          {prepared.values.map((value, index) => {
            const barP = progress(animationLocalFrame, animationFrames.bars[index], 7, power3Out);
            return <div key={prepared.labels[index]} data-bar-index={index} style={{width: 112, height: value / prepared.maxValue * chartHeight, borderRadius: "10px 10px 0 0", background: prepared.accent, transformOrigin: "50% 100%", transform: `scaleY(${barP})`}}/>;
          })}
        </div>
        <div data-track="baseline" style={{position: "absolute", left: 0, right: 0, bottom: -2, height: 3, background: "#d2d2d7", transformOrigin: "0% 50%", transform: `scaleX(${baselineP})`}}/>
        <div data-track="labels" style={{position: "absolute", left: 0, right: 0, bottom: -54, display: "flex", justifyContent: "space-between", color: "#73737a", fontSize: 25}}>
          {prepared.labels.map((label) => <span key={label} style={{width: 112, textAlign: "center", whiteSpace: "nowrap"}}>{label}</span>)}
        </div>
      </div>
      <div data-track="source" style={{position: "absolute", left: 0, bottom: 0, fontSize: 24, color: "#8a8a90"}}>来源：{prepared.source}</div>
    </div>
  </AbsoluteFill>;
}
