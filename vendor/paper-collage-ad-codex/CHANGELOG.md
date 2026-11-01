# Changelog

## 1.1.0 — Gemini Omni intermediate pass

- Add an optional Gemini Omni motion-draft stage between approved keyframes and final animation.
- Document ChatCut `model: "omni"` first-frame drafting and `continueFrom` localized editing.
- Route 1080p, clips longer than 10 seconds, exact CJK text, extensions and finishing work to Seedance, Kling or HyperFrames.
- Add a copyable Omni shot-plan example while keeping credentials and project assets outside the repository.

## 1.0.1 — Complete workflow guide

- Add a complete Chinese workflow from Codex installation and project setup through storyboard, keyframes, animation, optional IndexTTS-2 voice cloning, music, sound effects, assembly, QC and delivery.
- Distinguish one-time machine dependencies from per-project private voice and production assets.
- Document the exact local paths used by the optional TTS runtime, reference recording, speaker conditioning and final narration.

## 1.0.0 — Codex edition

- Package the full paper-collage advertisement workflow for OpenAI Codex desktop and CLI.
- Include deterministic storyboard, layered-animation, rendering, assembly and QC resources.
- Add optional Seedance, Jimeng, MiniMax and ElevenLabs adapters that read credentials only from environment variables.
- Add a local Apple-Silicon IndexTTS-2 MLX wrapper for authorized user-supplied voice references.
- Keep reference audio, speaker conditioning, model weights, generated narration and project media out of Git by default.
- Remove private brand, voice and project-specific production assets from the public package.
