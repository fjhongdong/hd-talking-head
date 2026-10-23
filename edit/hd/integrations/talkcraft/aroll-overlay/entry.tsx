import React from 'react';
import {AbsoluteFill, Composition, registerRoot, useCurrentFrame, useVideoConfig} from 'remotion';
import {Sketch, Panel, Plate, Connector, Node, Label, DrawPath, inOut2} from '../upstream/template/motion-systems/schematic';
import type {ArollOverlayInput, RelationOverlayInput, ThresholdOverlayInput} from './types';

const ink = '#f3f6fb';
const accent = '#67c8ff';
const warm = '#ffc94d';

const Threshold: React.FC<ThresholdOverlayInput> = (input) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const progress = Math.min(1, Math.max(0, (t - input.timing.shift) / input.timing.shift_duration));
  const shift = 360 * inOut2(progress);
  const opacity = Math.min(1, Math.max(0, (input.timing.exit - t) / input.timing.exit_duration));
  return <AbsoluteFill style={{background: 'transparent'}}>
    <Sketch width={input.canvas.width} height={input.canvas.height} opacity={opacity}>
      <Panel abs={t} at={input.timing.panel} x={68} y={113} w={944} h={175} r={22} alpha={0.88} dark/>
      <Label abs={t} at={input.timing.fixed_label} x={214} y={174} text={input.labels.fixed} size={36} color={ink}/>
      <Node abs={t} at={input.timing.node} x={214} y={225} r={16} color={accent} fill={accent}/>
      <Connector abs={t} at={input.timing.axis} from={{x:236,y:225}} to={{x:876,y:225}} color={ink} width={4} arrow/>
      <DrawPath abs={t} at={input.timing.threshold} d={`M ${325 + shift} 200 V 253`} color={warm} width={7}/>
      <Label abs={t} at={input.timing.moving_label} x={325 + shift} y={174} text={input.labels.moving} size={36} color={warm}/>
      <Connector abs={t} at={input.timing.connector} from={{x:325,y:258}} to={{x:325 + shift,y:258}} color={warm} width={5} dashed={8}/>
    </Sketch>
  </AbsoluteFill>;
};

const Relation: React.FC<RelationOverlayInput> = (input) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const opacity = Math.min(1, Math.max(0, (input.timing.exit - t) / input.timing.exit_duration));
  const isFlow = input.mode === 'flow';
  const centers = isFlow ? [200, 540, 880] : [315, 765];
  const labelTimes = input.timing.label_times ?? input.labels.map((_, index) => (input.timing.first ?? 0) + index * (input.timing.step ?? 0));
  return <AbsoluteFill style={{background: 'transparent'}}>
    <Sketch width={input.canvas.width} height={input.canvas.height} opacity={opacity}>
      <Panel abs={t} at={input.timing.panel} x={92} y={72} w={896} h={260} r={28} alpha={0.88} dark/>
      {input.labels.map((label, index) => {
        const at = labelTimes[index];
        const x = centers[index];
        const active = isFlow ? index === input.labels.length - 1 : index === 1;
        return <React.Fragment key={`${index}-${label}`}>
          <Plate abs={t} at={at} dur={0.25} fillDelay={0} x={x - 118} y={147} w={236} h={118} r={24}
            color={active ? warm : ink} width={4}
            fill={active ? 'rgba(255,201,77,0.92)' : 'rgba(40,54,75,0.82)'}/>
          <Label abs={t} at={at + 0.55} x={x} y={210} text={label} size={38}
            color={active ? '#172131' : ink}/>
        </React.Fragment>;
      })}
      {isFlow && <>
        <Connector abs={t} at={labelTimes[1] - 0.12}
          from={{x:322,y:207}} to={{x:418,y:207}} color={accent} width={5} arrow/>
        <Connector abs={t} at={labelTimes[2] - 0.12}
          from={{x:662,y:207}} to={{x:758,y:207}} color={accent} width={5} arrow/>
      </>}
      {!isFlow && <DrawPath abs={t} at={labelTimes[1] - 0.12}
        d="M 531 139 V 279" color={accent} width={5}/>}
    </Sketch>
  </AbsoluteFill>;
};

const Overlay: React.FC<ArollOverlayInput> = (input) =>
  input.schema_version === 1 ? <Threshold {...input}/> : <Relation {...input}/>;

export const RemotionRoot: React.FC = () => (
  <Composition<any, ArollOverlayInput>
    id="ArollOverlay"
    component={Overlay}
    defaultProps={{schema_version: 1, canvas: {width: 1080, height: 1920, fps: 24, frames: 1}, labels: {fixed: '能力', moving: '标准'}, timing: {panel: .2, plate: .3, fixed_label: .5, node: .8, axis: .9, shift: 1.6, shift_duration: .7, threshold: 1.65, connector: 2.35, moving_label: 2.55, exit: 3.2, exit_duration: .25}}}
    durationInFrames={1}
    fps={24}
    width={1080}
    height={1920}
    calculateMetadata={({props}) => ({durationInFrames: props.canvas.frames, fps: props.canvas.fps, width: props.canvas.width, height: props.canvas.height})}
  />
);

registerRoot(RemotionRoot);
