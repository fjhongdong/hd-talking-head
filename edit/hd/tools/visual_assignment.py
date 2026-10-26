"""Exact lexicographic assignment of visual candidates.

The planner supplies one domain per semantic visual item.  This helper keeps
the complete candidate domains and chooses a globally optimal assignment:
first maximize distinct canonical channels, then distinct concrete templates.
It deliberately does not infer aliases or solve budget/group constraints.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping, Sequence


def _validate_candidate(value: Mapping) -> dict:
    if not isinstance(value, Mapping):
        raise ValueError("visual candidate must be a mapping")
    channel = value.get("channel")
    candidate_id = value.get("candidate_id")
    template = value.get("template_id")
    if not isinstance(channel, str) or not channel.strip():
        raise ValueError("visual candidate channel must be a non-empty string")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("visual candidate candidate_id must be a non-empty string")
    if template is not None and (not isinstance(template, str) or not template.strip()):
        raise ValueError("visual candidate template_id must be a non-empty string or None")
    result = dict(value)
    result["channel"] = channel
    result["candidate_id"] = candidate_id
    result["template_id"] = template
    return result


def _validate_fixed_channels(values: Sequence[str]) -> frozenset[str]:
    result = frozenset(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError("fixed channel must be a non-empty string")
    return result


def _validate_fixed_templates(values: Sequence[tuple[str, str]]) -> frozenset[tuple[str, str]]:
    result = frozenset(values)
    for item in result:
        if (not isinstance(item, tuple) or len(item) != 2
                or any(not isinstance(value, str) or not value.strip() for value in item)):
            raise ValueError("fixed template must be a (channel, template_id) tuple")
    return result


def assign_candidates(
    domains: Sequence[Sequence[Mapping]],
    *,
    fixed_channels: Sequence[str] = (),
    fixed_templates: Sequence[tuple[str, str]] = (),
) -> list[dict]:
    """Choose one candidate per slot with global lexicographic maxima.

    The returned list contains copies of the selected input candidates in slot
    order.  `fixed_channels` and `fixed_templates` describe already-used
    identities; aliases must be canonicalized by the caller.
    """
    if not isinstance(domains, Sequence):
        raise ValueError("domains must be a sequence")
    fixed_c = _validate_fixed_channels(fixed_channels)
    fixed_t = _validate_fixed_templates(fixed_templates)
    if any(channel not in fixed_c for channel, _ in fixed_t):
        raise ValueError("fixed template channel must also be a fixed channel")
    normalized: list[list[dict]] = []
    for domain in domains:
        if not isinstance(domain, Sequence) or not domain:
            raise ValueError("every visual slot must have at least one candidate")
        candidates = [_validate_candidate(candidate) for candidate in domain]
        if len({candidate["candidate_id"] for candidate in candidates}) != len(candidates):
            raise ValueError("candidate_id must be unique within a slot")
        normalized.append(candidates)

    return _assign_flow(normalized, fixed_c, fixed_t)


def _assign_flow(domains, fixed_channels, fixed_templates):
    """Min-cost max-flow with lexicographic source/template rewards."""
    nslots = len(domains); source = 0; next_node = 1
    slot_nodes = list(range(next_node, next_node + nslots)); next_node += nslots
    template_keys = sorted({(c["channel"], c["template_id"]) for d in domains for c in d if c["template_id"] is not None})
    template_nodes = {key: next_node + i for i, key in enumerate(template_keys)}; next_node += len(template_keys)
    channels = sorted({c["channel"] for d in domains for c in d} | set(fixed_channels))
    channel_nodes = {key: next_node + i for i, key in enumerate(channels)}; next_node += len(channels)
    sink = next_node; graph=[[] for _ in range(sink+1)]
    def add(a,b,cap,cost,tag=None):
        graph[a].append([b, len(graph[b]), cap, cost, tag]); graph[b].append([a, len(graph[a])-1, 0, -cost, None])
    for i,d in enumerate(domains):
        add(source,slot_nodes[i],1,0)
        for c in d:
            target = template_nodes.get((c["channel"],c["template_id"])) if c["template_id"] is not None else channel_nodes[c["channel"]]
            add(slot_nodes[i],target,1,0, c)
    reward_source=len(domains)+1
    for key,node in template_nodes.items():
        add(node,channel_nodes[key[0]],1,0 if key in fixed_templates else -1)
        add(node,channel_nodes[key[0]],len(domains),0)
    for channel,node in channel_nodes.items():
        add(node,sink,1,0 if channel in fixed_channels else -reward_source)
        add(node,sink,len(domains),0)
    for _ in domains:
        dist=[10**9]*len(graph); prev=[None]*len(graph); dist[source]=0
        for _ in range(len(graph)):
            changed=False
            for a,edges in enumerate(graph):
                for j,e in enumerate(edges):
                    if e[2] and dist[a] < 10**9 and dist[a]+e[3]<dist[e[0]]:
                        dist[e[0]]=dist[a]+e[3]; prev[e[0]]=(a,j); changed=True
            if not changed: break
        if prev[sink] is None: raise ValueError("no complete visual assignment")
        v=sink
        while v!=source:
            a,j=prev[v]; e=graph[a][j]; e[2]-=1; graph[v][e[1]][2]+=1; v=a
    result=[]
    for i,d in enumerate(domains):
        chosen=None
        for e in graph[slot_nodes[i]]:
            if e[4] is not None and e[2]==0: chosen=e[4]; break
        if chosen is None: raise ValueError("flow did not assign every visual slot")
        result.append(chosen)
    return deepcopy(result)
