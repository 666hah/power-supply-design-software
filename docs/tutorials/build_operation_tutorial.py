"""Build the desktop's offline chapters and Word manual from the same content."""

import argparse
from html import escape
from pathlib import Path
import shutil
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.shared import Mm, Pt
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from docs.calculation_reference_layout import prepare_book, _set_bookmark, _toc_link
from docx_layout import table
from operation_topics_design import TOPICS as DESIGN
from operation_topics_validation import TOPICS as VALIDATION


TITLE = '开关电源设计软件操作教程'
SUBTITLE = '从供电架构到计算 仿真与交付'
WORD = TITLE + '.docx'
INTRO = (
    '本教程用于桌面版。从启动后的供电网络画布开始，依次配置电源单元、核对计算、'
    '准备磁件与电路仿真，再保存可复核的工程和报告。可按目录学习，也可从软件顶部的'
    '“功能架构”直接打开所需一章。'
)
EXAMPLES = (
    '截图来自软件随附的练习工程。三路 CCM 反激用来说明功率级和补偿元件，Buck 电压模式用来说明环路页。'
    '双路 L6565 准谐振反激可以用来练习绕制和磁件仿真。'
    '分阶段电源树用来说明系统启停。各字段的数值应按自己的器件和工作条件填写。'
)
GROUPS = (
    ('系统与供电网络', ('project', 'tree', 'ldo')),
    ('单元参数和设计计算', ('needs', 'initial', 'power', 'mag', 'loop')),
    ('仿真与工程交付', ('sequence', 'fem', 'spice', 'joint', 'review', 'report')),
)
TOPICS = DESIGN | VALIDATION
KEYS = tuple(key for _, keys in GROUPS for key in keys)
ORDER = {key: n for n, key in enumerate(KEYS, 1)}
FIELDS = ('字段或选项', '单位或取值', '输入的含义及用途')


def chapter_title(key):
    return f"{ORDER[key]:02d}  {TOPICS[key]['title']}"


def write_word(output, screens):
    doc = Document(ROOT/'docs/reference/计算方法与公式说明.docx')
    doc._body.clear_content()
    for identifier, relation in list(doc.part.rels.items()):
        if relation.reltype.rsplit('/', 1)[-1] in ('image', 'hyperlink'):
            doc.part.drop_rel(identifier)
    # Retain the reference's page, styles, and recurring elements.
    prepare_book(doc)
    doc.sections[0].header.paragraphs[0].text = '开关电源设计与环路分析　｜　软件操作教程'
    doc.core_properties.title = TITLE
    doc.core_properties.subject = '桌面版功能架构与操作'
    doc.add_paragraph(TITLE, 'Title').paragraph_format.space_before = Pt(104)
    doc.add_paragraph(SUBTITLE, 'Subtitle')
    doc.add_paragraph(INTRO)
    doc.add_paragraph(EXAMPLES)
    doc.add_paragraph('先从第 1–4 章认识工程文件与输入。需要回填电磁仿真参数时，连读第 7、10、12 章。')

    directory = doc.add_paragraph('目录', 'Contents Title')
    directory.paragraph_format.page_break_before = True
    directory.paragraph_format.keep_with_next = True
    for group, keys in GROUPS:
        doc.add_paragraph(group, 'Contents Group').paragraph_format.keep_with_next = True
        for key in keys:
            entry = doc.add_paragraph(style='Contents Entry')
            entry.paragraph_format.left_indent = Mm(5)
            entry.paragraph_format.tab_stops.add_tab_stop(
                Mm(174), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            _toc_link(entry, chapter_title(key), f'calculation_chapter_{ORDER[key]}')

    for key in KEYS:
        topic, chapter = TOPICS[key], ORDER[key]
        heading = doc.add_heading(chapter_title(key), level=1)
        heading.paragraph_format.page_break_before = chapter in (1, 4, 9)
        _set_bookmark(heading, chapter)
        doc.add_paragraph(topic['intro'])
        doc.add_paragraph(topic['entry'], 'Reference Note')
        doc.add_heading('操作步骤', level=2)
        for step, (action, detail) in enumerate(topic['steps'], 1):
            line = doc.add_paragraph()
            line.add_run(f'{step}.  {action}　').bold = True
            line.add_run(detail)
        for index, (shot, caption, instruction) in enumerate(topic.get('figures', ()), 1):
            path = screens/f'{shot}.jpg'
            with Image.open(path) as image:
                width = Mm(min(179, 98 * image.width / image.height))
            picture = doc.add_paragraph()
            picture.alignment = WD_ALIGN_PARAGRAPH.CENTER
            picture.paragraph_format.keep_with_next = True
            graphic = picture.add_run().add_picture(str(path), width=width)
            graphic._inline.docPr.set('descr', caption)
            label = doc.add_paragraph(f'图 {chapter}-{index}　{caption}', 'Caption')
            label.paragraph_format.keep_with_next = True
            label.alignment = WD_ALIGN_PARAGRAPH.CENTER
            doc.add_paragraph(instruction, 'Reference Note')
        fields = doc.add_heading('输入字段', level=2)
        fields.paragraph_format.keep_with_next = True
        caption = doc.add_paragraph(f'表 {chapter}-1　主要字段与使用位置', 'Caption')
        caption.paragraph_format.keep_with_next = True
        table(doc, FIELDS, topic['fields'], widths=(1.78, 1.13, 4.1))
        doc.add_heading('结果核对', level=2)
        for note in topic['checks']:
            doc.add_paragraph(note)
    doc.save(output/WORD)


def html_page(title, body, *, word_download=False):
    download = f'<a href="{WORD}" download>下载完整 Word 手册</a>' if word_download else ''
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · {TITLE}</title>
  <link rel="stylesheet" href="book.css">
</head>
<body>
  <nav aria-label="教程导航"><a href="index.html">操作教程目录</a>{download}</nav>
  <main>{body}</main>
</body>
</html>
"""


def write_html(output, *, word_download=False):
    parts = [f'<h1>{TITLE}</h1><p>{INTRO}</p><p>{EXAMPLES}</p>']
    for group, keys in GROUPS:
        parts.append(f'<h2>{escape(group)}</h2><ul class="toc">')
        parts.extend(f'<li><a href="{key}.html">{escape(chapter_title(key))}</a></li>' for key in keys)
        parts.append('</ul>')
    (output/'index.html').write_text(
        html_page('目录', '\n'.join(parts), word_download=word_download), encoding='utf-8')

    for key in KEYS:
        topic, chapter = TOPICS[key], ORDER[key]
        parts = [f'<h1>{escape(chapter_title(key))}</h1>',
                 f"<p>{escape(topic['intro'])}</p>",
                 f"<p class='entry'>{escape(topic['entry'])}</p>",
                 '<h2>操作步骤</h2><ol>']
        parts.extend(f'<li><strong>{escape(action)}</strong> {escape(detail)}</li>'
                     for action, detail in topic['steps'])
        parts.append('</ol>')
        for index, (shot, caption, note) in enumerate(topic.get('figures', ()), 1):
            label = escape(caption)
            parts.append(f'<figure><a href="screens/{shot}.jpg" target="_blank"'
                         f' aria-label="查看原图 {label}"><img src="screens/{shot}.jpg"'
                         f' alt="{label}"></a><figcaption>图 {chapter}-{index}　{label}'
                         f'</figcaption><p>{escape(note)}</p></figure>')
        parts.append(f'<h2>输入字段</h2><div class="table"><table>'
                     f'<caption>表 {chapter}-1　主要字段与使用位置</caption><thead><tr>')
        parts.extend(f'<th scope="col">{label}</th>' for label in FIELDS)
        parts.append('</tr></thead><tbody>')
        for label, unit, note in topic['fields']:
            parts.append(f'<tr><th scope="row">{escape(label)}</th>'
                         f'<td>{escape(unit)}</td><td>{escape(note)}</td></tr>')
        parts.append('</tbody></table></div><h2>结果核对</h2>')
        parts.extend(f'<p>{escape(note)}</p>' for note in topic['checks'])
        pages = []
        for offset, label in ((-1, '上一章'), (1, '下一章')):
            adjacent = chapter - 1 + offset
            if 0 <= adjacent < len(KEYS):
                other = KEYS[adjacent]
                pages.append(f'<a href="{other}.html">{label}　{escape(TOPICS[other]["title"])}</a>')
        parts.append('<div class="paging">' + ' '.join(pages) + '</div>')
        (output/f'{key}.html').write_text(
            html_page(topic['title'], '\n'.join(parts), word_download=word_download), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screens', type=Path, required=True, help='Actual desktop screenshots in JPEG format')
    parser.add_argument('--out', type=Path, default=ROOT/'resources/help/operations')
    parser.add_argument('--html-only', action='store_true', help='Update the offline HTML without writing a Word file')
    args = parser.parse_args()
    if set(TOPICS) != set(KEYS):
        raise ValueError('The chapter list and tutorial contents do not match.')
    screenshots = sorted({name for topic in TOPICS.values() for name, _, _ in topic.get('figures', ())})
    missing = [name for name in screenshots if not (args.screens/f'{name}.jpg').is_file()]
    if missing:
        raise FileNotFoundError(', '.join(missing))
    output_screens = args.out/'screens'
    output_screens.mkdir(parents=True, exist_ok=True)
    for name in screenshots:
        image = f'{name}.jpg'
        if (args.screens/image).resolve() != (output_screens/image).resolve():
            shutil.copyfile(args.screens/image, output_screens/image)
    stylesheet = ROOT/'resources/help/operations/book.css'
    if stylesheet.resolve() != (args.out/'book.css').resolve():
        shutil.copyfile(stylesheet, args.out/'book.css')
    if not args.html_only:
        write_word(args.out, output_screens)
    write_html(args.out, word_download=not args.html_only)
    print(f'{len(KEYS)} chapters, {len(screenshots)} screenshots, {args.out}')


if __name__ == '__main__':
    main()
