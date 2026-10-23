import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./callout-line-label.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "callout-line-label", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as ReadonlyArray<string>;
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;
export const animationFrames = {dots: [14, 34], lines: [19, 38], labels: [29, 48], texts: [31, 50], outs: [95, 98]} as const;

type Rect = {x: number; y: number; width: number; height: number};
type Annotation = {title: string; subtitle: string; side: "left" | "right"; targetBox: Rect; labelRect: Rect};
type Point = {x: number; y: number};
type Geometry = Annotation & {mappedTargetBox: Rect; target: Point; elbow: Point; end: Point; pathLength: number};
type CalloutPrepared = PreparedCard & {annotations: Geometry[]; color: string; ink: string};

const MEDIA = {x: 180, y: 180, width: 720, height: 450} as const;
const COLOR = /^#[0-9a-fA-F]{6}$/;
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const textLength = (value: unknown) => typeof value === "string" ? Array.from(value.trim()).length : 0;
const finiteRect = (value: unknown): value is Rect => {
  if (!exactObject(value, ["height", "width", "x", "y"])) return false;
  const rect = value as Record<string, unknown>;
  return [rect.x, rect.y, rect.width, rect.height].every((item) => typeof item === "number" && Number.isFinite(item)) &&
    (rect.width as number) > 0 && (rect.height as number) > 0;
};
const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
const segmentIntersectsRect = (start: Point, end: Point, rect: Rect) => {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const p = [-dx, dx, -dy, dy];
  const q = [start.x - rect.x, rect.x + rect.width - start.x, start.y - rect.y, rect.y + rect.height - start.y];
  let near = 0;
  let far = 1;
  for (let index = 0; index < p.length; index += 1) {
    if (p[index] === 0) {
      if (q[index] < 0) return false;
      continue;
    }
    const ratio = q[index] / p[index];
    if (p[index] < 0) near = Math.max(near, ratio);
    else far = Math.min(far, ratio);
    if (near > far) return false;
  }
  return true;
};
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const lerp = (from: number, to: number, progress: number) => from + (to - from) * progress;
const power1Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 2);
const power2Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 3);
const power3Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 4);
const power2In = (value: number) => Math.pow(clamp01(value), 3);
const backOut = (value: number) => {const x = clamp01(value) - 1; return 1 + 3.2 * x * x * x + 2.2 * x * x;};
const progress = (frame: number, start: number, duration: number, ease: (value: number) => number) => ease((frame - start) / duration);

export const prepareCard = (raw: unknown, context: CardContext): CalloutPrepared => {
  if (!exactObject(raw, ["annotations", "color", "ink"])) throw new Error("callout-line-label input is invalid");
  const input = raw as Record<string, unknown>;
  const metadata = context.sceneInputMetadata?.["subject-image"];
  if (!metadata || !Number.isInteger(metadata.width) || !Number.isInteger(metadata.height) || metadata.width <= 0 || metadata.height <= 0 ||
      !Array.isArray(input.annotations) || input.annotations.length !== 2 ||
      typeof input.color !== "string" || !COLOR.test(input.color) || typeof input.ink !== "string" || !COLOR.test(input.ink) ||
      context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames < 118) {
    throw new Error("callout-line-label candidate context is invalid");
  }
  const annotations = input.annotations.map((value) => {
    if (!exactObject(value, ["labelRect", "side", "subtitle", "targetBox", "title"])) throw new Error("callout-line-label annotation is invalid");
    const item = value as Record<string, unknown>;
    if (!finiteRect(item.targetBox) || !finiteRect(item.labelRect) || !new Set(["left", "right"]).has(item.side as string) ||
        textLength(item.title) < 2 || textLength(item.title) > 10 || textLength(item.subtitle) < 2 || textLength(item.subtitle) > 12 ||
        item.targetBox.x < 0 || item.targetBox.y < 0 || item.targetBox.x + item.targetBox.width > metadata.width || item.targetBox.y + item.targetBox.height > metadata.height ||
        item.labelRect.x < 24 || item.labelRect.y < 96 || item.labelRect.x + item.labelRect.width > 1056 || item.labelRect.y + item.labelRect.height > 820 ||
        item.labelRect.width < 220 || item.labelRect.height < 96) throw new Error("callout-line-label annotation exceeds its approved capacity");
    const scale = Math.min(MEDIA.width / metadata.width, MEDIA.height / metadata.height);
    const offsetX = MEDIA.x + (MEDIA.width - metadata.width * scale) / 2;
    const offsetY = MEDIA.y + (MEDIA.height - metadata.height * scale) / 2;
    const box = item.targetBox as Rect;
    const label = item.labelRect as Rect;
    const side = item.side as "left" | "right";
    const sign = side === "right" ? 1 : -1;
    const mappedTargetBox = {x: offsetX + box.x * scale, y: offsetY + box.y * scale, width: box.width * scale, height: box.height * scale};
    const target = {x: offsetX + (side === "right" ? box.x + box.width : box.x) * scale, y: offsetY + (box.y + box.height / 2) * scale};
    const end = {x: side === "right" ? label.x : label.x + label.width, y: label.y + label.height / 2};
    const dy = end.y - target.y;
    const elbow = {x: target.x + sign * Math.abs(dy), y: end.y};
    if (Math.abs(dy) < 16 || sign * (end.x - elbow.x) < 24) throw new Error("callout-line-label cannot form an approved 45-degree callout");
    return {...item, title: (item.title as string).trim(), subtitle: (item.subtitle as string).trim(), side, targetBox: box, labelRect: label, mappedTargetBox, target, elbow, end, pathLength: Math.hypot(elbow.x - target.x, elbow.y - target.y) + Math.abs(end.x - elbow.x)} as Geometry;
  });
  const labelHitsTarget = annotations.some((annotation) => annotations.some((target) => overlaps(annotation.labelRect, target.mappedTargetBox)));
  const lineHitsOtherLabel = annotations.some((annotation, index) => annotations.some((other, otherIndex) =>
    index !== otherIndex && (segmentIntersectsRect(annotation.target, annotation.elbow, other.labelRect) || segmentIntersectsRect(annotation.elbow, annotation.end, other.labelRect))
  ));
  if (overlaps(annotations[0].targetBox, annotations[1].targetBox) || overlaps(annotations[0].labelRect, annotations[1].labelRect) || labelHitsTarget || lineHitsOtherLabel) {
    throw new Error("callout-line-label geometry overlaps");
  }
  return {annotations, color: input.color as string, ink: input.ink as string};
};

export default function CalloutLineLabel({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<CalloutPrepared>) {
  const image = sceneInputs["subject-image"];
  if (!image) throw new Error("callout-line-label subject image is missing");
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "transparent", color: prepared.ink, fontFamily: '"PingFang SC", "Hiragino Sans GB", sans-serif'}}>
    <div data-track="presenter" style={{position: "absolute", left: 180, top: 900, width: 720, height: 800, overflow: "hidden"}}>{sceneInputs.presenter}</div>
    <div data-track="subject-image" style={{position: "absolute", left: MEDIA.x, top: MEDIA.y, width: MEDIA.width, height: MEDIA.height, overflow: "hidden", borderRadius: 24, boxShadow: "0 18px 48px rgba(0,0,0,0.14)"}}>{image}</div>
    <svg data-track="callout-lines" viewBox="0 0 1080 1920" style={{position: "absolute", inset: 0, pointerEvents: "none"}}>
      {prepared.annotations.map((item, index) => {
        const dotP = animationLocalFrame < animationFrames.outs[index] + 7 ? progress(animationLocalFrame, animationFrames.dots[index], 5, backOut) : 1 - progress(animationLocalFrame, animationFrames.outs[index] + 7, 4, power2In);
        const rippleP = progress(animationLocalFrame, animationFrames.dots[index] + 1, 12, power2Out);
        const lineP = animationLocalFrame < animationFrames.outs[index] + 3 ? progress(animationLocalFrame, animationFrames.lines[index], 10, power2Out) : 1 - progress(animationLocalFrame, animationFrames.outs[index] + 3, 5, power2In);
        const path = `M ${item.target.x} ${item.target.y} L ${item.elbow.x} ${item.elbow.y} L ${item.end.x} ${item.end.y}`;
        return <g key={item.title}>
          {animationLocalFrame >= animationFrames.dots[index] + 1 ? <circle cx={item.target.x} cy={item.target.y} r={9} fill="none" stroke={prepared.color} strokeWidth={3} opacity={lerp(0.9, 0, rippleP)} transform={`translate(${item.target.x} ${item.target.y}) scale(${lerp(0.4, 3.2, rippleP)}) translate(${-item.target.x} ${-item.target.y})`}/> : null}
          <circle cx={item.target.x} cy={item.target.y} r={9} fill={prepared.color} opacity={clamp01(dotP)} transform={`translate(${item.target.x} ${item.target.y}) scale(${dotP}) translate(${-item.target.x} ${-item.target.y})`}/>
          <path d={path} fill="none" stroke={prepared.color} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={item.pathLength} strokeDashoffset={item.pathLength * (1 - lineP)}/>
        </g>;
      })}
    </svg>
    {prepared.annotations.map((item, index) => {
      const shown = animationLocalFrame < animationFrames.outs[index] ? progress(animationLocalFrame, animationFrames.labels[index], 6, power3Out) : 1 - progress(animationLocalFrame, animationFrames.outs[index], 5, power2In);
      const textP = progress(animationLocalFrame, animationFrames.texts[index], 5, power1Out);
      const clipPath = item.side === "right" ? `inset(0 ${(1 - shown) * 100}% 0 0)` : `inset(0 0 0 ${(1 - shown) * 100}%)`;
      return <div key={item.title} data-callout-index={index} style={{position: "absolute", left: item.labelRect.x, top: item.labelRect.y, width: item.labelRect.width, height: item.labelRect.height, boxSizing: "border-box", padding: "16px 20px", borderRadius: 14, background: "rgba(255,255,255,0.96)", border: "1px solid rgba(29,29,31,0.14)", boxShadow: "0 10px 30px rgba(0,0,0,0.12)", clipPath, whiteSpace: "nowrap"}}>
        <div style={{fontSize: 31, lineHeight: 1.15, fontWeight: 650, opacity: textP}}>{item.title}</div>
        <div style={{marginTop: 7, fontSize: 24, lineHeight: 1.1, color: "#6e6e73", opacity: textP}}>{item.subtitle}</div>
      </div>;
    })}
  </AbsoluteFill>;
}
