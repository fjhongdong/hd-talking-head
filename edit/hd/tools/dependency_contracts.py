"""Shared static execution identities and the one parent output policy."""
from __future__ import annotations
from typing import Any, Mapping

DEPENDENCY_CONTRACTS = {
    'html-video': {"executor": 'reference_adapter', "renderer": 'HyperFrames', "output": 'alpha_video'},
    'hyperframes': {"executor": 'reference_adapter', "renderer": 'HyperFrames', "output": 'alpha_video'},
    'hd-talking-head-local-canonical': {"executor": 'reference_adapter', "renderer": 'HyperFrames', "output": 'alpha_video'},
    'hd-talking-head-relation-motion': {"executor": 'reference_adapter', "renderer": 'RelationMotion', "output": 'opaque_video'},
    'hd-talking-head-semantic-state': {"executor": 'reference_adapter', "renderer": 'SemanticState', "output": 'opaque_video'},
    'hd-talking-head-talkcraft': {"executor": 'reference_adapter', "renderer": 'Remotion', "output": 'opaque_video'},
    'hd-talking-head-talkcraft-overlay': {"executor": 'reference_adapter', "renderer": 'Remotion', "output": 'alpha_video'},
    'paper-collage-ad': {"executor": 'reference_adapter', "renderer": 'PaperCollage', "output": 'opaque_video'},
    'whiteboard-video': {"executor": 'reference_adapter', "renderer": 'Whiteboard', "output": 'opaque_video'},
    'doudou-remotion-whiteboard': {"executor": 'reference_adapter', "renderer": 'Remotion', "output": 'opaque_video'},
    'talkcraft-native-adaptation': {"executor": 'reference_adapter', "renderer": 'Remotion', "output": 'opaque_video'},
    'hyperframes-native-adaptation': {"executor": 'reference_adapter', "renderer": 'HyperFrames', "output": 'by_composition'},
    'paper-collage-hyperframes': {"executor": 'reference_adapter', "renderer": 'HyperFrames', "output": 'opaque_video'},
    'lemo-opuscar': {"executor": 'reference_adapter', "renderer": 'HTMLCanvas', "output": 'opaque_video'},
    'onetake': {"executor": 'reference_adapter', "renderer": 'HTMLCanvas', "output": 'opaque_video'},
    'adu-motion-video': {"executor": 'reference_adapter', "renderer": 'HTMLCanvas', "output": 'opaque_video'},
    'hypit-native-chat': {"executor": 'reference_adapter', "renderer": 'HTMLCanvas', "output": 'opaque_video'},
    'huashu-art-motion': {"executor": 'reference_adapter', "renderer": 'HTMLCanvas', "output": 'opaque_video'},
    'eian-riso-broll': {"executor": 'reference_adapter', "renderer": 'HTMLCanvas', "output": 'opaque_video'},
    'wise-motion': {"executor": 'reference_adapter', "renderer": 'Remotion', "output": 'opaque_video'},
    'openfilm-motion-graphics': {"executor": 'reference_adapter', "renderer": 'OpenFilm', "output": 'opaque_video'},
    'overlay-studio-native': {"executor": 'reference_adapter', "renderer": 'OverlayStudio', "output": 'alpha_video'},
    'huashu-motion-native': {"executor": 'reference_adapter', "renderer": 'HuashuMotion', "output": 'alpha_video'},
    'motion-graphics-native': {"executor": 'reference_adapter', "renderer": 'HyperFrames', "output": 'alpha_video'},
    'lemo-wake': {"executor": 'reference_adapter', "renderer": 'HTMLCanvas', "output": 'opaque_video'},
    'video-talkcraft': {"executor": 'reference_adapter', "renderer": 'Remotion', "output": 'opaque_video'},
    'barty-motion-graphics': {"executor": 'reference_adapter', "renderer": 'HTMLCanvas', "output": 'by_composition'},
    'bang-motion': {"executor": 'reference_adapter', "renderer": 'HTMLCanvas', "output": 'opaque_video'},
}

PRIMARY_RENDERERS = {key: value["renderer"] for key, value in DEPENDENCY_CONTRACTS.items()}
REFERENCE_ADAPTER_DEPENDENCIES = frozenset(DEPENDENCY_CONTRACTS)

def _contract(dependency_id):
    if not isinstance(dependency_id, str) or dependency_id not in DEPENDENCY_CONTRACTS:
        raise ValueError("code generation requires a registered dependency")
    return DEPENDENCY_CONTRACTS[dependency_id]


def executor_for(kind: str, binding: Mapping[str, Any]) -> str:
    if kind in {"local_material", "official_material", "external_stock"}:
        return {"local_material": "local-media", "official_material": "official-media", "external_stock": "external-stock"}[kind]
    if kind == "code_generated":
        return _contract(binding.get("dependency_id"))["executor"]
    model = binding.get("model")
    if not isinstance(model, str) or not model:
        model = "invalid-binding"
    if model == "grok-imagine-video":
        return "OpenMontage:GrokVideo"
    provider = binding.get("provider")
    if not isinstance(provider, str) or not provider:
        provider = "invalid-binding"
    return f"ai-provider:{provider}:{model}"


def output_alpha(kind: str, dependency_id: Any, family: Any, layer_role: Any) -> bool:
    if kind != "code_generated":
        return False
    mode = _contract(dependency_id)["output"]
    if mode == "by_composition":
        return (family == "aroll_with_overlay" or
                (family == "evidence_with_data_overlay" and layer_role == "annotation"))
    return mode == "alpha_video"
