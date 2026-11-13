"""Review the CineCode routes against its pinned style recipes and their origins."""
from __future__ import annotations

from pathlib import Path

from edit.hd.tools.contract_artifacts import read_json_artifact

CATALOG = 'references/cinecode-template-catalog.json'
SOURCE = 'vendor/cinecode'
STYLE_INDEX = SOURCE + '/styles/index.json'
LOOKS = SOURCE + '/references/looks.md'
SKILL = SOURCE + '/SKILL.md'
COMMIT = 'c8a3e7552699360a2b0142c9620882af2069eedb'
INDUSTRIAL = 'cinematic-realistic'

# Only original branches with a real prerequisite belong here. The original
# Skill still chooses the shot, design and internal implementation.
IMAGES = ('.png', '.jpg', '.jpeg', '.webp', '.avif', '.tif', '.tiff', '.gif', '.bmp')
VIDEOS = ('.mp4', '.mov', '.webm', '.m4v', '.mkv')
MATERIAL_BRANCHES = {
    'variety-captions': {'video': VIDEOS, 'photo': IMAGES, 'drawn': ()},
    'archive-lighttable': {'archive_scan': (*IMAGES, '.pdf')},
    'microscope': {'micrograph': IMAGES, 'whole_slide': (*IMAGES, '.svs', '.ndpi', '.mrxs', '.scn')},
    'satellite-briefing': {'satellite_imagery': (*IMAGES, '.jp2')},
    'lidar-survey': {'point_cloud': ('.las', '.laz', '.copc', '.ply', '.pcd', '.xyz', '.csv', '.bin')},
    'teardown': {'engineering_files': ('.step', '.stp', '.iges', '.igs', '.kicad_pcb', '.stl', '.obj',
                                         '.glb', '.gltf', '.csv', '.xlsx', '.pdf', '.zip'),
                 'published_dimensions': (*IMAGES, '.pdf', '.html', '.md', '.txt', '.csv', '.json')},
    'living-screencast': {'product_reference': (*IMAGES, *VIDEOS, '.html', '.pdf', '.md', '.txt', '.json', '.svg')},
    'white-model': {'building_data': ('.geojson', '.json', '.gpkg', '.gml', '.csv', '.zip', '.glb', '.gltf', '.ifc')},
    'data-physical': {'source_data': ('.csv', '.tsv', '.xlsx', '.json', '.pdf', '.html', '.md', '.txt', *IMAGES)},
}
FUTURE_BRANCHES = {'video': 'video', 'photo': 'image'}
BRANCH_LABELS = {
    'video': '视频底图', 'photo': '照片底图', 'drawn': '原生绘制底图', 'archive_scan': '真实档案扫描',
    'micrograph': '真实显微图', 'whole_slide': '真实整片扫描', 'satellite_imagery': '真实卫星或航空影像',
    'point_cloud': '实测点云', 'engineering_files': '真实工程文件', 'published_dimensions': '已发布尺寸',
    'product_reference': '真实产品资料', 'building_data': '真实建筑数据', 'source_data': '真实统计数据',
}


def validate_material_plan(slug, plan, *, job_dir, generation_steps=(), key=()):
    """Validate a candidate's planning inputs without creating its native project."""
    branches = MATERIAL_BRANCHES.get(slug, {})
    if not branches:
        if plan is not None:
            raise ValueError('CineCode 配方没有需要声明的素材分支')
        return
    if not isinstance(plan, dict) or not isinstance(plan.get('branch'), str) or plan['branch'] not in branches:
        raise ValueError('CineCode 需先选定素材分支：' + '、'.join(branches))
    branch = plan['branch']
    if branch == 'drawn':
        if set(plan) != {'branch'}:
            raise ValueError('CineCode 手绘底图分支不声明外部底图')
        return
    if 'step_id' in plan:
        if (set(plan) != {'branch', 'step_id'} or branch not in FUTURE_BRANCHES
                or not isinstance(plan['step_id'], str) or not plan['step_id'] or not any(
                    step.get('id') == plan['step_id'] and step.get('purpose') == FUTURE_BRANCHES[branch]
                    and (step.get('segment_id'), step.get('component_id')) == key for step in generation_steps)):
            raise ValueError('CineCode 未来素材必须来自本镜已列明的同类生成步骤；真实证据不可用生成素材替代')
        return
    if (set(plan) != {'branch', 'material', 'source'} or job_dir is None
            or not isinstance(plan['source'], str) or not plan['source'].strip()):
        raise ValueError('CineCode 素材分支需要本镜已有素材及来源')
    from .motion_native_skill_adapter import exact
    file = exact(job_dir, plan['material'], input_fact=True)
    if not file.is_file() or file.suffix.lower() not in branches[branch]:
        raise ValueError('CineCode 本镜素材类型与所选原生分支不符：' + branch)
    if branch in FUTURE_BRANCHES:
        from .motion_native_skill_adapter import _cinecode_caption_material
        _cinecode_caption_material(job_dir, {'cinecode_material_branch': branch, 'materials': [plan['material']]})


def load_template_catalog(project_root: Path) -> list[dict]:
    project = Path(project_root).resolve(strict=True)
    styles = read_json_artifact(project / STYLE_INDEX)['styles']
    indexed = {style['id']: style for style in styles}
    if len(indexed) != 58 or len(styles) != len(indexed) or INDUSTRIAL in indexed:
        raise ValueError('CineCode requires its complete pinned style index')
    indexed[INDUSTRIAL] = {'source': 'cinecode', 'base': INDUSTRIAL,
                           'category': 'Cinematic Realism'}
    catalog = read_json_artifact(project / CATALOG)
    if (catalog.get('schema_version') != 3 or catalog.get('channel') != 'cinecode'
            or catalog.get('repository_commit') != COMMIT):
        raise ValueError('CineCode catalog identity changed')
    rows = catalog['native_paths']
    if len(rows) != len(indexed) or {row['style_slug'] for row in rows} != set(indexed):
        raise ValueError('CineCode catalog does not contain exactly its registered styles')

    for row in rows:
        slug = row['style_slug']
        style = indexed[slug]
        origin = 'cinecode' if style.get('source') == 'cinecode' else 'lemo-opuscar'
        recipe = LOOKS if slug == INDUSTRIAL else SOURCE + '/styles/' + slug + '.md'
        identity = {
            'candidate_id': 'cinecode:cinecode/' + slug,
            'template_id': 'cinecode/' + slug,
            'canonical_template': origin + '/' + slug,
            'style_origin': origin,
            'base_style': style['base'],
            'skill_path': SKILL,
            'recipe_path': recipe,
            'native_source': recipe,
            'native_template_group': style['category'],
            'native_role': 'scene',
            'uses': ['broll'],
        }
        if any(row.get(key) != value for key, value in identity.items()):
            raise ValueError('CineCode route differs from its selected native style: ' + slug)
        instructions = row['native_instructions']
        if (recipe not in instructions or LOOKS not in instructions
                or any(not path.startswith(SOURCE + '/') or '..' in Path(path).parts
                       or not (project / path).is_file() for path in instructions)):
            raise ValueError('CineCode native style instructions are incomplete: ' + slug)
        if origin == 'lemo-opuscar':
            lemo_style = project / 'vendor/lemo-opuscar/styles' / slug
            if (read_json_artifact(lemo_style / 'style.json').get('slug') != slug
                    or not (lemo_style / 'STYLE.md').is_file()):
                raise ValueError('CineCode shared style lacks its matching Lemo route: ' + slug)
    return [{**row, **({'cinecode_branches': list(MATERIAL_BRANCHES[row['style_slug']])}
                       if row['style_slug'] in MATERIAL_BRANCHES else {})} for row in rows]
