import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SubtitleCue, SubtitleEmphasis} from './types';
import {C, FONT} from '../upstream/template/motion-systems/theme';

const TEXT = C.text;
const GOLD = C.gold;
const BORDER = C.line;
const CARD = 'rgba(7, 11, 20, 0.72)';

const utf16Slice = (text: string, start: number, end: number) => text.slice(start, end);

const emphasisRange = (cue: SubtitleCue): SubtitleEmphasis | null => cue.emphasis;

export const Subtitles: React.FC<{cues: SubtitleCue[]}> = ({cues}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const cue = cues.find((item) => t >= item.start && t < item.end);
  if (!cue) return null;

  const emphasis = emphasisRange(cue);
  const before = emphasis ? utf16Slice(cue.text, 0, emphasis.text_start) : cue.text;
  const marked = emphasis ? utf16Slice(cue.text, emphasis.text_start, emphasis.text_end) : '';
  const after = emphasis ? utf16Slice(cue.text, emphasis.text_end, cue.text.length) : '';
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
        marginBottom: cue.placement === 'above_avatar' ? 228 : 350,
        marginLeft: cue.placement === 'above_avatar' ? 80 : 0,
        boxSizing: 'border-box',
        width: cue.placement === 'above_avatar' ? 640 : undefined,
        padding: '14px 42px',
        borderRadius: 14,
        background: CARD,
        border: `1px solid ${BORDER}`,
        fontFamily: FONT.cn,
        fontSize: 48,
        fontWeight: 600,
        letterSpacing: 2,
        maxWidth: cue.placement === 'above_avatar' ? 640 : '90%',
        textAlign: 'center',
        textWrap: cue.placement === 'above_avatar' ? 'balance' : undefined,
        color: TEXT,
      }}>
        {emphasis ? <>
          <span>{before}</span>
          <span style={{display: 'inline-block', color: popped ? GOLD : TEXT, fontWeight: 600, transform: lift ? `translateY(${lift}px)` : undefined, textShadow: popped ? '0 0 12px rgba(255, 201, 77, 0.38)' : undefined}}>{marked}</span>
          <span>{after}</span>
        </> : cue.text}
      </div>
    </AbsoluteFill>
  );
};
