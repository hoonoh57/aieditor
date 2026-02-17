#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checkbox_tree.py — CheckboxTreeview widget for ProjectScan
"""

import tkinter as tk
from tkinter import ttk


class CheckboxTreeview(ttk.Treeview):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self._checked = set()
        self.bind('<Button-1>', self._on_click)
        self.bind('<space>', self._on_space)

    def _on_click(self, event):
        region = self.identify_region(event.x, event.y)
        if region in ('tree', 'cell'):
            item = self.identify_row(event.y)
            if item:
                self._toggle(item)

    def _on_space(self, event):
        for item in self.selection():
            self._toggle(item)

    def _toggle(self, item):
        if item in self._checked:
            self._uncheck(item)
        else:
            self._check(item)

    def _check(self, item):
        self._checked.add(item)
        txt = self.item(item, 'text')
        if txt.startswith('[_] '):
            self.item(item, text='[v] ' + txt[4:])
        elif not txt.startswith('[v] '):
            self.item(item, text='[v] ' + txt)
        for child in self.get_children(item):
            self._check(child)

    def _uncheck(self, item):
        self._checked.discard(item)
        txt = self.item(item, 'text')
        if txt.startswith('[v] '):
            self.item(item, text='[_] ' + txt[4:])
        elif not txt.startswith('[_] '):
            self.item(item, text='[_] ' + txt)
        for child in self.get_children(item):
            self._uncheck(child)

    def check_all(self):
        for item in self.get_children(''):
            self._check(item)

    def uncheck_all(self):
        for item in self.get_children(''):
            self._uncheck(item)

    def get_checked(self):
        return set(self._checked)

    def insert_with_check(self, parent, index, text='', checked=True, **kw):
        prefix = '[v] ' if checked else '[_] '
        item = self.insert(parent, index, text=prefix + text, **kw)
        if checked:
            self._checked.add(item)
        return item
