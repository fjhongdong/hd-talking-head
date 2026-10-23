import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./scribble-annotation.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "scribble-annotation", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as string[];
export const sfxCues = contract.sfx_cues as CardSfxCue[];
type Rect = {x: number; y: number; width: number; height: number};
type Props = PreparedCard & {text: string; accent: string; targetBox: Rect};
const exact = (value: unknown, keys: string[]) => Boolean(value) && typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).sort().join(",") === keys.slice().sort().join(",");

export const prepareCard = (raw: unknown, context: CardContext): Props => {
  if (!exact(raw, ["accent", "targetBox", "text"])) throw Error("scribble-annotation exact input required");
  const value = raw as Record<string, unknown>;
  const box = value.targetBox as Rect;
  const presenter = context.sceneInputMetadata?.presenter;
  const subject = context.sceneInputMetadata?.["subject-image"];
  if (typeof value.text !== "string" || value.text.length < 2 || value.text.length > 18 || typeof value.accent !== "string" || !/^#[0-9a-f]{6}$/i.test(value.accent) || !exact(box, ["height", "width", "x", "y"]) || box.x < 0 || box.y < 0 || box.width <= 0 || box.height <= 0 || box.x + box.width > 1200 || box.y + box.height > 750 || presenter?.width !== 540 || presenter?.height !== 600 || subject?.width !== 1200 || subject?.height !== 750 || context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames !== 96) throw Error("scribble-annotation content exceeds approved capacity");
  return {text: value.text.trim(), accent: value.accent, targetBox: box};
};

export default function Card({prepared, animationLocalFrame, sceneInputs, namespace}: CardRenderProps<Props>) {
  const progress = Math.min(1, Math.max(0, (animationLocalFrame - 10) / 20));
  const b = prepared.targetBox;
  const x = 90 + (b.x + b.width / 2) * 0.75;
  const y = 220 + (b.y + b.height / 2) * 0.75;
  const rx = (b.width / 2 + 22) * 0.75;
  const ry = (b.height / 2 + 16) * 0.75;
  const startX = 540;
  const startY = 800;
  const endX = x + (x > 450 ? rx * 0.72 : -rx * 0.72);
  const endY = y + ry * 0.72;
  const controlX = (startX + endX) / 2 + (x > 450 ? 70 : -70);
  const controlY = Math.min(760, endY + 150);
  const arrowProgress = Math.max(0, Math.min(1, (progress - 0.2) / 0.8));
  const currentControlX = startX + (controlX - startX) * arrowProgress;
  const currentControlY = startY + (controlY - startY) * arrowProgress;
  const towardEndX = controlX + (endX - controlX) * arrowProgress;
  const towardEndY = controlY + (endY - controlY) * arrowProgress;
  const currentEndX = currentControlX + (towardEndX - currentControlX) * arrowProgress;
  const currentEndY = currentControlY + (towardEndY - currentControlY) * arrowProgress;
  const visibleCurve = `M ${startX} ${startY} Q ${currentControlX} ${currentControlY} ${currentEndX} ${currentEndY}`;
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#fff", fontFamily: '"PingFang SC", sans-serif'}}>
    <div style={{position: "absolute", left: 90, top: 220, width: 900, height: 560, overflow: "hidden", borderRadius: 24}}>{sceneInputs["subject-image"]}</div>
    <svg viewBox="0 0 1080 1920" style={{position: "absolute", inset: 0, pointerEvents: "none"}}><defs><marker id={`${namespace}-scribble-arrow`} viewBox="0 0 28 28" markerUnits="userSpaceOnUse" markerWidth="28" markerHeight="28" refX="25" refY="14" orient="auto"><path d="M 0 0 L 28 14 L 0 28 Z" fill={prepared.accent} /></marker></defs><ellipse cx={x} cy={y} rx={rx} ry={ry} fill="none" stroke={prepared.accent} strokeWidth="8" strokeLinecap="round" strokeDasharray="1800" strokeDashoffset={1800 * (1 - progress)} transform={`rotate(-2 ${x} ${y})`} /><circle cx={startX} cy={startY} r="7" fill={prepared.accent} opacity={arrowProgress} /><path d={visibleCurve} fill="none" stroke={prepared.accent} strokeWidth="8" strokeLinecap="round" opacity={arrowProgress} markerEnd={arrowProgress >= 0.99 ? `url(#${namespace}-scribble-arrow)` : undefined} /></svg>
    <div style={{position: "absolute", left: 120, top: 810, width: 840, textAlign: "center", color: prepared.accent, fontSize: 44, fontWeight: 700}}>{prepared.text}</div>
    <div style={{position: "absolute", left: 180, top: 930, width: 720, height: 800}}>{sceneInputs.presenter}</div>
  </AbsoluteFill>;
}
