import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SubtitleCue, SubtitleEmphasis} from './types';
import {C, FONT} from '../upstream/template/motion-systems/theme';
import {lineUnits} from './line-units.mjs';

const TEXT = C.text;
const GOLD = C.gold;
const BORDER = C.line;
const CARD = 'rgba(7, 11, 20, 0.72)';

export const SUBTITLE_TEXT_STYLE = {
  fontFamily: FONT.cn,
  fontSize: 48,
  fontWeight: 600,
  letterSpacing: 2,
};
export const SUBTITLE_CARD_METRICS = {paddingX: 42, borderWidth: 1};

const utf16Slice = (text: string, start: number, end: number) => text.slice(start, end);

const emphasisRange = (cue: SubtitleCue): SubtitleEmphasis | null => cue.emphasis;

export const Subtitles: React.FC<{cues: SubtitleCue[]}> = ({cues}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const cue = cues.find((item) => t >= item.start && t < item.end);
  if (!cue) return null;

  const emphasis = emphasisRange(cue);
  const narrow = cue.placement === 'above_avatar';
  const cardWidth = cue.placement === 'above_avatar' ? cue.width : undefined;
  const units: {start: number; end: number}[] = narrow
    ? lineUnits(cue.text, emphasis)
    : [{start: 0, end: cue.text.length}];
  const popped = Boolean(emphasis && t >= emphasis.start);
  const since = emphasis ? Math.max(0, t - emphasis.start) : 0;
  const lift = popped
    ? since < 0.18
      ? interpolate(since, [0, 0.18], [0, -4], {easing: Easing.out(Easing.quad)})
      : since < 0.4
        ? interpolate(since, [0.18, 0.4], [-4, 0], {easing: Easing.inOut(Easing.quad), extrapolateRight: 'clamp'})
        : 0
    : 0;

  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: cue.placement === 'above_avatar' ? 'flex-start' : 'center', pointerEvents: 'none'}}>
      <div style={{
        marginBottom: cue.bottom,
        marginLeft: cue.placement === 'above_avatar' ? 80 : 0,
        boxSizing: 'border-box',
        width: cardWidth,
        padding: `14px ${SUBTITLE_CARD_METRICS.paddingX}px`,
        borderRadius: 14,
        background: CARD,
        border: `${SUBTITLE_CARD_METRICS.borderWidth}px solid ${BORDER}`,
        ...SUBTITLE_TEXT_STYLE,
        maxWidth: narrow ? cardWidth : '90%',
        textAlign: 'center',
        textWrap: cue.placement === 'above_avatar' ? 'balance' : undefined,
        color: TEXT,
      }}>
        {units.map((unit) => {
          const marked = emphasis && unit.start <= emphasis.text_start && unit.end >= emphasis.text_end;
          return <React.Fragment key={unit.start}>
            <span style={narrow ? {whiteSpace: 'nowrap'} : undefined}>
              {marked && emphasis ? <>
                {utf16Slice(cue.text, unit.start, emphasis.text_start)}
                <span style={{display: 'inline-block', color: popped ? GOLD : TEXT, fontWeight: 600, transform: lift ? `translateY(${lift}px)` : undefined, textShadow: popped ? '0 0 12px rgba(255, 201, 77, 0.38)' : undefined}}>{utf16Slice(cue.text, emphasis.text_start, emphasis.text_end)}</span>
                {utf16Slice(cue.text, emphasis.text_end, unit.end)}
              </> : utf16Slice(cue.text, unit.start, unit.end)}
            </span>
            {narrow && unit.end < cue.text.length ? <wbr /> : null}
          </React.Fragment>;
        })}
      </div>
    </AbsoluteFill>
  );
};
