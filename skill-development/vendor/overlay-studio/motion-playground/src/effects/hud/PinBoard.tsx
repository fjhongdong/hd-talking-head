import type { EffectDef } from "../types";
import { PinBoardPlate } from "./PinBoardPlate";
import {
  ACCENT_OPTIONS,
  OFFSET_CONTROLS,
  OFFSET_DEFAULTS,
  THEME_OPTIONS,
} from "./accent";

export interface PinBoardParams {
  theme: "dark" | "light";
  position: "top-right" | "top-left";
  /** 章节大标题(描边小字,钉在最上),可空 */
  title: string;
  /** 强调副题(如 "AI反问法:"),可空 */
  subtitle: string;
  /** 要点黑牌,| 分隔,讲到哪条钉哪条 */
  items: string;
  /** 每条落钉间隔(卡点:对齐口播讲到的时刻) */
  stepMs: number;
  /** 每条落钉秒(| 分隔,相对卡片 start,踩台词开口)。留空 = 按 stepMs 匀速落 */
  times?: string;
  /** 合作者版本的同义字段,times 为空时读它 */
  itemTimes?: string;
  __t?: number;
  __start?: number;
  accent: string;
  offsetX?: number;
  offsetY?: number;
}

/**
 * 要点钉板:讲过的要点钉在角落全程不消失 —
 * 章节标题 + 强调副题钉住,黑牌要点逐条落钉("定角色→限制条件→工作指南")。
 * 卡片时长应覆盖整段讲述(20-60s),stepMs 对齐你讲到每条的时刻;
 * 观众任何时刻扫一眼角落,就知道讲到哪、前面讲了什么。
 */
const PinBoard = PinBoardPlate;

export const pinBoardDef: EffectDef<PinBoardParams> = {
  id: "pin-board",
  name: "PinBoard",
  description: "要点钉板 · 讲过的要点逐条钉在角落,全程不消失",
  tags: ["逐条落位", "堆叠累积"],
  selfPosition: true,
  defaults: {
    theme: "dark",
    position: "top-right",
    title: "本段主题写这里",
    subtitle: "小标题:",
    items: "要点一|要点二|要点三|要点四",
    stepMs: 4000,
    times: "",
    accent: "blue",
    ...OFFSET_DEFAULTS,
  },
  controls: [
    { key: "theme", label: "底色(此卡独立生效)", type: "select", options: THEME_OPTIONS },
    {
      key: "position",
      label: "落位",
      type: "select",
      options: [
        { label: "右上角", value: "top-right" },
        { label: "左上角", value: "top-left" },
      ],
    },
    { key: "title", label: "章节标题(可空)", type: "text" },
    { key: "subtitle", label: "强调副题(可空)", type: "text" },
    { key: "items", label: "要点(| 分隔,逐条落钉)", type: "text" },
    { key: "times", label: "每条落钉秒(| 分隔,踩台词开口;空 = 按下面匀速落)", type: "text" },
    { key: "stepMs", label: "每条落钉间隔(没填 times 时用)", type: "range", min: 1000, max: 15000, step: 250, unit: "ms" },
    { key: "accent", label: "强调色(副题)", type: "select", options: ACCENT_OPTIONS },
    ...OFFSET_CONTROLS,
  ],
  Component: PinBoard,
};
