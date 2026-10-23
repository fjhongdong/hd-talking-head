import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./keyword-pop-highlight.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "keyword-pop-highlight", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as ReadonlyArray<string>;
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;
export const animationFrames = {popStart: 13, popEnd: 18, shakeStart: 13, shakeEnd: 19, settleStart: 19, settleEnd: 24} as const;
export const layoutRects = {presenter: contract.geometry.presenter_rect, caption: contract.geometry.caption_rect} as const;
export const shakeOffsets = [0, 7, -7, 7, -7, 7, 0] as const;

type KeywordPopPrepared = PreparedCard & {
  before: string;
  keyword: string;
  after: string;
  ink: string;
  keywordColor: string;
  blockColor: string;
};

const POP_SCALE = 1.65;
const REST_SCALE = 1.15;
const SHAKE_PX = 7;
const COLOR = /^#[0-9a-fA-F]{6}$/;
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const length = (value: unknown) => typeof value === "string" ? Array.from(value.trim()).length : 0;
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const lerp = (from: number, to: number, progress: number) => from + (to - from) * progress;
const power4Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 5);
const backOut = (value: number, overshoot = 2.5) => {
  const shifted = clamp01(value) - 1;
  return 1 + (overshoot + 1) * shifted * shifted * shifted + overshoot * shifted * shifted;
};
const progress = (frame: number, start: number, end: number, ease: (value: number) => number) => ease((frame - start) / (end - start));

export const prepareCard = (raw: unknown, context: CardContext): KeywordPopPrepared => {
  if (!exactObject(raw, ["after", "before", "blockColor", "ink", "keyword", "keywordColor"])) throw new Error("keyword-pop-highlight input is invalid");
  const input = raw as Record<string, unknown>;
  const beforeLength = length(input.before);
  const keywordLength = length(input.keyword);
  const afterLength = length(input.after);
  const presenter = context.sceneInputMetadata?.presenter;
  if (beforeLength < 3 || beforeLength > 7 || keywordLength < 2 || keywordLength > 5 || afterLength < 3 || afterLength > 7 ||
      beforeLength + keywordLength + afterLength > 16 || [input.ink, input.keywordColor, input.blockColor].some((color) => typeof color !== "string" || !COLOR.test(color)) ||
      presenter?.width !== 540 || presenter.height !== 600 || context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames !== 48) {
    throw new Error("keyword-pop-highlight content exceeds its approved capacity");
  }
  return {
    before: (input.before as string).trim(), keyword: (input.keyword as string).trim(), after: (input.after as string).trim(),
    ink: input.ink as string, keywordColor: input.keywordColor as string, blockColor: input.blockColor as string,
  };
};

export default function KeywordPopHighlight({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<KeywordPopPrepared>) {
  const presenter = sceneInputs.presenter;
  if (!presenter) throw new Error("keyword-pop-highlight presenter is missing");
  const popP = progress(animationLocalFrame, animationFrames.popStart, animationFrames.popEnd, power4Out);
  const settleP = progress(animationLocalFrame, animationFrames.settleStart, animationFrames.settleEnd, (value) => backOut(value));
  const beforeSettle = animationLocalFrame < animationFrames.settleStart;
  const scale = beforeSettle ? lerp(0, POP_SCALE, popP) : lerp(POP_SCALE, REST_SCALE, settleP);
  const rotate = beforeSettle ? lerp(-8, 2, popP) : lerp(2, 0, settleP);
  const shakeFrame = animationLocalFrame - animationFrames.shakeStart;
  const shakeX = shakeFrame >= 0 && shakeFrame < shakeOffsets.length ? shakeOffsets[shakeFrame] : 0;
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#ffffff", overflow: "hidden", fontFamily: '"PingFang SC", "Hiragino Sans GB", sans-serif'}}>
    <AbsoluteFill data-track="impact-stage" style={{background: "#ffffff", transform: `translateX(${shakeX}px)`}}>
      <div data-track="presenter" data-alpha-source="libvpx-vp9" style={{position: "absolute", left: layoutRects.presenter.x, top: layoutRects.presenter.y, width: layoutRects.presenter.width, height: layoutRects.presenter.height, overflow: "hidden"}}>{presenter}</div>
      <div data-track="caption-zone" style={{position: "absolute", left: layoutRects.caption.x, top: layoutRects.caption.y, width: layoutRects.caption.width, height: layoutRects.caption.height, display: "flex", alignItems: "center", justifyContent: "center"}}>
        <div style={{display: "flex", alignItems: "baseline", justifyContent: "center", maxWidth: "100%", whiteSpace: "nowrap", padding: "28px 34px", borderRadius: 34, background: "rgba(255,255,255,0.94)", boxShadow: "0 18px 54px rgba(29,29,31,0.12)", color: prepared.ink, fontSize: 54, fontWeight: 620, lineHeight: 1.25, letterSpacing: "0.02em"}}>
          <span>{prepared.before}</span>
          <span data-track="keyword" style={{display: "inline-block", position: "relative", isolation: "isolate", margin: "0 0.36em", padding: "0.04em 0.18em", fontWeight: 800, color: prepared.keywordColor, transformOrigin: "50% 80%", opacity: popP, transform: `rotate(${rotate}deg) scale(${scale})`}}>
            <span aria-hidden="true" style={{position: "absolute", inset: 0, zIndex: -1, borderRadius: "0.14em", background: prepared.blockColor, transform: "skewX(-6deg)"}}/>
            {prepared.keyword}
          </span>
          <span>{prepared.after}</span>
        </div>
      </div>
    </AbsoluteFill>
  </AbsoluteFill>;
}
