import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MusicReleaseContractTests(unittest.TestCase):
    def test_preflight_requires_formal_music_validator(self):
        manifest = json.loads((ROOT / 'references/dependency-manifest.json').read_text())
        preview = next(item for item in manifest['dependencies'] if item['id'] == 'preview-runner')
        self.assertIn('validate_preview_music', preview['api'])

    def test_entry_and_contract_state_music_authorization(self):
        entry = (ROOT / 'SKILL.md').read_text()
        self.assertIn('默认无背景音乐', entry)
        self.assertNotIn('BGM 正式混音尚未接入', entry)
        contract = (ROOT / 'references/cover-opening-bgm.md').read_text()
        for token in ('默认无背景音乐', '用户明确要求', '本次授权', '局部返修'):
            self.assertIn(token, contract)


if __name__ == '__main__':
    unittest.main()
