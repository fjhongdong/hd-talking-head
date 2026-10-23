export type ThresholdOverlayInput = {
  schema_version: 1;
  canvas: {width: 1080; height: 1920; fps: 24; frames: number};
  labels: {fixed: string; moving: string};
  timing: {
    panel: number; plate: number; fixed_label: number; node: number; axis: number;
    shift: number; shift_duration: number; threshold: number; connector: number;
    moving_label: number; exit: number; exit_duration: number;
  };
};

export type RelationOverlayInput = {
  schema_version: 2;
  mode: 'flow' | 'contrast';
  canvas: {width: 1080; height: 1920; fps: 24; frames: number};
  labels: string[];
  timing: {panel: number; first?: number; step?: number; label_times?: number[]; exit: number; exit_duration: number};
};

export type ArollOverlayInput = ThresholdOverlayInput | RelationOverlayInput;

export type ArollOverlayBrief = {
  schema_version: 1;
  renderer_input: ArollOverlayInput;
  source_binding: {aroll_sha256: string; segment_id: string; start: number; end: number};
};
