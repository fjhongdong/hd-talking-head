import React, {createContext, useContext} from "react";
import {AbsoluteFill, useVideoConfig} from "remotion";
import contract from "../scene-foundation-contract.json";

const TOKEN_KEYS = ["canvas", "canvas_alt", "ink", "ink_muted", "hairline", "accent", "positive", "negative", "marker"] as const;
export type ThemeTokens = Record<(typeof TOKEN_KEYS)[number], string>;
export type ThemeInput = {preset: "light" | "dark"} | {custom: ThemeTokens};
export type Rect = {x: number; y: number; width: number; height: number};
export type SceneLayout = {
  activeSubjectGroups: number;
  heroGroups: number;
  demotedGroups: number;
  emptyQuadrant: "top-left" | "top-right" | "bottom-left" | "bottom-right";
  textBounds: Rect[];
  decorationBounds: Rect[];
  presenterSafeZone: Rect | null;
};
export type SceneCamera = {direction: "push" | "pull"; peakScale: number};

const ThemeContext = createContext<ThemeTokens>(contract.themes.light);
const CameraContext = createContext<{owner: string; scale: number} | null>(null);

export const useSceneTheme = () => useContext(ThemeContext);
export const useSceneCamera = () => useContext(CameraContext);

const finite = (value: number) => Number.isFinite(value);
const validRect = (rect: Rect) => finite(rect.x) && finite(rect.y) && finite(rect.width) && finite(rect.height) &&
  rect.width > 0 && rect.height > 0 && rect.x >= 0 && rect.y >= 0 &&
  rect.x + rect.width <= contract.canvas.width && rect.y + rect.height <= contract.canvas.height;
const intersects = (left: Rect, right: Rect) => left.x < right.x + right.width && left.x + left.width > right.x &&
  left.y < right.y + right.height && left.y + left.height > right.y;

export const resolveTheme = (input: ThemeInput): ThemeTokens => {
  if ("preset" in input) {
    const theme = contract.themes[input.preset];
    if (!theme) throw new Error("unknown scene theme preset");
    return theme;
  }
  const keys = Object.keys(input.custom).sort();
  if (keys.length !== TOKEN_KEYS.length || !TOKEN_KEYS.every((key, index) => [...TOKEN_KEYS].sort()[index] === keys[index])) {
    throw new Error("custom scene theme must provide exactly nine tokens");
  }
  if (TOKEN_KEYS.some((key) => typeof input.custom[key] !== "string" || input.custom[key].trim() === "")) {
    throw new Error("custom scene theme tokens must be non-empty strings");
  }
  return input.custom;
};

export const validateSceneLayout = (layout: SceneLayout) => {
  const whole = [
    ...layout.textBounds.map((rect) => ({kind: "text", rect})),
    ...layout.decorationBounds.map((rect) => ({kind: "decoration", rect})),
    ...(layout.presenterSafeZone === null ? [] : [{kind: "presenter", rect: layout.presenterSafeZone}]),
  ];
  if (whole.some(({rect}) => !validRect(rect))) throw new Error("scene layout contains an invalid rectangle");
  if (
    !Number.isInteger(layout.activeSubjectGroups) || layout.activeSubjectGroups < 1 || layout.activeSubjectGroups > contract.budgets.active_subject_groups_max ||
    !Number.isInteger(layout.heroGroups) || layout.heroGroups < 0 || layout.heroGroups > contract.budgets.hero_groups_max ||
    !Number.isInteger(layout.demotedGroups) || layout.demotedGroups < 0 || layout.demotedGroups > contract.budgets.demoted_groups_max ||
    !["top-left", "top-right", "bottom-left", "bottom-right"].includes(layout.emptyQuadrant)
  ) throw new Error("scene layout budget is invalid");
  if (layout.textBounds.some((rect) => rect.y + rect.height > contract.safe_lines.critical_text_max_y)) {
    throw new Error("critical text crosses the soft-safe line");
  }
  if (layout.decorationBounds.some((rect) => rect.y + rect.height > contract.safe_lines.decoration_max_y)) {
    throw new Error("decoration crosses the hard-safe line");
  }
  if (layout.presenterSafeZone !== null && [...layout.textBounds, ...layout.decorationBounds].some((rect) => intersects(rect, layout.presenterSafeZone!))) {
    throw new Error("scene layout intersects the presenter safe zone");
  }
};

export const cameraScaleAt = ({direction, peakScale}: SceneCamera, sourceFrame: number, durationFrames: number, fps: number) => {
  if (!contract.camera.directions.includes(direction) || !finite(peakScale) || peakScale < contract.camera.peak_scale_min || peakScale > contract.camera.peak_scale_max) {
    throw new Error("scene camera contract is invalid");
  }
  if (!Number.isInteger(sourceFrame) || sourceFrame < 0 || !Number.isInteger(durationFrames) || durationFrames < 2 || sourceFrame >= durationFrames || fps !== contract.canvas.fps) {
    throw new Error("scene camera time is invalid");
  }
  const endKey = durationFrames + contract.camera.end_overshoot_frames;
  const raw = sourceFrame / endKey;
  const progress = (1 - Math.cos(Math.PI * raw)) / 2;
  return direction === "push"
    ? 1 + (peakScale - 1) * progress
    : peakScale - (peakScale - 1) * progress;
};

const CameraRig: React.FC<{
  owner: string;
  camera: SceneCamera;
  sourceFrame: number;
  durationFrames: number;
  children: React.ReactNode;
}> = ({owner, camera, sourceFrame, durationFrames, children}) => {
  if (useContext(CameraContext) !== null) throw new Error("a scene cannot contain a second camera owner");
  const {fps} = useVideoConfig();
  const scale = cameraScaleAt(camera, sourceFrame, durationFrames, fps);
  return <CameraContext.Provider value={{owner, scale}}>
    <AbsoluteFill style={{transform: `scale(${scale})`, transformOrigin: "540px 960px"}}>{children}</AbsoluteFill>
  </CameraContext.Provider>;
};

const DebugOverlay: React.FC<{layout: SceneLayout}> = ({layout}) => {
  const presenter = layout.presenterSafeZone;
  return <AbsoluteFill style={{pointerEvents: "none", zIndex: 99}}>
    <div style={{position: "absolute", left: 0, right: 0, top: contract.safe_lines.critical_text_max_y, borderTop: "2px solid rgba(255,140,0,.8)"}}/>
    <div style={{position: "absolute", left: 0, right: 0, top: contract.safe_lines.decoration_max_y, borderTop: "2px solid rgba(255,0,0,.8)"}}/>
    {presenter && <div style={{position: "absolute", left: presenter.x, top: presenter.y, width: presenter.width, height: presenter.height, border: "3px solid rgba(255,0,120,.8)", background: "rgba(255,0,120,.06)"}}/>}
  </AbsoluteFill>;
};

export const SceneFoundation: React.FC<{
  sceneId: string;
  theme: ThemeInput;
  camera: SceneCamera;
  sourceFrame: number;
  durationFrames: number;
  layout: SceneLayout;
  background: {screen: React.ReactNode; world: React.ReactNode};
  subject: React.ReactNode;
  text: React.ReactNode;
  debug?: boolean;
}> = ({sceneId, theme, camera, sourceFrame, durationFrames, layout, background, subject, text, debug = false}) => {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(sceneId)) throw new Error("sceneId is invalid");
  if (!Object.hasOwn(background, "screen") || !Object.hasOwn(background, "world") || subject === undefined || text === undefined) {
    throw new Error("all three scene planes must be assigned explicitly");
  }
  validateSceneLayout(layout);
  const tokens = resolveTheme(theme);
  return <ThemeContext.Provider value={tokens}>
    <AbsoluteFill data-scene-id={sceneId} style={{background: tokens.canvas, color: tokens.ink, overflow: "hidden"}}>
      <AbsoluteFill data-plane="background.screen">{background.screen}</AbsoluteFill>
      <CameraRig owner={sceneId} camera={camera} sourceFrame={sourceFrame} durationFrames={durationFrames}>
        <AbsoluteFill data-plane="background.world">{background.world}</AbsoluteFill>
        <AbsoluteFill data-plane="subject.world">{subject}</AbsoluteFill>
      </CameraRig>
      <AbsoluteFill data-plane="text.screen">{text}</AbsoluteFill>
      {debug && <DebugOverlay layout={layout}/>} 
    </AbsoluteFill>
  </ThemeContext.Provider>;
};
