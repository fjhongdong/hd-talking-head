import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./behind-text-title.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "behind-text-title", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as ReadonlyArray<string>;
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;
export const animationFrames = {titleStart: 10, titleEnd: 24, subtitleStart: 18, subtitleEnd: 28, driftStart: 24, driftPeriod: 192} as const;
export const layoutRects = {presenter: contract.geometry.presenter_rect, title: contract.geometry.title_rect} as const;

type BehindTextPrepared = PreparedCard & {titleLines: [string, string]; subtitle: string; accent: string; fontSizes: [number, number]};

const COLOR = /^#[0-9a-fA-F]{6}$/;
const TITLE_LINE_GAP = 28;
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const textLength = (value: unknown) => typeof value === "string" ? Array.from(value.trim()).length : 0;
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const lerp = (from: number, to: number, progress: number) => from + (to - from) * progress;
const power2Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 3);
const power3Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 4);
const progress = (frame: number, start: number, end: number, ease: (value: number) => number) => ease((frame - start) / (end - start));
const yoyo = (frame: number, start: number, period: number) => {
  if (frame <= start) return 0;
  const phase = ((frame - start) % period) / (period / 2);
  const linear = phase <= 1 ? phase : 2 - phase;
  return -(Math.cos(Math.PI * linear) - 1) / 2;
};
const extrusion = Array.from({length: 20}, (_, index) => {
  const depth = index + 1;
  const shade = 212 - index * 5;
  return `${depth}px ${depth}px 0 rgb(${shade},${shade},${shade + 4})`;
}).concat("30px 38px 48px rgba(0,0,0,0.18)").join(",");

export const prepareCard = (raw: unknown, context: CardContext): BehindTextPrepared => {
  if (!exactObject(raw, ["accent", "subtitle", "title_lines"])) throw new Error("behind-text-title input is invalid");
  const input = raw as Record<string, unknown>;
  const presenter = context.sceneInputMetadata?.presenter;
  const titleLines = input.title_lines;
  if (!Array.isArray(titleLines) || titleLines.length !== 2 || titleLines.some((line) => textLength(line) < 2 || textLength(line) > 3) ||
      textLength(input.subtitle) < 4 || textLength(input.subtitle) > 28 ||
      typeof input.accent !== "string" || !COLOR.test(input.accent) ||
      presenter?.width !== 540 || presenter.height !== 600 ||
      context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames < 76) {
    throw new Error("behind-text-title content exceeds its approved capacity");
  }
  const normalizedLines = titleLines.map((line) => (line as string).trim()) as [string, string];
  const fontSizes = normalizedLines.map((line) => Array.from(line).length === 2 ? 430 : 310) as [number, number];
  return {titleLines: normalizedLines, subtitle: (input.subtitle as string).trim(), accent: input.accent as string, fontSizes};
};

export default function BehindTextTitle({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<BehindTextPrepared>) {
  const presenter = sceneInputs.presenter;
  if (!presenter) throw new Error("behind-text-title presenter is missing");
  const titleP = progress(animationLocalFrame, animationFrames.titleStart, animationFrames.titleEnd, power3Out);
  const subtitleP = progress(animationLocalFrame, animationFrames.subtitleStart, animationFrames.subtitleEnd, power2Out);
  const drift = 5 * yoyo(animationLocalFrame, animationFrames.driftStart, animationFrames.driftPeriod);
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#ffffff", overflow: "hidden", fontFamily: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'}}>
    <div data-track="subtitle" style={{position: "absolute", zIndex: 3, left: 80, right: 80, top: 210, textAlign: "center", color: prepared.accent, fontSize: 34, lineHeight: 1.2, fontWeight: 650, letterSpacing: "0.18em", opacity: subtitleP, transform: `translateY(${lerp(14, 0, subtitleP)}px)`, whiteSpace: "nowrap"}}>{prepared.subtitle}</div>
    <div data-track="title" data-text={prepared.titleLines.join("\n")} style={{position: "absolute", zIndex: 1, left: layoutRects.title.x, top: layoutRects.title.y, width: layoutRects.title.width, height: layoutRects.title.height, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: TITLE_LINE_GAP, fontFamily: '"Yuanti SC", "PingFang SC", sans-serif', lineHeight: 0.93, fontWeight: 700, whiteSpace: "nowrap", opacity: titleP, letterSpacing: `${lerp(0.1, 0.02, titleP)}em`, transform: `translate(${drift}px, ${lerp(84, 0, titleP)}px)`}}>
      {prepared.titleLines.map((line, index) => <span key={index} style={{position: "relative", display: "block", fontSize: prepared.fontSizes[index]}}>
        <span data-title-depth="true" aria-hidden="true" style={{position: "absolute", inset: 0, color: "#d4d4d9", textShadow: extrusion}}>{line}</span>
        <span data-title-face="true" style={{position: "relative", display: "block", background: "linear-gradient(180deg,rgba(124,124,134,0.98) 0%,rgba(82,82,91,0.98) 52%,rgba(50,50,56,0.98) 100%)", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent", WebkitTextFillColor: "transparent", textShadow: "none"}}>{line}</span>
      </span>)}
    </div>
    <div data-track="presenter" data-alpha-source="libvpx-vp9" style={{position: "absolute", zIndex: 2, left: layoutRects.presenter.x, top: layoutRects.presenter.y, width: layoutRects.presenter.width, height: layoutRects.presenter.height, transform: `translateX(${-drift}px)`, overflow: "hidden"}}>{presenter}</div>
  </AbsoluteFill>;
}
