"""Public maintainer and repository information for the desktop app."""

import webbrowser
from tkinter import messagebox


AUTHOR = 'szj'
GITHUB_URL = 'https://github.com/sunzhanjie2-sudo/power-supply-design-software'
GITHUB_LABEL = f'{AUTHOR} · GitHub ↗'


def open_github(parent):
    if not webbrowser.open_new_tab(GITHUB_URL):
        messagebox.showinfo('项目 GitHub', GITHUB_URL, parent=parent)


def add_github_menu_item(menu, parent):
    menu.add_command(label=f'项目 GitHub · {AUTHOR}', command=lambda: open_github(parent))
