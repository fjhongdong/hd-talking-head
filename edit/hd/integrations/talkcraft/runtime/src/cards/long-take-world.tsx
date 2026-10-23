import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

// long-take-world · 长镜头世界画布 —— 自包含 Remotion 源码（与 demos/long-take-world/index.html 同画面）
// 复制本文件进你的工程即可用。
export const meta = { width: 960, height: 540, fps: 30, durationInFrames: 213 };

const FPS = 24;

// —— 可摘走的核心动画 ——
// 站点表 + 相机反向 transform + "接近度揭示"（arrive）：内容在相机赶到前 0.4 屏就开始成形。
const CONFIG = {
  stops: [                       // 相机注视点（世界坐标）+ 到站后停留
    { x: 0,    y: 0,   zoom: 1.0,  hold: 1.1 },
    { x: 1150, y: 330, zoom: 1.06, hold: 1.2 },
    { x: 420,  y: 960, zoom: 0.96, hold: 1.4 },
  ],
  travel: 1.5,       // 站间运镜时长 s（速度 ≤1.5 屏宽/s 铁律）
  arriveLead: 420,   // 接近半径 px：距离小于它内容开始成形
  drift: 5,          // 到站微漂 ±px（永不完全静止）
};

/* 时间表（demo 秒，站间 travel=1.5 sine.inOut）
   0.00–1.11  起点 hold（微漂持续）
   1.11–2.61  运镜 → 站 B (1150,330) zoom1.06
   2.61–3.81  站 B hold
   3.81–5.31  运镜 → 站 C (420,960) zoom0.96
   5.31–6.71  站 C hold */

// —— 缓动 helper（对照 GSAP 名字）——
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
const sineInOut = (x: number) => -(Math.cos(Math.PI * x) - 1) / 2;

// 站点与途经点（世界坐标）
const STATIONS = [
  { x: 0, y: 0, title: <>起点 · <em>钩子</em></>, note: "相机停在这，内容已在世界坐标上" },
  { x: 1150, y: 330, title: <>站 B · <em>数据</em></>, note: '讲到哪，镜头移到哪，到点即"到站"' },
  { x: 420, y: 960, title: <>站 C · <em>结论</em></>, note: "没有切镜——空间连续性就是转场" },
];
const WAYPOINTS = [{ x: 600, y: 170 }, { x: 900, y: 750 }];

const CSS = `
/* 世界网格：本卡唯一必需的"底"——它让相机位移可被看见，不是装饰纹理 */
#worldgrid {
  position: absolute; left: -1500px; top: -900px; width: 4200px; height: 2200px;
  background-image: linear-gradient(#ececef 1px, transparent 1px),
                    linear-gradient(90deg, #ececef 1px, transparent 1px);
  background-size: 130px 130px;
}
.station { position: absolute; transform: translate(-50%, -50%); text-align: center; }
.station .card {
  background: #fff; border: 1px solid #e0e0e0; border-radius: 10px;
  padding: 36px 48px;
}
.station h2 { font-size: 44px; color: #1d1d1f; margin-bottom: 10px; white-space: nowrap; }
.station h2 em { font-style: normal; }
/* 途经点：唯一保留的强调色接口——复用时整组换品牌色 */
.waypoint { position: absolute; width: 14px; height: 14px; border-radius: 50%;
  background: #ffffff; border: 2px solid #1d1d1f; transform: translate(-50%,-50%); }
`;

function UpstreamCard({ title, subtitle, accent }: { title: string; subtitle: string; accent: string }) {
  const t = useCurrentFrame() / FPS;
  const stations = [
    { ...STATIONS[0], title: <>起点 · <em style={{color:accent}}>{title}</em></>, note: subtitle },
    { ...STATIONS[1], title: <>展开 · <em style={{color:accent}}>{subtitle}</em></>, note: `围绕「${title}」持续推进` },
    { ...STATIONS[2], title: <>结论 · <em style={{color:accent}}>{title}</em></>, note: subtitle },
  ];

  // —— 相机：站点表摊平成绝对秒（travel=1.5 sine.inOut，站间 hold）——
  const [s0, s1, s2] = CONFIG.stops;
  let cam = { x: s0.x, y: s0.y, zoom: s0.zoom };
  const seg1 = 0.01 + s0.hold;                 // 1.11 起运镜去站 B
  const seg2 = seg1 + CONFIG.travel + s1.hold; // 3.81 起运镜去站 C
  if (t < seg1) {
    cam = { x: s0.x, y: s0.y, zoom: s0.zoom };
  } else if (t < seg1 + CONFIG.travel) {
    const p = sineInOut(clamp01((t - seg1) / CONFIG.travel));
    cam = { x: lerp(s0.x, s1.x, p), y: lerp(s0.y, s1.y, p), zoom: lerp(s0.zoom, s1.zoom, p) };
  } else if (t < seg2) {
    cam = { x: s1.x, y: s1.y, zoom: s1.zoom };
  } else if (t < seg2 + CONFIG.travel) {
    const p = sineInOut(clamp01((t - seg2) / CONFIG.travel));
    cam = { x: lerp(s1.x, s2.x, p), y: lerp(s1.y, s2.y, p), zoom: lerp(s1.zoom, s2.zoom, p) };
  } else {
    cam = { x: s2.x, y: s2.y, zoom: s2.zoom };
  }

  // 微漂：双不可通约正弦，任何"到站"时刻都不完全静止
  const dx = Math.sin(t * 0.61 + 1.3) * CONFIG.drift;
  const dy = Math.sin(t * 0.47 + 4.1) * CONFIG.drift * 0.7;

  return (
    <AbsoluteFill style={{
      background: "#ffffff", color: "#1d1d1f", overflow: "hidden",
      fontFamily: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
    }}>
      <style>{CSS}</style>
      {/* 世界画布：超大 div，相机 = 反向 transform */}
      <div id="world" style={{
        position: "absolute", left: "50%", top: "50%", width: 0, height: 0,
        willChange: "transform",
        transform: `scale(${cam.zoom}) translate(${-(cam.x + dx)}px, ${-(cam.y + dy)}px)`,
      }}>
        <div id="worldgrid" />
        {stations.map((st, i) => {
          // arrive 揭示：相机接近哪站，哪站成形（提前 arriveLead 就开始）
          const dist = Math.hypot(cam.x - st.x, cam.y - st.y);
          const a = clamp01(1 - (dist - CONFIG.arriveLead * 0.4) / (CONFIG.arriveLead * 0.6));
          return (
            <div key={i} className="station" style={{ left: st.x, top: st.y }}>
              <div className="card" style={{
                opacity: a,
                transform: `translateY(${26 * (1 - a)}px) scale(${0.94 + 0.06 * a})`,
              }}>
                <h2>{st.title}</h2>
                <p>{st.note}</p>
              </div>
            </div>
          );
        })}
        {WAYPOINTS.map((w, i) => (
          <div key={i} className="waypoint" style={{ left: w.x, top: w.y, borderColor: accent }} />
        ))}
      </div>
    </AbsoluteFill>
  );
}

import contract from "./long-take-world.contract.json";
import type {CandidateScene,CardContext,CardRenderProps,CardSfxCue} from "../production-card-root";
type Prepared={title:string;subtitle:string;accent:string};
export const cardMeta={card_id:"long-take-world",api_version:1} as const;export const candidateScene=contract.scene as CandidateScene;export const sceneInputSlots=contract.scene_input_slots as string[];export const sfxCues=contract.sfx_cues as CardSfxCue[];
export const prepareCard=(raw:unknown,c:CardContext):Prepared=>{const v=raw as Partial<Prepared>|null;if(!v||c.width!==1080||c.height!==1920||c.fps!==24||c.durationInFrames!==170||typeof v.title!=="string"||v.title.length<2||v.title.length>12||typeof v.subtitle!=="string"||v.subtitle.length<2||v.subtitle.length>18||typeof v.accent!=="string"||!/^#[0-9A-Fa-f]{6}$/.test(v.accent))throw Error("long-take-world invalid input");return{title:v.title,subtitle:v.subtitle,accent:v.accent}};
export default function Card({prepared,sceneInputs}:CardRenderProps<Prepared>){return <AbsoluteFill className="candidate-generated" style={{background:"#fff",overflow:"hidden"}}><div style={{position:"absolute",left:0,top:90,width:1080,height:675,overflow:"hidden"}}><div style={{position:"absolute",left:-60,width:960,height:540,transform:"scale(1.25)",transformOrigin:"top left"}}><UpstreamCard title={prepared.title} subtitle={prepared.subtitle} accent={prepared.accent}/></div></div><div style={{position:"absolute",left:70,top:790,width:940,textAlign:"center",zIndex:8}}><div style={{fontSize:64,fontWeight:800,lineHeight:1.12,color:"#1d1d1f"}}>{prepared.title}</div><div style={{display:"inline-block",marginTop:18,padding:"10px 22px",borderRadius:999,background:prepared.accent,color:"#fff",fontSize:30,fontWeight:650}}>{prepared.subtitle}</div></div><div style={{position:"absolute",left:180,top:1040,width:720,height:780,zIndex:5}}>{sceneInputs.presenter}</div></AbsoluteFill>}
