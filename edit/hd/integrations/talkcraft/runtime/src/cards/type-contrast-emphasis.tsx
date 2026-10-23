import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./type-contrast-emphasis.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "type-contrast-emphasis", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as ReadonlyArray<string>;
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;
export const layoutRects = {presenter: contract.geometry.presenter_rect, caption: contract.geometry.caption_rect} as const;

type Word = {text: string; frame: number; emphasis: "normal" | "serif" | "color"};
type TypeContrastPrepared = PreparedCard & {words: Word[]; accent: string; ink: string};

const WORD_FRAMES = [4, 21, 28, 36, 40] as const;
const WORD_FROM_SCALE = 0.95;
const ACCENT_FROM_SCALE = 0.92;
const COLOR = /^#[0-9a-fA-F]{6}$/;
const serifFamily = '"Songti SC", "STSong", "Noto Serif CJK SC", Georgia, serif';
const sansFamily = '"PingFang SC", "Hiragino Sans GB", sans-serif';
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const textLength = (value: unknown) => typeof value === "string" ? Array.from(value.trim()).length : 0;
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const lerp = (from: number, to: number, amount: number) => from + (to - from) * amount;
const power2Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 3);
const power3Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 4);

export const prepareCard = (raw: unknown, context: CardContext): TypeContrastPrepared => {
  if (!exactObject(raw, ["accent", "ink", "words"])) throw new Error("type-contrast-emphasis input is invalid");
  const input = raw as Record<string, unknown>;
  const words = input.words;
  const presenter = context.sceneInputMetadata?.presenter;
  if (!Array.isArray(words) || words.length !== 5 || !COLOR.test(String(input.accent)) || !COLOR.test(String(input.ink)) ||
      presenter?.width !== 540 || presenter.height !== 600 || context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames !== 54) {
    throw new Error("type-contrast-emphasis content exceeds its approved capacity");
  }
  const expectedEmphasis = ["normal", "normal", "serif", "normal", "color"];
  const valid = words.every((word, index) => exactObject(word, ["emphasis", "frame", "text"]) &&
    textLength((word as Record<string, unknown>).text) >= 1 && textLength((word as Record<string, unknown>).text) <= 6 &&
    (word as Record<string, unknown>).frame === WORD_FRAMES[index] && (word as Record<string, unknown>).emphasis === expectedEmphasis[index]);
  const totalLength = words.reduce((sum, word) => sum + textLength((word as Record<string, unknown>).text), 0);
  if (!valid || totalLength > 14) throw new Error("type-contrast-emphasis word contract is invalid");
  return {words: words.map((word) => ({...(word as Word), text: (word as Word).text.trim()})), accent: input.accent as string, ink: input.ink as string};
};

export default function TypeContrastEmphasis({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<TypeContrastPrepared>) {
  const presenter = sceneInputs.presenter;
  if (!presenter) throw new Error("type-contrast-emphasis presenter is missing");
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#ffffff", overflow: "hidden", fontFamily: sansFamily}}>
    <div data-track="caption-zone" style={{position: "absolute", zIndex: 3, left: layoutRects.caption.x, top: layoutRects.caption.y, width: layoutRects.caption.width, height: layoutRects.caption.height, display: "flex", alignItems: "center", justifyContent: "center"}}>
      <div data-track="word-line" style={{display: "flex", flexWrap: "nowrap", alignItems: "baseline", justifyContent: "center", gap: 16, whiteSpace: "nowrap"}}>
        {prepared.words.map((word, index) => {
          const emphasized = word.emphasis !== "normal";
          const duration = emphasized ? 4 : 3;
          const rawProgress = (animationLocalFrame - word.frame) / duration;
          const p = emphasized ? power3Out(rawProgress) : power2Out(rawProgress);
          const transform = word.emphasis === "serif"
            ? `translateY(${lerp(14, 0, p)}px) scale(${lerp(ACCENT_FROM_SCALE, 1, p)}) skewX(-7deg)`
            : word.emphasis === "color"
              ? `translateY(${lerp(14, 0, p)}px) scale(${lerp(ACCENT_FROM_SCALE, 1, p)})`
              : `scale(${lerp(WORD_FROM_SCALE, 1, p)})`;
          return <span key={`${word.frame}-${index}`} data-track={`word-${index}`} data-emphasis={word.emphasis} style={{display: "inline-block", opacity: p, transform, transformOrigin: "50% 100%", fontFamily: word.emphasis === "serif" ? serifFamily : sansFamily, fontSize: word.emphasis === "serif" ? 90 : word.emphasis === "color" ? 84 : 56, fontWeight: word.emphasis === "color" ? 800 : 620, lineHeight: 1.25, letterSpacing: "-0.03em", color: word.emphasis === "color" ? prepared.accent : prepared.ink, marginRight: word.emphasis === "serif" ? 6 : 0}}>{word.text}</span>;
        })}
      </div>
    </div>
    <div data-track="presenter" data-alpha-source="libvpx-vp9" style={{position: "absolute", zIndex: 2, left: layoutRects.presenter.x, top: layoutRects.presenter.y, width: layoutRects.presenter.width, height: layoutRects.presenter.height, overflow: "hidden"}}>{presenter}</div>
  </AbsoluteFill>;
}
