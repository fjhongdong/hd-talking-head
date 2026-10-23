import { createContext, useContext, useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";
import type { EffectDef } from "./types";
import { useCardElapsed } from "./hud/useTimelineTime";
import { FxSpeedContext } from "./useAnimation";

/**
 * 呼吸层:卡片落定之后画面也不完全静止。
 * 几件事叠在一起:
 *  - 手持镜头:整张卡几条快慢不同的正弦叠加,几个像素地晃,外加极小的转角
 *  - 落定后漂浮:卡里的部件各自上下浮,相位错开,不会整齐划一
 *  - 落地余震:东西落地那一刻镜头震一下再衰减。落地时刻由卡自己在根元素上标
 *    data-land="0.3,2,3.6"(距卡片开始的秒);没标就用进场那一下
 *  - 跟随与重叠:整卡震的时候,里面的部件晚半拍才跟上、晚一点停(12 原则第 5 条)
 * 全部按卡片时间(useCardElapsed)算,导出逐帧确定,和预览一致。
 * 只写 CSS 变量(--br-*),由 hud.css 末尾的「呼吸层」规则落到独立的 translate/rotate 属性上,不碰各卡自己的 transform;
 *
 * 打开方式:BreathContext(整片开关 doc.breath,顶栏「呼吸感」)。
 * 单卡参数 breath 盖过整片开关:false = 这张卡不呼吸,true = 整片关着也让它呼吸,没设 = 跟随整片。
 */
export const BreathContext = createContext(false);

/** 这张卡要不要开呼吸 */
export function useBreathOn(params: { breath?: boolean }): boolean {
  const global = useContext(BreathContext);
  if (params.breath === false) return false;
  return params.breath === true || global;
}

/** 参与漂浮的部件:有承载面的块。读数、轨道、连线这类内部零件跟着父级走,不单独动 */
const FLOATERS =
  '[data-fx-role="item"],[data-fx-role="icon"],[data-fx-role="frame"],[data-fx-role="label"],[data-fx-role="excerpt"],[data-fx-role="warning"]';
const PARTS = `[data-fx-role="group"],${FLOATERS}`;

/** 手持镜头幅度(px)、转角(deg);漂浮幅度:整块 / 整块里的零件 / 独立零件(px);周期(s) */
const HAND = 3;
const HAND_ROT = 0.22;
const FLOAT_GROUP = 5;
const FLOAT_INNER = 1.5;
const FLOAT_SOLO = 4;
const PERIOD = 3.2;
/** 进场后多久开始呼吸、多久渐入到满幅(s):别和进场动画抢 */
const RAMP_AT = 0.5;
const RAMP_LEN = 1.2;
/** 落地余震:卡没标落地时刻时,进场后这一刻震一下;第一下最重,后面每下轻一些 */
const LAND_AT = 0.32;
const LAND_AMP = 5;
const LAND_AMP_LATER = 3;
/** 跟随与重叠:部件比整卡晚多少秒跟上,跟多少 */
const FOLLOW_LAG = 0.07;
const FOLLOW_AMT = 0.7;

const ramp = (t: number) => Math.max(0, Math.min(1, (t - RAMP_AT) / RAMP_LEN));

/** 落地余震在 t 时刻的位移:每个落地点一段衰减振荡 */
function shakeAt(t: number, lands: number[]): [number, number] {
  let x = 0;
  let y = 0;
  lands.forEach((t0, i) => {
    const s = t - t0;
    if (s <= 0 || s >= 0.6) return;
    const a = i === 0 ? LAND_AMP : LAND_AMP_LATER;
    y += a * Math.sin(s * 30) * Math.exp(-s * 8);
    x += a * 0.4 * Math.sin(s * 23) * Math.exp(-s * 8);
  });
  return [x, y];
}

type BreathParams = { __t?: number; __start?: number; breath?: boolean };

/**
 * 不吃呼吸层的卡:要稳的东西晃起来就是事故。
 * 全程常驻层(章节条、字幕、钉板)和带口播画面的运镜卡。
 */
export const BREATH_STILL = new Set([
  // 常驻层
  "chapter-bar", "caption-track", "pin-board",
  // 运镜(带口播画面)
  "focus-card",
]);

export function Breath({
  kind,
  params,
  playToken,
  children,
}: {
  kind: string;
  params: BreathParams;
  playToken: number;
  children: ReactNode;
}) {
  return useBreathOn(params) && !BREATH_STILL.has(kind) ? (
    <ActiveBreath params={params} playToken={playToken}>
      {children}
    </ActiveBreath>
  ) : (
    <>{children}</>
  );
}

function ActiveBreath({
  params,
  playToken,
  children,
}: {
  params: BreathParams;
  playToken: number;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const speed = useContext(FxSpeedContext);
  const t = useCardElapsed(params, playToken) * (speed > 0 ? speed : 1);

  useLayoutEffect(() => {
    const box = ref.current;
    if (!box) return;
    const root = box.querySelector<HTMLElement>(".hud");
    const k = ramp(t);
    const lands = (root?.dataset.land ?? "")
      .split(",")
      .map(Number)
      .filter((v) => Number.isFinite(v) && v >= 0);
    if (!lands.length) lands.push(LAND_AT);

    // 手持镜头 + 落地余震:整张卡
    if (root) {
      const [sx, sy] = shakeAt(t, lands);
      const hx = HAND * k * (Math.sin(t * 1.3) + 0.5 * Math.sin(t * 3.1 + 1)) + sx;
      const hy = HAND * k * (Math.cos(t * 1.1 + 0.5) + 0.5 * Math.sin(t * 2.7)) + sy;
      root.dataset.brRoot = "1";
      root.style.setProperty("--br-hx", `${hx.toFixed(2)}px`);
      root.style.setProperty("--br-hy", `${hy.toFixed(2)}px`);
      root.style.setProperty("--br-hr", `${(HAND_ROT * k * Math.sin(t * 0.7)).toFixed(3)}deg`);
    }

    // 落定后漂浮 + 跟随:每个部件相位错开;整块浮得多,整块里的零件只在整块上再轻轻错一点;
    // 嵌在另一个漂浮零件里的不再单独动,免得一块东西被拆开晃。
    // 跟随:整卡震完,部件按自己的延迟把同一段震动再走一遍(方向相反 = 被甩在后面),越里层越晚
    const inBox = (el: Element | null | undefined) => (el && box.contains(el) ? el : null);
    const w = (2 * Math.PI) / PERIOD;
    box.querySelectorAll<HTMLElement>(PARTS).forEach((el, i) => {
      const up = el.parentElement;
      const isGroup = el.dataset.fxRole === "group";
      const inGroup = inBox(up?.closest('[data-fx-role="group"]'));
      const nested = !isGroup && inBox(up?.closest(FLOATERS));
      const amp = nested ? 0 : isGroup ? (inGroup ? FLOAT_INNER : FLOAT_GROUP) : inGroup ? FLOAT_INNER : FLOAT_SOLO;
      const ph = i * 1.9;
      const lag = FOLLOW_LAG * (inGroup ? 2 : 1) + (i % 3) * 0.015;
      const [nx, ny] = shakeAt(t, lands);
      const [fx, fy] = shakeAt(t - lag, lands);
      const followX = nested ? 0 : (fx - nx) * FOLLOW_AMT;
      const followY = nested ? 0 : (fy - ny) * FOLLOW_AMT;
      el.style.setProperty("--br-x", `${(amp * 0.35 * k * Math.sin(t * w * 0.73 + ph * 1.7) + followX).toFixed(2)}px`);
      el.style.setProperty("--br-y", `${(amp * k * Math.sin(t * w + ph) + followY).toFixed(2)}px`);
    });
  });

  // 卸载/关掉时把写上去的属性清掉
  useLayoutEffect(() => {
    const box = ref.current;
    return () => {
      if (!box) return;
      const root = box.querySelector<HTMLElement>(".hud");
      if (root) {
        delete root.dataset.brRoot;
        ["--br-hx", "--br-hy", "--br-hr"].forEach((v) => root.style.removeProperty(v));
      }
      box.querySelectorAll<HTMLElement>(PARTS).forEach((el) => {
        el.style.removeProperty("--br-x");
        el.style.removeProperty("--br-y");
      });
    };
  }, []);

  return (
    <div ref={ref} className="fx-breath" style={{ display: "contents" }}>
      {children}
    </div>
  );
}

/** 给卡片定义套上呼吸层:Component 换成「呼吸层包着原卡」,其余字段原样 */
export function withBreath<P>(def: EffectDef<P>): EffectDef<P> {
  const Original = def.Component;
  return {
    ...def,
    Component: function BreathingEffect(props) {
      return (
        <Breath kind={def.id} params={props.params as BreathParams} playToken={props.playToken}>
          <Original {...props} />
        </Breath>
      );
    },
  };
}
