"""Ensure every desktop diagram card resolves to an offline help chapter."""

from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import unquote
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_resources import resource_path
from software_architecture_data import PAGES, TOPICS
from software_architecture_help import open_architecture_tutorial


TEXT_GUIDES = {'mag', 'sequence', 'fem', 'spice', 'joint'}
LOCAL_SCREENSHOTS = TEXT_GUIDES | {'mag_winding'}


class LocalLinks(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.targets = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.targets.extend(unquote(value) for key, value in attrs
                            if key in ('href', 'src') and value)


class ArchitectureTutorialCheck(unittest.TestCase):
    def test_all_card_topics_and_chapter_assets_are_available(self):
        directory = resource_path('resources/help/operations')
        topics = {TOPICS[node[0]] for page in PAGES.values() for node in page['nodes']}
        self.assertEqual(len(topics), 14)
        page_names = {path.stem for path in directory.glob('*.html')}
        self.assertEqual(topics | {'index'}, page_names)
        for topic in page_names:
            with self.subTest(topic=topic):
                page = directory / f'{topic}.html'
                content = page.read_text(encoding='utf-8')
                links = LocalLinks(content).targets
                for link in links:
                    self.assertTrue((directory/link).is_file(), link)
                    self.assertNotIn(link, {f'screens/{shot}.jpg' for shot in LOCAL_SCREENSHOTS})
                with patch('software_architecture_help.os.startfile') as launch:
                    open_architecture_tutorial(topic, None)
                launch.assert_called_once_with(str(page))
                if topic in TEXT_GUIDES:
                    self.assertIn('操作步骤', content)
                    self.assertIn('输入字段', content)
                elif topic != 'index':
                    self.assertTrue(any(link.startswith('screens/') for link in links))

    def test_word_contains_native_chapter_navigation_and_images(self):
        word = resource_path('resources/help/operations/开关电源设计软件操作教程.docx')
        if not word.is_file():
            self.skipTest('Word 是可选的本地构建产物，公开仓库随附完整 HTML 章节。')
        with ZipFile(word) as archive:
            xml = archive.read('word/document.xml')
            self.assertEqual(xml.count(b'w:anchor="calculation_chapter_'), 14)
            self.assertGreaterEqual(xml.count(b'<w:drawing>'), 11)
            self.assertEqual(xml.count(b'<w:tblHeader'), 14)
            self.assertIsNone(archive.testzip())


if __name__ == '__main__':
    unittest.main(verbosity=2)
