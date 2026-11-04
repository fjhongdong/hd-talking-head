export type SubtitleWord = {
  start: number;
  end: number;
  text_start: number;
  text_end: number;
};

export type SubtitleEmphasis = {
  text_start: number;
  text_end: number;
  start: number;
  end: number;
};

export type NativeCaptionSource = {
  dependency_id: 'sweety-handdraw-video';
  template_id: `sweety-handdraw-video/style-${string}`;
  segment_id: string;
  component_id: string;
  result_record: {path: string; sha256: string; bytes: number};
};

export type SubtitleCue = {
  cue_id: string;
  start: number;
  end: number;
  text: string;
  words: SubtitleWord[];
  emphasis: SubtitleEmphasis | null;
  long_keyword: boolean;
  bottom: number;
  // Emitted by Python only after verification of this frozen native completion.
  native_caption?: NativeCaptionSource;
} & ({placement: 'standard'} | {placement: 'above_avatar'; width: number});

export type SubtitleInput = {
  schema_version: 2;
  canvas: {width: number; height: number; fps: number; frames: number};
  cues: SubtitleCue[];
};
