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

export type SubtitleCue = {
  cue_id: string;
  start: number;
  end: number;
  text: string;
  words: SubtitleWord[];
  emphasis: SubtitleEmphasis | null;
  placement: 'standard' | 'above_avatar';
  bottom: number;
};

export type SubtitleInput = {
  schema_version: 2;
  canvas: {width: number; height: number; fps: number; frames: number};
  cues: SubtitleCue[];
};
