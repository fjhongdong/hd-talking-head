"""Relation content exceptions must not loosen legacy proof paths."""
import importlib.util
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / 'skill-development/hd-talking-head/scripts/verify_broll_template.py'
spec = importlib.util.spec_from_file_location('relation_qualification_content', PATH)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class RelationQualificationContentTests(unittest.TestCase):
    def test_historical_runtime_contracts_are_strict_and_bound_to_argv(self):
        contracts = {
            'node': {'kind': 'file_snapshot', 'path': '/runtime/node', 'version': 'v1',
                     'sha256': 'a' * 64, 'library_discovery': 'mach_o_static_v1', 'libraries': []},
            'playwright': {'kind': 'directory_tree', 'path': '/runtime/playwright/index.js',
                           'version': 'v1', 'roots': [{'path': '/runtime/playwright', 'sha256': 'b' * 64}]},
            'browser': {'kind': 'directory_tree', 'path': '/runtime/browser/chrome',
                        'version': 'v1', 'roots': [{'path': '/runtime/browser', 'sha256': 'c' * 64}]},
            'ffmpeg': {'kind': 'file_snapshot', 'path': '/runtime/ffmpeg', 'version': 'v1',
                       'sha256': 'd' * 64, 'library_discovery': 'mach_o_static_v1', 'libraries': []},
            'ffprobe': {'kind': 'file_snapshot', 'path': '/runtime/ffprobe', 'version': 'v1',
                        'sha256': 'e' * 64, 'library_discovery': 'mach_o_static_v1', 'libraries': []},
        }
        encoded = json.dumps(contracts, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'))
        binding = {'runtime_contracts': contracts}
        evidence = {'runtime_contracts': copy.deepcopy(contracts),
                    'argv': ['render', '--runtime-contracts', encoded]}
        self.assertEqual(verifier._verify_runtime_contract_binding(binding, evidence), contracts)
        bad = copy.deepcopy(evidence)
        bad['runtime_contracts']['node']['version'] = 'v2'
        with self.assertRaises(verifier.RegistryError):
            verifier._verify_runtime_contract_binding(binding, bad)
        for mutation in ('missing_tool', 'bad_path', 'empty_roots', 'bad_library',
                         'downgrade_static', 'argv_mismatch'):
            changed_binding, changed_evidence = copy.deepcopy(binding), copy.deepcopy(evidence)
            if mutation == 'missing_tool':
                del changed_binding['runtime_contracts']['ffprobe']
                changed_evidence['runtime_contracts'] = copy.deepcopy(changed_binding['runtime_contracts'])
            elif mutation == 'bad_path':
                changed_binding['runtime_contracts']['node']['path'] = '/runtime/../node'
                changed_evidence['runtime_contracts'] = copy.deepcopy(changed_binding['runtime_contracts'])
            elif mutation == 'empty_roots':
                changed_binding['runtime_contracts']['browser']['roots'] = []
                changed_evidence['runtime_contracts'] = copy.deepcopy(changed_binding['runtime_contracts'])
            elif mutation == 'bad_library':
                changed_binding['runtime_contracts']['ffprobe']['libraries'] = [False]
                changed_evidence['runtime_contracts'] = copy.deepcopy(changed_binding['runtime_contracts'])
            elif mutation == 'downgrade_static':
                for record in (changed_binding['runtime_contracts'], changed_evidence['runtime_contracts']):
                    record['node'].pop('library_discovery')
                    record['node'].pop('libraries')
                changed_evidence['argv'][-1] = json.dumps(changed_evidence['runtime_contracts'],
                    ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            else:
                changed_evidence['argv'][-1] = '{}'
            with self.subTest(mutation=mutation), self.assertRaises(verifier.RegistryError):
                verifier._verify_runtime_contract_binding(changed_binding, changed_evidence)

    def test_semantic_execution_pair_consumes_native_brief(self):
        from edit.hd.tests.test_semantic_state_renderer import brief
        registry = json.loads((PATH.parents[1] / 'references/verified-template-registry.json').read_text())
        base = next(item for item in registry['templates'] if item['template_origin'] == 'verified_local_canonical')
        for family in ('replacement', 'threshold', 'delay', 'hierarchy', 'feedback'):
            item = copy.deepcopy(base)
            item.update(template_id='hd-talking-head/semantic-state-' + family,
                        source_entrypoint='scripts/semantic_state_renderer_bundle.py')
            item['upstream']['project'] = 'hd-talking-head-semantic-state'
            item['render_contract'].update(engine='SemanticState', composition_id='semantic-state-' + family)
            item['execution_qa']['content_paths'] = ['/title', '/motion/source_text', '/motion/subjects']
            previous = copy.deepcopy(item)
            previous['verification_id'] = verifier._verification_id(previous)
            value = brief(family)
            recipe = {'schema_version': 2, 'mode': 'single',
                      'canvas': {'width': 1080, 'height': 1920, 'fps': 24}, 'components': [{}]}
            # Stop at request derivation: no fake receipt or synthetic pixels qualify.
            class RequestReached(Exception):
                pass
            with self.subTest(family=family), mock.patch.object(verifier, '_proof_json', side_effect=[
                    {'schema_version': 1, 'templates': [previous]}, value, recipe, {}]), \
                 mock.patch.object(verifier, '_proof_asset', return_value=Path('/not-published')), \
                 mock.patch.object(verifier, '_semantic_state_template_request', side_effect=RequestReached) as request:
                with self.assertRaises(RequestReached):
                    verifier._verify_execution_pair(PATH.parents[1], item)
                request.assert_called_once_with(value, family)

    def test_semantic_request_derived_from_brief_not_supplied_metadata(self):
        from edit.hd.tests.test_semantic_state_renderer import brief
        for family in ('replacement', 'threshold', 'delay', 'hierarchy', 'feedback'):
            value = brief(family)
            with self.subTest(family=family):
                self.assertEqual(verifier._semantic_state_template_request(value, family), {
                    'semantic_family': family, 'information_units': len(value['motion']['subjects']),
                    'numeric_values': [], 'numeric_scale': 'not_applicable'})
                for changes in ({'template_request': {}}, {'roles': None}, {'motion': None}):
                    with self.assertRaises(verifier.RegistryError):
                        verifier._semantic_state_template_request(dict(value, **changes), family)
                with self.assertRaises(verifier.RegistryError):
                    verifier._semantic_state_template_request(value, 'unknown')
                bad = copy.deepcopy(value)
                bad['motion']['subjects'].append(copy.deepcopy(bad['motion']['subjects'][0]))
                with self.assertRaises(verifier.RegistryError):
                    verifier._semantic_state_template_request(bad, family)

    def test_semantic_identity_reaches_source_gate_not_qualification(self):
        registry = json.loads((PATH.parents[1] / 'references/verified-template-registry.json').read_text())
        base = next(item for item in registry['templates']
                    if item['template_origin'] == 'verified_local_canonical')
        class SourceReached(Exception):
            pass
        for family in ('replacement', 'threshold', 'delay', 'hierarchy', 'feedback'):
            template = copy.deepcopy(base)
            template.pop('execution_qa')
            template.update(template_id='hd-talking-head/semantic-state-' + family,
                            source_entrypoint='scripts/semantic_state_renderer_bundle.py')
            template['upstream']['project'] = 'hd-talking-head-semantic-state'
            template['render_contract'].update(engine='SemanticState', composition_id='semantic-state-' + family)
            template['verification_id'] = verifier._verification_id(template)
            with self.subTest(family=family), mock.patch.object(verifier, '_relative_asset', side_effect=SourceReached):
                with self.assertRaises(SourceReached):
                    verifier._verify_template(PATH.parents[1], template, require_execution=False)
                for section, key, value in ((None, 'template_id', 'hd-talking-head/semantic-state-unknown'),
                        (None, 'source_entrypoint', 'scripts/other.py'),
                        ('render_contract', 'engine', 'RelationMotion'),
                        ('render_contract', 'composition_id', 'semantic-state-unknown'),
                        ('upstream', 'repository', 'elsewhere')):
                    bad = copy.deepcopy(template)
                    (bad if section is None else bad[section])[key] = value
                    bad['verification_id'] = verifier._verification_id(bad)
                    with self.subTest(key=key), self.assertRaises(verifier.RegistryError):
                        verifier._verify_template(PATH.parents[1], bad, require_execution=False)

    def test_native_relation_identity_reaches_source_verification_without_qualifying(self):
        registry = json.loads((PATH.parents[1] / 'references/verified-template-registry.json').read_text())
        template = copy.deepcopy(next(item for item in registry['templates']
                                      if item['template_origin'] == 'verified_local_canonical'))
        template.pop('execution_qa')
        template.update(template_id='hd-talking-head/relation-motion',
                        source_entrypoint='scripts/relation_motion_renderer_bundle.py')
        template['upstream']['project'] = 'hd-talking-head-relation-motion'
        template['render_contract'].update(engine='RelationMotion', composition_id='relation-motion')

        class SourceReached(Exception):
            pass

        template['verification_id'] = verifier._verification_id(template)
        with mock.patch.object(verifier, '_relative_asset', side_effect=SourceReached):
            with self.assertRaises(SourceReached):
                verifier._verify_template(PATH.parents[1], template, require_execution=False)
            for section, key, value in ((None, 'template_id', 'different'),
                                        (None, 'source_entrypoint', 'scripts/other.py'),
                                        ('render_contract', 'engine', 'HyperFrames'),
                                        ('render_contract', 'composition_id', 'different'),
                                        ('upstream', 'project', 'different'),
                                        ('upstream', 'repository', 'different')):
                wrong = copy.deepcopy(template)
                (wrong if section is None else wrong[section])[key] = value
                wrong['verification_id'] = verifier._verification_id(wrong)
                with self.subTest(section=section, key=key), self.assertRaises(verifier.RegistryError):
                    verifier._verify_template(PATH.parents[1], wrong, require_execution=False)

    def test_relation_registry_proof_uses_runtime_evidence_not_a_cli_flag(self):
        reference = {'path': 'assets/verified-templates/relation/qualification/source-registry.json',
                     'sha256': 'a' * 64}
        evidence = {'argv': ['$LAUNCHER', '$DEPENDENCY/bundle.py'],
                    'qualification_registry': reference}
        verifier._verify_registry_invocation(evidence, reference, relation=True)
        for change in ({}, {'path': 'different.json', 'sha256': 'a' * 64},
                       dict(reference, sha256='b' * 64), dict(reference, extra=True)):
            with self.subTest(change=change), self.assertRaises(verifier.RegistryError):
                verifier._verify_registry_invocation(dict(evidence, qualification_registry=change),
                                                     reference, relation=True)
        with self.assertRaises(verifier.RegistryError):
            verifier._verify_registry_invocation({'argv': ['--registry-sha256', 'a' * 64]},
                                                 reference, relation=True)

    def test_legacy_registry_proof_still_requires_its_existing_cli_contract(self):
        reference = {'path': 'registry.json', 'sha256': 'a' * 64}
        verifier._verify_registry_invocation({'argv': ['render', '--registry-sha256', 'a' * 64]},
                                             reference, relation=False)
        with self.assertRaises(verifier.RegistryError):
            verifier._verify_registry_invocation({'argv': ['render'], 'qualification_registry': reference},
                                                 reference, relation=False)

    def test_candidate_hash_and_validation_use_the_same_bytes(self):
        first = {key: "first" for key in verifier.PROVENANCE_FIELDS}
        second = {key: "second" for key in verifier.PROVENANCE_FIELDS}
        first_bytes = json.dumps({"schema_version": 1, "templates": [first]}).encode()
        second_bytes = json.dumps({"schema_version": 1, "templates": [second]}).encode()
        digest = hashlib.sha256(first_bytes).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source-registry.json'
            path.write_bytes(first_bytes)

            def hash_then_replace(candidate):
                result = hashlib.sha256(candidate.read_bytes()).hexdigest()
                candidate.write_bytes(second_bytes)
                return result

            with mock.patch.object(verifier, '_relative_asset', return_value=path), \
                 mock.patch.object(verifier, '_sha256', side_effect=hash_then_replace), \
                 mock.patch.object(verifier, '_verify_template', side_effect=lambda root, item, **kw: item):
                with self.assertRaises(verifier.RegistryError):
                    verifier.verify_candidate_binding(second,
                        'assets/verified-templates/relation/qualification/source-registry.json', digest)

    def test_candidate_reads_one_snapshot(self):
        candidate = {key: 'value' for key in verifier.PROVENANCE_FIELDS}
        snapshot = json.dumps({'schema_version': 1, 'templates': [candidate]}).encode()
        with mock.patch.object(verifier, '_relative_asset', return_value=Path('/candidate.json')), \
             mock.patch.object(Path, 'read_bytes', return_value=snapshot) as read, \
             mock.patch.object(verifier, '_verify_template', side_effect=lambda root, item, **kw: item):
            result = verifier.verify_candidate_binding(candidate,
                'assets/verified-templates/relation/qualification/source-registry.json',
                hashlib.sha256(snapshot).hexdigest())
        self.assertEqual(result, candidate)
        read.assert_called_once_with()

    def test_relation_request_is_derived_from_strict_brief(self):
        brief = {'schema_version': 1, 'canvas': {}, 'title': '关系',
                 'motion': {'family': 'relation', 'subjects': [
                     {'id': 'a'}, {'id': 'b'}, {'id': 'hub'}]},
                 'source_ids': ['a', 'b'], 'hub_id': 'hub'}
        self.assertEqual(verifier._relation_template_request(brief), {
            'semantic_family': 'relation', 'information_units': 2,
            'numeric_values': [], 'numeric_scale': 'not_applicable'})
        for changes in ({'template_request': {}}, {'source_ids': ['a', 'a']},
                        {'hub_id': 'a'}, {'motion': {'family': 'delay'}}):
            with self.subTest(changes=changes), self.assertRaises(verifier.RegistryError):
                verifier._relation_template_request(dict(brief, **changes))

    def test_relation_content_paths_bind_real_labels_not_style(self):
        brief = {'title': '工作细节', 'motion': {'source_text': '原文',
                 'subjects': [{'id': 'a', 'label': '经验'}]}, 'canvas': {'fps': 24}}
        self.assertEqual(verifier._proof_content(brief, '/motion/subjects', relation=True),
                         brief['motion']['subjects'])
        self.assertEqual(verifier._proof_content(brief, '/title', relation=True), '工作细节')
        with self.assertRaises(verifier.RegistryError):
            verifier._proof_content(brief, '/canvas/fps', relation=True)

    def test_legacy_paths_stay_strict(self):
        with self.assertRaises(verifier.RegistryError):
            verifier._proof_content({'title': 'new'}, '/title')
        self.assertEqual(verifier._proof_content({'props': {'data': {'label': 'old'}}},
                                                '/props/data/label'), 'old')
