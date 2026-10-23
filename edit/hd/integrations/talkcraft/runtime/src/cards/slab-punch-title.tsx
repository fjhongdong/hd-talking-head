import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./slab-punch-title.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "slab-punch-title", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as ReadonlyArray<string>;
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;
export const animationFrames = {line1Start: 10, line1End: 14, slabStart: 16, slabEnd: 21, punchStart: 21, punchEnd: 25} as const;
export const layoutRects = {presenter: contract.geometry.presenter_rect, title: contract.geometry.title_rect} as const;

type SlabPunchPrepared = PreparedCard & {line1: string; line2: string; accent: string; ink: string; wordColor: string};

const COLOR = /^#[0-9a-fA-F]{6}$/;
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const textLength = (value: unknown) => typeof value === "string" ? Array.from(value.trim()).length : 0;
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const lerp = (from: number, to: number, amount: number) => from + (to - from) * amount;
const power3Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 4);
const progress = (frame: number, start: number, end: number) => power3Out((frame - start) / (end - start));

export const prepareCard = (raw: unknown, context: CardContext): SlabPunchPrepared => {
  if (!exactObject(raw, ["accent", "ink", "line1", "line2", "wordColor"])) throw new Error("slab-punch-title input is invalid");
  const input = raw as Record<string, unknown>;
  const presenter = context.sceneInputMetadata?.presenter;
  if (textLength(input.line1) < 2 || textLength(input.line1) > 4 || textLength(input.line2) < 2 || textLength(input.line2) > 5 ||
      [input.accent, input.ink, input.wordColor].some((color) => typeof color !== "string" || !COLOR.test(color)) ||
      presenter?.width !== 540 || presenter.height !== 600 || context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames !== 64) {
    throw new Error("slab-punch-title content exceeds its approved capacity");
  }
  return {line1: (input.line1 as string).trim(), line2: (input.line2 as string).trim(), accent: input.accent as string, ink: input.ink as string, wordColor: input.wordColor as string};
};

export default function SlabPunchTitle({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<SlabPunchPrepared>) {
  const presenter = sceneInputs.presenter;
  if (!presenter) throw new Error("slab-punch-title presenter is missing");
  const line1P = progress(animationLocalFrame, animationFrames.line1Start, animationFrames.line1End);
  const slabP = progress(animationLocalFrame, animationFrames.slabStart, animationFrames.slabEnd);
  const punchP = progress(animationLocalFrame, animationFrames.punchStart, animationFrames.punchEnd);
  const wordOpacity = animationLocalFrame < animationFrames.punchStart ? 0 : 1;
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#ffffff", overflow: "hidden", fontFamily: '"PingFang SC", "Hiragino Sans GB", sans-serif'}}>
    <div data-track="title-zone" style={{position: "absolute", zIndex: 3, left: layoutRects.title.x, top: layoutRects.title.y, width: layoutRects.title.width, height: layoutRects.title.height, display: "flex", alignItems: "flex-start", justifyContent: "center", flexDirection: "column"}}>
      <div data-track="title-rotation" style={{transform: "rotate(-2.5deg)", transformOrigin: "50% 50%"}}>
        <div data-track="lead-line" style={{fontSize: 150, fontWeight: 720, lineHeight: 1.08, letterSpacing: "-0.04em", color: prepared.ink, whiteSpace: "nowrap", opacity: line1P, transformOrigin: "0% 50%", transform: `scale(${lerp(1.04, 1, line1P)})`}}>{prepared.line1}</div>
        <div data-track="slab-row" style={{position: "relative", display: "inline-block", marginTop: 20, padding: "20px 44px 24px", isolation: "isolate"}}>
          <span data-track="slab" aria-hidden="true" style={{position: "absolute", inset: 0, zIndex: -1, background: prepared.accent, transformOrigin: "50% 50%", transform: `scaleX(${slabP})`}}/>
          <span data-track="punch-word" style={{display: "inline-block", marginLeft: -44, fontSize: 150, fontWeight: 760, lineHeight: 1.08, letterSpacing: "-0.04em", color: prepared.wordColor, whiteSpace: "nowrap", opacity: wordOpacity, transformOrigin: "50% 50%", transform: `scale(${lerp(1.12, 1, punchP)})`}}>{prepared.line2}</span>
        </div>
      </div>
    </div>
    <div data-track="presenter" data-alpha-source="libvpx-vp9" style={{position: "absolute", zIndex: 2, left: layoutRects.presenter.x, top: layoutRects.presenter.y, width: layoutRects.presenter.width, height: layoutRects.presenter.height, overflow: "hidden"}}>{presenter}</div>
  </AbsoluteFill>;
}
