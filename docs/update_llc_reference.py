"""Append the LLC method to the shipped, editable calculation reference."""

import argparse
from pathlib import Path
import sys

from docx import Document
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from docs.calculation_reference_layout import finish_book
from docs.llc_calculation_chapter import add_llc_chapter


def insert_llc_reference(doc):
    if any(p.style.name=='Heading 1' and p.text.startswith('22  ') for p in doc.paragraphs):
        raise ValueError('第 22 章已存在，请从增补前的主文档生成')
    appendix=next(p._p for p in doc.paragraphs if p.style.name=='Heading 1' and p.text.startswith('附录 A'))
    original=set(doc.element.body)
    add_llc_chapter(doc)
    for block in list(doc.element.body):
        if block not in original and block.tag != qn('w:sectPr'):
            appendix.addprevious(block)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    book=Document(args.source)
    insert_llc_reference(book)
    finish_book(book)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    book.save(args.output)
