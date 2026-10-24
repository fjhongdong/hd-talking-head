#!/usr/bin/env python3
"""Execute or review the current full-v2 stage using the existing runtime.

Inputs are explicit files. The user approves the complete visual list once;
host QA then advances production and delivery. Cover keeps its own decisions.
Releases and Job migrations are
handled by their existing maintenance commands, outside this entrypoint.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


def verify_skill_package(root: Path | None = None) -> dict:
    from verify_skill_release import verify_release
    report = verify_release(root or SKILL)
    if report['status'] != 'pass':
        raise ValueError('Skill package verification failed: ' + '; '.join(report['failures']))
    return report


def setup_paths(project_root: str | Path | None = None) -> Path:
    project = Path(project_root or SKILL.parents[1]).resolve()
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
    if plan.is_file() and job.stages['visual_direction']['status'] == 'approved':
        command += ['--visual-plan', str(plan)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError('Dependency preflight failed: ' + (result.stdout or result.stderr)[-2000:])
    startup.require_startup(job)


def _summary(job, stage: str, **extra) -> dict:
    result = {'job_id': job.job_id, 'job_dir': str(job.job_dir),
            'stage': stage, 'status': job.stages[stage]['status'],
            'revision': job.revision, 'artifacts': job.stages[stage]['artifacts'], **extra}
    if result['status'] == 'ready_for_review':
        result['review_required'] = 'user' if stage in {'cover_direction', 'cover', 'visual_direction'} else 'host'
        if stage in {'visual_canary', 'visual_assets', 'preview'}:
            from edit.hd.tools import motion_readability
            if motion_readability._managed(job):
                result['motion_readability'] = motion_readability.inspect_job(job, stage)
                if result['motion_readability']['status'] not in {'sampled_pass', 'not_applicable'}:
                    result['next'] = '先按实际文字框修正小字、裁切或遮挡，再重跑受影响镜头；识别不确定项由宿主逐项查看真实帧并量框复核，不交给用户逐个找问题。'
        if stage == 'speech_cleanup' and (job.job_dir / '05-speech-cleanup/cleanup-proposal.json').is_file():
            from edit.hd.tools import speech_edit_v2
            result['cleanup_checks'] = speech_edit_v2.cleanup_check_candidates(job)
            if result['cleanup_checks']:
                result['next'] = '宿主逐项核听；口误重说按原流程剪除后重建提案，必要强调/呼吸保留并在speech_cleanup_resolutions逐项写明理由。无需用户逐项确认。'
        if stage == 'visual_direction':
            table = next((r['path'] for r in result['artifacts']
                          if r['path'].startswith('07-visual-confirmation/')
                          and r['path'].endswith('/visual-routing.md')), None)
            result['visual_list'] = table or '07-visual-direction/visual-routing.md'
            result['next'] = '展示完整贴片/B-roll总表，取得本次整表确认后继续制作并直接交付。'
            try:
                from edit.hd.tools.visual_confirmation import validate_visual_authorization
                confirmation = validate_visual_authorization(job)
            except (ValueError, OSError):
                confirmation = None
            if confirmation is not None:
                result['user_confirmed'] = True
                result['review_required'] = 'host'
                result['next'] = '整表已确认，等待宿主按确认方案调用生图/生视频渠道并完成后续制作。'
    return result


def _review(job, stage: str, review: dict) -> dict:
    from edit.hd.tools import contract_artifacts, delivery_approval, state
    if (review.get('stage') != stage or review.get('revision') != job.revision
            or review.get('passed') is not True or not str(review.get('note', '')).strip()):
        raise ValueError('Review must identify this stage/revision, passed=true and an actual QA note')
    if job.stages[stage]['status'] != 'ready_for_review':
        raise ValueError('Only the current ready candidate can be reviewed')
    if (review.get('job_id') != job.job_id
            or review.get('job_dir') != str(job.job_dir)
            or review.get('artifacts') != job.stages[stage]['artifacts']):
        raise ValueError('Review must match this Job and the exact candidate artifacts returned for review')
    confirmation = review.get('user_confirmation', '')
    human = stage in {'cover_direction', 'cover', 'visual_direction'}
    if human and not confirmation.strip():
        raise ValueError("This stage requires the current user's actual confirmation")
    if stage == 'speech_cleanup' and not (job.job_dir / '05-speech-cleanup/cleanup-proposal.json').is_file():
        raise ValueError('Finish the cleanup proposal before approving speech_cleanup')
    if stage == 'speech_cleanup':
        from edit.hd.tools import speech_edit_v2
        speech_edit_v2.validate_cleanup_review(job, review)
    receipt = {**review, 'reviewed_by': 'human' if human else 'host'}
    if stage in {'visual_canary', 'visual_assets', 'preview'}:
        from edit.hd.tools import motion_readability
        if motion_readability._managed(job):
            receipt['motion_readability'] = motion_readability.validate_stage_review(job, stage, review)
    if stage == 'visual_direction':
        paths = {record['path'] for record in job.stages[stage]['artifacts']}
        if any(path.startswith('07-visual-confirmation/') and path.endswith('/proposal.json') for path in paths):
            from edit.hd.tools import visual_confirmation
            visual_confirmation.save_user_confirmation(job, review)
            return _summary(job, stage, reviewed=True)
        if not {'07-visual-direction/visual-plan.json', '07-visual-direction/visual-routing.md'} <= paths:
            raise ValueError('Review must include the complete visual list and its actual plan')
        receipt['approval_scope'] = 'visual_plan_and_delivery'
    if stage == 'delivery':
        final = next((record for record in job.stages[stage]['artifacts']
                      if record['path'] == '12-delivery/final.mp4'), None)
        if final is None:
            raise ValueError('The reviewed delivery has no registered final.mp4')
        delivery_approval.approve_plan_delivery(job, expected_revision=job.revision,
            delivery_sha256=final['sha256'], qa_note=review['note'])
    else:
        contract_artifacts.write_json_artifact(
            job.job_dir / 'manifests' / f'local-qa-{stage}-r{job.revision}.json', receipt)
        state.approve(job, stage)
    return _summary(state.load_job(job.job_dir), stage, reviewed=True)


def run_speech_cleanup(job_dir: Path, project: Path, video_use_result: Path | None = None,
                       invocation_path: Path | None = None, cleanup_plan: Path | None = None) -> dict:
    from edit.hd.tools import speech_edit_v2, state, transcribe
    job = state.load_job(job_dir)
    generation = job_dir / '05-speech-cleanup'
    if video_use_result is not None:
        if invocation_path is None:
            return {'blocked': '请提供与当前原视频对应的真实 --invocation-json。'}
        transcribe.transcribe_job(job, video_use_result=_path(job, video_use_result),
                                 invocation=_json(_path(job, invocation_path)))
        job = state.load_job(job_dir)
    elif not (generation / 'report.json').is_file():
        return {'blocked': '请传入已完成的 --video-use-result 和真实 --invocation-json；不会重新收费转写。'}
    if cleanup_plan is not None:
        speech_edit_v2.prepare_cleanup_proposal(job, plan=_json(_path(job, cleanup_plan)))
    result = _summary(state.load_job(job_dir), 'speech_cleanup')
    if not (generation / 'cleanup-proposal.json').is_file():
        result['next'] = '按原稿校对并提供 --cleanup-plan，复用当前转写，不重复识别。'
    return result


def run_visual_direction(job_dir: Path, project: Path, director_brief: Path | None = None,
                         treatment: Path | None = None, reviewed_visual_text: Path | None = None) -> dict:
    from edit.hd.tools import state, visual_plan, visual_confirmation
    job = state.load_job(job_dir)
    if director_brief is None or treatment is None:
        return {'blocked': '请提供当前草稿的 --director-brief 和 --treatment。'}
    reviewed = _json(_path(job, reviewed_visual_text)) if reviewed_visual_text else None
    prepare_visual_dependencies(project, _json(_path(job, director_brief)))
    source = visual_confirmation.prepare_visual_confirmation(job, _path(job, director_brief),
        _path(job, treatment), reviewed_visual_text=reviewed)
    result = _summary(state.load_job(job_dir), 'visual_direction')
    result['confirmation_source'] = str(source.relative_to(job.job_dir))
    return result


def resume_visual_direction(job, project: Path, payload: dict | None = None) -> dict:
    """Continue approved work; real host tool results arrive via input-json."""
    from edit.hd.tools import state, visual_confirmation as confirmation, visual_plan
    from edit.hd.tools import generation_channels, generation_queue
    data = payload or {}
    authorized = confirmation.validate_visual_authorization(job)
    if any(r['path'].endswith('/' + confirmation.MAPPING) for r in job.stages['visual_direction']['artifacts']):
        confirmation.validate_visual_authorization(job, require_realized=True)
        state.approve(job, 'visual_direction')
        return _summary(state.load_job(job.job_dir), 'visual_direction', reviewed=True)
    for result in data.get('generation_results', []):
        generation_channels.record_result(job.job_dir, result['action'], result['response'],
            queried_task_ids=result.get('queried_task_ids'))
    actions = confirmation.generation_actions(job, account_limit=data.get('account_limit'))
    if actions:
        return _summary(job, 'visual_direction', actions=actions,
            next='宿主执行所列真实工具，通过 input-json.generation_results 回传结果后继续。')
    proposal = authorized['source']
    inputs = proposal['inputs']
    realized = data.get('realization')
    if proposal['generation_steps'] and realized is None:
        queue = generation_queue.status(job.job_dir)
        return _summary(job, 'visual_direction', actions=[{
            'action': 'prepare_template_inputs', 'proposal': authorized['payload']['source'],
            'completed_generations': [confirmation.generation_item(queue, proposal, step)[1]
                                      for step in proposal['generation_steps']],
            'return_fields': ['realization.director_brief', 'realization.treatment',
                              'realization.host_qa_note'],
        }], next='宿主按所选模板原生入口绑定实际素材，核对实际语义后回传 realization；无需用户确认。')
    realized = realized or {}
    director = _path(job, realized.get('director_brief', inputs['director']['path']))
    treatment = _path(job, realized.get('treatment', inputs['treatment']['path']))
    reviewed = realized.get('reviewed_visual_text') or inputs.get('reviewed_visual_text', {}).get('path')
    note = realized.get('host_qa_note') or (authorized['payload']['note'] if not proposal['generation_steps'] else None)
    if not isinstance(note, str) or not note.strip():
        raise ValueError('Actual generated content needs a host semantic QA note')
    confirmation.validate_realization_draft(job, _json(director), _json(treatment))
    visual_plan.prepare_visual_direction(job, director, job.job_dir / 'official-previews',
        treatment_path=treatment, reviewed_visual_text=_json(_path(job, reviewed)) if reviewed else None)
    job = state.load_job(job.job_dir)
    confirmation.write_realization_mapping(job, host_qa_note=note, director_path=director, treatment_path=treatment)
    state.approve(job, 'visual_direction')
    confirmation.validate_visual_authorization(job, require_realized=True)
    return _summary(state.load_job(job.job_dir), 'visual_direction', reviewed=True)


def _module(name: str):
    spec = importlib.util.spec_from_file_location('hd_stage_' + name, SKILL / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Default constructor bindings; selection and preparation use these same IDs.
_NATIVE_MODULES = {
    'hyperframes-native-adaptation': ('hyperframes_native_adapter', 'python'),
    'eian-riso-broll': ('riso_native_adapter', 'python'),
    'huashu-art-motion': ('huashu_motion_adapter', 'python'),
    'overlay-studio-native': ('overlay_studio_adapter', 'python'),
    'openfilm-motion-graphics': ('openfilm_motion_adapter', 'python'),
    'huashu-motion-native': ('huashu_stat_adapter', 'python'),
    'doudou-remotion-whiteboard': ('doudou_adapter', 'node'),
    'talkcraft-native-adaptation': ('talkcraft_native_adapter', 'node'),
    'wise-motion': ('wise_motion_adapter', 'node'),
    'adu-motion-video': ('adu_native_adapter', 'node'),
    'hypit-native-chat': ('hypit_native_adapter', 'node'),
    'paper-collage-hyperframes': ('paper_hyperframes_adapter', 'python'),
    'lemo-opuscar': ('upstream_scene_adapter', 'python'),
    'onetake': ('upstream_scene_adapter', 'python'),
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


def prepare_visual_dependencies(project: Path, director: dict) -> None:
    """Prepare the selected draft bindings before publishing any user candidate."""
    router = _module('broll_capability_router')
    bindings = []
    for segment in director['segments']:
        for component in segment['visual_strategy']['components']:
            if component['kind'] != 'code_generated':
                continue
            binding = segment.get('bindings', {}).get(component['component_id'], {})
            _check_default_binding(binding)
            fields = ('dependency_id', 'entrypoint', 'producer_version', 'primary_renderer')
            if any(not isinstance(binding.get(key), str) or not binding[key] for key in fields):
                raise ValueError('Selected template needs its actual execution binding before confirmation')
            selected = {key: binding[key] for key in fields}
            selected.update(executor=router._executor(component['kind'], binding))
            if selected not in bindings:
                bindings.append(selected)
    if bindings:
        from project_python import project_environment, prepare_environment
        environment, packages = project_environment(project)
        prepare_environment(project, environment, packages,
                            {binding['dependency_id'] for binding in bindings}, bindings)


def native_component_adapters(project: Path, job) -> dict:
    """Prepare only native dependencies selected by this Job."""
    from edit.hd.tools import visual_canary
    plan = visual_canary.load_approved_visual_plan(job)
    selected = [c for s in plan['segments'] for c in s['shot_recipe']['components']]
    noncode = [c for c in selected if c['kind'] != 'code_generated']
    dependencies = {c['dependency_id'] for c in selected if c['kind'] == 'code_generated'}

    def brief_loader(current, recipe, component):
        for candidate in (current.job_dir / 'native-inputs').rglob('brief.json'):
            payload = candidate.read_bytes()
            if hashlib.sha256(payload).hexdigest() == component['brief_sha256']:
                return payload
        raise ValueError('Frozen native brief is missing: ' + component['brief_sha256'])

    adapters = {}
    for dependency in sorted(dependencies):
        components = [c for c in selected if c['kind'] == 'code_generated' and c['dependency_id'] == dependency]
        for component in components:
            _check_default_binding(component)
        if dependency == 'hyperframes':
            runtime = _module('hyperframes_runtime').resolve_runtime(
                project / 'skill-development/runtime/hyperframes-0.8.167')['root']
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
                project / 'skill-development/vendor/paper-collage-ad-codex', sys.executable,
                shutil.which('node'), shutil.which('ffmpeg'), shutil.which('ffprobe'), brief_loader)
        elif dependency == 'whiteboard-video':
            vendor = project / 'skill-development/vendor'
            engine = vendor / 'whiteboard-video-engine'
            adapters[dependency] = _module('whiteboard_adapter').create_adapter(
                vendor / 'codex-whiteboard-video-skill', engine, sys.executable,
                engine / '.venv/bin/python', shutil.which('ffmpeg'), shutil.which('ffprobe'), brief_loader)
        else:
            name, launcher_kind = _NATIVE_MODULES[dependency]
            launcher = sys.executable if launcher_kind == 'python' else shutil.which('node')
            module = _module(name)
            adapters[dependency] = (module.create_adapter(project, dependency, launcher, brief_loader)
                                    if dependency in {'lemo-opuscar', 'onetake'}
                                    else module.create_adapter(project, launcher, brief_loader))
    result = {'code_generated': adapters}
    if any(c['kind'] == 'ai_generated' for c in noncode):
        from edit.hd.tools import visual_confirmation as confirmation
        evidence = confirmation.validate_visual_authorization(job, require_realized=True)
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


def _coverage_gate(job, treatment: Path | None = None) -> dict:
    from edit.hd.tools import visual_coverage
    visual = _json(job.job_dir / '07-visual-direction/visual-plan.json')
    subs = _json(job.job_dir / '10-subtitles/subtitle-plan.json')
    report = visual_coverage.require_density(visual, subtitles=subs,
        treatment=_json(_path(job, treatment)) if treatment else None,
        content_analysis=_json(job.job_dir / '02-content-analysis/content-analysis.json'))
    if report['blocking_issues']:
        raise ValueError('Visual coverage: ' + '; '.join(report['blocking_issues']))
    return report


def execute_stage(job_dir: Path, project: Path, stage: str | None = None, *, payload: dict | None = None,
                  video_use_result: Path | None = None, invocation_path: Path | None = None,
                  cleanup_plan: Path | None = None, director_brief: Path | None = None,
                  treatment: Path | None = None, reviewed_visual_text: Path | None = None,
                  review: dict | None = None, component_adapters: dict | None = None,
                  adapter_factory: Path | None = None) -> dict:
    from edit.hd.tools import state
    job = state.load_job(job_dir)
    current = state.current_stage(job)
    stage = stage or current
    if stage is None:
        return _module('audit_job_completion').audit_job_completion(job.root)
    if stage not in job.stages:
        raise ValueError('Unknown stage: ' + stage)
    if job.stages[stage]['status'] == 'approved':
        if any(value is not None for value in (payload, video_use_result, invocation_path, cleanup_plan,
                                               director_brief, treatment, reviewed_visual_text, review)):
            raise ValueError('Stage already approved; explicitly revise it before changing inputs')
        return _summary(job, stage, reused=True)
    if stage != current:
        raise ValueError(f'Current unfinished stage is {current}; cannot execute {stage}')
    _startup(job, project)
    if stage in {'visual_canary', 'visual_assets', 'subtitles', 'preview', 'delivery'}:
        from edit.hd.tools import delivery_approval
        delivery_approval.validate_visual_plan_approval(job)
    if review is not None:
        return _review(job, stage, review)
    status = job.stages[stage]['status']
    if status == 'blocked':
        return _summary(job, stage, blocked=job.stages[stage]['reason'])
    completing_cleanup = (stage == 'speech_cleanup' and cleanup_plan is not None
                          and not (job_dir / '05-speech-cleanup/cleanup-proposal.json').is_file())
    if status == 'ready_for_review' and not completing_cleanup:
        if stage == 'visual_direction':
            try:
                from edit.hd.tools.visual_confirmation import validate_visual_authorization
                validate_visual_authorization(job)
            except (ValueError, OSError):
                return _summary(job, stage, reused=True)
            return resume_visual_direction(job, project, payload)
        return _summary(job, stage, reused=True)
    if not completing_cleanup:
        state.require_runnable(job, stage)
    data = payload or {}
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
        return run_speech_cleanup(job_dir, project, video_use_result, invocation_path, cleanup_plan)
    elif stage == 'edit_structure':
        from edit.hd.tools import speech_edit_v2
        speech_edit_v2.render_edit(job)
    elif stage == 'visual_direction':
        return run_visual_direction(job_dir, project, director_brief, treatment, reviewed_visual_text)
    elif stage in {'visual_canary', 'visual_assets'}:
        if component_adapters is None and adapter_factory is not None:
            spec = importlib.util.spec_from_file_location('hd_job_adapters', _path(job, adapter_factory))
            factory = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(factory)
            component_adapters = factory.create_adapters(job, project)
        adapters = component_adapters if component_adapters is not None else native_component_adapters(project, job)
        if stage == 'visual_canary':
            from edit.hd.tools import visual_canary
            scope = (data.get('segment_ids') or job.stages[stage].get('artifact_scope')
                     or job.stages.get('visual_direction', {}).get('artifact_scope'))
            options = {'segment_ids': scope} if scope else {}
            visual_canary.prepare_visual_canary(job, component_adapters=adapters, **options)
        else:
            from edit.hd.tools import visual_assets_v2
            visual_assets_v2.prepare_visual_assets_v2(job, component_adapters=adapters)
    elif stage == 'subtitles':
        from edit.hd.tools import subtitles
        subtitles.prepare_subtitles(job)
    elif stage == 'preview':
        from edit.hd.tools import preview_v2
        coverage = _coverage_gate(job, treatment)
        defaults = _json(SKILL / 'references/production-defaults.json')
        setup = _json(job_dir / 'manifests/setup-approval.json')
        preview_v2.prepare_preview_v2(job, opening=data.get('opening', {
            **defaults['opening'], 'user_confirmation': setup['user_confirmation']}), music=data.get('music'))
        return _summary(state.load_job(job_dir), stage, needs_review_items=coverage.get('needs_review_items', []))
    elif stage == 'delivery':
        from edit.hd.tools import qa_delivery_v2
        _coverage_gate(job, treatment)
        qa_delivery_v2.prepare_delivery_v2(job)
    return _summary(state.load_job(job_dir), stage)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-context', required=True, type=Path)
    parser.add_argument('--stage', help='Omit to use the current unfinished stage')
    parser.add_argument('--project-root', type=Path)
    for option in ('input-json', 'review-json', 'video-use-result', 'invocation-json', 'cleanup-plan',
                   'director-brief', 'treatment', 'reviewed-visual-text', 'adapter-factory'):
        parser.add_argument('--' + option, type=Path)
    args = parser.parse_args()
    try:
        context = _json(args.job_context)
        project = setup_paths(args.project_root or context['project_root'])
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
