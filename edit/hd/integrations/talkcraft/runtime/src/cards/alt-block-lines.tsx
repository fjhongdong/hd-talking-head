import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./alt-block-lines.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "alt-block-lines", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as string[];
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;

type AltBlockPrepared = PreparedCard & {
  lines: [string, string];
  accent: string;
  canvas: string;
  ink: string;
  outline: string;
  lead: number;
  duration: number;
  stagger: number;
  textLag: number;
};

const COLOR = /^#[0-9a-fA-F]{6}$/;
const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const power3Out = (value: number) => 1 - Math.pow(1 - clamp01(value), 4);
const exactObject = (value: unknown, keys: string[]) => value !== null && typeof value === "object" && !Array.isArray(value) &&
  Object.keys(value).sort().join(",") === [...keys].sort().join(",");

export const prepareCard = (raw: unknown, context: CardContext): AltBlockPrepared => {
  if (!exactObject(raw, ["accent", "canvas", "ink", "lines", "outline"])) throw new Error("alt-block-lines input is invalid");
  const input = raw as {lines: unknown; accent: unknown; canvas: unknown; ink: unknown; outline: unknown};
  if (!Array.isArray(input.lines) || input.lines.length !== 2 || input.lines.some((line) => typeof line !== "string" || Array.from(line.trim()).length < 3 || Array.from(line.trim()).length > 6)) {
    throw new Error("alt-block-lines requires exactly two lines of 3 to 6 characters");
  }
  if ([input.accent, input.canvas, input.ink, input.outline].some((color) => typeof color !== "string" || !COLOR.test(color))) {
    throw new Error("alt-block-lines colors are invalid");
  }
  const lead = 10;
  const duration = 6;
  const stagger = 3;
  const textLag = 2;
  const minimumHold = 29;
  const minimumFrames = lead + stagger + textLag + duration + minimumHold;
  if (context !== null && (context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames < minimumFrames)) {
    throw new Error(`alt-block-lines requires at least ${minimumFrames} frames`);
  }
  return {
    lines: [input.lines[0].trim(), input.lines[1].trim()],
    accent: input.accent as string, canvas: input.canvas as string,
    ink: input.ink as string, outline: input.outline as string,
    lead, duration, stagger, textLag,
  };
};

export default function AltBlockLines({prepared, animationLocalFrame, namespace, sceneInputs}: CardRenderProps<AltBlockPrepared>) {
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "transparent", fontFamily: '"PingFang SC", "Hiragino Sans GB", sans-serif'}}>
    <div style={{position: "absolute", left: 54, top: 700, width: 972, height: 1080, overflow: "hidden"}}>{sceneInputs.presenter}</div>
    <div data-talkcraft-layout="portrait-stack-copy" style={{position: "absolute", left: "50%", top: 240, width: "max-content", transform: "translateX(-50%)", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 24}}>
      {prepared.lines.map((line, index) => {
        const start = prepared.lead + index * prepared.stagger;
        const blockProgress = power3Out((animationLocalFrame - start) / prepared.duration);
        const textProgress = power3Out((animationLocalFrame - start - prepared.textLag) / prepared.duration);
        const first = index === 0;
        return <div key={index} style={{position: "relative", display: "inline-block", padding: "17px 35px 20px"}}>
          <div data-track={`block-${index}`} style={{position: "absolute", inset: 0, borderRadius: 7, transformOrigin: "0% 50%", transform: `scaleX(${blockProgress})`, background: first ? prepared.accent : prepared.canvas, boxShadow: first ? "none" : `inset 0 0 0 2px ${prepared.outline}`}}/>
          <div data-track={`text-${index}`} style={{position: "relative", display: "inline-block", whiteSpace: "nowrap", fontSize: 96, fontWeight: 700, lineHeight: 1.08, color: first ? prepared.canvas : prepared.ink, clipPath: `inset(0 ${(1 - textProgress) * 100}% 0 0)`}}>{line}</div>
        </div>;
      })}
    </div>
  </AbsoluteFill>;
}
