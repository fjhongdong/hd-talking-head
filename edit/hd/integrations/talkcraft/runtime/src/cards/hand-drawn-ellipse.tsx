import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./hand-drawn-ellipse.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "hand-drawn-ellipse", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as string[];
export const sfxCues = contract.sfx_cues as CardSfxCue[];
type Rect = {x: number; y: number; width: number; height: number};
type Props = PreparedCard & {text: string; accent: string; targetBox: Rect};
const exact = (value: unknown, keys: string[]) => Boolean(value) && typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).sort().join(",") === keys.slice().sort().join(",");

export const prepareCard = (raw: unknown, context: CardContext): Props => {
  if (!exact(raw, ["accent", "targetBox", "text"])) throw Error("hand-drawn-ellipse exact input required");
  const value = raw as Record<string, unknown>;
  const box = value.targetBox as Rect;
  const presenter = context.sceneInputMetadata?.presenter;
  const subject = context.sceneInputMetadata?.["subject-image"];
  if (typeof value.text !== "string" || value.text.length < 2 || value.text.length > 18 || typeof value.accent !== "string" || !/^#[0-9a-f]{6}$/i.test(value.accent) || !exact(box, ["height", "width", "x", "y"]) || box.x < 0 || box.y < 0 || box.width <= 0 || box.height <= 0 || box.x + box.width > 1200 || box.y + box.height > 750 || presenter?.width !== 540 || presenter?.height !== 600 || subject?.width !== 1200 || subject?.height !== 750 || context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames !== 102) throw Error("hand-drawn-ellipse content exceeds approved capacity");
  return {text: value.text.trim(), accent: value.accent, targetBox: box};
};

export default function Card({prepared, animationLocalFrame, sceneInputs, namespace}: CardRenderProps<Props>) {
  const progress = Math.min(1, Math.max(0, (animationLocalFrame - 10) / 20));
  const b = prepared.targetBox;
  const x = (b.x + b.width / 2) * 0.75;
  const y = (b.y + b.height / 2) * 0.75;
  const rx = (b.width / 2 + 24) * 0.75;
  const ry = (b.height / 2 + 18) * 0.75;
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#fff", fontFamily: '"PingFang SC", sans-serif'}}>
    <div style={{position: "absolute", left: 90, top: 220, width: 900, height: 560, overflow: "hidden", borderRadius: 24}}>{sceneInputs["subject-image"]}<svg viewBox="0 0 900 560" style={{position: "absolute", inset: 0}}><ellipse cx={x} cy={y} rx={rx} ry={ry} fill="none" stroke={prepared.accent} strokeWidth="9" strokeLinecap="round" strokeDasharray="1800" strokeDashoffset={1800 * (1 - progress)} transform={`rotate(-2 ${x} ${y})`} /><ellipse cx={x + 3} cy={y - 2} rx={rx + 5} ry={ry - 3} fill="none" stroke={prepared.accent} strokeWidth="4" opacity={0.55} strokeLinecap="round" strokeDasharray="1800" strokeDashoffset={1800 * (1 - Math.max(0, (progress - 0.12) / 0.88))} transform={`rotate(2 ${x} ${y})`} /></svg></div>
    <div style={{position: "absolute", left: 120, top: 810, width: 840, textAlign: "center", color: prepared.accent, fontSize: 44, fontWeight: 700}}>{prepared.text}</div>
    <div style={{position: "absolute", left: 180, top: 930, width: 720, height: 800}}>{sceneInputs.presenter}</div>
  </AbsoluteFill>;
}
