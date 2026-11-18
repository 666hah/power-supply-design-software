"""Open an installed operation tutorial at the chapter selected on the diagram."""

import os
import re
from tkinter import messagebox

from app_resources import resource_path


def open_architecture_tutorial(topic, parent):
    if not re.fullmatch(r'[a-z]+', topic):
        raise ValueError('Invalid architecture tutorial topic')
    directory = resource_path('resources/help/operations')
    page = directory / f'{topic}.html'
    try:
        if not page.is_file():
            page = directory / 'index.html'
        if not page.is_file():
            raise FileNotFoundError('请保留完整程序目录中的内置教程文件。')
        os.startfile(str(page))
    except OSError as error:
        messagebox.showerror('打开软件操作教程', str(error), parent=parent)
