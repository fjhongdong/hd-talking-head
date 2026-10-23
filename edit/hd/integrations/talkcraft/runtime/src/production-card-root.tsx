import React from "react";
import {AbsoluteFill, Audio, Composition, Img, Loop, OffthreadVideo, Sequence, registerRoot, staticFile, useCurrentFrame} from "remotion";
import type {ProductionBrief, ProductionInputAdapter, ProductionProps, StagedMedia} from "./production-input";

export type CardContext = {width: 1080; height: 1920; fps: 24; durationInFrames: number; sceneInputMetadata?: Readonly<Record<string, {width: number; height: number}>>};
export type PreparedCard = Record<string, unknown>;
export type CandidateScene = "portrait-stack" | "full-frame";
export type CandidateRect = {x: number; y: number; width: number; height: number};
export type CardSfxCue = {cueId: string; frame: number; anchor: string; name: string; assetKey: string; volume: number; playbackRate: number};
export type CardSceneInput = {slot: string; kind: "presenter-on-white" | "presenter-alpha" | "video-cover" | "image-contain"; src: string; sha256: string; width?: number; height?: number};
export type CardRenderProps<T extends PreparedCard = PreparedCard> = {
  prepared: T;
  animationLocalFrame: number;
  namespace: string;
  sceneInputs: Readonly<Record<string, React.ReactNode>>;
};
export type CardModule<T extends PreparedCard = PreparedCard> = {
  cardMeta: {card_id: string; api_version: 1};
  candidateScene: CandidateScene;
  sfxCues: ReadonlyArray<CardSfxCue>;
  sceneInputSlots?: ReadonlyArray<string>;
  prepareCard: (raw: unknown, context: CardContext) => T;
  default: React.FC<CardRenderProps<T>>;
};
export type CandidateProps = {
  cardId: string;
  caseId: string;
  raw: unknown;
  durationInFrames: number;
  scene: {layout: CandidateScene; presenterRect: CandidateRect | null};
  presenter: {src: string; sha256: string} | null;
  sceneInputs?: Array<CardSceneInput>;
  sfx: Array<CardSfxCue & {src: string; sha256: string}>;
};
type ProductionRequestProps = {brief: unknown; stagedMedia: Array<{mediaRef: string; publicSrc: string}>};

const ID = /^[a-z][a-z0-9-]{0,63}$/;
const PRODUCTION_SRC = /^production\/[0-9a-f]{64}\.(?:jpe?g|mov|mp4|png|webm|webp)$/;

export const registerBriefProductionCard = <T extends PreparedCard>(card: CardModule<T>, adapt: ProductionInputAdapter) => {
  if (!ID.test(card.cardMeta?.card_id ?? "") || card.cardMeta.api_version !== 1 ||
      card.candidateScene !== "full-frame" || typeof card.prepareCard !== "function" ||
      typeof card.default !== "function") {
    throw new Error("production card module ABI is invalid");
  }
  const Production: React.FC<ProductionProps> = (props) => {
    if (props.cardId !== card.cardMeta.card_id) throw new Error("production card identity is invalid");
    const slots = card.sceneInputSlots ?? [];
    if (!Array.isArray(props.sceneInputs) || props.sceneInputs.length !== slots.length ||
        JSON.stringify(props.sceneInputs.map((item) => item.slot)) !== JSON.stringify(slots) ||
        props.sceneInputs.some((item) => !ID.test(item.slot) ||
          !new Set(["presenter-on-white", "presenter-alpha", "video-cover", "image-contain"]).has(item.kind) ||
          !PRODUCTION_SRC.test(item.src) || !Number.isInteger(item.width) || !Number.isInteger(item.height) ||
          item.width <= 0 || item.height <= 0)) {
      throw new Error("production scene inputs differ from the card contract");
    }
    const sceneInputMetadata = Object.fromEntries(props.sceneInputs.map((item) => [item.slot, {width: item.width, height: item.height}]));
    const prepared = card.prepareCard(props.raw, {width: 1080, height: 1920, fps: 24, durationInFrames: props.durationInFrames, sceneInputMetadata});
    const Card = card.default;
    const sceneInputs = Object.fromEntries(props.sceneInputs.map((item) => [item.slot,
      item.kind === "image-contain"
        ? <AbsoluteFill><Img src={staticFile(item.src)} style={{width: "100%", height: "100%", objectFit: "contain"}}/></AbsoluteFill>
        : <AbsoluteFill style={{background: item.kind === "video-cover" || item.kind === "presenter-on-white" ? "#ffffff" : "transparent"}}>
          <OffthreadVideo src={staticFile(item.src)} muted transparent={item.kind === "presenter-alpha" || item.kind === "presenter-on-white"} style={{width: "100%", height: "100%", objectFit: item.kind === "video-cover" ? "cover" : "contain", objectPosition: "50% 100%"}}/>
        </AbsoluteFill>
    ]));
    return <AbsoluteFill style={{background: "#ffffff", overflow: "hidden"}}>
      <Card prepared={prepared} animationLocalFrame={useCurrentFrame()} namespace={`${props.cardId}-production`} sceneInputs={sceneInputs}/>
    </AbsoluteFill>;
  };
  const Request: React.FC<ProductionRequestProps> = (request) => <Production {...adapt(request.brief as ProductionBrief, request.stagedMedia as StagedMedia[])}/>;
  const Root: React.FC = () => <Composition
    id="TalkCraftProductionCard"
    component={Request}
    width={1080}
    height={1920}
    fps={24}
    durationInFrames={72}
    defaultProps={{brief: {}, stagedMedia: []}}
    calculateMetadata={({props}) => {
      const durationInFrames = adapt((props as ProductionRequestProps).brief as ProductionBrief, (props as ProductionRequestProps).stagedMedia as StagedMedia[]).durationInFrames;
      if (!Number.isInteger(durationInFrames) || durationInFrames < 1 || durationInFrames > 720) {
        throw new Error("production duration is invalid");
      }
      return {durationInFrames};
    }}
  />;
  registerRoot(Root);
};

export const registerProductionCard = <T extends PreparedCard>(card: CardModule<T>) => {
  if (!ID.test(card.cardMeta?.card_id ?? "") || card.cardMeta.api_version !== 1 ||
      !new Set<CandidateScene>(["portrait-stack", "full-frame"]).has(card.candidateScene) ||
      typeof card.prepareCard !== "function" || typeof card.default !== "function" || !Array.isArray(card.sfxCues)) {
    throw new Error("production card module ABI is invalid");
  }
  const Candidate: React.FC<CandidateProps> = (props) => {
    if (props.cardId !== card.cardMeta.card_id || !ID.test(props.caseId)) throw new Error("candidate card identity is invalid");
    const rect = props.scene?.presenterRect;
    const validRect = rect !== null && typeof rect === "object" && Object.keys(rect).sort().join(",") === "height,width,x,y" &&
      [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) && rect.x >= 0 && rect.y >= 0 && rect.width > 0 && rect.height > 0 &&
      rect.x + rect.width <= 1080 && rect.y + rect.height <= 1920;
    if (props.scene?.layout !== card.candidateScene) throw new Error("candidate scene differs from the card contract");
    if (props.scene.layout === "portrait-stack" && (!validRect || props.presenter === null || typeof props.presenter !== "object" ||
        Object.keys(props.presenter).sort().join(",") !== "sha256,src" ||
        !props.presenter.src.startsWith("qualification/") || !/^[0-9a-f]{64}$/.test(props.presenter.sha256))) {
      throw new Error("candidate presenter fixture is invalid");
    }
    if (props.scene.layout === "full-frame" && (props.presenter !== null || rect !== null)) throw new Error("full-frame candidate must not inject a presenter");
    const sceneInputSlots = card.sceneInputSlots ?? [];
    const sceneInputAssets = props.sceneInputs ?? [];
    if (!Array.isArray(sceneInputSlots) || sceneInputSlots.length > 8 || sceneInputSlots.some((slot) => !ID.test(slot)) || new Set(sceneInputSlots).size !== sceneInputSlots.length ||
        !Array.isArray(sceneInputAssets) || sceneInputAssets.length !== sceneInputSlots.length || sceneInputAssets.some((asset) =>
          asset === null || typeof asset !== "object" ||
        !ID.test(asset.slot) || !new Set(["presenter-on-white", "presenter-alpha", "video-cover", "image-contain"]).has(asset.kind) ||
          !asset.src.startsWith("qualification/") || !/^[0-9a-f]{64}$/.test(asset.sha256) ||
          (asset.kind === "image-contain" || asset.kind === "presenter-alpha"
            ? Object.keys(asset).sort().join(",") !== "height,kind,sha256,slot,src,width" || !Number.isInteger(asset.width) || !Number.isInteger(asset.height) || (asset.width ?? 0) <= 0 || (asset.height ?? 0) <= 0
            : Object.keys(asset).sort().join(",") !== "kind,sha256,slot,src")
        ) || JSON.stringify(sceneInputAssets.map((asset) => asset.slot)) !== JSON.stringify(sceneInputSlots)) {
      throw new Error("candidate scene inputs differ from the card contract");
    }
    if (!Array.isArray(props.sfx) || props.sfx.length > 8 || props.sfx.some((cue) =>
      cue === null || typeof cue !== "object" || Object.keys(cue).sort().join(",") !== "anchor,assetKey,cueId,frame,name,playbackRate,sha256,src,volume" ||
      !ID.test(cue.cueId) || !ID.test(cue.anchor) || !ID.test(cue.name) || !ID.test(cue.assetKey) ||
      !Number.isInteger(cue.frame) || cue.frame < 0 || cue.frame >= props.durationInFrames ||
      !cue.src.startsWith("qualification/") || !/^[0-9a-f]{64}$/.test(cue.sha256) || !Number.isFinite(cue.volume) || cue.volume <= 0 || cue.volume > 1 ||
      !Number.isFinite(cue.playbackRate) || cue.playbackRate < 0.5 || cue.playbackRate > 2
    )) throw new Error("candidate SFX cues are invalid");
    if (new Set(props.sfx.map((cue) => cue.cueId)).size !== props.sfx.length ||
        JSON.stringify(props.sfx.map(({src: _src, sha256: _sha256, ...cue}) => cue)) !== JSON.stringify(card.sfxCues)) {
      throw new Error("candidate SFX cues differ from the card action contract");
    }
    const sceneInputMetadata = Object.fromEntries(sceneInputAssets.filter((asset) => asset.kind === "image-contain" || asset.kind === "presenter-alpha").map((asset) => [asset.slot, {width: asset.width as number, height: asset.height as number}]));
    const context: CardContext = {width: 1080, height: 1920, fps: 24, durationInFrames: props.durationInFrames, sceneInputMetadata};
    const prepared = card.prepareCard(props.raw, context);
    const Card = card.default;
    const sceneInputs = Object.fromEntries(sceneInputAssets.map((asset) => [asset.slot,
      asset.kind === "presenter-on-white"
        ? <AbsoluteFill style={{background: "#ffffff"}}><Loop durationInFrames={312}><OffthreadVideo src={staticFile(asset.src)} muted transparent style={{width: "100%", height: "100%", objectFit: "contain", objectPosition: "50% 100%"}}/></Loop></AbsoluteFill>
        : asset.kind === "presenter-alpha"
          ? <AbsoluteFill><Loop durationInFrames={312}><OffthreadVideo src={staticFile(asset.src)} muted transparent style={{width: "100%", height: "100%", objectFit: "contain", objectPosition: "50% 100%"}}/></Loop></AbsoluteFill>
        : asset.kind === "video-cover"
          ? <AbsoluteFill style={{background: "#ffffff"}}><Loop durationInFrames={240}><OffthreadVideo src={staticFile(asset.src)} muted style={{width: "100%", height: "100%", objectFit: "cover"}}/></Loop></AbsoluteFill>
          : <AbsoluteFill><Img src={staticFile(asset.src)} style={{width: "100%", height: "100%", objectFit: "contain"}}/></AbsoluteFill>
    ]));
    return <AbsoluteFill style={{background: "#ffffff", overflow: "hidden"}}>
      {props.scene.layout === "portrait-stack" && props.presenter && rect ? <div data-talkcraft-plane="subject.world" data-talkcraft-layout="portrait-stack" style={{position: "absolute", left: rect.x, top: rect.y, width: rect.width, height: rect.height, overflow: "hidden"}}>
        <Loop durationInFrames={312}>
          <OffthreadVideo src={staticFile(props.presenter.src)} muted transparent style={{position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain"}}/>
        </Loop>
      </div> : null}
      <div data-talkcraft-plane={props.scene.layout === "full-frame" ? "background.world" : "text.screen"}><Card prepared={prepared} animationLocalFrame={useCurrentFrame()} namespace={`${props.cardId}-${props.caseId}`} sceneInputs={sceneInputs}/></div>
      {props.sfx.map((cue, index) => <Sequence key={`${cue.name}-${cue.frame}-${index}`} from={cue.frame} layout="none">
        <Audio src={staticFile(cue.src)} volume={cue.volume} playbackRate={cue.playbackRate}/>
      </Sequence>)}
    </AbsoluteFill>;
  };
  const Root: React.FC = () => <Composition
    id="TalkCraftQualificationCandidate"
    component={Candidate}
    width={1080}
    height={1920}
    fps={24}
    durationInFrames={72}
    defaultProps={{cardId: card.cardMeta.card_id, caseId: "invalid", raw: null, durationInFrames: 72, scene: {layout: card.candidateScene, presenterRect: null}, presenter: null, sceneInputs: [], sfx: []}}
    calculateMetadata={({props}) => {
      const durationInFrames = Number((props as CandidateProps).durationInFrames);
      if (!Number.isInteger(durationInFrames) || durationInFrames < 1 || durationInFrames > 720) {
        throw new Error("candidate duration is invalid");
      }
      const sceneInputMetadata = Object.fromEntries(((props as CandidateProps).sceneInputs ?? []).filter((asset) => asset.kind === "image-contain" || asset.kind === "presenter-alpha").map((asset) => [asset.slot, {width: asset.width as number, height: asset.height as number}]));
      card.prepareCard((props as CandidateProps).raw, {width: 1080, height: 1920, fps: 24, durationInFrames, sceneInputMetadata});
      return {durationInFrames};
    }}
  />;
  registerRoot(Root);
};
