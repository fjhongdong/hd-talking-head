import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./scanline-annotate.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id: "scanline-annotate", api_version: 1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as string[];
export const sfxCues = contract.sfx_cues as CardSfxCue[];
type Rect = {x: number; y: number; width: number; height: number};
type Props = PreparedCard & {title: string; detail: string; accent: string; targetBox: Rect};
const exact = (value: unknown, keys: string[]) => Boolean(value) && typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).sort().join(",") === keys.slice().sort().join(",");

export const prepareCard = (raw: unknown, context: CardContext): Props => {
  if (!exact(raw, ["accent", "detail", "targetBox", "title"])) throw Error("scanline-annotate exact input required");
  const value = raw as Record<string, unknown>;
  const box = value.targetBox as Rect;
  const presenter = context.sceneInputMetadata?.presenter;
  const subject = context.sceneInputMetadata?.["subject-image"];
  if (typeof value.title !== "string" || value.title.trim().length < 2 || value.title.trim().length > 18 || typeof value.detail !== "string" || value.detail.trim().length < 2 || value.detail.trim().length > 36 || typeof value.accent !== "string" || !/^#[0-9a-f]{6}$/i.test(value.accent) || !exact(box, ["height", "width", "x", "y"]) || ![box.x, box.y, box.width, box.height].every(Number.isFinite) || box.x < 0 || box.y < 0 || box.width <= 0 || box.height <= 0 || box.x + box.width > 1200 || box.y + box.height > 750 || presenter?.width !== 540 || presenter?.height !== 600 || subject?.width !== 1200 || subject?.height !== 750 || context.width !== 1080 || context.height !== 1920 || context.fps !== 24 || context.durationInFrames !== 180) throw Error("scanline-annotate content exceeds approved capacity");
  return {title: value.title.trim(), detail: value.detail.trim(), accent: value.accent, targetBox: box};
};

export default function Card({prepared, animationLocalFrame, sceneInputs, namespace}: CardRenderProps<Props>) {
  const scan = Math.min(1, Math.max(0, (animationLocalFrame - 8) / 88));
  const scanY = -24 + 608 * scan;
  const box = {x: prepared.targetBox.x * 0.75, y: prepared.targetBox.y * 0.75, width: prepared.targetBox.width * 0.75, height: prepared.targetBox.height * 0.75};
  const reached = Math.min(1, Math.max(0, (scanY - box.y - box.height) / 28));
  const frameScale = 1.75 - 0.75 * reached;
  const label = Math.min(1, Math.max(0, (scanY - box.y - box.height - 20) / 24));
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background: "#fff", fontFamily: '"PingFang SC", sans-serif'}}>
    <div style={{position: "absolute", left: 90, top: 170, width: 900, height: 560, overflow: "hidden", borderRadius: 24}}>
      {sceneInputs["subject-image"]}
      <div style={{position: "absolute", left: 0, right: 0, top: scanY, height: 4, background: `linear-gradient(90deg,transparent,${prepared.accent} 18%,${prepared.accent} 82%,transparent)`, boxShadow: `0 0 18px ${prepared.accent}`}} />
      <div style={{position: "absolute", left: box.x, top: box.y, width: box.width, height: box.height, border: `4px solid ${prepared.accent}`, transform: `scale(${frameScale})`, opacity: reached, transformOrigin: "center", borderRadius: 10}} />
    </div>
    <div style={{position: "absolute", left: 100, top: 770, width: 880, textAlign: "center", opacity: label, transform: `translateY(${(1 - label) * 18}px)`}}><div style={{fontSize: 42, fontWeight: 700}}>{prepared.title}</div><div style={{fontSize: 28, color: "#666", marginTop: 10}}>{prepared.detail}</div></div>
    <div style={{position: "absolute", left: 180, top: 1050, width: 720, height: 800}}>{sceneInputs.presenter}</div>
  </AbsoluteFill>;
}
