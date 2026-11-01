import { STAGE } from "../../stage";

/**
 * 运镜几何 —— 画布(预览)和卡片(导出)共用,两边必须算出同一个结果。
 *
 * 画布和卡片都需要这份几何,所以放进共享模块,两边引用同一份。
 */

/** focus-card 需要的字段 */
export interface FocusCamGeomInput {
  side?: "left" | "right";
  camDX?: number;
  camDY?: number;
  camW?: number;
  camH?: number;
}

/**
 * focus-card 的口播落位框 —— 预览(Canvas)、导出(卡片 --fcd-*)共用这一份。
 *
 * 这套几何以前在 Canvas 和 FocusCard 里各写了一份,注释说「严格同源」其实是
  * 复制的;改排版时只改了一处,画面里人像和落位框就对不上了。收进这里。
 *
  * 人缩到左/右侧 700×700 方框,要点在另一侧。
 */
export function focusCamGeom(p: FocusCamGeomInput) {
  const { w: SW } = STAGE;
  const y = 190;
  const w = Number(p.camW) || 700;
  const h = Number(p.camH) || 700;
  const x = (p.side ?? "left") === "right" ? SW - 110 - w : 110;
  return {
    x: x + (Number(p.camDX) || 0),
    y: y + (Number(p.camDY) || 0),
    w,
    h,
    r: 36,
  };
}


/* ============ focus-card 精修版:满屏缩进侧边圆角方框(预览画布 / 卡内烤入导出共用) ============ */

export interface FocusCamAtInput extends FocusCamGeomInput {
  /** 口播框大小(%,只在精修版生效):100 = camW×camH,以框的外侧边、垂直中线为基准缩放 */
  camSize?: number;
}

/** 精修版落位终点:camSize=100 时和 focusCamGeom 完全一样;放大缩小守住靠画面外侧的那条边 */
export function focusCamBox(p: FocusCamAtInput) {
  const B = focusCamGeom(p);
  const { h: SH } = STAGE;
  const k0 = Math.max(60, Math.min(160, Number(p.camSize) || 100)) / 100;
  const k = Math.min(k0, Math.max(0.3, (SH - 60) / B.h));
  if (k === 1) return B;
  const w = B.w * k, h = B.h * k;
  const x = (p.side ?? "left") === "right" ? B.x + B.w - w : B.x;
  const y = Math.max(30, Math.min(SH - 30 - h, B.y + (B.h - h) / 2));
  return { x, y, w, h, r: B.r };
}

const fcSeg = (t: number, a: number, b: number) => (t <= a ? 0 : t >= b ? 1 : (t - a) / (b - a));
/** cubic-bezier,二分求解(确定性,原作 bez 原样) */
export function fcBez(x1: number, y1: number, x2: number, y2: number) {
  const c = (a1: number, a2: number, s: number) => { const u = 1 - s; return 3 * u * u * s * a1 + 3 * u * s * s * a2 + s * s * s; };
  return (x: number) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let lo = 0, hi = 1, m = 0.5;
    for (let i = 0; i < 40; i++) { m = (lo + hi) / 2; if (c(x1, x2, m) < x) lo = m; else hi = m; }
    return c(y1, y2, m);
  };
}
const fcEaseIn = fcBez(0.55, 0, 0.12, 1); // 缩进:起步克制,迅速落位
const fcEaseBack = fcBez(0.6, 0, 0.25, 1); // 回满屏

/**
 * 时间节点(秒,卡内)。原作 12s:回满屏 10.95→11.7,结束前 0.3s 走完(编辑台最后 0.3s 整卡淡出)。
 * 没有结束时间时 back0/end 都是 Infinity(一直停在方框)。
 */
export function focusCardTimes(dur: number) {
  // 回满屏要在编辑台最后 0.3s 的整卡淡出前走完(否则重影)
  const end = dur - Math.min(0.3, dur * 0.1);
  return { back0: end - Math.min(0.75, dur * 0.2), end };
}

/**
 * 口播在 t 秒(卡内已过秒数)的几何,原作 camGeom 逐拍搬来:
 * 0.05→1.05s 贝塞尔(0.55,0,0.12,1)从满屏缩进方框 → 落位后 ±4px、5.2s 周期上下浮动(回满屏前 0.65s 平滑归零)
 * → back0→end 贝塞尔(0.6,0,0.25,1)回满屏。
 */
export function focusCamGeomAt(p: FocusCamAtInput, t: number, dur: number) {
  const { w: SW, h: SH } = STAGE;
  const B = focusCamBox(p);
  if (!Number.isFinite(t)) return B;
  const { back0, end } = focusCardTimes(dur);
  if (t <= 0 || t >= end) return { x: 0, y: 0, w: SW, h: SH, r: 0 };
  const k = t < back0 ? fcEaseIn(fcSeg(t, 0.05, 1.05)) : 1 - fcEaseBack(fcSeg(t, back0, end));
  const env = fcSeg(t, 1.2, 2.2) * (1 - fcSeg(t, back0 - 0.65, back0));
  const bob = Math.sin(((t - 1.2) * Math.PI * 2) / 5.2) * 4 * env;
  return { x: B.x * k, y: B.y * k + bob, w: SW + (B.w - SW) * k, h: SH + (B.h - SH) * k, r: B.r * k };
}
