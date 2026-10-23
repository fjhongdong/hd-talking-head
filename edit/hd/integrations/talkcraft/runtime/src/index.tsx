import React from "react";
import {Composition, registerRoot} from "remotion";
import {MechanismProbe, type ProbeProps} from "./mechanism-probe";
import {FoundationProbe, type FoundationProbeProps} from "./foundation-probe";
import {SceneProbe, type SceneProbeProps} from "./scene-probe";
import {TextLayoutProbe, type TextLayoutProbeProps} from "./text-layout-probe";
import {TimeDomainProbe, type TimeDomainProbeProps} from "./time-domain-probe";
import {DeterminismProbe, type DeterminismProbeProps} from "./determinism-probe";
import foundationContract from "../foundation-contract.json";
import sceneContract from "../scene-foundation-contract.json";

type RuntimeProps = ProbeProps & {durationInFrames?: number};

const defaults: RuntimeProps = {
  mode: "text",
  alpha: false,
  title: "TalkCraft",
  value: 108,
  namespace: "talkcraft-probe",
  durationInFrames: 48,
};

const foundationDefaults: FoundationProbeProps = {
  kind: "backdrop",
  sourceFrames: foundationContract.source_frames,
  namespace: "talkcraft-foundation-probe",
  durationInFrames: 36,
};

const sceneDefaults: SceneProbeProps = {
  sourceFrames: sceneContract.probe.source_frames,
  durationInFrames: sceneContract.probe.variants.length * sceneContract.probe.source_frames.length,
};

const textLayoutDefaults: TextLayoutProbeProps = {mode: "valid", durationInFrames: 1};
const timeDomainDefaults: TimeDomainProbeProps = {globalFrames: [48, 72, 95], durationInFrames: 3};
const determinismDefaults: DeterminismProbeProps = {animationLocalFrames: [0, 24, 47], durationInFrames: 3};

const Root: React.FC = () => (
  <>
    <Composition
      id="TalkCraftMechanismProbe"
      component={MechanismProbe}
      width={1080}
      height={1920}
      fps={24}
      durationInFrames={48}
      defaultProps={defaults}
      calculateMetadata={({props}) => ({
        durationInFrames: Number((props as RuntimeProps).durationInFrames ?? 48),
      })}
    />
    <Composition
      id="TalkCraftFoundationProbe"
      component={FoundationProbe}
      width={1080}
      height={1920}
      fps={24}
      durationInFrames={36}
      defaultProps={foundationDefaults}
      calculateMetadata={({props}) => ({
        durationInFrames: Number((props as FoundationProbeProps).durationInFrames ?? 36),
      })}
    />
    <Composition
      id="TalkCraftSceneFoundationProbe"
      component={SceneProbe}
      width={1080}
      height={1920}
      fps={24}
      durationInFrames={sceneDefaults.durationInFrames}
      defaultProps={sceneDefaults}
      calculateMetadata={({props}) => ({
        durationInFrames: Number((props as SceneProbeProps).durationInFrames ?? sceneDefaults.durationInFrames),
      })}
    />
    <Composition
      id="TalkCraftTextLayoutProbe"
      component={TextLayoutProbe}
      width={1080}
      height={1920}
      fps={24}
      durationInFrames={1}
      defaultProps={textLayoutDefaults}
      calculateMetadata={({props}) => ({
        durationInFrames: Number((props as TextLayoutProbeProps).durationInFrames ?? 1),
      })}
    />
    <Composition
      id="TalkCraftTimeDomainProbe"
      component={TimeDomainProbe}
      width={1080}
      height={1920}
      fps={24}
      durationInFrames={3}
      defaultProps={timeDomainDefaults}
      calculateMetadata={({props}) => ({
        durationInFrames: Number((props as TimeDomainProbeProps).durationInFrames ?? 3),
      })}
    />
    <Composition
      id="TalkCraftDeterminismProbe"
      component={DeterminismProbe}
      width={1080}
      height={1920}
      fps={24}
      durationInFrames={3}
      defaultProps={determinismDefaults}
      calculateMetadata={({props}) => ({
        durationInFrames: Number((props as DeterminismProbeProps).durationInFrames ?? 3),
      })}
    />
  </>
);

registerRoot(Root);
