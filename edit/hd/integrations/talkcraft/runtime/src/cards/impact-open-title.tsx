import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./impact-open-title.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "impact-open-title", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as ReadonlyArray<string>;
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;
export const animationFrames = {slamStart: 10, slamEnd: 14, cornerStart: 10, cornerEnd: 17, wordStart: 17, wordEnd: 21, dotsStart: 19, dotsEnd: 29, subtitleStart: 23, subtitleEnd: 30} as const;
export const layoutRects = {presenter: contract.geometry.presenter_rect, title: contract.geometry.title_rect, subtitle: contract.geometry.subtitle_rect} as const;

type ImpactOpenPrepared = PreparedCard & {lead: string; impact: string; subtitle: string; accent: string};

const COLOR = /^#[0-9a-fA-F]{6}$/;
const DOTS_OPACITY = 0.5;
const cornerVectors: [string, number, number][] = [["tl", -1, -1], ["br", 1, 1]];
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const textLength = (value: unknown) => typeof value === "string" ? Array.from(value.trim()).length : 0;
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const lerp = (from: number, to: number, progress: number) => from + (to - from) * progress;
const easeOut = (power: number) => (value: number) => 1 - Math.pow(1 - clamp01(value), power + 1);
const progress = (frame: number, start: number, end: number, ease: (value: number) => number) => ease((frame - start) / (end - start));
const mixHex = (from: string, to: string, amount: number) => {
  const channels = (value: string) => [1, 3, 5].map((index) => Number.parseInt(value.slice(index, index + 2), 16));
  const left = channels(from);
  const right = channels(to);
  return `rgb(${left.map((value, index) => Math.round(lerp(value, right[index], amount))).join(",")})`;
};

export const prepareCard = (raw: unknown, context: CardContext): ImpactOpenPrepared => {
  if (!exactObject(raw, ["accent", "impact", "lead", "subtitle"])) throw new Error("impact-open-title input is invalid");
  const input = raw as Record<string, unknown>;
  const presenter = context.sceneInputMetadata?.presenter;
  if (textLength(input.lead) < 3 || textLength(input.lead) > 5 || textLength(input.impact) < 2 || textLength(input.impact) > 3 ||
      textLength(input.subtitle) < 10 || textLength(input.subtitle) > 18 || typeof input.accent !== "string" || !COLOR.test(input.accent) ||
      presenter?.width !== 540 || presenter.height !== 600 || context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames !== 76) {
    throw new Error("impact-open-title content exceeds its approved capacity");
  }
  return {lead: (input.lead as string).trim(), impact: (input.impact as string).trim(), subtitle: (input.subtitle as string).trim(), accent: input.accent};
};

export default function ImpactOpenTitle({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<ImpactOpenPrepared>) {
  const presenter = sceneInputs.presenter;
  if (!presenter) throw new Error("impact-open-title presenter is missing");
  const slamP = progress(animationLocalFrame, animationFrames.slamStart, animationFrames.slamEnd, easeOut(4));
  const cornerP = progress(animationLocalFrame, animationFrames.cornerStart, animationFrames.cornerEnd, easeOut(2));
  const wordP = progress(animationLocalFrame, animationFrames.wordStart, animationFrames.wordEnd, easeOut(3));
  const dotsP = progress(animationLocalFrame, animationFrames.dotsStart, animationFrames.dotsEnd, easeOut(1));
  const subtitleP = progress(animationLocalFrame, animationFrames.subtitleStart, animationFrames.subtitleEnd, easeOut(2));
  const wordScale = animationLocalFrame < animationFrames.wordStart ? 1 : lerp(1.15, 1, wordP);
  const wordColor = animationLocalFrame < animationFrames.wordStart ? "#1d1d1f" : mixHex("#1d1d1f", prepared.accent, wordP);
  const cornerOffset = lerp(32, 0, cornerP);
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#ffffff", overflow: "hidden", fontFamily: '"PingFang SC", "Hiragino Sans GB", sans-serif'}}>
    <div data-track="presenter" data-alpha-source="libvpx-vp9" style={{position: "absolute", zIndex: 1, left: layoutRects.presenter.x, top: layoutRects.presenter.y, width: layoutRects.presenter.width, height: layoutRects.presenter.height, overflow: "hidden"}}>{presenter}</div>
    <div data-track="dots" aria-hidden="true" style={{position: "absolute", zIndex: 2, left: 816, top: 250, width: 144, height: 180, opacity: DOTS_OPACITY * dotsP, backgroundImage: `radial-gradient(circle, ${prepared.accent} 4px, transparent 4.5px)`, backgroundSize: "36px 36px", backgroundPosition: "4px 4px"}}/>
    <div data-track="title-group" style={{position: "absolute", zIndex: 3, left: layoutRects.title.x, top: layoutRects.title.y, width: layoutRects.title.width, height: layoutRects.title.height, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "flex-start", gap: 14, opacity: slamP, transformOrigin: "0% 50%", transform: `scale(${lerp(1.08, 1, slamP)})`}}>
      <span style={{fontSize: 150, fontWeight: 760, lineHeight: 0.96, color: "#1d1d1f", whiteSpace: "nowrap"}}>{prepared.lead}</span>
      <span data-track="impact-word" style={{display: "inline-block", fontSize: 190, fontWeight: 760, lineHeight: 0.94, color: wordColor, whiteSpace: "nowrap", transformOrigin: "0% 50%", transform: `scale(${wordScale})`}}>{prepared.impact}</span>
    </div>
    <div data-track="subtitle" style={{position: "absolute", zIndex: 3, left: layoutRects.subtitle.x, top: layoutRects.subtitle.y, width: layoutRects.subtitle.width, height: layoutRects.subtitle.height, color: "#7a7a82", fontSize: 36, fontWeight: 500, lineHeight: 1.35, letterSpacing: "0.08em", whiteSpace: "nowrap", opacity: subtitleP, transform: `translateY(${lerp(18, 0, subtitleP)}px)`}}>{prepared.subtitle}</div>
    {cornerVectors.map(([corner, dx, dy]) => {
      const topLeft = corner === "tl";
      return <div key={corner} data-track={`corner-${corner}`} aria-hidden="true" style={{position: "absolute", zIndex: 5, width: 120, height: 120, left: topLeft ? 64 : undefined, right: topLeft ? undefined : 64, top: topLeft ? 64 : undefined, bottom: topLeft ? undefined : 64, opacity: cornerP, transform: `translate(${dx * cornerOffset}px, ${dy * cornerOffset}px)`}}>
        <span style={{position: "absolute", left: 0, bottom: topLeft ? undefined : 0, top: topLeft ? 0 : undefined, width: 120, height: 7, background: prepared.accent}}/>
        <span style={{position: "absolute", left: topLeft ? 0 : undefined, right: topLeft ? undefined : 0, top: topLeft ? 0 : undefined, bottom: topLeft ? undefined : 0, width: 7, height: 120, background: prepared.accent}}/>
      </div>;
    })}
  </AbsoluteFill>;
}
