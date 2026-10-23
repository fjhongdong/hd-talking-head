import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Subtitles} from './Subtitles';
import type {SubtitleInput} from './types';

export const Root: React.FC<SubtitleInput> = (input) => <Subtitles cues={input.cues} />;

export const RemotionRoot: React.FC = () => (
  <Composition<any, SubtitleInput>
    id="TalkCraftSubtitles"
    component={Root}
    defaultProps={{schema_version: 1, canvas: {width: 1080, height: 1920, fps: 24, frames: 1}, cues: []}}
    durationInFrames={1}
    fps={24}
    width={1080}
    height={1920}
    calculateMetadata={({props}) => ({
      durationInFrames: props.canvas.frames,
      fps: props.canvas.fps,
      width: props.canvas.width,
      height: props.canvas.height,
    })}
  />
);

export default RemotionRoot;

registerRoot(RemotionRoot);
