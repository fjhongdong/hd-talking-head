import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import foundationContract from "../foundation-contract.json";

export const BACKDROP_KINDS = foundationContract.backdrops;
export type BackdropKind = "mesh-flow-dark" | "aurora-veil" | "beams-grid" | "spotlight-stage" | "dot-field-wave" | "orbs-dark" | "pastel-mesh-flow" | "paper-grain" | "grid-spot-light" | "iridescent-sheen" | "glass-blobs" | "ink-wash";

export const FRAME_KINDS = foundationContract.frames;
export type FrameKind = "browser-retro" | "magazine" | "film" | "polaroid" | "blueprint" | "laptop" | "stamp" | "hairline";

const fill: React.CSSProperties = {position: "absolute", inset: 0};
const clamp = (value: number) => Math.max(0, Math.min(1, value));

const Orb: React.FC<{
  color: string;
  size: number;
  x: number;
  y: number;
  blur: number;
  opacity?: number;
}> = ({color, size, x, y, blur, opacity = 1}) => (
  <div style={{
    position: "absolute", width: size, height: size, left: x, top: y,
    borderRadius: "50%", background: color, filter: `blur(${blur}px)`, opacity,
  }}/>
);

export const Backdrop: React.FC<{kind: BackdropKind; namespace: string; sourceFrame?: number}> = ({kind, namespace, sourceFrame}) => {
  const currentFrame = useCurrentFrame();
  const frame = sourceFrame ?? currentFrame;
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const wave = (period: number, phase = 0) => Math.sin((t / period) * Math.PI * 2 + phase);
  const grain = <AbsoluteFill style={{
    opacity: kind.includes("dark") || kind === "aurora-veil" ? 0.08 : 0.045,
    mixBlendMode: "overlay",
    backgroundImage: "repeating-radial-gradient(circle at 17% 23%,rgba(255,255,255,.55) 0 1px,transparent 1px 4px)",
    backgroundSize: "19px 17px",
  }}/>;

  let content: React.ReactNode;
  switch (kind) {
    case "mesh-flow-dark":
      content = <AbsoluteFill style={{background: "#07101e", overflow: "hidden"}}>
        <Orb color="#335cff" size={1150} x={-520 + wave(18) * 90} y={-160 + wave(23, 1) * 80} blur={150} opacity={0.48}/>
        <Orb color="#00bfae" size={980} x={420 + wave(21, 2) * 110} y={840 + wave(17) * 90} blur={170} opacity={0.34}/>
        <Orb color="#8338c9" size={900} x={-220 + wave(27, 1) * 80} y={1250 + wave(19) * 70} blur={160} opacity={0.34}/>
      </AbsoluteFill>;
      break;
    case "aurora-veil":
      content = <AbsoluteFill style={{background: "linear-gradient(180deg,#020713,#081426)", overflow: "hidden"}}>
        {[0, 1, 2].map((index) => <div key={index} style={{
          position: "absolute", left: -260, top: 330 + index * 360 + wave(14 + index * 3, index) * 90,
          width: 1600, height: 210, borderRadius: "50%",
          background: index === 0 ? "#39e6bd" : index === 1 ? "#587cff" : "#b164ff",
          filter: "blur(95px)", opacity: 0.2 + index * 0.04,
          transform: `rotate(${-18 + index * 13 + wave(20, index) * 3}deg)`,
        }}/>)
      }</AbsoluteFill>;
      break;
    case "beams-grid":
      content = <AbsoluteFill style={{
        backgroundColor: "#070a12",
        backgroundImage: "linear-gradient(rgba(105,137,255,.11) 1px,transparent 1px),linear-gradient(90deg,rgba(105,137,255,.11) 1px,transparent 1px)",
        backgroundSize: "72px 72px", overflow: "hidden",
      }}>
        <div style={{...fill, background: `linear-gradient(${112 + wave(24) * 5}deg,transparent 23%,rgba(70,120,255,.32) 42%,transparent 58%)`, transform: `translateX(${wave(16) * 120}px)`}}/>
        <div style={{...fill, background: "radial-gradient(circle at 50% 42%,rgba(58,118,255,.22),transparent 45%)"}}/>
      </AbsoluteFill>;
      break;
    case "spotlight-stage":
      content = <AbsoluteFill style={{background: "#07080d"}}>
        <div style={{...fill, background: `radial-gradient(ellipse 58% 42% at ${50 + wave(22) * 4}% 38%,rgba(255,255,255,.24),rgba(92,118,255,.09) 36%,transparent 72%)`}}/>
        <div style={{position: "absolute", left: 90, right: 90, bottom: 210, height: 260, borderRadius: "50%", background: "rgba(112,135,255,.12)", filter: "blur(45px)"}}/>
      </AbsoluteFill>;
      break;
    case "dot-field-wave":
      content = <AbsoluteFill style={{
        backgroundColor: "#090b12",
        backgroundImage: "radial-gradient(circle,rgba(201,220,255,.7) 0 2px,transparent 2.7px)",
        backgroundSize: "42px 42px",
        backgroundPosition: `${wave(18) * 12}px ${wave(21, 1) * 12}px`,
      }}><div style={{...fill, background: `linear-gradient(${118 + wave(20) * 8}deg,#090b12 8%,transparent 46%,#090b12 88%)`}}/></AbsoluteFill>;
      break;
    case "orbs-dark":
      content = <AbsoluteFill style={{background: "#090b14", overflow: "hidden"}}>
        <Orb color="#3866ff" size={780} x={-260 + wave(25) * 110} y={120 + wave(18, 1) * 90} blur={95} opacity={0.46}/>
        <Orb color="#a14cff" size={660} x={500 + wave(31, 1) * 120} y={720 + wave(22) * 100} blur={110} opacity={0.38}/>
        <Orb color="#25c9b5" size={620} x={40 + wave(28, 2) * 100} y={1320 + wave(19) * 80} blur={105} opacity={0.3}/>
      </AbsoluteFill>;
      break;
    case "pastel-mesh-flow":
      content = <AbsoluteFill style={{background: "#fafafd", overflow: "hidden"}}>
        <Orb color="#86b6ff" size={980} x={-430 + wave(21) * 90} y={-190} blur={165} opacity={0.52}/>
        <Orb color="#ffb0cc" size={900} x={480 + wave(24, 1) * 80} y={430} blur={170} opacity={0.47}/>
        <Orb color="#a99aff" size={880} x={-300} y={1080 + wave(26, 2) * 80} blur={170} opacity={0.42}/>
        <Orb color="#8de5cc" size={720} x={500} y={1390 + wave(19) * 60} blur={150} opacity={0.4}/>
      </AbsoluteFill>;
      break;
    case "paper-grain":
      content = <AbsoluteFill style={{
        backgroundColor: "#f4efe6",
        backgroundImage: "repeating-linear-gradient(7deg,rgba(90,65,35,.025) 0 1px,transparent 1px 7px),radial-gradient(circle at 18% 12%,#fffaf0,transparent 44%)",
      }}><div style={{...fill, opacity: 0.16, background: "radial-gradient(circle at 75% 70%,#c9b697,transparent 52%)"}}/></AbsoluteFill>;
      break;
    case "grid-spot-light":
      content = <AbsoluteFill style={{
        backgroundColor: "#f6f7fa",
        backgroundImage: "linear-gradient(#dfe3ea 1px,transparent 1px),linear-gradient(90deg,#dfe3ea 1px,transparent 1px)",
        backgroundSize: "64px 64px",
      }}><div style={{...fill, background: `radial-gradient(circle at ${52 + wave(19) * 5}% ${42 + wave(23, 1) * 4}%,rgba(255,255,255,.96),rgba(226,232,244,.18) 40%,rgba(205,213,228,.42) 85%)`}}/></AbsoluteFill>;
      break;
    case "iridescent-sheen":
      content = <AbsoluteFill style={{
        background: `conic-gradient(from ${105 + t * 2}deg at 48% 46%,#f8fbff,#dff4ff,#efe2ff,#ffe8ec,#e2fff5,#f8fbff)`,
      }}><div style={{...fill, backdropFilter: "blur(50px)", background: "rgba(255,255,255,.36)"}}/></AbsoluteFill>;
      break;
    case "glass-blobs":
      content = <AbsoluteFill style={{background: "linear-gradient(160deg,#eef4ff,#fff7fb 52%,#edfff9)", overflow: "hidden"}}>
        <Orb color="#6495ff" size={720} x={-260 + wave(22) * 80} y={170} blur={75} opacity={0.34}/>
        <Orb color="#ff8db8" size={620} x={530} y={620 + wave(27, 1) * 100} blur={75} opacity={0.32}/>
        <Orb color="#62d9bc" size={650} x={80 + wave(24, 2) * 90} y={1330} blur={85} opacity={0.3}/>
        <div style={{position: "absolute", inset: 100, border: "1px solid rgba(255,255,255,.72)", borderRadius: 90, background: "rgba(255,255,255,.12)", boxShadow: "inset 0 0 80px rgba(255,255,255,.28)"}}/>
      </AbsoluteFill>;
      break;
    case "ink-wash":
      content = <AbsoluteFill style={{background: "#f5f0e4", overflow: "hidden"}}>
        <Orb color="#20252d" size={1050} x={-500 + wave(30) * 70} y={-160} blur={145} opacity={0.16}/>
        <Orb color="#46505b" size={900} x={480 + wave(26, 1) * 80} y={680} blur={160} opacity={0.12}/>
        <div style={{position: "absolute", left: -120, right: -120, bottom: 180, height: 520, background: "linear-gradient(165deg,transparent,#242a32 48%,transparent 72%)", filter: "blur(90px)", opacity: 0.12, transform: `translateX(${wave(32) * 70}px)`}}/>
      </AbsoluteFill>;
      break;
  }
  return <AbsoluteFill data-foundation="backdrop" data-kind={kind} data-namespace={namespace}>{content}{grain}</AbsoluteFill>;
};

const PADS: Record<FrameKind, {left: number; right: number; top: number; bottom: number}> = {
  "browser-retro": {left: 10, right: 10, top: 82, bottom: 28},
  magazine: {left: 0, right: 0, top: 46, bottom: 42},
  film: {left: 58, right: 58, top: 70, bottom: 78},
  polaroid: {left: 30, right: 30, top: 30, bottom: 126},
  blueprint: {left: 50, right: 50, top: 50, bottom: 50},
  laptop: {left: 46, right: 46, top: 34, bottom: 72},
  stamp: {left: 34, right: 34, top: 34, bottom: 34},
  hairline: {left: 18, right: 18, top: 18, bottom: 18},
};

export const frameBox = (kind: FrameKind, width: number, height: number) => {
  const pad = PADS[kind];
  return {
    width: width + pad.left + pad.right,
    height: height + pad.top + pad.bottom,
    x: pad.left,
    y: pad.top,
  };
};

export const ThemeFrame: React.FC<{
  kind: FrameKind;
  width: number;
  height: number;
  namespace: string;
  sourceFrame?: number;
  children: React.ReactNode;
}> = ({kind, width, height, namespace, sourceFrame, children}) => {
  const currentFrame = useCurrentFrame();
  const frame = sourceFrame ?? currentFrame;
  const {fps} = useVideoConfig();
  const pad = PADS[kind];
  const box = frameBox(kind, width, height);
  const draw = clamp(frame / (fps * 0.8));
  const content = <div style={{
    position: "absolute", left: pad.left, top: pad.top, width, height,
    overflow: "hidden", background: "#111", borderRadius: kind === "hairline" ? 18 : 2,
  }}>{children}</div>;
  let chrome: React.ReactNode;

  switch (kind) {
    case "browser-retro":
      chrome = <div style={{...fill, background: "#d7d7d7", border: "2px solid #222", boxShadow: "0 22px 60px rgba(0,0,0,.22)"}}>
        <div style={{height: 32, borderBottom: "2px solid #333", background: "repeating-linear-gradient(#eee 0 2px,#c5c5c5 2px 4px)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, color: "#111"}}>MEDIA</div>
        <div style={{position: "absolute", left: 12, right: 12, top: 42, height: 27, border: "1px solid #555", background: "white"}}/>
      </div>;
      break;
    case "magazine":
      chrome = <><div style={{position: "absolute", top: 12, left: 0, fontSize: 18, letterSpacing: 4, color: "#1d1d1f", opacity: draw}}>FIG. 01 / VISUAL RECORD</div><div style={{position: "absolute", top: 38, left: 0, width: `${draw * 100}%`, height: 2, background: "#1d1d1f"}}/><div style={{position: "absolute", right: 0, bottom: 8, fontFamily: "Georgia,serif", fontSize: 20}}>024</div></>;
      break;
    case "film": {
      const holes = Array.from({length: 16}, (_, index) => index);
      chrome = <div style={{...fill, background: "#151515"}}>{[16, box.height - 44].flatMap((top) => holes.map((index) => <span key={`${top}-${index}`} style={{position: "absolute", left: 18 + index * ((box.width - 44) / 15), top, width: 22, height: 28, borderRadius: 4, background: "#f4f0e8"}}/>))}<div style={{position: "absolute", left: pad.left, bottom: 18, color: "#e4a43b", fontFamily: "monospace", letterSpacing: 3}}>24 · 400TX</div></div>;
      break;
    }
    case "polaroid":
      chrome = <div style={{...fill, background: "#fff", border: "1px solid #e5e5e5", boxShadow: "0 24px 70px rgba(0,0,0,.22)"}}/>;
      break;
    case "blueprint":
      chrome = <svg viewBox={`0 0 ${box.width} ${box.height}`} style={{...fill, overflow: "visible"}}><rect x="20" y="20" width={box.width - 40} height={box.height - 40} fill="none" stroke="#245a9b" strokeWidth="2" pathLength="1" strokeDasharray="1 1" strokeDashoffset={1 - draw}/><rect x={pad.left} y={pad.top} width={width} height={height} fill="none" stroke="#245a9b"/><path d={`M ${pad.left} 10 H ${pad.left + width} M ${pad.left} 2 V 18 M ${pad.left + width} 2 V 18`} stroke="#245a9b" fill="none"/><text x={box.width / 2} y="9" textAnchor="middle" fill="#245a9b" fontFamily="monospace" fontSize="12">760 PX · SCALE 1:1</text></svg>;
      break;
    case "laptop":
      chrome = <><div style={{position: "absolute", left: 20, right: 20, top: 0, height: height + 58, borderRadius: 24, background: "#202124", boxShadow: "0 22px 70px rgba(0,0,0,.28)"}}><span style={{position: "absolute", width: 8, height: 8, left: "50%", top: 13, borderRadius: "50%", background: "#050505"}}/></div><div style={{position: "absolute", left: 0, right: 0, bottom: 10, height: 34, borderRadius: "0 0 18px 18px", background: "linear-gradient(#4a4b4e,#26272a)"}}/></>;
      break;
    case "stamp":
      chrome = <div style={{position: "absolute", inset: 8, background: "#fff", boxShadow: "0 16px 50px rgba(0,0,0,.15)", border: "12px dotted #eef0f4", outline: "22px solid #fff"}}/>;
      break;
    case "hairline":
      chrome = <><div style={{...fill, border: "1px solid rgba(20,25,35,.28)", borderRadius: 30, opacity: draw}}/><svg viewBox={`0 0 ${box.width} ${box.height}`} style={{...fill}}><path d={`M0 48V24Q0 0 24 0H48 M${box.width - 48} 0H${box.width - 24}Q${box.width} 0 ${box.width} 24V48 M${box.width} ${box.height - 48}V${box.height - 24}Q${box.width} ${box.height} ${box.width - 24} ${box.height}H${box.width - 48} M48 ${box.height}H24Q0 ${box.height} 0 ${box.height - 24}V${box.height - 48}`} fill="none" stroke="#202630" strokeWidth="3" pathLength="1" strokeDasharray="1 1" strokeDashoffset={1 - draw}/></svg></>;
      break;
  }
  return <div data-foundation="frame" data-kind={kind} data-namespace={namespace} style={{position: "relative", width: box.width, height: box.height}}>
    <div style={{...fill, transform: kind === "polaroid" ? "rotate(-1.4deg)" : undefined}}>{chrome}{content}</div>
  </div>;
};
