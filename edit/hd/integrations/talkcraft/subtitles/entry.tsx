import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Subtitles, SUBTITLE_CARD_METRICS, SUBTITLE_TEXT_STYLE} from './Subtitles';
import type {SubtitleInput} from './types';
import {lineUnits} from './line-units.mjs';

const validateNarrowWords = async (cues: SubtitleInput['cues']) => {
  const narrow = cues.filter((cue) => cue.placement === 'above_avatar');
  if (!narrow.length) return;
  const probe = document.createElement('span');
  Object.assign(probe.style, {
    position: 'absolute', visibility: 'hidden', whiteSpace: 'nowrap',
    fontFamily: SUBTITLE_TEXT_STYLE.fontFamily,
    fontSize: `${SUBTITLE_TEXT_STYLE.fontSize}px`,
    fontWeight: String(SUBTITLE_TEXT_STYLE.fontWeight),
    letterSpacing: `${SUBTITLE_TEXT_STYLE.letterSpacing}px`,
  });
  document.body.appendChild(probe);
  try {
    await document.fonts.ready;
    for (const cue of narrow) {
      if (cue.placement !== 'above_avatar') continue;
      const available = cue.width - 2 * (SUBTITLE_CARD_METRICS.paddingX + SUBTITLE_CARD_METRICS.borderWidth);
      for (const unit of lineUnits(cue.text, cue.emphasis)) {
        probe.textContent = cue.text.slice(unit.start, unit.end);
        if (probe.getBoundingClientRect().width > available + 0.01) {
          throw new Error(`[TALKCRAFT_SUBTITLES_INVALID] ${cue.cue_id}: complete word at ${unit.start}:${unit.end} does not fit subtitle content width`);
        }
      }
    }
  } finally {
    probe.remove();
  }
};

export const Root: React.FC<SubtitleInput> = (input) => <Subtitles cues={input.cues} />;

export const RemotionRoot: React.FC = () => (
  <Composition<any, SubtitleInput>
    id="TalkCraftSubtitles"
    component={Root}
    defaultProps={{schema_version: 2, canvas: {width: 1080, height: 1920, fps: 24, frames: 1}, cues: []}}
    durationInFrames={1}
    fps={24}
    width={1080}
    height={1920}
    calculateMetadata={async ({props}) => {
      await validateNarrowWords(props.cues);
      return {
        durationInFrames: props.canvas.frames,
        fps: props.canvas.fps,
        width: props.canvas.width,
        height: props.canvas.height,
      };
    }}
  />
);

export default RemotionRoot;

registerRoot(RemotionRoot);
