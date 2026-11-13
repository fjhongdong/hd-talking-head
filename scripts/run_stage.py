#!/usr/bin/env python3
"""Produce directly from real inputs and authorization; the user accepts the final film."""
from __future__ import annotations
from package_paths import PACKAGE_ROOT

import argparse
import copy
from functools import wraps
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter

SKILL = PACKAGE_ROOT


def _creative_adapters():
    from edit.hd.tools.dependency_contracts import CREATIVE_SKILL_ADAPTERS
    return CREATIVE_SKILL_ADAPTERS


def _operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        project = kwargs.get('project', args[1] if function.__name__ == 'execute_stage' and len(args) > 1 else None)
        setup_paths(project)
        from edit.hd.tools.startup import operation_scope
        with operation_scope() as operation:
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                error.add_note('operation_timing=' + json.dumps(operation.metrics()))
                raise
            return {**result, 'operation_timing': operation.metrics()}
    return wrapped


def verify_skill_package(root: Path | None = None) -> dict:
    from verify_skill_release import verify_release
    report = verify_release(root or SKILL)
    if report['status'] != 'pass':
        raise ValueError('Skill package verification failed: ' + '; '.join(report['failures']))
    return report


def setup_paths(project_root: str | Path | None = None) -> Path:
    project = Path(project_root or SKILL).resolve()
    for path in (project, SKILL / 'scripts'):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return project


def _json(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'Expected a JSON object: {path}')
    return value


def _path(job, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else job.job_dir / path


def _startup(job, project: Path) -> None:
    """Refresh stale checks without rewriting identity or configuration approval."""
    from edit.hd.tools import startup, state
    try:
        startup.require_startup(job)
        return
    except state.WorkflowError as error:
        if not any(message in str(error) for message in (
            'preflight is stale', 'preflight does not match the approved visual plan',
        )):
            raise
    command = [sys.executable, str(SKILL / 'scripts/project_python.py'),
               '--project-root', str(project), '--', str(SKILL / 'scripts/dependency_preflight.py'),
               '--manifest', str(SKILL / 'references/dependency-manifest.json'),
               '--project-root', str(project), '--job-context', str(job.root / 'job-context.json'),
               '--output', str(job.job_dir / 'manifests/dependency-preflight.json'), '--summary-only']
    plan = job.job_dir / '07-visual-direction/visual-plan.json'
    if plan.is_file() and job.stages['visual_direction']['status'] == 'completed':
        command += ['--visual-plan', str(plan)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError('Dependency preflight failed: ' + (result.stdout or result.stderr)[-2000:])
    startup.require_startup(job)


def _summary(job, stage: str, **extra) -> dict:
    result = {'job_id': job.job_id, 'job_dir': str(job.job_dir),
              'stage': stage, 'status': job.stages[stage]['status'],
              'revision': job.revision, 'artifacts': job.stages[stage]['artifacts'], **extra}
    if stage == 'visual_direction' and result['status'] == 'ready':
        table = next((r['path'] for r in result['artifacts']
                      if r['path'].endswith('/visual-routing.md')), None)
        if table:
            result['visual_list'] = table
    if stage == 'delivery' and result['status'] == 'completed':
        from edit.hd.tools import delivery_approval
        result.update(delivery_approval.current_delivery_status(job))
        from export_delivery import exported_paths
        result.update(exported_paths(job))
        if result['delivery_status'] == 'delivered':
            result['next'] = '成片已交付，等待用户实际观看后终验。'
    return result


def _finish_stage(job_dir: Path, stage: str, **extra) -> dict:
    from edit.hd.tools import state, delivery_approval
    job = state.load_job(job_dir)
    if job.stages[stage]['status'] == 'ready':
        state.complete(job, stage)
    if stage == 'delivery' and job.stages[stage]['status'] == 'completed':
        delivery_approval.record_delivery(job)
        from export_delivery import export_delivery
        export_delivery(job)
    return _summary(job, stage, **extra)


def _review(job, stage: str, review: dict) -> dict:
    """Consume only real list authorization or delivered-film acceptance."""
    from edit.hd.tools import delivery_approval, visual_confirmation, state
    if (review.get('stage') != stage
            or (stage != 'delivery' and review.get('revision') != job.revision)
            or review.get('job_id') != job.job_id or review.get('job_dir') != str(job.job_dir)
            or review.get('artifacts') != job.stages[stage]['artifacts']
            or not isinstance(review.get('user_confirmation'), str)
            or not review['user_confirmation'].strip()):
        raise ValueError('User confirmation must identify this Job, revision and exact current artifacts')
    if stage == 'visual_direction':
        visual_confirmation.save_user_confirmation(job, review)
        return _summary(job, stage, user_confirmed=True)
    if stage == 'delivery':
        final = next(r for r in job.stages[stage]['artifacts'] if r['path'] == '12-delivery/final.mp4')
        manifest = next(r for r in job.stages[stage]['artifacts'] if r['path'] == '12-delivery/delivery-manifest.json')
        delivery_approval.approve_delivery(job, delivery_manifest_sha256=manifest['sha256'],
            delivery_sha256=final['sha256'], user_confirmation=review['user_confirmation'])
        return _summary(state.load_job(job.job_dir), stage)
    raise ValueError('Machine stages complete automatically; only the visual list and delivered film consume user confirmation')


def run_speech_cleanup(job_dir: Path, project: Path, video_use_result: Path | None = None,
                       invocation_path: Path | None = None, cleanup_plan: Path | None = None) -> dict:
    from edit.hd.tools import speech_edit_v2, state, transcribe
    job = state.load_job(job_dir)
    generation = job_dir / '05-speech-cleanup'
    if video_use_result is not None:
        if invocation_path is None:
            return _summary(job, 'speech_cleanup', actions=[{'action':'provide_transcription_invocation', 'argument':'--invocation-json'}])
        transcribe.transcribe_job(job, video_use_result=_path(job, video_use_result),
                                 invocation=_json(_path(job, invocation_path)))
        job = state.load_job(job_dir)
    elif not (generation / 'report.json').is_file():
        return _summary(job, 'speech_cleanup', actions=[{'action':'provide_transcription_result', 'arguments':['--video-use-result', '--invocation-json']}])
    if cleanup_plan is not None:
        speech_edit_v2.prepare_cleanup_proposal(job, plan=_json(_path(job, cleanup_plan)))
    result = _summary(state.load_job(job_dir), 'speech_cleanup')
    if not (generation / 'cleanup-proposal.json').is_file():
        result['actions'] = [{'action':'provide_cleanup_plan', 'argument':'--cleanup-plan'}]
        result['next'] = '按原稿校对并提供 --cleanup-plan，复用当前转写，不重复识别。'
    return result


def run_visual_direction(job_dir: Path, project: Path, director_brief: Path | None = None,
                         treatment: Path | None = None, reviewed_visual_text: Path | None = None) -> dict:
    from edit.hd.tools import state, visual_plan, visual_confirmation, avatar_profile, contract_artifacts
    job = state.load_job(job_dir)
    if director_brief is None or treatment is None:
        return _summary(job, 'visual_direction', actions=[{'action':'provide_visual_plan', 'arguments':['--director-brief', '--treatment']}])
    reviewed = _json(_path(job, reviewed_visual_text)) if reviewed_visual_text else None
    director = _json(_path(job, director_brief))
    planned = avatar_profile.plan_avatar_policy(director['segments'])
    if planned['actions']:
        return _summary(job, 'visual_direction', prepared=False, needs_visual_preparation=True,
            actions=planned['actions'],
            next='宿主按目标时窗延续原生末态，保留原声与编号；重新准备brief、绑定、完整口播引用、阅读窗和真实头像采样后重入本阶段。未支持安全末态保持时先内部调整草稿，不请求额外用户确认。')
    if planned['segments'] != director['segments']:
        director = {**director, 'segments': planned['segments']}
        digest = contract_artifacts.sha256_json(director)[:16]
        normalized = job.job_dir / '07-visual-confirmation' / 'drafts' / (digest + '.json')
        normalized.parent.mkdir(parents=True, exist_ok=True)
        contract_artifacts.write_json_artifact(normalized, director)
        director_brief = normalized
    source = visual_confirmation.prepare_visual_confirmation(job, _path(job, director_brief),
        _path(job, treatment), reviewed_visual_text=reviewed)
    result = _summary(state.load_job(job_dir), 'visual_direction')
    result['confirmation_source'] = str(source.relative_to(job.job_dir))
    return result


def _validate_prepared_native_inputs(job, project, director, treatment, *, planned=(), check_expressions=False):
    # Only exact future-input bindings are absent from this view. Prepared
    # bindings, even broken ones next to a planned item, retain every gate.
    prepared = {**director, 'segments': [{**segment, 'bindings': {
        cid: binding for cid, binding in segment.get('bindings', {}).items()
        if (segment['segment_id'], cid) not in planned}} for segment in director['segments']]}
    from lemo_wake_adapter import validate_selected_inputs
    from talkcraft_skill_adapter import validate_selected_inputs as validate_talkcraft_inputs
    from motion_native_skill_adapter import validate_selected_inputs as validate_motion_inputs
    validate_selected_inputs(job, prepared, treatment)
    validate_talkcraft_inputs(job, prepared, treatment)
    validate_motion_inputs(job, prepared, treatment)
    for name in ('anidoodle_native_adapter', 'sweety_native_adapter', 'garden_native_adapter'):
        _module(name).validate_selected_inputs(job, prepared, treatment)
    _validate_selected_native_sources(job, prepared, treatment)
    _validate_existing_native_schemas(job, project, prepared, treatment, check_expressions=check_expressions)
    _validate_selected_lemo_workflows(job, project, prepared, treatment)
    _validate_selected_native_parent_layouts(job, prepared, treatment)
    _validate_selected_hw_word_anchors(job, prepared, treatment)


def _validate_existing_native_schemas(job, project, director, treatment, *, check_expressions=False):
    from edit.hd.tools import motion_capabilities as motion
    from edit.hd.tools.motion_match_cache import selected_expression_bases, validate_native_expression
    from edit.hd.tools.semantic_visual_plan import component_semantic_rows, component_use
    targets = [(segment, component, segment.get('bindings', {}).get(component['component_id'], {}))
               for segment in director['segments'] for component in segment['visual_strategy']['components']
               if segment.get('bindings', {}).get(component['component_id'], {}).get('producer_type') == 'dependency']
    if not targets:
        return
    semantic_rows = component_semantic_rows(treatment) if check_expressions else {}
    expressions = selected_expression_bases(treatment) if check_expressions else {}
    catalog = motion.load_catalog(project)
    selection = treatment.get('skill_selection', {})
    selected = {(a['segment_id'], a['component_id']): a['candidate_id']
                for a in [*selection.get('assignments', []), *selection.get('overlay_assignments', [])]}
    scenes = {(s.get('segment_id'), s.get('component_id')): s for s in treatment.get('scenes', [])}
    for segment, component, binding in targets:
        cid = component['component_id']
        candidates = [row for row in catalog if all(row.get(field) == binding.get(field)
                      for field in ('dependency_id', 'entrypoint', 'template_id'))
                      and (selected.get((segment['segment_id'], cid)) is None
                           or row['candidate_id'] == selected[(segment['segment_id'], cid)])]
        if len(candidates) != 1:
            raise ValueError('existing native brief has no exact selected route validator')
        key = (segment['segment_id'], cid)
        brief = _json(_path(job, scenes[key]['brief_path']))
        report = motion._native_input_check(project, candidates[0], brief, job_dir=job.job_dir,
            segment=segment, component_id=cid, use=component_use(segment, component))
        if report['status'] != 'pass':
            raise ValueError('existing native brief is invalid: ' + str(report))
        if check_expressions:
            validate_native_expression(brief, semantic_rows[key], expressions.get(key))


def _validate_selected_native_sources(job, director: dict, treatment: dict) -> None:
    """Catch missing or changed native inputs before approving their execution."""
    from edit.hd.tools.startup import _operation_cache
    from native_result_reuse import input_file_digest
    cache = _operation_cache(SKILL)
    scenes = {(s.get('segment_id'), s.get('component_id')): s
              for s in treatment.get('scenes', [])}
    for segment in director.get('segments', []):
        for cid, binding in segment.get('bindings', {}).items():
            if binding.get('producer_type') != 'dependency':
                continue
            scene = scenes.get((segment['segment_id'], cid))
            if not scene or not isinstance(scene.get('brief_path'), str):
                raise ValueError('selected native input is missing its scene brief')
            payload = _path(job, scene['brief_path']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != binding.get('brief_sha256'):
                raise ValueError('selected native input brief differs from its binding')
            brief = json.loads(payload)
            inputs = brief.get('assets', []) + brief.get('files', [])
            inputs.extend(brief.get('materials', []))
            inputs.extend(brief[field] for field in ('hand', 'image', 'speech') if isinstance(brief.get(field), dict))
            if isinstance(brief.get('entry'), dict):
                inputs.append(brief['entry'])
            for item in inputs:
                records = [(item.get('job_path'), item.get('sha256'))]
                provenance = item.get('provenance', {})
                if 'record_path' in provenance:
                    records.append((provenance['record_path'], provenance.get('record_sha256')))
                for name, digest in records:
                    if name is None:
                        continue
                    source = _path(job, name)
                    if (source.is_symlink() or not source.resolve().is_relative_to(job.job_dir.resolve())
                            or input_file_digest(job.job_dir, source, cache=cache) != digest):
                        raise ValueError(f'selected native source changed: {segment["segment_id"]}/{cid}: {name}')
            if (binding.get('dependency_id') == 'hyperframes-native-adaptation'
                    and binding.get('entrypoint') == 'scripts/hyperframes_native_adapter.py'):
                from hyperframes_native_adapter import check_runtime, sha
                runtime, _ = check_runtime(SKILL)
                if sha(runtime['route_sources'][brief['upstream_route']]) != brief['source_pins']['sha256']:
                    raise ValueError('selected HyperFrames original source pin differs from the actual registered route')
                text = _path(job, brief['entry']['job_path']).read_text()
                if not (re.search(r'<head(?:\s|>)', text, re.I) and re.search(r'<body(?:\s|>)', text, re.I)):
                    raise ValueError('selected HyperFrames scene needs an explicit head and body to retain mounted styles')
                if re.search(r'<template(?:\s|>)', text, re.I) and 'data-composition-src' not in text:
                    raise ValueError('selected HyperFrames mountable template needs a full scene host')
                urls = re.findall(r'''(?:src|url)\s*(?:=|\()\s*["']?([^"')\s>]+)''', text)
                allowed = {'vendor/gsap.min.js', *(a['scene_path'] for a in brief['assets'])}
                if (any(url not in allowed for url in urls)
                        or re.search(r'fetch\s*\(|https?://|<audio|<video|@import',
                                     text.replace('http://www.w3.org/2000/svg', ''))):
                    raise ValueError('selected HyperFrames entry differs from its frozen local assets')


def _validate_selected_lemo_workflows(job, project: Path, director: dict, treatment: dict) -> None:
    """Read the actual native workflow before freezing or paying for a plan."""
    from upstream_scene_adapter import validate_brief, validate_workflow
    scenes = {(s.get('segment_id'), s.get('component_id')): s
              for s in treatment.get('scenes', [])}
    for segment in director.get('segments', []):
        for cid, binding in segment.get('bindings', {}).items():
            if binding.get('dependency_id') != 'lemo-opuscar':
                continue
            scene = scenes.get((segment['segment_id'], cid))
            if not scene or not isinstance(scene.get('brief_path'), str):
                raise ValueError('selected Lemo workflow is missing its scene brief')
            payload = _path(job, scene['brief_path']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != binding.get('brief_sha256'):
                raise ValueError('selected Lemo workflow brief differs from its binding')
            brief = validate_brief(payload)
            with tempfile.TemporaryDirectory(prefix='.lemo-input-check-', dir=job.job_dir) as directory:
                root = Path(directory)
                for item in brief['files']:
                    source = _path(job, item['job_path'])
                    if source.is_symlink() or not source.resolve().is_relative_to(job.job_dir.resolve()):
                        raise ValueError('selected Lemo source must belong to this Job')
                    data = source.read_bytes()
                    if hashlib.sha256(data).hexdigest() != item['sha256']:
                        raise ValueError('selected Lemo workflow source changed')
                    target = root / item['scene_path']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                validate_workflow(brief, root, project / 'vendor/lemo-opuscar')


def _validate_selected_native_parent_layouts(job, director: dict, treatment: dict) -> None:
    """Check selected native parent geometry against the real compiler."""
    from edit.hd.tools import visual_plan
    from overlay_studio_adapter import validate_brief, validate_parent_layout
    from huashu_stat_adapter import validate_brief as validate_stat_brief
    scenes = {(s.get('segment_id'), s.get('component_id')): s
              for s in treatment.get('scenes', [])}
    for segment in director.get('segments', []):
        selected = {cid: b for cid, b in segment.get('bindings', {}).items()
                    if b.get('dependency_id') in {'overlay-studio-native', 'useanimations'}
                    or (b.get('dependency_id') == 'huashu-motion-native'
                        and b.get('template_id') == 'huashu-motion/talking-head-stat')}
        if not selected:
            continue
        strategy = segment['visual_strategy']
        router = visual_plan._load_router_module()
        components = {component['component_id']: router.component_geometry(
            component, strategy['composition'], round((segment['end'] - segment['start']) * 24),
            index=index, dependency_id=selected[component['component_id']]['dependency_id'])
            for index, component in enumerate(strategy['components']) if component['component_id'] in selected}
        for cid, binding in selected.items():
            scene = scenes.get((segment['segment_id'], cid))
            if not scene or not isinstance(scene.get('brief_path'), str):
                raise ValueError('selected native parent layout is missing its scene brief')
            payload = _path(job, scene['brief_path']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != binding.get('brief_sha256'):
                raise ValueError('selected native parent layout brief differs from its binding')
            if binding['dependency_id'] == 'overlay-studio-native':
                validate_parent_layout(validate_brief(payload), components[cid])
            elif binding['dependency_id'] == 'useanimations':
                from useanimations_native_adapter import validate_brief as validate_icon_brief
                if validate_icon_brief(payload)['parent_safe_zone'] != components[cid]['render_window']['safe_zone']:
                    raise ValueError('useAnimations parent safe zone differs from the compiled layout')
            elif validate_stat_brief(payload)['parent_safe_zone'] != components[cid]['render_window']['safe_zone']:
                raise ValueError('selected Stat parent safe zone differs from the compiled layout')


def _validate_selected_hw_word_anchors(job, director: dict, treatment: dict) -> None:
    """Validate selected HW briefs before the visual proposal is frozen."""
    from hyperframes_hw_pipeline_adapter import _checked_brief, _validate_word_anchors

    scenes = {(item.get('segment_id'), item.get('component_id')): item
              for item in treatment.get('scenes', []) if isinstance(item, dict)}
    segments = {item.get('segment_id'): item for item in director.get('segments', [])}
    node = Path(shutil.which('node') or 'node')
    for segment_id, segment in segments.items():
        for component in segment.get('visual_strategy', {}).get('components', []):
            component_id = component.get('component_id')
            binding = segment.get('bindings', {}).get(component_id, {})
            if (binding.get('dependency_id') != 'hyperframes'
                    or binding.get('entrypoint') != 'scripts/render_hyperframes_hw_pipeline.cjs'):
                continue
            scene = scenes.get((segment_id, component_id))
            if not scene or not isinstance(scene.get('brief_path'), str):
                raise ValueError('selected HW component is missing its treatment scene brief')
            brief_path = _path(job, scene['brief_path'])
            payload = brief_path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != binding.get('brief_sha256'):
                raise ValueError('selected HW brief does not match its binding')
            brief = _checked_brief(node, payload)
            try:
                _validate_word_anchors(job, segment, brief)
            except ValueError as error:
                raise ValueError(
                    f"HW word-anchor validation failed for {segment_id}/{component_id}: {error}") from error


def resume_visual_direction(job, project: Path, payload: dict | None = None) -> dict:
    """Continue approved work; real host tool results arrive via input-json."""
    from edit.hd.tools import state, visual_confirmation as confirmation, visual_plan
    from edit.hd.tools import generation_channels, generation_queue, contract_artifacts
    from edit.hd.tools.subtitles_v2 import subtitle_layout
    data = payload or {}
    authorized = confirmation.validate_visual_authorization(job)
    if any(r['path'].endswith('/' + confirmation.MAPPING) for r in job.stages['visual_direction']['artifacts']):
        confirmation.validate_visual_authorization(job, require_realized=True)
        state.complete(job, 'visual_direction')
        return _summary(state.load_job(job.job_dir), 'visual_direction', production_completed=True)
    for result in data.get('generation_results', []):
        generation_channels.record_result(job.job_dir, result['action'], result['response'],
            queried_task_ids=result.get('queried_task_ids'))
    preparations = data.get('gbro_frame_preparations', [])
    if not isinstance(preparations, list):
        raise ValueError('gbro_frame_preparations must contain actual preparation descriptors')
    for descriptor in preparations:
        confirmation.record_gbro_frame_preparation(job, descriptor)
    proposal = authorized['source']
    inputs = proposal['inputs']
    realized = data.get('realization') or {}
    director = _path(job, realized.get('director_brief', inputs['director']['path']))
    treatment = _path(job, realized.get('treatment', inputs['treatment']['path']))
    reviewed = realized.get('reviewed_visual_text') or inputs.get('reviewed_visual_text', {}).get('path')
    draft, scene_plan = _json(director), _json(treatment)
    confirmation.validate_realization_draft(job, draft, scene_plan, native_targets=set())
    frozen_treatment = confirmation._read(confirmation._exact(job.job_dir, inputs['treatment']))
    handoffs = confirmation._semantic_handoffs(frozen_treatment, authorized['payload']['source'])

    pending = confirmation.unprepared_template_targets(draft, scene_plan)
    errors, invalid, native_actions = [], set(), {}
    parent_inputs = None
    if any(binding.get('dependency_id') and (segment['segment_id'], cid) not in pending
           for segment in draft['segments'] for cid, binding in segment.get('bindings', {}).items()):
        parent_inputs = (confirmation._read(confirmation._exact(job.job_dir, inputs['director'])),
                         frozen_treatment)
    unfinished = set(pending)
    for segment in draft['segments']:
        for cid in segment.get('bindings', {}):
            key = (segment['segment_id'], cid)
            if key in pending:
                continue
            scoped = {**draft, 'segments': [{**segment, 'bindings': {cid: segment['bindings'][cid]}}]}
            try:
                if segment['bindings'][cid].get('dependency_id'):
                    confirmation._validate_authorized_native_inputs(job.job_dir, proposal, *parent_inputs,
                        draft, scene_plan, targets={key})
                _validate_prepared_native_inputs(job, project, scoped, scene_plan)
                actions = pending_native_actions(job, scoped, scene_plan)
                native_actions[key] = actions
                if actions:
                    unfinished.add(key)
            except (ValueError, OSError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
                invalid.add(key)
                errors.append({'segment_id': key[0], 'component_id': key[1], 'error': str(error)})
    generation_candidates = confirmation.generation_actions(job, account_limit=data.get('account_limit'),
        defer_submission=True, excluded_targets=invalid, errors=errors)
    queue = generation_queue.status(job.job_dir) if proposal['generation_steps'] else {'items': {}}
    steps = {}
    for step in proposal['generation_steps']:
        key = (step['segment_id'], step['component_id'])
        try:
            steps[step['id']] = confirmation.generation_item(queue, proposal, step, job)[1]
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
            steps[step['id']] = None
            if key not in invalid:
                errors.append({'segment_id': key[0], 'component_id': key[1], 'step_id': step['id'], 'error': str(error)})
            invalid.add(key)
    invalid.update((error['segment_id'], error['component_id']) for error in errors
                   if 'segment_id' in error and 'component_id' in error)
    blocked = invalid | {(step['segment_id'], step['component_id']) for step in proposal['generation_steps']
                         if (steps[step['id']] or {}).get('status') != 'completed'}
    unfinished.update(blocked)
    dependency_blocked = set()
    for segment in draft['segments']:
        dependencies = segment['visual_strategy'].get('composition', {}).get('component_dependencies', [])
        # Components are a small validated DAG; only their real prerequisites wait.
        for _ in dependencies:
            for edge in dependencies:
                if any((segment['segment_id'], cid) in unfinished for cid in edge['depends_on']):
                    key = (segment['segment_id'], edge['component_id'])
                    blocked.add(key)
                    dependency_blocked.add(key)
                    unfinished.add(key)
    creative_context = (
        'Use semantic_row as the confirmed task: preserve its quote, meaning, visible relationship or '
        'change, and every required_content item. Fill the selected fixed route\'s approved content slots '
        'from expression_basis.content when present. In a creative route, use the native workflow to '
        'choose recognizable objects, actions and staging. Use a short label when needed to identify '
        'an object or clarify an ambiguous relationship. Leave time to read the result and respect '
        'the presenter and subtitle safe zones. Refer to the confirmed proposal for other rows using '
        'this route so each has a distinct treatment grounded in its own meaning. The native workflow '
        'owns creative design and its technical QA.')
    actions = []
    for sid, cid in sorted(pending):
        if (sid, cid) in blocked:
            continue
        required = [step for step in proposal['generation_steps']
                    if (step['segment_id'], step['component_id']) == (sid, cid)]
        if any((steps[step['id']] or {}).get('status') != 'completed' for step in required):
            continue
        action = {'action': 'prepare_template_inputs', 'segment_id': sid, 'component_id': cid,
            'completed_generations': [steps[step['id']] for step in required],
            'return_fields': ['realization.director_brief', 'realization.treatment'],
            'next': creative_context, **handoffs[(sid, cid)]}
        segment = next(s for s in draft['segments'] if s['segment_id'] == sid)
        strategy = segment['visual_strategy']
        zones, placement = subtitle_layout(strategy['mode'], strategy.get('composition', {}))
        action['parent_subtitle_layout'] = {'safe_zones': zones, 'placement': placement}
        if segment.get('bindings', {}).get(cid, {}).get('producer_type') == 'dependency':
            action['speech_input_contract'] = {
                'argv_prefix': [shutil.which('ffmpeg') or 'ffmpeg', '-v', 'error', '-i',
                    str(job.job_dir / '06-edit-structure/edited-aroll.mp4'), '-ss', str(segment['start']),
                    '-t', str(segment['end'] - segment['start']), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le'],
                'output_argument': 'Append a new Job-local .wav path and bind its actual SHA/bytes as speech; no audio filters or replacement narration.',
                'word_anchors': 'Use every overlapping approved word, clipped to this segment and shifted to its local clock.'}
        actions.append(action)
    for key, native in native_actions.items():
        if key not in blocked:
            try:
                for action in native:
                    confirmation.freeze_native_dispatch(job, proposal, frozen_treatment, key,
                                                        action['dependency_id'], Path(action['brief_path']),
                                                        action['brief_sha256'])
                    action.update(handoffs[key])
                    action['next'] = (action.get('next', '') + ' ' + creative_context).strip()
            except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
                invalid.add(key)
                errors.append({'segment_id': key[0], 'component_id': key[1], 'error': str(error)})
                continue
            actions.extend(native)
    candidates = [candidate for candidate in generation_candidates
                  if (candidate.get('segment_id'), candidate.get('component_id')) not in invalid | dependency_blocked]
    if actions or candidates or pending or errors or any((item or {}).get('status') != 'completed' for item in steps.values()):
        response = _summary(job, 'visual_direction', actions=actions, errors=errors,
            next='宿主可并行执行所列就绪项；错误项及其依赖暂停，回传生成结果或 realization 后继续。无需用户再次确认。')
        contract_artifacts.canonical_json_bytes(response)
        return generation_channels.issue_actions(job, candidates, response, account_limit=data.get('account_limit'))
    # Recheck the complete realization only at the final join.
    confirmation.validate_realization_draft(job, draft, scene_plan)
    # Join once: no partial realization may enter compilation or final mapping.
    prepare_visual_dependencies(project, draft, job=job, treatment=scene_plan)
    visual_plan.prepare_visual_direction(job, director, job.job_dir / 'official-previews',
        treatment_path=treatment, reviewed_visual_text=_json(_path(job, reviewed)) if reviewed else None)
    job = state.load_job(job.job_dir)
    confirmation.write_realization_mapping(job, director_path=director, treatment_path=treatment)
    state.complete(job, 'visual_direction')
    confirmation.validate_visual_authorization(job, require_realized=True)
    return _summary(state.load_job(job.job_dir), 'visual_direction', production_completed=True)


def pending_native_actions(job, director: dict, treatment: dict) -> list:
    """Only after whole-list approval: hand off missing native creative work."""
    native_modules = {'lemo-wake': 'lemo_wake_adapter', 'video-talkcraft': 'talkcraft_skill_adapter',
                      'barty-motion-graphics': 'motion_native_skill_adapter', 'bang-motion': 'motion_native_skill_adapter',
                         'mg-styles-15': 'motion_native_skill_adapter', 'video-shotcraft': 'motion_native_skill_adapter', 'bb-video': 'motion_native_skill_adapter', **_creative_adapters()}
    from edit.hd.tools.subtitles_v2 import subtitle_layout
    scenes = {(s.get('segment_id'), s.get('component_id')): s for s in treatment.get('scenes', [])}
    actions = []
    for segment in director['segments']:
        for component in segment['visual_strategy']['components']:
            cid = component['component_id']
            binding = segment.get('bindings', {}).get(cid, {})
            dependency = binding.get('dependency_id')
            if dependency not in native_modules:
                continue
            module = _module(native_modules[dependency])
            scene = scenes.get((segment['segment_id'], cid), {})
            brief_path = _path(job, scene['brief_path'])
            payload = brief_path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != binding['brief_sha256']:
                raise ValueError('Native Skill brief changed after visual approval')
            brief = module.validate_brief(payload)
            result_path = _path(job, brief['result_record_path'])
            if not result_path.exists() and not result_path.is_symlink():
                composition = segment['visual_strategy'].get('composition', {})
                zones, placement = subtitle_layout(segment['visual_strategy']['mode'], composition)
                options = ({'approved_task_source': module.task_source(director, treatment, segment['segment_id'], cid)}
                           if dependency in _creative_adapters() else {})
                if dependency != 'lemo-wake':
                    options['defer_runtime'] = True
                action = module.native_task(job, {'segment_id': segment['segment_id']},
                    {**binding, 'component_id': cid}, brief_path, **options)
                if dependency == 'barty-motion-graphics':
                    directory = _path(job, brief['project_directory'])
                    output = directory / 'out'
                    if (not directory.absolute().is_relative_to(job.job_dir / 'native-projects')
                            or output.resolve() != output.absolute()):
                        raise ValueError('Native output directory must remain in this Job project')
                    output.mkdir(parents=True, exist_ok=True)
                    action['output_directory'] = str(output)
                    action['next'] += ' The parent has prepared output_directory. Write the native media directly into it; prepare any authored subdirectory before capture_render.'
                action['requirements']['parent_subtitle_layout'] = {'safe_zones': zones, 'placement': placement}
                actions.append(action)
            else:
                module.inspect_result(job.job_dir, payload)
    return actions


def _module(name: str):
    spec = importlib.util.spec_from_file_location('hd_stage_' + name, SKILL / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Default constructor bindings; selection and preparation use these same IDs.
_NATIVE_MODULES = {
    'barty-motion-graphics': ('motion_native_skill_adapter', 'python'),
    'bang-motion': ('motion_native_skill_adapter', 'python'),
    'mg-styles-15': ('motion_native_skill_adapter', 'python'),
    'cinecode': ('motion_native_skill_adapter', 'python'),
    'video-shotcraft': ('motion_native_skill_adapter', 'python'),
    'bb-video': ('motion_native_skill_adapter', 'python'),
    'video-talkcraft': ('talkcraft_skill_adapter', 'python'),
    'hyperframes-native-adaptation': ('hyperframes_native_adapter', 'python'),
    'eian-riso-broll': ('riso_native_adapter', 'python'),
    'datamagic': ('datamagic_native_adapter', 'python'),
    'huashu-art-motion': ('motion_native_skill_adapter', 'python'),
    'anidoodle': ('anidoodle_native_adapter', 'python'),
    'sweety-handdraw-video': ('sweety_native_adapter', 'python'),
    'garden-motion-showreel': ('garden_native_adapter', 'python'),
    'useanimations': ('useanimations_native_adapter', 'python'),
    'overlay-studio-native': ('overlay_studio_adapter', 'python'),
    'openfilm-motion-graphics': ('openfilm_motion_adapter', 'python'),
    'huashu-motion-native': ('huashu_stat_adapter', 'python'),
    'motion-graphics-native': ('motion_graphics_adapter', 'python'),
    'doudou-remotion-whiteboard': ('doudou_adapter', 'node'),
    'talkcraft-native-adaptation': ('talkcraft_native_adapter', 'node'),
    'wise-motion': ('wise_motion_adapter', 'node'),
    'adu-motion-video': ('adu_native_adapter', 'node'),
    'hypit-native-chat': ('hypit_native_adapter', 'node'),
    'paper-collage-hyperframes': ('paper_hyperframes_adapter', 'python'),
    'lemo-opuscar': ('upstream_scene_adapter', 'python'),
    'onetake': ('upstream_scene_adapter', 'python'),
    'lemo-wake': ('lemo_wake_adapter', 'python'),
}
_HYPERFRAMES_MODULES = {
    'scripts/render_hyperframes_hw_pipeline.cjs': 'hyperframes_hw_pipeline_adapter',
    'scripts/render_hyperframes_notification.cjs': 'hyperframes_notification_adapter',
    'scripts/render_hyperframes_chatgpt_exchange.cjs': 'hyperframes_chatgpt_exchange_adapter',
}


def _check_default_binding(binding):
    dependency = binding.get('dependency_id')
    if dependency not in {*_NATIVE_MODULES, 'hyperframes', 'html-video', 'paper-collage-ad', 'whiteboard-video'}:
        raise ValueError(f'Selected dependency {dependency} has no default execution binding')
    if dependency == 'html-video' and binding.get('entrypoint') != 'scripts/render_data_rollup.cjs':
        raise ValueError('Selected html-video entrypoint has no default execution binding')
    if dependency == 'hyperframes' and binding.get('entrypoint') not in _HYPERFRAMES_MODULES:
        raise ValueError('Selected HyperFrames entrypoint has no default execution binding')
    if dependency == 'motion-graphics-native' and (
            binding.get('entrypoint') != 'scripts/render_motion_graphics.cjs'
            or binding.get('template_id') != 'motion-graphics-native/callout_pin'):
        raise ValueError('Selected motion graphics route has no default execution binding; use the connected callout-pin route')


def _validate_previous_native_result(job, module, payload, segment_id, component_id, binding):
    """A completed file must still match any registered reviewed version."""
    from edit.hd.tools import visual_confirmation as confirmation
    stage = job.stages['visual_direction']
    for record in [*stage.get('artifacts', []), *stage.get('lineage', [])]:
        if not record.get('path', '').endswith('/execution-mapping.json'):
            continue
        descriptor = {key: record[key] for key in ('path', 'sha256', 'bytes')}
        mapping = confirmation._read(confirmation._exact(job.job_dir, descriptor))
        matches = [item for item in mapping.get('native_inputs', [])
                   if (item.get('segment_id'), item.get('component_id')) == (segment_id, component_id)
                   and item.get('artifact', {}).get('sha256') == binding.get('brief_sha256')]
        if len(matches) > 1:
            raise ValueError('Previous native result mapping is ambiguous')
        if not matches:
            continue
        receipt, _ = confirmation._validate_source(job.job_dir, mapping['source_approval'], job_id=job.job_id)
        if mapping.get('proposal') != receipt['source']:
            raise ValueError('Previous native result differs from its approved proposal')
        if confirmation._exact(job.job_dir, matches[0]['artifact']).read_bytes() != payload:
            raise ValueError('Native reuse differs from its previously reviewed brief')
        module.load_result(job.job_dir, payload, expected_record=matches[0]['result_record'],
                           expected_renderer_version=binding['renderer_version'])


def prepare_visual_dependencies(project: Path, director: dict, *, job, treatment: dict, planned=()) -> None:
    """Prepare only ready execution bindings after visual authorization."""
    router = _module('broll_capability_router')
    scenes = {(scene.get('segment_id'), scene.get('component_id')): scene
              for scene in treatment.get('scenes', [])}
    motion = _creative_adapters()
    bindings = []
    for segment in director['segments']:
        for component in segment['visual_strategy']['components']:
            if component['kind'] != 'code_generated':
                continue
            if component['component_id'] not in segment.get('bindings', {}):
                continue  # A scoped ready view excludes deferred component bindings.
            binding = segment.get('bindings', {}).get(component['component_id'], {})
            _check_default_binding(binding)
            fields = ('dependency_id', 'entrypoint', 'producer_version', 'primary_renderer')
            if any(not isinstance(binding.get(key), str) or not binding[key] for key in fields):
                raise ValueError('Selected template needs its actual execution binding before confirmation')
            key = (segment['segment_id'], component['component_id'])
            if binding['dependency_id'] in motion and key not in planned:
                scene = scenes.get(key, {})
                if not isinstance(scene.get('brief_path'), str):
                    raise ValueError('Selected native motion requires its existing task brief')
                payload = _path(job, scene['brief_path']).read_bytes()
                if hashlib.sha256(payload).hexdigest() != binding.get('brief_sha256'):
                    raise ValueError('Native brief differs from its selected binding')
                module = _module(_creative_adapters()[binding['dependency_id']])
                brief = module.validate_brief(payload, dependency_id=binding['dependency_id'])
                if brief['job_id'] != job.job_id:
                    raise ValueError('Native brief belongs to another Job')
                result = _path(job, brief['result_record_path'])
                if result.exists() or result.is_symlink():
                    module.inspect_result(job.job_dir, payload)
                    _validate_previous_native_result(job, module, payload, *key, binding)
                    continue
            selected = {key: binding[key] for key in fields}
            selected.update(executor=router._executor(component['kind'], binding))
            if selected not in bindings:
                bindings.append(selected)
    if bindings:
        from motion_native_skill_adapter import check_selected_template_dependencies
        check_selected_template_dependencies(job, director, treatment)
        from project_python import project_environment, prepare_environment
        environment, packages = project_environment(project)
        prepare_environment(project, environment, packages,
                            {binding['dependency_id'] for binding in bindings}, bindings)


def _approved_native_brief(job, evidence):
    """Bind a loader to one fully checked factory call and persisted workflow."""
    from edit.hd.tools import visual_confirmation as confirmation
    fields = ('job_dir', 'job_id', 'revision', 'expected_sha256', 'expected_bytes')
    identity = tuple(getattr(job, field) for field in fields)
    workflow = {'path': 'workflow.json', 'sha256': job.expected_sha256, 'bytes': job.expected_bytes}
    statuses = {name: stage['status'] for name, stage in job.stages.items()}
    visual_stage = copy.deepcopy(job.stages['visual_direction'])
    mappings = [r for r in visual_stage['artifacts'] if r['path'].endswith('/' + confirmation.MAPPING)]
    if visual_stage['status'] != 'completed' or len(mappings) != 1:
        raise ValueError('Approved native mapping is missing or ambiguous')
    mapping_ref, approval_ref = mappings[0], copy.deepcopy(evidence['artifact'])
    mapping = confirmation._read(confirmation._exact(job.job_dir, mapping_ref))
    if mapping != evidence['mapping'] or mapping.get('source_approval') != approval_ref:
        raise ValueError('Approved native mapping differs from its verified confirmation')
    confirmation._exact(job.job_dir, workflow)
    confirmation._exact(job.job_dir, approval_ref)

    def load(current, recipe, component):
        if (tuple(getattr(current, field) for field in fields) != identity
                or {name: stage['status'] for name, stage in current.stages.items()} != statuses
                or current.stages['visual_direction'] != visual_stage):
            raise ValueError('Native adapters belong to another workflow revision or stage')
        confirmation._exact(current.job_dir, workflow)
        confirmation._exact(current.job_dir, approval_ref)
        mapping = confirmation._read(confirmation._exact(current.job_dir, mapping_ref))
        if mapping.get('source_approval') != approval_ref:
            raise ValueError('Approved native mapping differs from its verified confirmation')
        matches = [item for item in mapping['native_inputs']
                   if item.get('segment_id') == recipe['segment_id']
                   and item.get('component_id') == component['component_id']]
        if len(matches) != 1 or matches[0].get('artifact', {}).get('sha256') != component['brief_sha256']:
            raise ValueError('Approved native brief is missing or ambiguous')
        return confirmation._exact(current.job_dir, matches[0]['artifact']).read_bytes()

    return load


def native_component_adapters(project: Path, job) -> dict:
    """Prepare only native dependencies selected by this Job."""
    from edit.hd.tools import visual_canary
    plan = visual_canary.load_approved_visual_plan(job)
    selected = [c for s in plan['segments'] for c in s['shot_recipe']['components']]
    noncode = [c for c in selected if c['kind'] != 'code_generated']
    dependencies = {c['dependency_id'] for c in selected if c['kind'] == 'code_generated'}
    for component in selected:
        if component['kind'] == 'code_generated':
            _check_default_binding(component)

    evidence = None
    if dependencies or any(c['kind'] == 'ai_generated' for c in noncode):
        from edit.hd.tools import visual_confirmation as confirmation
        evidence = confirmation.validate_visual_authorization(job, require_realized=True)
    brief_loader = _approved_native_brief(job, evidence) if dependencies else None

    adapters = {}
    for dependency in sorted(dependencies):
        if dependency == 'hyperframes':
            runtime = _module('hyperframes_runtime').resolve_runtime(
                project / 'runtime/hyperframes-0.8.167')['root']
            registry = {}
            for segment in plan['segments']:
                for component in segment['shot_recipe']['components']:
                    if component.get('dependency_id') != dependency:
                        continue
                    registry[(segment['segment_id'], component['component_id'])] = _module(
                        _HYPERFRAMES_MODULES[component['entrypoint']]).create_adapter(
                            runtime_root=runtime, node_executable=shutil.which('node'),
                            browser_executable='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                            ffmpeg_executable=shutil.which('ffmpeg'), brief_loader=brief_loader)
            adapters[dependency] = registry
        elif dependency == 'html-video':
            adapters[dependency] = _module('data_rollup_adapter').create_default_adapter(project, brief_loader)
        elif dependency == 'paper-collage-ad':
            adapters[dependency] = _module('paper_collage_adapter').create_adapter(
                project / 'vendor/paper-collage-ad-codex', sys.executable,
                shutil.which('node'), shutil.which('ffmpeg'), shutil.which('ffprobe'), brief_loader)
        elif dependency == 'whiteboard-video':
            vendor = project / 'vendor'
            engine = vendor / 'whiteboard-video-engine'
            adapters[dependency] = _module('whiteboard_adapter').create_adapter(
                vendor / 'codex-whiteboard-video-skill', engine, sys.executable,
                engine / '.venv/bin/python', shutil.which('ffmpeg'), shutil.which('ffprobe'), brief_loader)
        elif dependency == 'video-talkcraft' or dependency in _creative_adapters():
            module = _module('talkcraft_skill_adapter' if dependency == 'video-talkcraft' else _creative_adapters()[dependency])
            options = {} if dependency == 'video-talkcraft' else {'dependency_id': dependency}
            adapters[dependency] = {
                (segment['segment_id'], component['component_id']): module.create_adapter(
                    project, sys.executable, brief_loader, renderer_version=component['renderer_version'], **options)
                for segment in plan['segments'] for component in segment['shot_recipe']['components']
                if component.get('dependency_id') == dependency}
        elif dependency == 'huashu-motion-native':
            module = _module('huashu_stat_adapter')
            adapters[dependency] = {
                (segment['segment_id'], component['component_id']): module.create_adapter(
                    project, sys.executable, brief_loader,
                    execution_mode=module.validate_brief(brief_loader(
                        job, segment['shot_recipe'], component))['execution_mode'])
                for segment in plan['segments'] for component in segment['shot_recipe']['components']
                if component.get('dependency_id') == dependency}
        else:
            name, launcher_kind = _NATIVE_MODULES[dependency]
            launcher = sys.executable if launcher_kind == 'python' else shutil.which('node')
            module = _module(name)
            adapters[dependency] = (module.create_adapter(project, dependency, launcher, brief_loader)
                                    if dependency in {'lemo-opuscar', 'onetake'}
                                    else module.create_adapter(project, launcher, brief_loader))
    result = {'code_generated': adapters}
    if any(c['kind'] == 'ai_generated' for c in noncode):
        records = [_json(confirmation._exact(job.job_dir, ref))
                   for ref in evidence['mapping']['completed_records']]
        generic_targets = {(seg['segment_id'], c['component_id']) for seg in plan['segments']
                           for c in seg['shot_recipe']['components'] if c['executor'] == 'generated_media'}
        generic = [record for record in records if (record['segment_id'], record['component_id']) in generic_targets]
        registry = _module('generated_media').create_job_adapter(job, generic)
        for record in records:
            key = (record['segment_id'], record['component_id'])
            if key not in registry:
                registry[key] = _module('lovart_existing_video_adapter').create_adapter(job, record)
        result['ai_generated'] = registry
    from edit.hd.tools import material_adapter
    for kind in ('local_material', 'external_stock', 'official_material'):
        entries = [(seg['segment_id'], c) for seg in plan['segments']
                   for c in seg['shot_recipe']['components'] if c['kind'] == kind]
        if entries:
            result[kind] = {(sid, c['component_id']): material_adapter.create_adapter(
                kind, c['media_type'], shutil.which('ffmpeg'), shutil.which('ffprobe')) for sid, c in entries}
    # The dispatcher probes both direct images and native opaque/alpha videos.
    result['artifact_probe'] = material_adapter.create_artifact_probe(ffprobe_executable=shutil.which('ffprobe'))
    return result


def _execute_one_stage(job_dir: Path, project: Path, stage: str | None = None, *, payload: dict | None = None,
                  video_use_result: Path | None = None, invocation_path: Path | None = None,
                  cleanup_plan: Path | None = None, director_brief: Path | None = None,
                  treatment: Path | None = None, reviewed_visual_text: Path | None = None,
                  review: dict | None = None, component_adapters: dict | None = None,
                  adapter_factory: Path | None = None) -> dict:
    from edit.hd.tools import state
    job = state.load_job(job_dir)
    current = state.current_stage(job)
    stage = stage or current
    if stage is None and review is not None:
        if review.get('stage') != 'delivery':
            raise ValueError('Completed production only consumes delivered-film acceptance')
        stage = 'delivery'
    if stage is None:
        return _finish_stage(job_dir, 'delivery', reused=True)
    if stage not in job.stages:
        raise ValueError('Unknown stage: ' + stage)
    if job.stages[stage]['status'] == 'completed':
        if review is not None and stage == 'delivery':
            return _review(job, stage, review)
        if stage == 'delivery':
            return _finish_stage(job_dir, stage, reused=True)
        if any(value is not None for value in (payload, video_use_result, invocation_path, cleanup_plan,
                                               director_brief, treatment, reviewed_visual_text, review)):
            raise ValueError('Stage already completed; explicitly revise it before changing inputs')
        return _summary(job, stage, reused=True)
    _startup(job, project)
    if stage in {'visual_assets', 'subtitles', 'preview', 'delivery'}:
        from edit.hd.tools import delivery_approval
        delivery_approval.validate_visual_plan_approval(job)
    if review is not None:
        _review(job, stage, review)
        return resume_visual_direction(job, project, payload)
    status = job.stages[stage]['status']
    if status == 'blocked':
        return _summary(job, stage, blocked=job.stages[stage]['reason'])
    completing_cleanup = (stage == 'speech_cleanup' and cleanup_plan is not None
                          and not (job_dir / '05-speech-cleanup/cleanup-proposal.json').is_file())
    if status == 'ready' and not completing_cleanup:
        if stage == 'speech_cleanup' and not (job_dir / '05-speech-cleanup/cleanup-proposal.json').is_file():
            return _summary(job, stage, actions=[{'action': 'provide_cleanup_plan', 'argument': '--cleanup-plan'}])
        if stage == 'visual_direction':
            try:
                from edit.hd.tools.visual_confirmation import validate_visual_authorization
                validate_visual_authorization(job)
            except (ValueError, OSError):
                return _summary(job, stage, actions=[{'action': 'confirm_visual_list', 'visual_list': _summary(job, stage).get('visual_list'), 'required': 'actual user_confirmation matching this Job/revision/artifacts'}])
            return resume_visual_direction(job, project, payload)
        if stage == 'preview':
            from edit.hd.tools import preview_v2
            preview_v2.prepare_preview_v2(job)
        return _finish_stage(job_dir, stage, reused=True)
    if not completing_cleanup:
        state.require_runnable(job, stage)
    data = payload or {}
    needed = {'content_analysis': ('analysis',), 'cover_direction': ('direction',), 'cover': ('image', 'prompt')}.get(stage, ())
    missing = [field for field in needed if field not in data]
    if missing:
        return _summary(job, stage, actions=[{'action': 'provide_stage_input', 'stage': stage, 'fields': missing}])
    if stage == 'inspect':
        from edit.hd.tools import inspect_inputs
        inspect_inputs.inspect_job(job)
    elif stage == 'content_analysis':
        from edit.hd.tools import content_analysis
        content_analysis.prepare_content_analysis(job, data['analysis'])
    elif stage == 'cover_direction':
        from edit.hd.tools import cover_direction
        preview = _path(job, data['direction_preview']) if data.get('direction_preview') else None
        cover_direction.prepare_cover_direction(job, data['direction'], direction_preview=preview)
    elif stage == 'cover':
        from edit.hd.tools import cover
        image = _path(job, data['image'])
        cover.prepare_cover(job, approved_preview=image, approved_preview_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                            approved_preview_prompt=data['prompt'])
    elif stage == 'speech_cleanup':
        result = run_speech_cleanup(job_dir, project, video_use_result, invocation_path, cleanup_plan)
        if ((job_dir / '05-speech-cleanup/cleanup-proposal.json').is_file()
                and result.get('status') == 'ready' and not result.get('actions')):
            return _finish_stage(job_dir, stage)
        return result
    elif stage == 'edit_structure':
        from edit.hd.tools import speech_edit_v2
        speech_edit_v2.render_edit(job)
    elif stage == 'visual_direction':
        if data.get('realization') is not None:
            return resume_visual_direction(job, project, data)
        return run_visual_direction(job_dir, project, director_brief, treatment, reviewed_visual_text)
    elif stage == 'visual_assets':
        if component_adapters is None and adapter_factory is not None:
            spec = importlib.util.spec_from_file_location('hd_job_adapters', _path(job, adapter_factory))
            factory = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(factory)
            component_adapters = factory.create_adapters(job, project)
        adapters = component_adapters if component_adapters is not None else native_component_adapters(project, job)
        from edit.hd.tools import visual_assets_v2
        visual_assets_v2.prepare_visual_assets_v2(job, component_adapters=adapters)
    elif stage == 'subtitles':
        from edit.hd.tools import subtitles
        subtitles.prepare_subtitles(job)
    elif stage == 'preview':
        from edit.hd.tools import preview_v2
        # Opening belongs to the final timeline; all semantic items retain the body clock.
        if data.get('opening') is not None:
            opening = data['opening']
        else:
            from edit.hd.tools import startup, visual_confirmation
            body_opening = visual_confirmation.approved_body_opening(job)
            if body_opening is not None:
                # Preserve the specifically approved native Wake body opening.
                # Ordinary semantic Wake items have no such declaration.
                if body_opening.get('candidate_id') != 'lemo-wake:wake':
                    raise ValueError('Approved body opening declaration is invalid')
                opening = None
            else:
                config = _json(job.job_dir / 'manifests/provider-config.json')
                if 'video' in startup.selected_channels(config):
                    return _summary(job, stage, actions=[{'action': 'provide_stage_input',
                        'stage': stage, 'fields': ['opening'],
                        'required': 'Bind the approved one-second cover opening as opening.video'}])
                defaults = _json(SKILL / 'references/production-defaults.json')['opening']
                opening = {'hold_frames': defaults['static_hold_frames'],
                    'transition_frames': defaults['transition_frames'],
                    'user_confirmation': visual_confirmation.validate_visual_authorization(job)['payload']['user_confirmation']}
        preview_v2.prepare_preview_v2(job, opening=opening, music=data.get('music'))
        return _finish_stage(job_dir, stage)
    elif stage == 'delivery':
        from edit.hd.tools import qa_delivery_v2
        qa_delivery_v2.prepare_delivery_v2(job)
    return _finish_stage(job_dir, stage)


@_operation
def execute_stage(job_dir: Path, project: Path, stage: str | None = None, **options) -> dict:
    """Continue available machine stages until an actual creative input is missing."""
    from edit.hd.tools import state
    explicit = stage is not None
    payload = options.pop('payload', None)
    per_stage = payload.get('stages') if isinstance(payload, dict) else None
    current_options = dict(options)
    while True:
        current = state.current_stage(state.load_job(job_dir))
        requested = stage or current
        data = per_stage.get(requested) if isinstance(per_stage, dict) else payload
        from edit.hd.tools.startup import current_operation
        operation = current_operation()
        started = perf_counter()
        timing = {'stage': requested, 'status': 'failed'}
        try:
            result = _execute_one_stage(job_dir, project, requested, payload=data, **current_options)
            timing['status'] = result.get('status', 'pending')
        finally:
            timing['elapsed_seconds'] = round(perf_counter() - started, 6)
            if operation is not None:
                operation.stage_timings.append(timing)
        if explicit or result.get('status') != 'completed' or requested == 'delivery':
            return result
        after = state.current_stage(state.load_job(job_dir))
        if after == current:
            return result
        stage = None
        payload = None
        current_options.pop('review', None)


@_operation
def check_stage(job_dir: Path, stage: str | None = None) -> dict:
    """Read the same runnable gate before invoking an external stage tool."""
    from edit.hd.tools import state
    job = state.load_job(job_dir)
    current = state.current_stage(job)
    stage = stage or current
    if stage is None:
        raise ValueError('No unfinished stage to execute')
    try:
        state.require_runnable(job, stage)
    except state.WorkflowError as error:
        error.add_note(f'Current unfinished stage is {current}; requested {stage}')
        raise
    return {'job_id': job.job_id, 'job_dir': str(job.job_dir), 'stage': stage,
            'status': job.stages[stage]['status'], 'revision': job.revision, 'runnable': True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-context', required=True, type=Path)
    parser.add_argument('--stage', help='Run one stage only; omit to continue until delivery or required input')
    parser.add_argument('--check-only', action='store_true',
                        help='Read-only runnable check; do not refresh preflight or execute tools')
    parser.add_argument('--project-root', type=Path)
    for option in ('input-json', 'review-json', 'video-use-result', 'invocation-json', 'cleanup-plan',
                   'director-brief', 'treatment', 'reviewed-visual-text', 'adapter-factory'):
        parser.add_argument('--' + option, type=Path)
    args = parser.parse_args()
    try:
        context = _json(args.job_context)
        project = setup_paths(args.project_root or context['project_root'])
        if args.check_only:
            if any(getattr(args, key) is not None for key in ('input_json', 'review_json',
                    'video_use_result', 'invocation_json', 'cleanup_plan', 'director_brief',
                    'treatment', 'reviewed_visual_text', 'adapter_factory')):
                raise ValueError('--check-only does not consume stage inputs')
            result = check_stage(Path(context['job_dir']), args.stage)
        else:
            result = execute_stage(Path(context['job_dir']), project, args.stage,
                payload=_json(args.input_json) if args.input_json else None,
                review=_json(args.review_json) if args.review_json else None,
                video_use_result=args.video_use_result, invocation_path=args.invocation_json,
                cleanup_plan=args.cleanup_plan, director_brief=args.director_brief, treatment=args.treatment,
                reviewed_visual_text=args.reviewed_visual_text, adapter_factory=args.adapter_factory)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        result = {'error': str(error)}
        if getattr(error, '__notes__', None):
            result['diagnostics'] = list(error.__notes__)
    except Exception as error:
        # WorkflowError and adapter boundary failures are user-facing results.
        result = {'error': str(error)}
        if getattr(error, '__notes__', None):
            result['diagnostics'] = list(error.__notes__)
    print(json.dumps(result, ensure_ascii=False))
    return int('error' in result or 'blocked' in result or result.get('status') == 'inconsistent')


if __name__ == '__main__':
    raise SystemExit(main())
