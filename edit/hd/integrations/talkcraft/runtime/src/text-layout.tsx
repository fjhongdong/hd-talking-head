import React, {useLayoutEffect, useMemo, useRef} from "react";
import {cancelRender, continueRender, delayRender} from "remotion";
import contract from "../text-layout-contract.json";
import type {Rect} from "./scene-foundations";

export type TextLayoutSpec = {
  id: string;
  text: string;
  plane: "text.screen";
  bounds: Rect;
  maxLines: number;
  font: {
    family: string;
    size: number;
    weight: 400 | 600 | 700;
    lineHeight: number;
    letterSpacing: number;
  };
  color: string;
  align: "left" | "center" | "right";
  effectOutset: number;
  overflow: "visible";
};

export type TextLayoutMeasurement = {
  contentBounds: Rect;
  lineCount: number;
  scrollWidth: number;
  scrollHeight: number;
  fontFamily: string;
};

const finite = (value: number) => Number.isFinite(value);
const intersects = (left: Rect, right: Rect) => left.x < right.x + right.width && left.x + left.width > right.x &&
  left.y < right.y + right.height && left.y + left.height > right.y;

export const validateTextLayoutSpec = (spec: TextLayoutSpec) => {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(spec.id)) throw new Error("text layout id is invalid");
  if (spec.plane !== contract.allowed_plane) throw new Error("text must render in text.screen");
  if (typeof spec.text !== "string" || spec.text.trim() === "") throw new Error("text layout content is empty");
  if (spec.overflow !== "visible") throw new Error("text clipping is forbidden");
  if (!Number.isInteger(spec.maxLines) || spec.maxLines < 1) throw new Error("text maxLines is invalid");
  if (
    !finite(spec.font.size) || spec.font.size <= 0 ||
    !finite(spec.font.lineHeight) || spec.font.lineHeight < 1 ||
    !finite(spec.font.letterSpacing) ||
    typeof spec.font.family !== "string" || spec.font.family.trim() === "" ||
    ![400, 600, 700].includes(spec.font.weight)
  ) throw new Error("text font specification is invalid");
  if (!finite(spec.effectOutset) || spec.effectOutset < 0) throw new Error("text effect outset is invalid");
};

export const assertTextLayout = (
  measurement: TextLayoutMeasurement,
  spec: TextLayoutSpec,
  presenterSafeZone: Rect | null,
) => {
  const tolerance = 1;
  const declaredRight = spec.bounds.x + spec.bounds.width;
  const declaredBottom = spec.bounds.y + spec.bounds.height;
  const contentRight = measurement.contentBounds.x + measurement.contentBounds.width;
  const contentBottom = measurement.contentBounds.y + measurement.contentBounds.height;
  const effective = {
    x: measurement.contentBounds.x - spec.effectOutset,
    y: measurement.contentBounds.y - spec.effectOutset,
    width: measurement.contentBounds.width + spec.effectOutset * 2,
    height: measurement.contentBounds.height + spec.effectOutset * 2,
  };
  if (effective.y + effective.height > contract.safe_line_max_y + tolerance) {
    throw new Error("measured text crosses the soft-safe line");
  }
  if (presenterSafeZone !== null && intersects(effective, presenterSafeZone)) {
    throw new Error("measured text intersects the presenter safe zone");
  }
  if (
    measurement.lineCount > spec.maxLines ||
    measurement.scrollWidth > spec.bounds.width + tolerance ||
    measurement.scrollHeight > spec.bounds.height + tolerance ||
    measurement.contentBounds.x - spec.effectOutset < spec.bounds.x - tolerance ||
    measurement.contentBounds.y - spec.effectOutset < spec.bounds.y - tolerance ||
    contentRight + spec.effectOutset > declaredRight + tolerance ||
    contentBottom + spec.effectOutset > declaredBottom + tolerance
  ) throw new Error(`measured text exceeds its approved bounds or capacity: ${JSON.stringify({measurement, approvedBounds: spec.bounds, maxLines: spec.maxLines, effectOutset: spec.effectOutset})}`);
};

const measureRenderedText = (node: HTMLDivElement, spec: TextLayoutSpec): TextLayoutMeasurement => {
  const range = document.createRange();
  range.selectNodeContents(node);
  const box = node.getBoundingClientRect();
  const content = range.getBoundingClientRect();
  const scale = box.width / spec.bounds.width;
  if (!finite(scale) || scale <= 0) throw new Error("text measurement scale is invalid");
  const lineTops: number[] = [];
  for (const rect of range.getClientRects()) {
    const top = (rect.top - box.top) / scale;
    if (!lineTops.some((value) => Math.abs(value - top) < 1)) lineTops.push(top);
  }
  return {
    contentBounds: {
      x: spec.bounds.x + (content.left - box.left) / scale,
      y: spec.bounds.y,
      width: content.width / scale,
      height: node.scrollHeight,
    },
    lineCount: lineTops.length,
    scrollWidth: node.scrollWidth,
    scrollHeight: node.scrollHeight,
    fontFamily: getComputedStyle(node).fontFamily,
  };
};

export const ScreenTextBlock: React.FC<{
  spec: TextLayoutSpec;
  presenterSafeZone: Rect | null;
}> = ({spec, presenterSafeZone}) => {
  validateTextLayoutSpec(spec);
  const nodeRef = useRef<HTMLDivElement>(null);
  const renderHandle = useMemo(() => delayRender(`measure text layout: ${spec.id}`), [spec.id]);

  useLayoutEffect(() => {
    let active = true;
    let settled = false;
    const fontQuery = `${spec.font.weight} ${spec.font.size}px ${spec.font.family}`;
    document.fonts.load(fontQuery, spec.text).then(() => {
      if (!active) return;
      if (!document.fonts.check(fontQuery, spec.text)) throw new Error("approved text font is unavailable");
      const node = nodeRef.current;
      if (node === null) throw new Error("rendered text node is unavailable");
      const measurement = measureRenderedText(node, spec);
      assertTextLayout(measurement, spec, presenterSafeZone);
      node.dataset.layoutMeasurement = JSON.stringify(measurement);
      settled = true;
      continueRender(renderHandle);
    }).catch((error: unknown) => {
      if (!active) return;
      settled = true;
      cancelRender(error instanceof Error ? error : new Error("text layout measurement failed"));
    });
    return () => {
      active = false;
      if (!settled) continueRender(renderHandle);
    };
  }, [presenterSafeZone, renderHandle, spec]);

  return <div
    ref={nodeRef}
    data-text-layout-id={spec.id}
    data-text-plane={spec.plane}
    style={{
      position: "absolute",
      left: spec.bounds.x,
      top: spec.bounds.y,
      width: spec.bounds.width,
      color: spec.color,
      fontFamily: spec.font.family,
      fontSize: spec.font.size,
      fontWeight: spec.font.weight,
      lineHeight: spec.font.lineHeight,
      letterSpacing: spec.font.letterSpacing,
      textAlign: spec.align,
      whiteSpace: "pre-wrap",
      overflow: "visible",
      overflowWrap: "normal",
      wordBreak: "normal",
    }}
  >{spec.text}</div>;
};
