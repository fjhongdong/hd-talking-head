import React, {useLayoutEffect, useRef} from "react";
import * as THREE from "three";
import type {Timeline} from "./anime-runtime";
import {animationSeekMs} from "./anime-bridge";
import {claimNamespace} from "./isolation";

type Dispose = () => void;
export type ThreeSetup = (input: {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  namespace: string;
  seed: string;
  registerDispose: (dispose: Dispose) => void;
}) => Timeline;

const disposeAll = (disposers: Dispose[]) => {
  const errors: unknown[] = [];
  for (const dispose of [...disposers].reverse()) {
    try { dispose(); } catch (error) { errors.push(error); }
  }
  if (errors.length) throw new AggregateError(errors, "Three resources failed to dispose");
};

export const ThreeFrameCanvas: React.FC<{
  namespace: string;
  seed: string;
  instanceKey: string;
  animationLocalFrame: number;
  leadFrames?: number;
  width: number;
  height: number;
  setup: ThreeSetup;
  style?: React.CSSProperties;
}> = ({namespace, seed, instanceKey, animationLocalFrame, leadFrames = 0, width, height, setup, style}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<{timeline: Timeline; renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera} | null>(null);
  const setupRef = useRef(setup);
  setupRef.current = setup;
  const seekMs = animationSeekMs(animationLocalFrame, leadFrames);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) throw new Error("Three canvas is unavailable");
    const release = claimNamespace(namespace, canvas);
    const disposers: Dispose[] = [];
    const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true, preserveDrawingBuffer: true});
    renderer.setPixelRatio(1);
    renderer.setSize(width, height, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x000000, 0);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 100);
    camera.position.set(0, 0, 5);
    let timeline: Timeline | null = null;
    try {
      timeline = setupRef.current({scene, camera, namespace, seed, registerDispose: (dispose) => disposers.push(dispose)});
      timeline.pause();
      timeline.seek(seekMs, true);
      scene.updateMatrixWorld(true);
      camera.updateMatrixWorld(true);
      renderer.clear();
      renderer.render(scene, camera);
      stateRef.current = {timeline, renderer, scene, camera};
      canvas.dataset.talkcraftReady = "true";
    } catch (error) {
      timeline?.revert();
      disposeAll(disposers);
      renderer.dispose();
      release();
      throw error;
    }
    return () => {
      delete canvas.dataset.talkcraftReady;
      stateRef.current = null;
      const errors: unknown[] = [];
      try { timeline?.revert(); } catch (error) { errors.push(error); }
      try { disposeAll(disposers); } catch (error) { errors.push(error); }
      scene.clear();
      try { renderer.dispose(); } catch (error) { errors.push(error); }
      release();
      if (errors.length) throw new AggregateError(errors, "Three bridge cleanup failed");
    };
  }, [height, instanceKey, namespace, seed, width]);

  useLayoutEffect(() => {
    const state = stateRef.current;
    if (!state) throw new Error("Three bridge is unavailable");
    state.timeline.seek(seekMs, true);
    state.scene.updateMatrixWorld(true);
    state.camera.updateMatrixWorld(true);
    state.renderer.clear();
    state.renderer.render(state.scene, state.camera);
  }, [seekMs]);

  return <canvas ref={canvasRef} data-talkcraft-scope={namespace} width={width} height={height} style={style}/>;
};
