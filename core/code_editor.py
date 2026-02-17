#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
code_editor.py — Built-in code editor widget for ProjectScan
"""

import os
import re
import tkinter as tk
from tkinter import ttk, messagebox
from .encoding_handler import EncodingHandler


class CodeEditor(tk.Frame):
    KEYWORDS = {
        'vb': ['Sub','Function','End','If','Then','Else','ElseIf','For',
               'Next','While','Do','Loop','Dim','As','New','Private','Public',
               'Protected','Class','Module','Imports','Return','Nothing',
               'True','False','And','Or','Not','Integer','String','Boolean',
               'Double','Long','ByVal','ByRef','Handles','WithEvents','Shared',
               'Overrides','Overloads','MustOverride','Optional','Property',
               'Get','Set','RaiseEvent','Try','Catch','Finally','Throw',
               'Select','Case','Each','In','Of','Is','Like','Inherits',
               'Implements','Interface','Enum','Structure','Using','With',
               'Me','MyBase','Partial'],
        'cs': ['using','namespace','class','struct','interface','enum',
               'public','private','protected','internal','static','void',
               'int','string','bool','double','float','long','var','new',
               'return','if','else','for','foreach','while','do','switch',
               'case','break','continue','try','catch','finally','throw',
               'null','true','false','this','base','virtual','override',
               'abstract','sealed','async','await','readonly','const',
               'get','set','partial','where','yield','ref','out','in'],
        'py': ['def','class','if','elif','else','for','while','return',
               'import','from','as','try','except','finally','raise',
               'with','yield','lambda','pass','break','continue',
               'True','False','None','and','or','not','in','is','self'],
        'js': ['function','var','let','const','if','else','for','while',
               'do','switch','case','break','continue','return','try',
               'catch','finally','throw','new','this','class','extends',
               'import','export','default','async','await','yield',
               'true','false','null','undefined','typeof','instanceof'],
    }

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self._file_path = None
        self._original = ''
        self._modified = False
        self._lang = 'default'
        self._setup_ui()

    def _setup_ui(self):
        self._header = tk.Label(self, text="editor -- select a file",
            bg='#1e1e2e', fg='#cdd6f4', font=('Consolas', 10, 'bold'), anchor='w')
        self._header.pack(fill='x')
        body = tk.Frame(self, bg='#1e1e2e')
        body.pack(fill='both', expand=True)
        self._ln = tk.Text(body, width=5, bg='#181825', fg='#6c7086',
            font=('Consolas', 10), state='disabled', relief='flat',
            selectbackground='#181825', cursor='arrow', padx=4)
        self._ln.pack(side='left', fill='y')
        self._text = tk.Text(body, bg='#1e1e2e', fg='#cdd6f4',
            font=('Consolas', 10), insertbackground='#f5e0dc',
            selectbackground='#45475a', undo=True, wrap='none', relief='flat', padx=4)
        self._text.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(body, command=self._sync_scroll)
        sb.pack(side='right', fill='y')
        self._text.config(yscrollcommand=sb.set)
        self._text.bind('<KeyRelease>', self._on_edit)
        self._text.bind('<MouseWheel>', self._on_scroll)
        self._setup_tags()

    def _sync_scroll(self, *args):
        self._text.yview(*args)
        self._update_line_numbers()

    def _on_scroll(self, event):
        self._text.after(10, self._update_line_numbers)

    def _setup_tags(self):
        self._text.tag_configure('keyword', foreground='#cba6f7')
        self._text.tag_configure('string', foreground='#a6e3a1')
        self._text.tag_configure('comment', foreground='#6c7086',
                                 font=('Consolas', 10, 'italic'))
        self._text.tag_configure('number', foreground='#fab387')

    def _on_edit(self, event=None):
        self._modified = True
        if self._file_path:
            self._header.config(text="* modified -- " + os.path.basename(self._file_path))
        self._update_line_numbers()
        self._highlight()

    def _update_line_numbers(self):
        self._ln.config(state='normal')
        self._ln.delete('1.0', 'end')
        cnt = int(self._text.index('end-1c').split('.')[0])
        self._ln.insert('1.0', '\n'.join(str(i) for i in range(1, cnt + 1)))
        self._ln.config(state='disabled')
        self._ln.yview_moveto(self._text.yview()[0])

    def _detect_lang(self, path):
        ext = os.path.splitext(path)[1].lower()
        m = {'.vb': 'vb', '.cs': 'cs', '.py': 'py', '.js': 'js',
             '.ts': 'js', '.jsx': 'js', '.tsx': 'js',
             '.c': 'cs', '.cpp': 'cs', '.h': 'cs', '.hpp': 'cs'}
        return m.get(ext, 'default')

    def _highlight(self):
        for tag in ('keyword', 'string', 'comment', 'number'):
            self._text.tag_remove(tag, '1.0', 'end')
        content = self._text.get('1.0', 'end')
        kws = self.KEYWORDS.get(self._lang, [])
        for kw in kws:
            pat = r'\b' + re.escape(kw) + r'\b'
            for m in re.finditer(pat, content):
                self._text.tag_add('keyword', f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in re.finditer(r'"[^"\n]*"', content):
            self._text.tag_add('string', f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in re.finditer(r"'[^'\n]*'", content):
            self._text.tag_add('string', f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        if self._lang == 'vb':
            for m in re.finditer(r"'[^\n]*", content):
                self._text.tag_add('comment', f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        else:
            for m in re.finditer(r'//[^\n]*', content):
                self._text.tag_add('comment', f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in re.finditer(r'\b\d+\.?\d*\b', content):
            self._text.tag_add('number', f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    def load_file(self, path):
        try:
            content, enc, bom, le = EncodingHandler.read_file(path)
        except Exception as e:
            messagebox.showerror("file open error", str(e))
            return
        self._file_path = path
        self._original = content
        self._modified = False
        self._lang = self._detect_lang(path)
        self._text.delete('1.0', 'end')
        self._text.insert('1.0', content)
        self._header.config(text=os.path.basename(path))
        self._update_line_numbers()
        self._highlight()

    def get_content(self):
        return self._text.get('1.0', 'end-1c')

    def set_content(self, text):
        self._text.delete('1.0', 'end')
        self._text.insert('1.0', text)
        self._modified = True
        if self._file_path:
            self._header.config(text="* modified -- " + os.path.basename(self._file_path))
        self._update_line_numbers()
        self._highlight()

    def save_file(self):
        if not self._file_path:
            messagebox.showwarning("save", "no file open")
            return False
        try:
            _, enc, bom, le = EncodingHandler.read_file(self._file_path)
            EncodingHandler.write_file(self._file_path, self.get_content(), enc, bom, le)
            self._original = self.get_content()
            self._modified = False
            self._header.config(text=os.path.basename(self._file_path))
            return True
        except Exception as e:
            messagebox.showerror("save error", str(e))
            return False

    @property
    def file_path(self):
        return self._file_path

    @property
    def is_modified(self):
        return self._modified
