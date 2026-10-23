import type { EffectDef } from "../types";
import { ChapterBarPlate } from "./ChapterBarPlate";
import { ACCENT_OPTIONS, OFFSET_CONTROLS, OFFSET_DEFAULTS, THEME_OPTIONS } from "./accent";

export interface ChapterBarParams {
  theme: "dark" | "light";
  /** 章节表:「名称 起始秒」用 | 分隔,如 "引入 0 | 变现问题 17 | 工作流 43" */
  chapters: string;
  accent: string;
  /** 当前章节底部显示进度线 */
  showProgress: boolean;
  /** 进度形态:fill 整条上色往前推 · line 只在当前章底部一条细线 */
  progMode?: "fill" | "line";
  /** 进度色(空=跟随强调色) */
  progAccent?: string;
  /** 进度色透明度(0.1-1,只要跟底色分得开就行) */
  progAlpha?: number;
  /** 隐藏时段(时间轴绝对秒,如 "119.11-139.064",多段用 | 分隔):到点淡出,进度照常在后台走 */
  hideAt?: string;
  offsetX?: number;
  offsetY?: number;
  /** 编辑台/导出注入:时间轴当前秒 */
  __t?: number;
  /** 编辑台/导出注入:本卡结束秒(最后一章的进度终点) */
  __end?: number;
  __start?: number;
}

/**
 * 常驻章节导航条:整期视频的地图,贴在画面顶部全程在场。
 * 当前章节高亮 + 章内进度线,讲到哪一章观众随时知道。
 * 用法:一张卡从 0 拉到视频结尾,章节表按你的稿子分段填。
 */
const ChapterBar = ChapterBarPlate;

export const chapterBarDef: EffectDef<ChapterBarParams> = {
  id: "chapter-bar",
  name: "ChapterBar",
  description: "常驻章节导航 · 顶部全程在场的本期地图",
  tags: ["生长描画"],
  selfPosition: true,
  defaults: {
    theme: "dark",
    chapters: "开场 0 | 章节名 6 | 按起始秒填 14 | 结尾 24",
    accent: "blue",
    showProgress: true,
    progMode: "fill",
    progAccent: "",
    progAlpha: 0.25,
    hideAt: "",
    ...OFFSET_DEFAULTS,
  },
  controls: [
    { key: "theme", label: "底色(此卡独立生效)", type: "select", options: THEME_OPTIONS },
    { key: "chapters", label: "章节表(名称 起始秒,| 分隔)", type: "text" },
    { key: "accent", label: "强调色", type: "select", options: ACCENT_OPTIONS },
    { key: "showProgress", label: "显示进度", type: "toggle" },
    {
      key: "progMode",
      label: "进度形态",
      type: "select",
      options: [
        { label: "整条上色 · 往前推", value: "fill" },
        { label: "细线 · 只在当前章底部", value: "line" },
      ],
    },
    {
      key: "progAccent",
      label: "进度色(默认跟随强调色)",
      type: "select",
      options: [{ label: "跟随强调色", value: "" }, ...ACCENT_OPTIONS],
    },
    { key: "progAlpha", label: "进度色透明度", type: "range", min: 0.1, max: 1, step: 0.05 },
    { key: "hideAt", label: "隐藏时段(绝对秒,如 119.11-139.064;多段用 | 分隔)", type: "text" },
    ...OFFSET_CONTROLS,
  ],
  Component: ChapterBar,
};
