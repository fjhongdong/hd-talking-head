import React from "react";
import { AbsoluteFill, Img, useCurrentFrame } from "remotion";

// word-relay-filmstrip · 动词接力胶片 —— 自包含 Remotion 源码（与 demos/word-relay-filmstrip/index.html 同画面）
// 左列等高截图卡纵向排列、深浅边框相间，切词那 0.4s 才滚动恰好一卡高、其余时间零位移；
// 右侧衬线两行——名词恒定、动词原位接力（旧词先灰化淡出、新词后落位，不叠影），词块垂直中心 = 当前卡中点。
// 复制本文件进你的工程即可用；文案与截图经 props 注入（noun / verbs / labels / srcs），不传 = demo 文案 + 灰调占位。
export const meta = { width: 960, height: 540, fps: 30, durationInFrames: 204 };   // 6.4s 镜头 + 0.4s 收尾（4 词）

const FPS = 24;

// ——————————————————————————————————————————————————————————
// 可摘走的核心参数（与 demo 的 CONFIG 同名同注释）
// 命门：① 胶片只在切词窗（0.4s）内滚动恰好一卡高，其余时间零位移——持续滚动是违例；
//      ② 旧词先灰化淡出（0.18s）、新词后落位（0.25s），同帧交叉必叠影；
//      ③ 词块垂直中心 = 当前卡中点（像素级，差 >8px 可感）；④ 末词换强调色收束。
// ——————————————————————————————————————————————————————————
const CONFIG = {
  period: 1.4,      // 词期 s（母本 45~60f，口播按句长放到 1.4；词期不必均匀，成片按口播摆）
  scroll: 0.4,      // 切词窗：胶片滚一卡高的时长 s（power2.inOut；持续滚动 = 违例）
  cardH: 212,       // 一卡高 = 200 卡 + 12 间距 px
  startY: 164,      // 胶片初始 y：首卡顶 164 → 卡中点 264 = 词块中心
  fadeOut: 0.18,    // 旧词灰化淡出 s（power1.in，先出）
  landIn: 0.25,     // 新词落位 s（power2.out，y 12→0，后进；与旧词淡出间隔 0.02 不叠影）
  firstAt: 0.4,     // 首词入场时刻 s
  holdEnd: 0.9,     // 末词落定后静置 s
  exitDur: 0.45,    // 胶片 + 词块同收 s（power2.in）
};

/* 时间表（demo 秒，4 词）
   0.40–0.65  首词落位（opacity 0→1、y 12→0，power2.out）
   1.80 / 3.20 / 4.60  切词：旧词 0.18s 灰化淡出；胶片同起 0.4s 滚一卡高（power2.inOut）；新词 +0.20s 起 0.25s 落位
   5.95–6.40  胶片 + 词块同收（power2.in） */

// —— 缓动与 tween helper（对照 GSAP 名字）——
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const tw = (t: number, t0: number, d: number, ease: (x: number) => number) => ease(clamp01((t - t0) / d));
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
const power1In = (x: number) => x * x;
const power2Out = (x: number) => 1 - Math.pow(1 - x, 3);
const power2In = (x: number) => x * x * x;
const power2InOut = (x: number) => (x < 0.5 ? 4 * x ** 3 : 1 - Math.pow(-2 * x + 2, 3) / 2);
const mixHex = (a: string, b: string, p: number) => {
  const A = a.match(/\w\w/g)!.map((h) => parseInt(h, 16)), B = b.match(/\w\w/g)!.map((h) => parseInt(h, 16));
  return `rgb(${A.map((v, i) => Math.round(lerp(v, B[i], p))).join(",")})`;
};

// —— 演示语境（不属于动效）：样式照搬 demo（类名 wrf- 前缀）——
const CSS = `
* { margin: 0; padding: 0; box-sizing: border-box; }
.wrf-ph { position: absolute; overflow: hidden; inset: 0; }
.wrf-ph::before { content: ""; position: absolute; inset: 0; }
.wrf-ph.t1::before { background: linear-gradient(160deg, #a4b0c6, #7d8aa3); }
.wrf-ph.t2::before { background: linear-gradient(160deg, #bfa5ae, #957c86); }
.wrf-ph.t3::before { background: linear-gradient(160deg, #9fb9ae, #789389); }
.wrf-ph.t4::before { background: linear-gradient(160deg, #c2b39a, #9c8f78); }
.wrf-ph.t5::before { background: linear-gradient(160deg, #a3a9b8, #7f8594); }
.wrf-ph svg { position: absolute; left: 50%; top: 50%; width: 56px; height: 48px; transform: translate(-50%, -56%); opacity: .35; }
.wrf-win { position: absolute; left: 80px; top: 0; width: 360px; height: 540px; overflow: hidden; }
.wrf-strip { position: absolute; left: 0; top: 0; width: 360px; will-change: transform; }
.wrf-fc { position: relative; width: 360px; height: 200px; margin-bottom: 12px; border-radius: 10px; overflow: hidden; border: 6px solid #1d1d1f; }
.wrf-fc.lt { border-color: #ffffff; box-shadow: 0 0 0 1px #e0e0e0; }
.wrf-fc .n { position: absolute; left: 12px; bottom: 10px; font-size: 13px; color: #fff; background: rgba(0,0,0,.55); padding: 2px 8px; border-radius: 4px; }
.wrf-words { position: absolute; left: 520px; top: 0; height: 528px; display: flex; flex-direction: column; justify-content: center; }
.wrf-noun { font-family: "Songti SC", "Noto Serif CJK SC", "Source Han Serif SC", serif; font-size: 34px; color: #7a7a7a; font-weight: 600; letter-spacing: 2px; }
.wrf-verbwrap { position: relative; height: 72px; margin-top: 8px; }
.wrf-verb { position: absolute; left: 0; top: 0; font-family: "Songti SC", "Noto Serif CJK SC", "Source Han Serif SC", serif; font-size: 60px; font-weight: 700; letter-spacing: 2px; line-height: 72px; white-space: nowrap; }
`;

const GLYPH = (
  <svg viewBox="0 0 48 40" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinejoin="round">
    <rect x="2" y="2" width="44" height="36" rx="4" /><circle cx="16" cy="14" r="4" /><path d="M4 34 L18 22 L27 30 L34 24 L44 34" />
  </svg>
);

/** 素材占位：灰调渐变 + 相框图标；传 src 则铺真图（object-fit cover） */
const Ph: React.FC<{ tone: number; src?: string }> = ({ tone, src }) => (
  <div className={`wrf-ph t${tone}`}>
    {src ? <Img src={src} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} /> : GLYPH}
  </div>
);

type Props = {
  /** 恒定的名词（上行，灰色衬线） */
  noun?: string;
  /** 轮换的动词（下行，衬线大字；末词换强调色） */
  verbs?: string[];
  /** 胶片卡标签（与动词一一对应；多给一张 = 露在下方的"下一张"） */
  labels?: string[];
  /** 胶片卡真图（与 labels 同序；不传 = 灰调占位） */
  srcs?: (string | undefined)[];
  /** 末词颜色（唯一强调色） */
  accent?: string;
};

function UpstreamCard({
  noun = "一个 AI，能",
  verbs = ["写文案", "做配图", "剪视频", "配旁白"],
  labels = ["文案 · 初稿", "配图 · 3 版", "成片 · 时间线", "旁白 · 波形", "封面 · 候选"],
  srcs,
  accent = "#0066cc",
}: Props) {
  const t = useCurrentFrame() / FPS;
  const n = Math.max(1, verbs.length);

  // 时间表：第 i 词切换点 swapAt(i) = firstAt + i·period；末词落定 = swapAt(n-1) + fadeOut + 0.02 + landIn
  const swapAt = (i: number) => CONFIG.firstAt + i * CONFIG.period;
  const exitAt = swapAt(n - 1) + (n > 1 ? CONFIG.fadeOut + 0.02 : 0) + CONFIG.landIn + CONFIG.holdEnd;
  const exitK = 1 - tw(t, exitAt, CONFIG.exitDur, power2In);

  // 胶片：只在切词窗内滚一卡高，其余零位移
  let stripY = CONFIG.startY;
  for (let i = 1; i < n; i++) stripY -= CONFIG.cardH * tw(t, swapAt(i), CONFIG.scroll, power2InOut);

  // 词接力：旧词先灰化淡出，新词后落位（不叠影）
  const verbStyle = (i: number): React.CSSProperties => {
    const inAt = i === 0 ? CONFIG.firstAt : swapAt(i) + CONFIG.fadeOut + 0.02;
    const inP = tw(t, inAt, CONFIG.landIn, power2Out);
    const outP = i < n - 1 ? tw(t, swapAt(i + 1), CONFIG.fadeOut, power1In) : 0;
    const base = i === n - 1 ? accent : "#1d1d1f";
    return { opacity: inP * (1 - outP), transform: `translateY(${lerp(12, 0, inP)}px)`, color: outP > 0 ? mixHex(base, "#9a9da6", outP) : base };
  };

  return (
    <AbsoluteFill style={{ background: "#ffffff", color: "#1d1d1f", overflow: "hidden", fontFamily: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif' }}>
      <style>{CSS}</style>
      <div className="wrf-win" style={{ opacity: exitK }}>
        <div className="wrf-strip" style={{ transform: `translateY(${stripY}px)` }}>
          {labels.map((lb, i) => (
            <div key={i} className={`wrf-fc${i % 2 ? " lt" : ""}`}>
              <Ph tone={(i % 5) + 1} src={srcs?.[i]} />
              <div className="n">{lb}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="wrf-words" style={{ opacity: exitK }}>
        <div className="wrf-noun">{noun}</div>
        <div className="wrf-verbwrap">
          {verbs.map((v, i) => <div key={i} className="wrf-verb" style={verbStyle(i)}>{v}</div>)}
        </div>
      </div>
    </AbsoluteFill>
  );
}

import contract from "./word-relay-filmstrip.contract.json";
import type {CandidateScene,CardContext,CardRenderProps,CardSfxCue} from "../production-card-root";
type Prepared={title:string;subtitle:string;accent:string};
export const cardMeta={card_id:"word-relay-filmstrip",api_version:1} as const;export const candidateScene=contract.scene as CandidateScene;export const sceneInputSlots=contract.scene_input_slots as string[];export const sfxCues=contract.sfx_cues as CardSfxCue[];
export const prepareCard=(raw:unknown,c:CardContext):Prepared=>{const v=raw as Partial<Prepared>|null;if(!v||c.width!==1080||c.height!==1920||c.fps!==24||c.durationInFrames!==163||typeof v.title!=="string"||v.title.length<2||v.title.length>12||typeof v.subtitle!=="string"||v.subtitle.length<2||v.subtitle.length>18||typeof v.accent!=="string"||!/^#[0-9A-Fa-f]{6}$/.test(v.accent))throw Error("word-relay-filmstrip invalid input");return{title:v.title,subtitle:v.subtitle,accent:v.accent}};
export default function Card({prepared,sceneInputs}:CardRenderProps<Prepared>){return <AbsoluteFill className="candidate-generated" style={{background:"#fff",overflow:"hidden"}}><style>{`.candidate-generated .host-badge,.candidate-generated .host-col,.candidate-generated .host-full{display:none!important}`}</style><div style={{position:"absolute",left:0,top:90,width:1080,height:675,overflow:"hidden"}}><div style={{position:"absolute",left:-60,top:0,width:960,height:540,transform:"scale(1.25)",transformOrigin:"top left"}}><UpstreamCard noun={prepared.title} verbs={[prepared.subtitle,"形成结果"]} labels={[prepared.title,prepared.subtitle,"结果·落定"]} accent={prepared.accent}/></div></div><div style={{position:"absolute",left:70,top:790,width:940,textAlign:"center",zIndex:8}}><div style={{fontSize:64,fontWeight:800,lineHeight:1.12,color:"#1d1d1f"}}>{prepared.title}</div><div style={{display:"inline-block",marginTop:18,padding:"10px 22px",borderRadius:999,background:prepared.accent,color:"#fff",fontSize:30,fontWeight:650}}>{prepared.subtitle}</div></div><div style={{position:"absolute",left:180,top:1040,width:720,height:780,zIndex:5}}>{sceneInputs.presenter}</div></AbsoluteFill>}
