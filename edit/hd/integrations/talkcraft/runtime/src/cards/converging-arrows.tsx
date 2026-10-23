import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./converging-arrows.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "converging-arrows", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as string[];
export const sfxCues = contract.sfx_cues as CardSfxCue[];
type Rect = {x: number; y: number; width: number; height: number};
type Props = PreparedCard & {text: string; accent: string; targetBox: Rect};
const exact = (value: unknown, keys: string[]) => Boolean(value) && typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).sort().join(",") === keys.slice().sort().join(",");

export const prepareCard = (raw: unknown, context: CardContext): Props => {
  if (!exact(raw, ["accent", "targetBox", "text"])) throw Error("converging-arrows exact input required");
  const value = raw as Record<string, unknown>;
  const box = value.targetBox as Rect;
  const presenter = context.sceneInputMetadata?.presenter;
  const subject = context.sceneInputMetadata?.["subject-image"];
  if (typeof value.text !== "string" || value.text.length < 2 || value.text.length > 18 || typeof value.accent !== "string" || !/^#[0-9a-f]{6}$/i.test(value.accent) || !exact(box, ["height", "width", "x", "y"]) || box.x < 0 || box.y < 0 || box.width <= 0 || box.height <= 0 || box.x + box.width > 1200 || box.y + box.height > 750 || presenter?.width !== 540 || presenter?.height !== 600 || subject?.width !== 1200 || subject?.height !== 750 || context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames !== 89) throw Error("converging-arrows content exceeds approved capacity");
  return {text: value.text.trim(), accent: value.accent, targetBox: box};
};

export default function Card({prepared, animationLocalFrame, sceneInputs, namespace}: CardRenderProps<Props>) {
  const progress = Math.min(1, Math.max(0, (animationLocalFrame - 10) / 16));
  const b = prepared.targetBox;
  const x = (b.x + b.width / 2) * 0.75;
  const y = (b.y + b.height / 2) * 0.75;
  const leftEnd = x - b.width * 0.375;
  const rightEnd = x + b.width * 0.375;
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#fff", fontFamily: '"PingFang SC", sans-serif'}}>
    <div style={{position: "absolute", left: 90, top: 220, width: 900, height: 560, overflow: "hidden", borderRadius: 24}}>{sceneInputs["subject-image"]}<svg viewBox="0 0 900 560" style={{position: "absolute", inset: 0}}><defs><marker id={`${namespace}-arrow`} viewBox="0 0 30 30" markerUnits="userSpaceOnUse" markerWidth="30" markerHeight="30" refX="27" refY="15" orient="auto"><path d="M 0 0 L 30 15 L 0 30 Z" fill={prepared.accent} /></marker></defs><path d={`M 55 ${Math.max(55, y - 150)} Q 190 ${y - 80} ${leftEnd} ${y}`} fill="none" stroke={prepared.accent} strokeWidth="9" strokeLinecap="round" markerEnd={`url(#${namespace}-arrow)`} strokeDasharray="900" strokeDashoffset={900 * (1 - progress)} /><path d={`M 845 ${Math.min(505, y + 150)} Q 710 ${y + 80} ${rightEnd} ${y}`} fill="none" stroke={prepared.accent} strokeWidth="9" strokeLinecap="round" markerEnd={`url(#${namespace}-arrow)`} strokeDasharray="900" strokeDashoffset={900 * (1 - progress)} /><circle cx={x} cy={y} r={12 + 7 * Math.sin(Math.min(1, progress) * Math.PI)} fill={prepared.accent} opacity={Math.max(0, (progress - 0.72) / 0.28)} /></svg></div>
    <div style={{position: "absolute", left: 120, top: 810, width: 840, textAlign: "center", color: prepared.accent, fontSize: 44, fontWeight: 700}}>{prepared.text}</div>
    <div style={{position: "absolute", left: 180, top: 930, width: 720, height: 800}}>{sceneInputs.presenter}</div>
  </AbsoluteFill>;
}
