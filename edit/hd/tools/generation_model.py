"""Single source of truth for generation channel model identity."""
from __future__ import annotations

import json
from pathlib import Path


def validate_binding(binding):
    if not isinstance(binding, dict) or binding.get("mode") not in {"argument", "fixed"}:
        raise ValueError("generation channel model_binding is missing or invalid")
    if binding["mode"] == "argument" and (not isinstance(binding.get("parameter"), str) or not binding["parameter"].strip()):
        raise ValueError("argument model_binding must declare a parameter")
    if binding["mode"] == "fixed" and set(binding) != {"mode"}:
        raise ValueError("fixed model_binding cannot declare a parameter")
    return binding


def _binding(job_dir, channel):
    path = Path(job_dir) / "manifests/generation-channels.json"
    binding = None
    if path.is_file():
        data = json.loads(path.read_text())
        purpose = channel.get("purpose")
        binding = data.get(purpose, {}).get("model_binding")
    return validate_binding(binding)


def prepare_arguments(job_dir, channel, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("generation arguments must be an object")
    args = dict(arguments)
    binding = _binding(job_dir, channel)
    model = channel.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("generation channel has no confirmed model")
    parameter = binding["parameter"] if binding["mode"] == "argument" else "model"
    if binding["mode"] == "argument":
        if parameter in args and args[parameter] != model:
            raise ValueError("requested model differs from the confirmed channel")
        args.setdefault(parameter, model)
    elif any(key in args for key in ("model", "model_id")):
        raise ValueError("fixed generation channel must not receive a model parameter")
    return args


def request_identity(job_dir, request, config):
    if not isinstance(request, dict) or not isinstance(config, dict):
        raise ValueError("invalid generation request or configuration")
    purpose = request.get("purpose")
    providers = [p for p in config.get("providers", []) if p.get("purpose") == purpose]
    if len(providers) != 1:
        raise ValueError("generation channel configuration is incomplete")
    channel = dict(providers[0])
    channel["purpose"] = purpose
    if request.get("tool") != channel.get("endpoint_id"):
        raise ValueError("generation tool differs from confirmed provider")
    binding = _binding(job_dir, channel)
    original_args = request.get("arguments")
    args = prepare_arguments(job_dir, channel, original_args)
    if args != original_args:
        raise ValueError("generation request must be prepared with its confirmed model before queueing")
    if purpose == "video" and (channel.get("provider") == "Lovart" or request.get("tool") == "mcp__lovart__generate_video"):
        if not isinstance(args.get("project_id"), str) or not args["project_id"]:
            raise ValueError("Lovart requires one real project_id")
    return {"provider": channel["provider"], "model": channel["model"],
            "endpoint_id": channel["endpoint_id"], "model_binding": binding}
