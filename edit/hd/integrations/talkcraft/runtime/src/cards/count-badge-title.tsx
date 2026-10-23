import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./count-badge-title.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "count-badge-title", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as string[];
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;

type CountBadgePrepared = PreparedCard & {
  number: string;
  quantifier: string;
  line2: string;
  accent: string;
  canvas: string;
  ink: string;
};

const COLOR = /^#[0-9a-fA-F]{6}$/;
const DIGITS = /^\d{1,2}$/;
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) &&
  Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const lerp = (from: number, to: number, progress: number) => from + (to - from) * progress;
const power1Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 2);
const power2Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 3);
const power3Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 4);
const progress = (frame: number, start: number, duration: number, ease: (value: number) => number) => ease((frame - start) / duration);
const parseHex = (value: string): [number, number, number] => [1, 3, 5].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16)) as [number, number, number];
const mixColor = (from: string, to: string, amount: number) => {
  const a = parseHex(from);
  const b = parseHex(to);
  return `rgb(${a.map((channel, index) => Math.round(lerp(channel, b[index], amount))).join(",")})`;
};

export const prepareCard = (raw: unknown, context: CardContext): CountBadgePrepared => {
  if (!exactObject(raw, ["accent", "canvas", "ink", "line2", "number", "quantifier"])) throw new Error("count-badge-title input is invalid");
  const input = raw as Record<string, unknown>;
  const length = (value: unknown) => typeof value === "string" ? Array.from(value.trim()).length : 0;
  if (typeof input.number !== "string" || !DIGITS.test(input.number) || length(input.quantifier) < 2 || length(input.quantifier) > 4 || length(input.line2) < 3 || length(input.line2) > 6) {
    throw new Error("count-badge-title content exceeds its approved capacity");
  }
  if ([input.accent, input.canvas, input.ink].some((color) => typeof color !== "string" || !COLOR.test(color))) {
    throw new Error("count-badge-title colors are invalid");
  }
  if (context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames < 80) {
    throw new Error("count-badge-title requires 1080x1920@24 and at least 80 frames");
  }
  return {
    number: input.number,
    quantifier: (input.quantifier as string).trim(),
    line2: (input.line2 as string).trim(),
    accent: input.accent as string,
    canvas: input.canvas as string,
    ink: input.ink as string,
  };
};

export default function CountBadgeTitle({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<CountBadgePrepared>) {
  const numberIn = progress(animationLocalFrame, 10, 7, power3Out);
  const hue = progress(animationLocalFrame, 15, 3, power1Out);
  const quantifier = progress(animationLocalFrame, 18, 5, power3Out);
  const line2 = progress(animationLocalFrame, 20, 7, power3Out);
  let numberScale = lerp(1.6, 1, numberIn);
  if (animationLocalFrame >= 35 && animationLocalFrame < 36) numberScale = lerp(1, 1.06, power2Out(animationLocalFrame - 35));
  else if (animationLocalFrame >= 36) numberScale = lerp(1.06, 1, progress(animationLocalFrame, 36, 3, power3Out));
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "transparent", color: prepared.ink, fontFamily: '"PingFang SC", "Hiragino Sans GB", sans-serif'}}>
    <div style={{position: "absolute", left: 122, top: 850, width: 836, height: 930, overflow: "hidden"}}>{sceneInputs.presenter}</div>
    <div data-talkcraft-layout="portrait-stack-copy" style={{position: "absolute", left: 96, top: 128, width: 888, height: 652, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center"}}>
      <div data-track="line1" style={{display: "flex", alignItems: "baseline", justifyContent: "center", whiteSpace: "nowrap"}}>
        <span data-track="number" style={{display: "inline-block", fontSize: 176, lineHeight: 0.92, fontWeight: 700, fontVariantNumeric: "tabular-nums", letterSpacing: "-0.02em", transformOrigin: "50% 72%", opacity: numberIn, color: mixColor(prepared.ink, prepared.accent, hue), transform: `scale(${numberScale})`}}>{prepared.number}</span>
        <span data-track="quantifier" style={{display: "inline-block", marginLeft: 18, fontSize: 80, lineHeight: 1.1, fontWeight: 600, whiteSpace: "nowrap", clipPath: `inset(0 ${(1 - quantifier) * 100}% 0 0)`, transform: `translateX(${lerp(-10, 0, quantifier)}px)`}}>{prepared.quantifier}</span>
      </div>
      <div data-track="line2" style={{marginTop: 18, fontSize: 80, lineHeight: 1.2, fontWeight: 600, whiteSpace: "nowrap", opacity: line2, transform: `translateY(${lerp(8, 0, line2)}px)`}}>{prepared.line2}</div>
    </div>
  </AbsoluteFill>;
}
