"""Layout primitives shared by the three offline engineering workbooks."""
from math import ceil, isfinite
from numbers import Real
import struct

from xlsx_report_writer import Sheet, WIDTHS, fitted_height, number_format


DEFAULT_WIDTHS = (20, 16, 16, 15, 15, 15, 15, 17)
_STATE_STYLE = {
    'pass': 11, '通过': 11, '完成': 11, '模型内满足': 11, '符合': 11,
    'fail': 10, '失败': 10, '未通过': 10, '超限': 10, '不通过': 10,
    'review': 8, '待复核': 8, '需复核': 8, '超差': 8, '部分完成': 8, '待补充': 8,
    'missing': 8, 'undefined': 8, '缺失': 8, '未完成': 8, '证据不足': 8,
    'na': 7, '未启用': 7, '不适用': 7, '未覆盖': 7,
}
_STATE_LABEL = {
    'pass': '通过', 'fail': '失败', 'review': '待复核', 'missing': '证据不足',
    'undefined': '待复核', 'na': '不适用',
}


def page(name, title, context='', *, widths=None, freeze_rows=4):
    widths = tuple(widths or DEFAULT_WIDTHS)
    sheet = Sheet(name, column_count=len(widths), column_widths=widths,
                  freeze_rows=freeze_rows, orientation='landscape',
                  tab_color='173C64' if not freeze_rows else '397BA6')
    sheet.span(1, 0, sheet.column_count, title, 1)
    sheet.heights[1] = 31
    if context:
        sheet.span(2, 0, sheet.column_count, context, 7)
        sheet.heights[2] = fitted_height(context, sum(widths))
    sheet.heights[3] = 9
    return sheet


def band(sheet, row, text):
    sheet.span(row, 0, sheet.column_count, text, 2)
    sheet.heights[row] = 25
    return row+1


def _widths(sheet):
    return sheet.column_widths or WIDTHS[:sheet.column_count]


def note(sheet, row, text):
    if text:
        sheet.span(row, 0, sheet.column_count, text, 7)
        sheet.heights[row] = fitted_height(text, sum(_widths(sheet)))
        return row+1
    return row


def verdict(sheet, row, label, detail='', state='review'):
    sheet.span(row, 0, sheet.column_count, label, _STATE_STYLE.get(state, 8))
    sheet.heights[row] = max(31, fitted_height(label, sum(_widths(sheet))))
    return note(sheet, row+1, detail)


def table(sheet, row, headers, rows, *, spans=None, state_col=None):
    if not headers or len(headers)>sheet.column_count:
        raise ValueError(f'{sheet.name} 表头数量超出报告幅宽')
    if spans is None:
        width, remainder = divmod(sheet.column_count, len(headers))
        spans = tuple(width+int(i<remainder) for i in range(len(headers)))
    if len(spans) != len(headers) or min(spans)<=0 or sum(spans)!=sheet.column_count:
        raise ValueError(f'{sheet.name} 表头和列宽不匹配')
    columns = []
    col = 0
    widths = _widths(sheet)
    for count in spans:
        columns.append((col, count, sum(widths[col:col+count])))
        col += count
    for (col, count, _), header in zip(columns, headers):
        sheet.span(row, col, count, header, 5)
    sheet.heights[row] = max(fitted_height(value,width) for value,(_,_,width) in zip(headers,columns))
    end = row+1
    for i, values in enumerate(rows, 1):
        if len(values)!=len(headers):
            raise ValueError(f'{sheet.name} 表格第 {i} 行列数不匹配')
        height = 24
        for j,(value,(col,count,width)) in enumerate(zip(values,columns)):
            style, fmt = (6 if i%2==0 else 0), None
            if j == state_col:
                style = _STATE_STYLE.get(str(value), style)
                value = _STATE_LABEL.get(str(value), value)
            if isinstance(value,Real) and not isinstance(value,bool):
                if isfinite(value):
                    value = float(value)
                    fmt = number_format(value)
                else:
                    value = None
            if value is None:
                value = '—'
            sheet.span(row+i,col,count,value,style,fmt)
            if fmt is None:
                height = max(height, fitted_height(value,width))
        sheet.heights[row+i] = height
        end = row+i+1
    return end


def picture(sheet, row, png, caption):
    if not png:
        return row
    width, height = struct.unpack('>II', png[16:24])
    max_width = sum(w*7+5 for w in _widths(sheet))-20
    pixels = min(max_width, 540*width/height)
    height_pts = sheet.image(row, 0, png, caption, width=pixels, dx=8)*.75
    block_rows = max(1,ceil(height_pts/24))
    for offset in range(block_rows):
        sheet.heights[row+offset] = 24
    return note(sheet, row+block_rows, caption)


def index(sheet, row, entries):
    """Hyperlinks use workbook locations and survive report composition."""
    row = band(sheet,row,'证据索引')
    split = max(1,sheet.column_count//3)
    widths = _widths(sheet)
    for target,label,description in entries:
        sheet.span(row,0,split,label,4)
        sheet.links[row,0] = target
        sheet.span(row,split,sheet.column_count-split,description,7)
        sheet.heights[row] = max(fitted_height(label,sum(widths[:split])),
                                 fitted_height(description,sum(widths[split:])))
        row += 1
    return row
