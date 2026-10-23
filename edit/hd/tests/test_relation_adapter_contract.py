"""Dependency identity declaration does not grant template qualification."""
import unittest
from unittest import mock

from edit.hd.tools import broll_component_executor as executor


class RelationAdapterContractTests(unittest.TestCase):
    def test_router_identifies_relation_and_rejects_wrong_renderer(self):
        from edit.hd.tools.visual_plan import _load_router_module
        router = _load_router_module()
        dependency = 'hd-talking-head-relation-motion'
        self.assertEqual(router._executor('code_generated', {'dependency_id': dependency}),
                         'reference_adapter')
        router._validate_renderer_binding(dependency, 'RelationMotion')
        with self.assertRaises(router.RouterError):
            router._validate_renderer_binding(dependency, 'HyperFrames')

    def test_registered_engine_mapping_does_not_bypass_registry(self):
        from edit.hd.tools.visual_plan import _load_router_module
        router = _load_router_module()
        dependency = 'hd-talking-head-relation-motion'
        component = {'dependency_id': dependency, 'primary_renderer': 'RelationMotion',
                     'entrypoint': 'scripts/relation.py', 'template_origin': 'verified_local_canonical',
                     'invocation_record': {'argv': ['python3', 'scripts/relation.py']}}
        record = {'render_contract': {'engine': 'RelationMotion'},
                  'upstream': {'project': dependency}}
        with mock.patch.object(router, '_registered_template', return_value=record) as lookup:
            router._validate_code_cross_fields(component)
            lookup.assert_called_once_with(component, None)
        with mock.patch.object(router, '_registered_template', side_effect=router.RouterError('unqualified')):
            with self.assertRaisesRegex(router.RouterError, 'unqualified'):
                router._validate_code_cross_fields(component)

    def test_independent_renderer_identity_is_declared(self):
        self.assertEqual(
            executor._DEPENDENCY_CONTRACTS.get('hd-talking-head-relation-motion'),
            ('reference_adapter', 'RelationMotion'))
        self.assertEqual(executor._DEPENDENCY_CONTRACTS['hd-talking-head-local-canonical'],
                         ('reference_adapter', 'HyperFrames'))

    def test_declared_dependency_does_not_accept_an_unbound_adapter(self):
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor._validate_code_adapter(object(), {
                'dependency_id': 'hd-talking-head-relation-motion'})
        self.assertEqual(caught.exception.error_code, 'BROLL_DEPENDENCY_UNBOUND')
