from __future__ import annotations

from itertools import product
import copy
import unittest
from unittest.mock import patch

from edit.hd.tools import visual_assignment
from edit.hd.tools.visual_assignment import assign_candidates


def c(candidate_id, channel, template=None):
    return {"candidate_id": candidate_id, "channel": channel, "template_id": template}


def score(assignment, fixed_channels=(), fixed_templates=()):
    channels = set(fixed_channels) | {row["channel"] for row in assignment}
    templates = set(fixed_templates) | {
        row.get('template_identity', (row['channel'], row['template_id']))
        for row in assignment if row["template_id"] is not None
    }
    return len(channels), len(templates)


class VisualAssignmentTests(unittest.TestCase):
 def test_global_channel_maximum_counterexample(self):
    domains = [
        [c("a", "A", "a")],
        [c("a2", "A", "a"), c("b", "B", "b")],
        [c("b2", "B", "b"), c("cc", "C", "c")],
        [c("c2", "C", "c"), c("d", "D", "d")],
    ]
    result = assign_candidates(domains)
    self.assertEqual(score(result), (4, 4))


 def test_template_maximum_after_channel_maximum(self):
    domains = [
        [c("a1", "A", "one"), c("a2", "A", "two")],
        [c("a3", "A", "one"), c("a4", "A", "three")],
    ]
    result = assign_candidates(domains)
    self.assertEqual(score(result), (1, 2))


 def test_fixed_identities_and_creative_template(self):
    result = assign_candidates(
        [[c("new", "B", "fresh"), c("old", "A", "old")],
         [c("creative", "C", None)]],
        fixed_channels=("A",), fixed_templates=(("A", "old"),),
    )
    self.assertEqual(score(result, ("A",), (("A", "old"),)), (3, 2))
    self.assertIsNone(result[1]["template_id"])


 def test_matches_bruteforce_and_does_not_mutate_input(self):
    domains = [[c("a", "A", "a"), c("b", "B", "b")],
               [c("c", "A", "c"), c("d", "C", "d")],
               [c("e", "B", "e"), c("f", "C", "f")]]
    before = copy.deepcopy(domains)
    result = assign_candidates(domains)
    expected = max((score(choice) for choice in product(*domains)), key=lambda value: value)
    self.assertEqual(score(result), expected)
    self.assertEqual(domains, before)
    result[0]["candidate_id"] = "changed"
    self.assertEqual(domains[0][0]["candidate_id"], "a")


 def test_rejects_invalid_domains_and_fixed_identities(self):
    with self.assertRaises(ValueError):
        assign_candidates([[]])
    with self.assertRaises(ValueError):
        assign_candidates([[c("a", "A", "a")]], fixed_templates=(("B",),))
    with self.assertRaises(ValueError):
        assign_candidates([[c("a", "", "a")]])

 def test_twenty_slots_eight_sources_three_templates(self):
    domains = [[c(f"{i}-{s}-{t}", f"S{s}", f"T{t}")
                for s in range(8) for t in range(3)] for i in range(20)]
    result = assign_candidates(domains)
    self.assertEqual(len(result), 20)
    self.assertEqual(len({row["channel"] for row in result}), 8)
    self.assertEqual(len({(row["channel"], row["template_id"]) for row in result}), 20)

 def test_shared_origin_preserves_channels_and_optimizes_unique_templates(self):
    lemo = 'lemo-opuscar'
    cinecode = 'cinecode'
    blueprint = lemo + '/blueprint'
    dataviz = lemo + '/dataviz'
    domains = [
        [c('lemo-blueprint', lemo, blueprint)],
        [{**c('cinecode-blueprint', cinecode, blueprint), 'template_identity': (lemo, blueprint)},
         {**c('cinecode-dataviz', cinecode, dataviz), 'template_identity': (lemo, dataviz)}],
        [c('lemo-other', lemo, dataviz), c('cinecode-other', cinecode, 'cinecode/shape-morph')],
    ]
    chosen = assign_candidates(domains)
    self.assertEqual(score(chosen), max(score(choice) for choice in product(*domains)))
    self.assertEqual([row['candidate_id'] for row in chosen],
                     ['lemo-blueprint', 'cinecode-dataviz', 'cinecode-other'])
    chosen = assign_candidates([domains[1]], fixed_channels=(cinecode,),
                               fixed_templates=((lemo, blueprint),))
    self.assertEqual(chosen[0]['candidate_id'], 'cinecode-dataviz')

 def test_many_shared_templates_use_one_flow_when_both_channels_are_guaranteed(self):
    lemo = 'lemo-opuscar'
    cinecode = 'cinecode'
    styles = ('archive-lighttable', 'art-deco', 'ascii-crt', 'backrooms', 'blueprint',
              'brick-toy', 'briefing-board', 'cel-anime-80s', 'crayon-book', 'dataviz')
    domains = []
    for style in styles:
        template = f'{lemo}/{style}'
        domains.extend([
            [c(f'{lemo}:{template}', lemo, template)],
            [{**c(f'{cinecode}:cinecode/{style}', cinecode, template),
              'template_identity': (lemo, template)}],
        ])
    domains.append([c('cinecode:cinecode/shape-morph', cinecode, 'cinecode/shape-morph'),
                    c('cinecode:cinecode/line-boil', cinecode, 'cinecode/line-boil')])
    with patch.object(visual_assignment, '_assign_flow',
                      wraps=visual_assignment._assign_flow) as solve:
        result = assign_candidates(domains)
    self.assertEqual(score(result), (2, len(styles) + 1))
    self.assertEqual(result[:-1], [domain[0] for domain in domains[:-1]])
    self.assertEqual(solve.call_count, 1)

 def test_shared_pair_matches_exhaustive_choices_with_fixed_identities(self):
    left = c('left-shared', 'A', 'shared')
    right = {**c('right-shared', 'B', 'shared'), 'template_identity': ('A', 'shared')}
    creative = c('creative', 'A')
    other = c('other', 'A', 'other')
    third = c('third', 'C')
    fourth = c('fourth', 'C', 'fourth')
    domains_to_check = (
        [[left, right]],
        [[creative], [left, right, third]],
        [[left], [right, other]],
        [[left], [right, fourth]],
        [[left, third], [right, fourth]],
        [[left, third], [left, right, other], [third, fourth]],
    )
    for domains, channels, templates in product(
            domains_to_check, [(), ('A',), ('B',), ('A', 'B')],
            [(), (('A', 'shared'),), (('A', 'other'),)]):
        with self.subTest(domains=domains, channels=channels, templates=templates):
            chosen = assign_candidates(domains, fixed_channels=channels, fixed_templates=templates)
            self.assertTrue(all(row in domain for row, domain in zip(chosen, domains)))
            self.assertEqual(score(chosen, channels, templates),
                             max(score(choice, channels, templates) for choice in product(*domains)))

 def test_unrelated_shared_pairs_keep_independent_channel_scores(self):
    domains = [
        [c('a', 'A', 'x')],
        [{**c('b', 'B', 'x'), 'template_identity': ('A', 'x')}, c('b2', 'B', 'y')],
        [c('c', 'C', 'u')],
        [{**c('d', 'D', 'u'), 'template_identity': ('C', 'u')}, c('d2', 'D', 'v')],
    ]
    chosen = assign_candidates(domains)
    self.assertEqual([row['candidate_id'] for row in chosen], ['a', 'b2', 'c', 'd2'])
