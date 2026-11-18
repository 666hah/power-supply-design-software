"""Keep inherited DOCX theme fonts from overprinting CJK headings."""
from pathlib import Path
from io import BytesIO
import sys
import unittest
from lxml.etree import tostring

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docx.oxml.ns import qn
from design_theme import select
from docx_layout import (BODY_FONT, HEADING_FONT, LATIN_FONT, TABLE_HEADER,
                         equation, finalize_book_report, new_document, paragraph, table)
from report_architecture import add_paired_figure


class WordLayoutChecks(unittest.TestCase):
    def test_report_directory_keeps_conclusion_first_and_uses_actual_chapter_targets(self):
        from docx import Document
        from docx.enum.section import WD_SECTION_START
        from docx_layout import set_a4_page

        doc = new_document('设计报告', '布局检查', '页眉')
        doc.add_heading('1 评审结论', 1)
        paragraph(doc, '输出电压待复核')
        set_a4_page(doc.add_section(WD_SECTION_START.NEW_PAGE), landscape=True)
        doc.add_heading('2 电容与纹波', 1)
        data = table(doc, ['指标', 'Vinmin', 'Vinmax'], [('输出纹波 / mV', '12', '15')])
        formula = equation(doc, 'η=Po/Pin')
        math = tostring(formula._p.xpath('./m:oMath')[0])
        add_paired_figure(doc, None, None, '图 8-1  两端波形')
        finalize_book_report(doc)
        finalize_book_report(doc)

        stream = BytesIO()
        doc.save(stream)
        document = Document(stream)
        title = [p.text for p in document.paragraphs]
        self.assertEqual(title[2], '1 评审结论')
        self.assertEqual(title.count('目录'), 1)
        self.assertLess(title.index('目录'), title.index('2 电容与纹波'))
        self.assertIn('图 2-1  两端波形', title)
        self.assertIn('(2-1)', formula.text)
        self.assertEqual(math, tostring(formula._p.xpath('./m:oMath')[0]))
        self.assertEqual(data.cell(1, 2).text, '15')
        targets = {node.get(qn('w:name')) for node in document.element.xpath('.//w:bookmarkStart')}
        self.assertEqual(targets, {'report_chapter_1', 'report_chapter_2'})
        self.assertEqual({node.get(qn('w:anchor')) for node in document.element.xpath('.//w:hyperlink')},
                         targets)
        self.assertIsNotNone(document.settings.element.find(qn('w:updateFields')))

    def test_small_notes_do_not_inherit_larger_complex_script_size(self):
        doc = new_document('测试', '排版检查', '页眉')
        p = paragraph(doc, '小字号说明', True)
        prop = p.runs[0]._element.get_or_add_rPr()
        self.assertEqual(prop.find(qn('w:szCs')).get(qn('w:val')), '18')

    def test_core_styles_have_explicit_fonts_and_matching_script_sizes(self):
        doc = new_document('测试', '排版检查', '页眉')
        for name in ('Normal', 'Title', 'Subtitle', 'Heading 1', 'Heading 2', 'Heading 3', 'Caption'):
            with self.subTest(style=name):
                style = doc.styles[name]
                prop = style.element.get_or_add_rPr()
                fonts = prop.get_or_add_rFonts()
                self.assertFalse(any('theme' in key.lower() for key in fonts.attrib))
                for script in ('ascii', 'hAnsi', 'cs'):
                    self.assertEqual(fonts.get(qn('w:'+script)), LATIN_FONT)
                east_asia = HEADING_FONT if name.startswith(('Title', 'Heading')) else BODY_FONT
                self.assertEqual(fonts.get(qn('w:eastAsia')), east_asia)
                self.assertEqual(prop.find(qn('w:sz')).get(qn('w:val')),
                                 prop.find(qn('w:szCs')).get(qn('w:val')))

    def test_mixed_orientation_reports_use_a4(self):
        doc = new_document('工作点', '两端对比', '测试')
        add_paired_figure(doc, None, None, '图 1-1  两端波形', landscape=True)
        self.assertEqual(len(doc.sections), 3)
        for section, expected in zip(doc.sections, [(210,297), (297,210), (210,297)]):
            self.assertAlmostEqual(section.page_width.mm, expected[0], places=1)
            self.assertAlmostEqual(section.page_height.mm, expected[1], places=1)
        paired = doc.tables[0]
        self.assertEqual(str(paired.cell(0,0).paragraphs[0].runs[0].font.color.rgb), 'FFFFFF')

    def test_report_table_style_keeps_evidence_and_brand_colors(self):
        for theme, header_color, text_color in [('default', TABLE_HEADER, '243547'), ('pcs', '0D1726', 'FFFFFF')]:
            with self.subTest(theme=theme):
                select(theme)
                try:
                    doc = new_document('测试', '排版检查', '页眉')
                    grid = table(doc, ['器件', '结论'], [('Q1', '需复核')], [2, 2])
                    cell = grid.cell(0,0)
                    self.assertEqual(cell._tc.tcPr.find(qn('w:shd')).get(qn('w:fill')), header_color)
                    self.assertEqual(str(cell.paragraphs[0].runs[0].font.color.rgb), text_color)
                    self.assertEqual(str(grid.cell(1,1).paragraphs[0].runs[0].font.color.rgb), 'A12D24')
                    self.assertIsNotNone(grid.rows[0]._tr.trPr.find(qn('w:tblHeader')))
                finally:
                    select('default')


if __name__ == '__main__':
    unittest.main(verbosity=2)
