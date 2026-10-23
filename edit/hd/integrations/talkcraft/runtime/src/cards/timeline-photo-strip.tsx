import React from "react";
import { AbsoluteFill, Img, useCurrentFrame } from "remotion";

// timeline-photo-strip · 时间线照片带 —— 自包含 Remotion 源码（与 demos/timeline-photo-strip/index.html 同画面）
// 四张 240×160 沿一条时间线上下交替，日期 caption 靠线一侧；相机横移逐站停靠（当前站 1.03 亮 / 其余 .7）→ 拉开看全条、停一拍再与字同收。
// 复制本文件进你的工程即可用；真图经 srcs 注入（不传 = 灰调占位）。2026-09-06 由 multi-still-tour 拆出；平级的几个例子用 gallery-wall-dolly。
export const meta = { width: 960, height: 540, fps: 30, durationInFrames: 309 };   // 9.9s + 0.4s 收尾

const FPS = meta.fps;

// ——————————————————————————————————————————————————————————
// 可摘走的核心参数（与 demo 的 CONFIG 同名同注释）
// 运镜纪律：① 相机层是唯一被 transform 的元素，camTo(z, px, py) 反解到画心
//          ② 停靠段相机真静止，当前站 1.03 点亮防死、其余 .7
//          ③ 走完必拉开看全条；有意停留结束与字同收
// ——————————————————————————————————————————————————————————
const CONFIG = {
  stopZ: 1.05,      // 停靠焦距：邻站出画 24px（1.0 时邻站与画幅边齐平、邻站 caption 离边 6px，读作贴边）；上排照片离顶 49.5
  wideZ: 0.62,      // 拉开看全条的焦距
  move: 0.9,        // 站间横移（power2.inOut）
  hold: 1.0,        // 每站停留
  lead: 0.4,        // 起手：第一站先停一拍再点亮
  pull: 1.1,        // 拉开
  tailHold: 1.2,    // 拉开后看全条的有意停留
  dim: 0.7,         // 非当前站 brightness
  focus: 1.03,      // 当前站放大 1.03（0.4s，从移动中段起）
  exit: 0.4,        // 退场：caption + 时间线 → 照片，错峰 0.04
  end: 9.9,         // 动画结束秒（含退场）
  centers: [240, 600, 960, 1320], stripCenter: [780, 300] as [number, number],   // 四站中心 x / 全条中心
};
/* 时间表：0 第一站居中 · 0.4 点亮 · 1.4 / 3.3 / 5.2 横移到二三四站（移 0.9 + 停 1.0，点亮从移动 0.5s 起）
   · 7.1–8.2 拉开看全条（7.4 起 0.5s 全部复原）· 8.2–9.4 停 · 9.4–9.84 退场 · 9.9 结束 */
export const END = CONFIG.end;

type Cam = { scale: number; x: number; y: number };
const camTo = (z: number, px: number, py: number): Cam => ({ scale: z, x: 480 - z * px, y: 270 - z * py });

// —— 缓动与 tween helper（对照 GSAP 名字）——
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const tw = (t: number, t0: number, d: number, ease: (x: number) => number) => ease(clamp01((t - t0) / d));
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
const power1Out = (x: number) => 1 - Math.pow(1 - x, 2);   // GSAP 缺省 ease
const power2In = (x: number) => x * x * x;
const power2InOut = (x: number) => (x < 0.5 ? 4 * x ** 3 : 1 - Math.pow(-2 * x + 2, 3) / 2);
const camSeg = (cam: Cam, to: Cam, t: number, t0: number, d: number): Cam => {
  const p = tw(t, t0, d, power2InOut);
  return { scale: lerp(cam.scale, to.scale, p), x: lerp(cam.x, to.x, p), y: lerp(cam.y, to.y, p) };
};
const camStyle = (c: Cam): React.CSSProperties => ({ transform: `translate(${c.x}px, ${c.y}px) scale(${c.scale})`, transformOrigin: "0 0" });

// —— 演示语境（不属于动效）：样式照搬 demo（类名加 tps- 前缀）——
const CSS = `
* { margin: 0; padding: 0; box-sizing: border-box; }
.tps-cam { position: absolute; inset: 0; width: 1600px; transform-origin: 0 0; will-change: transform; }
.tps-line { position: absolute; left: 60px; top: 300px; width: 1500px; height: 3px; background: #1d1d1f; border-radius: 2px; }
.tps-photo { position: absolute; background: #ffffff; padding: 10px; border-radius: 12px; box-shadow: 0 12px 60px rgba(0,0,0,.22); width: 240px; height: 160px; transform-origin: 50% 50%; }
.tps-photo .frame { position: absolute; inset: 10px; border-radius: 5px; overflow: hidden; }
.tps-ph { position: absolute; inset: 0; overflow: hidden; }
.tps-ph::before { content: ""; position: absolute; inset: 0; }
.tps-ph.t1::before { background: linear-gradient(160deg, #a4b0c6, #7d8aa3); }
.tps-ph.t2::before { background: linear-gradient(160deg, #bfa5ae, #957c86); }
.tps-ph.t3::before { background: linear-gradient(160deg, #9fb9ae, #789389); }
.tps-ph.t4::before { background: linear-gradient(160deg, #c2b39a, #9c8f78); }
.tps-ph svg { position: absolute; left: 50%; top: 50%; width: 56px; height: 48px; transform: translate(-50%, -56%); opacity: .35; }
.tps-cap { position: absolute; font-size: 22px; font-weight: 700; color: #1d1d1f; white-space: nowrap; }
`;

const GLYPH = (
  <svg viewBox="0 0 48 40" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinejoin="round">
    <rect x="2" y="2" width="44" height="36" rx="4" /><circle cx="16" cy="14" r="4" /><path d="M4 34 L18 22 L27 30 L34 24 L44 34" />
  </svg>
);

const Ph: React.FC<{ tone: number; src?: string; node?: React.ReactNode }> = ({ tone, src, node }) => (
  <div className={`tps-ph t${tone}`}>
    {node ? <div style={{position:"absolute",inset:0}}>{node}</div> : src ? <Img src={src} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} /> : GLYPH}
  </div>
);

const LABELS = ["2019 · 一台笔记本", "2021 · 有了工位", "2023 · 全套设备", "2026 · 自己的工作室"];
// 几何：四站上下交替（上 top 90 / 下 top 330），caption 靠时间线一侧（上排在线下 318 / 下排在线上 266）
const POS = [{ left: 120, top: 82, cap: 340 }, { left: 480, top: 338, cap: 210 }, { left: 840, top: 82, cap: 340 }, { left: 1200, top: 338, cap: 210 }];

type Props = {
  /** 真图（四张）；不传用灰调占位 */
  srcs?: string[];
  /** 已解码的四张图片节点；正式生产优先使用 */
  mediaNodes?: React.ReactNode[];
  /** 日期 caption；不传用默认文案 */
  labels?: string[];
};

function UpstreamCard({ srcs, mediaNodes, labels }: Props) {
  const t = useCurrentFrame() / FPS;
  const C = CONFIG;
  const src = (i: number) => (srcs && srcs[i]) || undefined;
  const mediaNode = (i: number) => (mediaNodes && mediaNodes[i]) || undefined;
  const label = (i: number) => (labels && labels[i]) || LABELS[i];
  const wide = camTo(C.wideZ, C.stripCenter[0], C.stripCenter[1]);
  let cam = camTo(C.stopZ, C.centers[0], 270), tt = C.lead;
  const focusAt: number[] = [];
  C.centers.forEach((cx, i) => { if (i) cam = camSeg(cam, camTo(C.stopZ, cx, 270), t, tt, C.move); focusAt.push(tt + (i ? C.move * 0.5 : 0)); tt += (i ? C.move : 0) + C.hold; });
  cam = camSeg(cam, wide, t, tt, C.pull);
  const tPull = tt, tOut = tt + C.pull + C.tailHold;
  const opLine = 1 - tw(t, tOut, C.exit, power2In), opPhoto = 1 - tw(t, tOut + 0.04, C.exit, power2In);

  return (
    <AbsoluteFill style={{ background: "#ffffff", color: "#1d1d1f", overflow: "hidden", fontFamily: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif' }}>
      <style>{CSS}</style>
      <div className="tps-cam" style={camStyle(cam)}>
        <div className="tps-line" style={{ opacity: opLine }} />
        {C.centers.map((_, j) => {
          // 当前站亮 + 1.03，其余 .7（每站 0.4s）；拉开时 0.5s 全部复原
          let b = C.dim, s = 1;
          focusAt.forEach((f, i) => { const p = tw(t, f, 0.4, power1Out); b = lerp(b, i === j ? 1 : C.dim, p); s = lerp(s, i === j ? C.focus : 1, p); });
          const back = tw(t, tPull + 0.3, 0.5, power1Out); b = lerp(b, 1, back); s = lerp(s, 1, back);
          const P = POS[j];
          return (
            <React.Fragment key={j}>
              <div className="tps-photo" style={{ left: P.left, top: P.top, filter: `brightness(${b})`, transform: `scale(${s})`, opacity: opPhoto }}>
                <div className="frame"><Ph tone={j + 1} src={src(j)} node={mediaNode(j)} /></div>
              </div>
              <div className="tps-cap" style={{ left: P.left + 6, top: P.cap, opacity: opLine }}>{label(j)}</div>
            </React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
}
import contract from "./timeline-photo-strip.contract.json";
import type {CandidateScene,CardContext,CardRenderProps,CardSfxCue} from "../production-card-root";
type Prepared={title:string;subtitle:string;accent:string};
export const cardMeta={card_id:"timeline-photo-strip",api_version:1} as const;
export const candidateScene=contract.scene as CandidateScene;
export const sceneInputSlots=contract.scene_input_slots as string[];
export const sfxCues=contract.sfx_cues as CardSfxCue[];
export const prepareCard=(raw:unknown,c:CardContext):Prepared=>{const v=raw as Partial<Prepared>|null;if(!v||c.width!==1080||c.height!==1920||c.fps!==24||c.durationInFrames!==238||typeof v.title!=="string"||v.title.length<2||v.title.length>12||typeof v.subtitle!=="string"||v.subtitle.length<2||v.subtitle.length>18||typeof v.accent!=="string"||!/^#[0-9A-Fa-f]{6}$/.test(v.accent))throw Error("timeline-photo-strip invalid input");return{title:v.title,subtitle:v.subtitle,accent:v.accent}};
export default function Card({prepared,sceneInputs}:CardRenderProps<Prepared>){const mediaNodes=[sceneInputs["item-1"],sceneInputs["item-2"],sceneInputs["item-3"],sceneInputs["item-4"]];const labels=[prepared.title,prepared.subtitle,"持续迭代","完整交付"];return <AbsoluteFill className="candidate-media" style={{background:"#fff",overflow:"hidden"}}><style>{`.candidate-media .tps-cap{font-size:28px!important;line-height:1.15!important}.candidate-media .tps-line{height:4px!important}.candidate-media .host-badge,.candidate-media .host-col,.candidate-media .host-full{display:none!important}`}</style><div style={{position:"absolute",top:80,left:-60,width:1200,height:675,overflow:"hidden"}}><div style={{position:"relative",width:960,height:540,transform:"scale(1.25)",transformOrigin:"top left"}}><UpstreamCard labels={labels} mediaNodes={mediaNodes}/></div></div><div style={{position:"absolute",left:70,top:790,width:940,textAlign:"center",zIndex:8}}><div style={{fontSize:64,fontWeight:800,lineHeight:1.12,color:"#1d1d1f"}}>{prepared.title}</div><div style={{display:"inline-block",marginTop:18,padding:"10px 22px",borderRadius:999,background:prepared.accent,color:"#fff",fontSize:30,fontWeight:650}}>{prepared.subtitle}</div></div><div style={{position:"absolute",left:180,top:1040,width:720,height:780,zIndex:5}}>{sceneInputs.presenter}</div></AbsoluteFill>}
