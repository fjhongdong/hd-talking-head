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
            'requires_footage': slug == 'variety-captions',
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
    return rows
