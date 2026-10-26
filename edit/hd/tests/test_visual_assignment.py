from __future__ import annotations

from itertools import product
import copy
import unittest

from edit.hd.tools.visual_assignment import assign_candidates


def c(candidate_id, channel, template=None):
    return {"candidate_id": candidate_id, "channel": channel, "template_id": template}


def score(assignment, fixed_channels=(), fixed_templates=()):
    channels = set(fixed_channels) | {row["channel"] for row in assignment}
    templates = set(fixed_templates) | {
        (row["channel"], row["template_id"])
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
        assign_candidates([[c("a", "A", "a")]], fixed_templates=(("B", "b"),))
    with self.assertRaises(ValueError):
        assign_candidates([[c("a", "", "a")]])

 def test_twenty_slots_eight_sources_three_templates(self):
    domains = [[c(f"{i}-{s}-{t}", f"S{s}", f"T{t}")
                for s in range(8) for t in range(3)] for i in range(20)]
    result = assign_candidates(domains)
    self.assertEqual(len(result), 20)
    self.assertEqual(len({row["channel"] for row in result}), 8)
    self.assertEqual(len({(row["channel"], row["template_id"]) for row in result}), 20)
