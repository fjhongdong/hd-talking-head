import React from "react";
import {AbsoluteFill, Sequence} from "remotion";
import contract from "./shape-wipe-transition.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "shape-wipe-transition", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as ReadonlyArray<string>;
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;
export const transitionFrames = {
  starts: [22, 23, 25],
  centers: [27, 29, 30],
  ends: [32, 34, 36],
  swap: 29,
} as const;

type ShapeWipePrepared = PreparedCard & {
  colors: [string, string, string];
  direction: "left-to-right" | "right-to-left";
};

const COLOR = /^#[0-9a-fA-F]{6}$/;
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) &&
  Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const lerp = (from: number, to: number, progress: number) => from + (to - from) * progress;
const power4In = (value: number) => Math.pow(clamp01(value), 5);
const power4Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 5);
const colorTone = (value: string) => {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16) / 255);
  const high = Math.max(...channels);
  const low = Math.min(...channels);
  const delta = high - low;
  const lightness = (high + low) / 2;
  const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * lightness - 1));
  let hue = 0;
  if (delta > 0) {
    if (high === channels[0]) hue = ((channels[1] - channels[2]) / delta) % 6;
    else if (high === channels[1]) hue = (channels[2] - channels[0]) / delta + 2;
    else hue = (channels[0] - channels[1]) / delta + 4;
    hue = (hue * 60 + 360) % 360;
  }
  return {hue, saturation, lightness};
};
const hueDistance = (left: number, right: number) => Math.min(Math.abs(left - right), 360 - Math.abs(left - right));

export const prepareCard = (raw: unknown, context: CardContext): ShapeWipePrepared => {
  if (!exactObject(raw, ["colors", "direction"])) throw new Error("shape-wipe-transition input is invalid");
  const input = raw as Record<string, unknown>;
  if (!Array.isArray(input.colors) || input.colors.length !== 3 || input.colors.some((color) => typeof color !== "string" || !COLOR.test(color)) ||
      !new Set(["left-to-right", "right-to-left"]).has(input.direction as string)) {
    throw new Error("shape-wipe-transition parameters are invalid");
  }
  const tones = (input.colors as string[]).map(colorTone);
  const neutral = tones.every((tone) => tone.saturation <= 0.12);
  const sameHue = tones.every((tone) => tone.saturation > 0.12) && tones.slice(1).every((tone) => hueDistance(tones[0].hue, tone.hue) <= 25);
  if ((!neutral && !sameHue) || !(tones[0].lightness > tones[1].lightness && tones[1].lightness > tones[2].lightness)) {
    throw new Error("shape-wipe-transition colors must be one hue ordered light to dark");
  }
  if (context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames < 59) {
    throw new Error("shape-wipe-transition requires 1080x1920@24 and at least 59 frames");
  }
  return {colors: input.colors as [string, string, string], direction: input.direction as ShapeWipePrepared["direction"]};
};

export default function ShapeWipeTransition({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<ShapeWipePrepared>) {
  if (!sceneInputs.a || !sceneInputs.b) throw new Error("shape-wipe-transition requires real A and B scene inputs");
  const direction = prepared.direction === "left-to-right" ? 1 : -1;
  const layerAt = (index: number) => {
    const start = transitionFrames.starts[index];
    const center = transitionFrames.centers[index];
    const end = transitionFrames.ends[index];
    if (animationLocalFrame < center) {
      const progress = power4In((animationLocalFrame - start) / (center - start));
      return {xPercent: lerp(-80 * direction, 0, progress), scaleX: lerp(1, 1.22, progress)};
    }
    const progress = power4Out((animationLocalFrame - center) / (end - center));
    return {xPercent: lerp(0, 80 * direction, progress), scaleX: lerp(1.22, 1, progress)};
  };
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#ffffff", overflow: "hidden"}}>
    <Sequence from={0} durationInFrames={transitionFrames.swap} layout="none">{sceneInputs.a}</Sequence>
    <Sequence from={transitionFrames.swap} layout="none">{sceneInputs.b}</Sequence>
    {prepared.colors.map((color, index) => {
      const layer = layerAt(index);
      return <div key={index} data-track={`wipe-layer-${index}`} style={{
        position: "absolute", top: "-8%", left: "-90%", width: "280%", height: "116%",
        zIndex: index + 1, background: color, willChange: "transform", transformOrigin: "50% 50%",
        transform: `translate3d(${layer.xPercent}%, 0, 0) skewX(${-12 * direction}deg) scaleX(${layer.scaleX})`,
      }}/>;
    })}
  </AbsoluteFill>;
}
