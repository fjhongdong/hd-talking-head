import React from "react";
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";

export type ProbeMode = "text" | "data" | "annotation" | "transition";

export type ProbeProps = {
  mode: ProbeMode;
  alpha: boolean;
  title: string;
  value: number;
  namespace: string;
};

const font = "PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif";

export const MechanismProbe: React.FC<ProbeProps> = ({mode, alpha, title, value, namespace}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const enter = spring({fps, frame, config: {damping: 18, stiffness: 140, mass: 0.8}});
  const progress = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const base: React.CSSProperties = {
    background: alpha ? "transparent" : "linear-gradient(160deg, #0b1020, #172554)",
    color: "white",
    fontFamily: font,
  };

  if (mode === "annotation") {
    const dash = 1200 * (1 - progress);
    return (
      <AbsoluteFill style={base} data-namespace={namespace}>
        <svg viewBox="0 0 1080 1920" width="1080" height="1920">
          <rect x="160" y="650" width="760" height="460" rx="48" fill="none" stroke="#ffcc33"
            strokeWidth="18" strokeDasharray="1200" strokeDashoffset={dash}/>
          <path d="M180 1160 C420 1220 680 1120 900 1190" fill="none" stroke="#ffcc33"
            strokeWidth="22" strokeLinecap="round" pathLength="1" strokeDasharray="1" strokeDashoffset={1-progress}/>
        </svg>
      </AbsoluteFill>
    );
  }

  if (mode === "transition") {
    const x = interpolate(progress, [0, 1], [-1080, 1080]);
    return (
      <AbsoluteFill style={base} data-namespace={namespace}>
        <AbsoluteFill style={{background: "#10233f", transform: `translateX(${x}px) skewX(-8deg)`}}/>
        <AbsoluteFill style={{justifyContent: "center", alignItems: "center", fontFamily: font, fontSize: 94, fontWeight: 700}}>
          {title}
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  if (mode === "data") {
    return (
      <AbsoluteFill style={{...base, justifyContent: "center", padding: 120}} data-namespace={namespace}>
        <div style={{fontSize: 64, opacity: 0.75}}>{title}</div>
        <div style={{fontSize: 220, fontWeight: 800, fontVariantNumeric: "tabular-nums"}}>
          {Math.round(value * progress)}
        </div>
        <div style={{height: 36, borderRadius: 18, background: "#263555", overflow: "hidden"}}>
          <div style={{height: "100%", width: `${progress * 100}%`, background: "#55d6be"}}/>
        </div>
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{...base, justifyContent: "center", alignItems: "center", padding: 120}} data-namespace={namespace}>
      <div style={{fontSize: 112, lineHeight: 1.12, fontWeight: 800, textAlign: "center",
        opacity: enter, transform: `translateY(${(1 - enter) * 90}px) scale(${0.92 + enter * 0.08})`}}>
        {title}
      </div>
    </AbsoluteFill>
  );
};
