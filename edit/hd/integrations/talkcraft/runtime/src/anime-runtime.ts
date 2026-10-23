import "animejs/adapters/three";
import {engine} from "animejs";

engine.useDefaultMainLoop = false;
engine.pauseOnDocumentHidden = false;
engine.pause();

export {createTimeline} from "animejs";
export type {Timeline} from "animejs";
