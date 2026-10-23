import {useLayoutEffect, useRef} from "react";
import type {Timeline} from "./anime-runtime";
import {claimNamespace} from "./isolation";

export const animationSeekMs = (animationLocalFrame: number, leadFrames = 0, fps = 24) => {
  if (!Number.isInteger(animationLocalFrame) || animationLocalFrame < 0 ||
      !Number.isInteger(leadFrames) || leadFrames < 0 || fps !== 24) {
    throw new Error("animation seek input is invalid");
  }
  return Math.max(0, animationLocalFrame - leadFrames) * 1000 / fps;
};

export type AnimeSetup = (input: {
  root: HTMLElement;
  namespace: string;
  seed: string;
}) => Timeline;

export const useAnimeFrameSeek = ({
  rootRef, namespace, seed, instanceKey, animationLocalFrame, leadFrames = 0, setup,
}: {
  rootRef: React.RefObject<HTMLElement | null>;
  namespace: string;
  seed: string;
  instanceKey: string;
  animationLocalFrame: number;
  leadFrames?: number;
  setup: AnimeSetup;
}) => {
  const timelineRef = useRef<Timeline | null>(null);
  const setupRef = useRef(setup);
  setupRef.current = setup;
  const seekMs = animationSeekMs(animationLocalFrame, leadFrames);

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) throw new Error("anime root is unavailable");
    const release = claimNamespace(namespace, root);
    let timeline: Timeline | null = null;
    try {
      timeline = setupRef.current({root, namespace, seed});
      timeline.pause();
      timeline.seek(seekMs, true);
      timelineRef.current = timeline;
      root.dataset.talkcraftReady = "true";
    } catch (error) {
      timeline?.revert();
      release();
      throw error;
    }
    return () => {
      delete root.dataset.talkcraftReady;
      timelineRef.current = null;
      timeline?.revert();
      release();
    };
  }, [instanceKey, namespace, rootRef, seed]);

  useLayoutEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) throw new Error("anime timeline is unavailable");
    timeline.seek(seekMs, true);
  }, [seekMs]);
};
