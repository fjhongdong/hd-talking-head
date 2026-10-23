import React, {useRef} from "react";
import {AbsoluteFill, useCurrentFrame} from "remotion";
import * as THREE from "three";
import {createTimeline} from "./anime-runtime";
import {useAnimeFrameSeek, type AnimeSetup} from "./anime-bridge";
import {scopedClass, scopedSelector, seededUnit, svgId, svgUrl} from "./isolation";
import {SceneFoundation, type SceneLayout} from "./scene-foundations";
import {ThreeFrameCanvas, type ThreeSetup} from "./three-bridge";

export type DeterminismProbeProps = {animationLocalFrames: number[]; durationInFrames?: number};

const layout: SceneLayout = {
  activeSubjectGroups: 3,
  heroGroups: 1,
  demotedGroups: 1,
  emptyQuadrant: "top-right",
  textBounds: [{x: 72, y: 1580, width: 936, height: 90}],
  decorationBounds: [],
  presenterSafeZone: null,
};

const AnimeCard: React.FC<{namespace: string; seed: string; color: string; frame: number}> = ({namespace, seed, color, frame}) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const setup: AnimeSetup = ({root}) => {
    const target = root.querySelector(scopedSelector(namespace, "target"));
    if (!(target instanceof HTMLElement)) throw new Error("scoped anime target is unavailable");
    return createTimeline({autoplay: false}).add(target, {
      translateX: [-48, 48],
      rotate: [-8, 8],
      opacity: [0, 1],
      duration: 2000,
      ease: "inOutSine",
    }, 0);
  };
  useAnimeFrameSeek({
    rootRef, namespace, seed, instanceKey: `${namespace}:${seed}`,
    animationLocalFrame: frame, setup,
  });
  const dots = Array.from({length: 5}, (_, index) => ({
    left: 18 + seededUnit(seed, "dot-x", index) * 230,
    top: 18 + seededUnit(seed, "dot-y", index) * 120,
  }));
  const paint = svgId(namespace, "paint");
  return <div ref={rootRef} data-talkcraft-scope={namespace} style={{width: 390, height: 300, borderRadius: 36, background: "#ffffff", border: "2px solid #d5d7dd", overflow: "hidden", position: "relative"}}>
    <svg width="390" height="300" style={{position: "absolute", inset: 0}}>
      <defs><linearGradient id={paint}><stop stopColor={color}/><stop offset="1" stopColor="#111827"/></linearGradient></defs>
      <rect x="24" y="22" width="342" height="256" rx="28" fill={svgUrl(namespace, "paint")}/>
      {dots.map((dot, index) => <circle key={index} cx={dot.left} cy={dot.top} r="5" fill="rgba(255,255,255,.7)"/>)}
    </svg>
    <div className={scopedClass(namespace, "target")} style={{opacity: 0, position: "absolute", left: 108, top: 88, width: 174, height: 124, borderRadius: 24, background: "rgba(255,255,255,.9)", color: "#111827", display: "grid", placeItems: "center", fontSize: 42, fontWeight: 800}}>{namespace.endsWith("a") ? "A" : "B"}</div>
  </div>;
};

const setupThree: ThreeSetup = ({scene, camera, registerDispose}) => {
  camera.position.set(0, 0, 5);
  const geometry = new THREE.TorusKnotGeometry(0.9, 0.3, 96, 16);
  const material = new THREE.MeshNormalMaterial();
  registerDispose(() => geometry.dispose());
  registerDispose(() => material.dispose());
  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.x = 0.35;
  scene.add(mesh);
  return createTimeline({autoplay: false}).add(mesh, {
    x: [-0.8, 0.8], rotateY: [0, 210], rotateZ: [0, 35],
    duration: 2000, ease: "inOutSine",
  }, 0);
};

export const DeterminismProbe: React.FC<DeterminismProbeProps> = ({animationLocalFrames}) => {
  const outputFrame = useCurrentFrame();
  const animationLocalFrame = animationLocalFrames[outputFrame];
  const globalFrame = 48 + animationLocalFrame;
  return <SceneFoundation
    sceneId="determinism-probe"
    theme={{preset: "light"}}
    camera={{direction: "push", peakScale: 1.04}}
    sourceFrame={animationLocalFrame}
    durationFrames={72}
    layout={layout}
    background={{screen: <AbsoluteFill style={{background: "radial-gradient(circle at 70% 15%, #dbeafe 0, transparent 38%), #f5f5f7"}}/>, world: null}}
    subject={<AbsoluteFill>
      <div style={{position: "absolute", left: 105, top: 170, display: "flex", gap: 60}}>
        <AnimeCard namespace="probe-a" seed="stable-a" color="#0066ff" frame={animationLocalFrame}/>
        <AnimeCard namespace="probe-b" seed="stable-b" color="#ff375f" frame={animationLocalFrame}/>
      </div>
      <div style={{position: "absolute", left: 160, top: 560, width: 760, height: 760, borderRadius: 52, overflow: "hidden", background: "#0a1020", border: "2px solid #29334d"}}>
        <ThreeFrameCanvas namespace="probe-three" seed="stable-three" instanceKey="probe-three:v1" animationLocalFrame={animationLocalFrame} width={760} height={760} setup={setupThree} style={{width: 760, height: 760}}/>
      </div>
    </AbsoluteFill>}
    text={<div style={{position: "absolute", left: 72, top: 1580, fontSize: 32, color: "#475569"}}>global {globalFrame} → animation-local {animationLocalFrame} · DOM / SVG / WebGL</div>}
  />;
};
