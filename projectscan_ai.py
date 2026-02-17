"""
ProjectScan Pro v2.0 — AI 멀티파일 코드 수정 워크스테이션
- 체크박스 트리뷰 + 줄번호 편집기 + 프롬프트 빌더
- 멀티파일 Diff 파싱/적용 엔진
- GitHub 자동 업로드
단일 파일 완전판 (Part 1/2)
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import os
import fnmatch
import re
import xml.etree.ElementTree as ET
import datetime
import subprocess
import threading
import json
import shutil
import difflib
import tempfile


# ════════════════════════════════════════════════════════════════
#  1. CheckboxTreeview - 체크박스가 있는 트리뷰 위젯
# ════════════════════════════════════════════════════════════════

class CheckboxTreeview(ttk.Treeview):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._checked = set()
        self._unchecked = set()
        self.bind('<Button-1>', self._on_click)

    def _on_click(self, event):
        region = self.identify_region(event.x, event.y)
        if region in ('tree', 'image'):
            item = self.identify_row(event.y)
            if item:
                self.toggle_check(item)

    def insert(self, parent, index, iid=None, **kw):
        checked = kw.pop('checked', False)
        item = super().insert(parent, index, iid=iid, **kw)
        if checked:
            self._checked.add(item)
        else:
            self._unchecked.add(item)
        self._update_display(item)
        return item

    def toggle_check(self, item):
        was_checked = item in self._checked
        targets = [item] + self._all_children(item)
        for node in targets:
            self._checked.discard(node)
            self._unchecked.discard(node)
            if was_checked:
                self._unchecked.add(node)
            else:
                self._checked.add(node)
            self._update_display(node)
        self._update_parent(item)

    def is_checked(self, item):
        return item in self._checked

    def _all_children(self, item):
        children = []
        for c in self.get_children(item):
            children.append(c)
            children.extend(self._all_children(c))
        return children

    def _update_parent(self, item):
        parent = self.parent(item)
        if not parent:
            return
        kids = self.get_children(parent)
        n_checked = sum(1 for c in kids if c in self._checked)
        self._checked.discard(parent)
        self._unchecked.discard(parent)
        if n_checked == len(kids):
            self._checked.add(parent)
        else:
            self._unchecked.add(parent)
        self._update_display(parent)
        self._update_parent(parent)

    def _update_display(self, item):
        text = self.item(item, 'text')
        if text[:2] in ('☑ ', '☐ '):
            text = text[2:]
        mark = '☑' if item in self._checked else '☐'
        self.item(item, text=f'{mark} {text}')

    def check_all(self):
        for it in self._all_items():
            self._unchecked.discard(it)
            self._checked.add(it)
            self._update_display(it)

    def uncheck_all(self):
        for it in self._all_items():
            self._checked.discard(it)
            self._unchecked.add(it)
            self._update_display(it)

    def _all_items(self):
        items = []
        for it in self.get_children(''):
            items.append(it)
            items.extend(self._all_children(it))
        return items


# ════════════════════════════════════════════════════════════════
#  2. CodeEditor - 줄번호 + 구문강조 편집기
# ════════════════════════════════════════════════════════════════

class CodeEditor(tk.Frame):
    KEYWORDS = {
        'vb': (r'\b(Public|Private|Protected|Friend|Sub|Function|End|If|Then|Else|ElseIf|'
               r'For|Each|Next|While|Do|Loop|Until|Select|Case|With|Try|Catch|Finally|'
               r'Throw|Return|Dim|As|New|Class|Module|Imports|Namespace|Inherits|Implements|'
               r'Interface|Enum|Structure|Property|Get|Set|ReadOnly|Shared|Static|'
               r'Overrides|Overridable|MustOverride|Partial|ByVal|ByRef|Optional|'
               r'Event|Delegate|Of|Is|IsNot|Nothing|True|False|And|Or|Not|AndAlso|OrElse|'
               r'String|Integer|Long|Short|Double|Single|Decimal|Boolean|Byte|Object|'
               r'Me|MyBase|MyClass|Handles|WithEvents|Async|Await|Using|SyncLock|'
               r'AddHandler|RemoveHandler|RaiseEvent)\b'),
        'cs': (r'\b(using|namespace|class|struct|interface|enum|delegate|event|'
               r'public|private|protected|internal|static|readonly|const|volatile|'
               r'abstract|sealed|virtual|override|new|partial|async|await|'
               r'void|int|long|short|byte|float|double|decimal|bool|char|string|object|'
               r'var|dynamic|null|true|false|this|base|'
               r'if|else|switch|case|default|for|foreach|while|do|break|continue|return|'
               r'try|catch|finally|throw|lock|using|yield|in|out|ref|params)\b'),
        'cpp': (r'\b(auto|break|case|char|const|continue|default|do|double|else|enum|'
                r'extern|float|for|goto|if|int|long|register|return|short|signed|sizeof|'
                r'static|struct|switch|typedef|union|unsigned|void|volatile|while|'
                r'class|namespace|using|public|private|protected|virtual|override|'
                r'template|typename|new|delete|this|throw|try|catch|nullptr|'
                r'bool|true|false|inline|constexpr|include|define|ifdef|ifndef|endif)\b'),
        'py': (r'\b(False|None|True|and|as|assert|async|await|break|class|continue|'
               r'def|del|elif|else|except|finally|for|from|global|if|import|in|is|'
               r'lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b'),
        'default': (r'\b(if|else|for|while|return|class|function|var|let|const|'
                    r'import|export|from|new|this|null|true|false|void|int|string)\b'),
    }

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.configure(bg='#1e1e2e')
        self._current_file = None
        self._original_content = ""
        self._modified = False
        self._language = 'default'

        # 헤더
        self.header = tk.Frame(self, bg='#181825')
        self.header.pack(fill='x')
        self.file_label = tk.Label(
            self.header, text="파일을 선택하세요 (트리에서 더블클릭)",
            font=('맑은 고딕', 10), bg='#181825', fg='#a6adc8',
            anchor='w', padx=8, pady=4)
        self.file_label.pack(side='left', fill='x', expand=True)
        self.modified_label = tk.Label(
            self.header, text="", font=('맑은 고딕', 9),
            bg='#181825', fg='#f38ba8', padx=8)
        self.modified_label.pack(side='right')

        # 편집영역
        editor_frame = tk.Frame(self, bg='#1e1e2e')
        editor_frame.pack(fill='both', expand=True)

        self.line_numbers = tk.Text(
            editor_frame, width=5, padx=4, pady=8, takefocus=0, border=0,
            state='disabled', bg='#181825', fg='#6c7086',
            font=('Consolas', 11), relief='flat',
            selectbackground='#181825', selectforeground='#6c7086', cursor='arrow')
        self.line_numbers.pack(side='left', fill='y')

        scrollbar = ttk.Scrollbar(editor_frame, orient='vertical')
        scrollbar.pack(side='right', fill='y')

        self.text = tk.Text(
            editor_frame, wrap='none', font=('Consolas', 11),
            bg='#1e1e2e', fg='#cdd6f4', insertbackground='#f5e0dc',
            selectbackground='#45475a', selectforeground='#f5e0dc',
            relief='flat', padx=8, pady=8, undo=True, maxundo=50, tabs=('4c',))
        self.text.pack(side='left', fill='both', expand=True)

        scrollbar.config(command=self._on_scroll)
        self.text.config(yscrollcommand=self._on_text_scroll)

        h_scroll = ttk.Scrollbar(self, orient='horizontal', command=self.text.xview)
        h_scroll.pack(fill='x')
        self.text.config(xscrollcommand=h_scroll.set)

        # 태그
        for tag, cfg in [
            ('keyword', {'foreground': '#cba6f7'}),
            ('string', {'foreground': '#a6e3a1'}),
            ('comment', {'foreground': '#6c7086', 'font': ('Consolas', 11, 'italic')}),
            ('number', {'foreground': '#fab387'}),
            ('current_line', {'background': '#313244'}),
        ]:
            self.text.tag_configure(tag, **cfg)

        # 이벤트
        self.text.bind('<<Modified>>', self._on_modified)
        self.text.bind('<KeyRelease>', self._on_key_release)
        self.text.bind('<ButtonRelease-1>', self._update_current_line)
        self.text.bind('<Control-z>', lambda e: self.text.edit_undo() if self.text.edit('canundo') else None)
        self.text.bind('<Control-y>', lambda e: self.text.edit_redo() if self.text.edit('canredo') else None)
        self.text.bind('<Control-s>', lambda e: self.save_file())

        # 상태바
        self.status_bar = tk.Frame(self, bg='#11111b')
        self.status_bar.pack(fill='x')
        self.pos_label = tk.Label(
            self.status_bar, text="줄 1, 열 1", font=('Consolas', 9),
            bg='#11111b', fg='#6c7086', padx=8, pady=2)
        self.pos_label.pack(side='right')
        self.lang_label = tk.Label(
            self.status_bar, text="", font=('Consolas', 9),
            bg='#11111b', fg='#89b4fa', padx=8, pady=2)
        self.lang_label.pack(side='left')
        self.encoding_label = tk.Label(
            self.status_bar, text="UTF-8", font=('Consolas', 9),
            bg='#11111b', fg='#6c7086', padx=8, pady=2)
        self.encoding_label.pack(side='left')

    def _on_scroll(self, *args):
        self.text.yview(*args)
        self.line_numbers.yview(*args)

    def _on_text_scroll(self, first, last):
        self.line_numbers.yview_moveto(first)

    def _on_modified(self, event=None):
        if self.text.edit_modified():
            self._modified = (self.text.get('1.0', 'end-1c') != self._original_content)
            self.modified_label.config(text="● 수정됨" if self._modified else "")
            self.text.edit_modified(False)

    def _on_key_release(self, event=None):
        self._update_line_numbers()
        self._update_current_line()
        self._update_position()
        if event and event.keysym not in ('Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R'):
            self._highlight_current_line_only()

    def _update_position(self):
        pos = self.text.index(tk.INSERT)
        line, col = pos.split('.')
        self.pos_label.config(text=f"줄 {line}, 열 {int(col)+1}")

    def _update_current_line(self, event=None):
        self.text.tag_remove('current_line', '1.0', 'end')
        line = self.text.index(tk.INSERT).split('.')[0]
        self.text.tag_add('current_line', f'{line}.0', f'{line}.end+1c')
        self.text.tag_lower('current_line')
        self._update_position()

    def _update_line_numbers(self):
        self.line_numbers.config(state='normal')
        self.line_numbers.delete('1.0', 'end')
        line_count = int(self.text.index('end-1c').split('.')[0])
        width = max(4, len(str(line_count)) + 1)
        self.line_numbers.config(width=width)
        lines_text = '\n'.join(str(i).rjust(width - 1) for i in range(1, line_count + 1))
        self.line_numbers.insert('1.0', lines_text)
        self.line_numbers.config(state='disabled')

    def _detect_language(self, filepath):
        ext_map = {
            '.vb': 'vb', '.cs': 'cs', '.cpp': 'cpp', '.cxx': 'cpp',
            '.cc': 'cpp', '.c': 'cpp', '.h': 'cpp', '.hpp': 'cpp',
            '.py': 'py', '.pyw': 'py',
        }
        _, ext = os.path.splitext(filepath)
        return ext_map.get(ext.lower(), 'default')

    def _highlight_all(self):
        content = self.text.get('1.0', 'end-1c')
        for tag in ('keyword', 'string', 'comment', 'number'):
            self.text.tag_remove(tag, '1.0', 'end')
        if not content.strip():
            return

        kw_pattern = self.KEYWORDS.get(self._language, self.KEYWORDS['default'])
        for m in re.finditer(kw_pattern, content):
            self.text.tag_add('keyword', f"1.0+{m.start()}c", f"1.0+{m.end()}c")

        str_pat = r'"[^"\n]*"' if self._language == 'vb' else r'(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'
        for m in re.finditer(str_pat, content):
            self.text.tag_add('string', f"1.0+{m.start()}c", f"1.0+{m.end()}c")

        cmt_pat = {"vb": r"'[^\n]*", "py": r"#[^\n]*"}.get(self._language, r'//[^\n]*|/\*[\s\S]*?\*/')
        for m in re.finditer(cmt_pat, content):
            self.text.tag_add('comment', f"1.0+{m.start()}c", f"1.0+{m.end()}c")

        for m in re.finditer(r'\b\d+\.?\d*[fFdDlLuU]?\b', content):
            self.text.tag_add('number', f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    def _highlight_current_line_only(self):
        line = self.text.index(tk.INSERT).split('.')[0]
        line_start, line_end = f"{line}.0", f"{line}.end"
        line_text = self.text.get(line_start, line_end)
        for tag in ('keyword', 'string', 'comment', 'number'):
            self.text.tag_remove(tag, line_start, line_end)

        kw_pattern = self.KEYWORDS.get(self._language, self.KEYWORDS['default'])
        for m in re.finditer(kw_pattern, line_text):
            self.text.tag_add('keyword', f"{line}.{m.start()}", f"{line}.{m.end()}")

        str_pat = r'"[^"\n]*"' if self._language == 'vb' else r'(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'
        for m in re.finditer(str_pat, line_text):
            self.text.tag_add('string', f"{line}.{m.start()}", f"{line}.{m.end()}")

        cmt_pat = {"vb": r"'[^\n]*", "py": r"#[^\n]*"}.get(self._language, r'//[^\n]*')
        for m in re.finditer(cmt_pat, line_text):
            self.text.tag_add('comment', f"{line}.{m.start()}", f"{line}.{m.end()}")

        for m in re.finditer(r'\b\d+\.?\d*\b', line_text):
            self.text.tag_add('number', f"{line}.{m.start()}", f"{line}.{m.end()}")

    def load_file(self, filepath):
        content = self._read_file(filepath)
        if content is None:
            return False
        self._current_file = filepath
        self._original_content = content
        self._modified = False
        self._language = self._detect_language(filepath)

        self.text.delete('1.0', 'end')
        self.text.insert('1.0', content)
        self.text.edit_modified(False)
        self.text.edit_reset()

        self.file_label.config(text=f"📄 {os.path.basename(filepath)}")
        self.modified_label.config(text="")
        self.lang_label.config(text=self._language.upper())

        self._update_line_numbers()
        self._highlight_all()
        self.text.mark_set(tk.INSERT, '1.0')
        self.text.see('1.0')
        self._update_current_line()
        return True

    def get_content(self):
        return self.text.get('1.0', 'end-1c')

    def set_content(self, content):
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', content)
        self._update_line_numbers()
        self._highlight_all()

    def get_content_with_line_numbers(self):
        content = self.get_content()
        lines = content.split('\n')
        w = len(str(len(lines)))
        return '\n'.join(f"{str(i).rjust(w)}| {line}" for i, line in enumerate(lines, 1))

    def save_file(self):
        if not self._current_file:
            return False
        content = self.get_content()
        try:
            with open(self._current_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self._original_content = content
            self._modified = False
            self.modified_label.config(text="✅ 저장됨")
            self.after(2000, lambda: self.modified_label.config(
                text="" if not self._modified else "● 수정됨"))
            return True
        except Exception as e:
            messagebox.showerror("저장 실패", str(e))
            return False

    @property
    def current_file(self):
        return self._current_file

    @property
    def is_modified(self):
        return self._modified

    def _read_file(self, filepath):
        for enc in ['utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin-1']:
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    content = f.read()
                self.encoding_label.config(text=enc.upper())
                return content
            except (UnicodeDecodeError, UnicodeError):
                continue
        messagebox.showerror("읽기 실패", f"인코딩 문제: {filepath}")
        return None


# ════════════════════════════════════════════════════════════════
#  3. MultiFileDiffEngine - 멀티파일 Diff 파싱 & 적용 엔진
# ════════════════════════════════════════════════════════════════

class MultiFileDiffEngine:
    """
    AI가 반환하는 여러 파일에 걸친 수정사항을 파싱하고 순차 적용.
    지원 형식:
      1) === FILE: path === ... === END FILE ===
      2) git unified diff (--- a/ +++ b/)
      3) 마크다운 ### 📄 path + 코드블록
      4) SEARCH/REPLACE, 줄범위, 전체교체 (단일파일)
    """

    @classmethod
    def parse_multi_file_diff(cls, diff_text: str) -> list:
        """
        반환: [{'file': rel_path, 'diff_type': str, 'content': str}, ...]
        """
        blocks = []

        # 방법1: === FILE: ... === 블록
        pat1 = re.compile(
            r'===\s*FILE:\s*(.+?)\s*===\s*\n(.*?)\n\s*===\s*END\s*FILE\s*===',
            re.DOTALL | re.IGNORECASE)
        for m in pat1.finditer(diff_text):
            fp = m.group(1).strip().strip('"\'`')
            content = m.group(2).strip()
            blocks.append({
                'file': cls._normalize_path(fp),
                'diff_type': cls._detect_type(content),
                'content': content
            })
        if blocks:
            return blocks

        # 방법2: git diff
        pat2 = re.compile(
            r'---\s+a/(.+?)\n\+\+\+\s+b/(.+?)\n((?:@@.*?(?:\n|$)(?:[ +\-].*?\n|\\.*?\n)*)+)',
            re.DOTALL)
        for m in pat2.finditer(diff_text):
            fp = m.group(2).strip()
            content = f"--- a/{m.group(1)}\n+++ b/{fp}\n{m.group(3)}"
            blocks.append({
                'file': cls._normalize_path(fp),
                'diff_type': 'unified',
                'content': content
            })
        if blocks:
            return blocks

        # 방법3: 마크다운 ### 📄 파일명 + ```코드```
        pat3 = re.compile(r'###?\s*📄?\s*(.+?)\s*\n\s*```\w*\n(.*?)```', re.DOTALL)
        for m in pat3.finditer(diff_text):
            fp = m.group(1).strip().strip('`*')
            content = m.group(2).strip()
            dtype = cls._detect_type(content)
            if dtype == 'unknown':
                dtype = 'full_replace'
            blocks.append({
                'file': cls._normalize_path(fp),
                'diff_type': dtype,
                'content': content
            })
        if blocks:
            return blocks

        # 방법4: 파일 헤더 패턴
        pat4 = re.compile(
            r'(?:^|\n)(?:파일|File|FILE)[\s:：]+(.+?)(?:\n|$)(.*?)(?=(?:\n(?:파일|File|FILE)[\s:：])|$)',
            re.DOTALL | re.IGNORECASE)
        for m in pat4.finditer(diff_text):
            fp = m.group(1).strip().strip('"\'`')
            content = m.group(2).strip()
            if content:
                blocks.append({
                    'file': cls._normalize_path(fp),
                    'diff_type': cls._detect_type(content),
                    'content': content
                })

        return blocks

    @staticmethod
    def _normalize_path(path: str) -> str:
        path = path.replace('\\', '/')
        if path.startswith(('a/', 'b/')):
            path = path[2:]
        return path.strip().strip('`"\'')

    @staticmethod
    def _detect_type(content: str) -> str:
        if re.search(r'^@@\s*-\d+', content, re.MULTILINE):
            return 'unified'
        if re.search(r'<{3,4}\s*SEARCH', content, re.IGNORECASE):
            return 'search_replace'
        if re.search(r'(?:REPLACE|MODIFY|UPDATE|변경|수정)\s+(?:줄|line|L)?\s*\d+\s*[-~]\s*\d+',
                      content, re.IGNORECASE):
            return 'line_range'
        if re.search(r'```\w*\n', content):
            return 'full_replace'
        lines = content.strip().split('\n')
        if len(lines) > 3:
            return 'full_replace'
        return 'unknown'

    @classmethod
    def apply_single_diff(cls, original: str, diff_block: dict) -> tuple:
        dtype = diff_block['diff_type']
        content = diff_block['content']

        methods = {
            'unified': cls._apply_unified,
            'search_replace': cls._apply_search_replace,
            'line_range': cls._apply_line_range,
            'full_replace': cls._apply_full_replace,
        }

        if dtype in methods:
            result, msg = methods[dtype](original, content)
            if result is not None:
                return result, msg

        # 자동 감지 재시도
        for method in [cls._apply_search_replace, cls._apply_unified,
                       cls._apply_line_range, cls._apply_full_replace]:
            result, msg = method(original, content)
            if result is not None:
                return result, msg

        return None, "적용 가능한 diff 형식을 감지하지 못했습니다."

    @staticmethod
    def _apply_unified(original: str, diff_text: str) -> tuple:
        lines = original.split('\n')
        hunks = []
        current = None
        for line in diff_text.strip().split('\n'):
            if line.startswith('@@'):
                m = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
                if m:
                    current = {'start': int(m.group(1)), 'lines': []}
                    hunks.append(current)
            elif current is not None:
                if line.startswith(('+', '-', ' ')):
                    current['lines'].append(line)
                elif line.startswith('\\'):
                    continue
        if not hunks:
            return None, "unified diff hunk 없음"

        hunks.sort(key=lambda h: h['start'], reverse=True)
        changes = []
        for h in hunks:
            start = h['start'] - 1
            remove_lines = []
            add_lines = []
            for dl in h['lines']:
                if dl.startswith('-'):
                    remove_lines.append(dl[1:])
                elif dl.startswith('+'):
                    add_lines.append(dl[1:])
                elif dl.startswith(' '):
                    remove_lines.append(dl[1:])
                    add_lines.append(dl[1:])
            end = start + len(remove_lines)
            if end <= len(lines):
                lines[start:end] = add_lines
                n_del = len([l for l in h['lines'] if l.startswith('-')])
                n_add = len([l for l in h['lines'] if l.startswith('+')])
                changes.append(f"줄 {h['start']}: -{n_del} +{n_add}")
        return '\n'.join(lines), '\n'.join(changes) if changes else "변경 적용"

    @staticmethod
    def _apply_search_replace(original: str, diff_text: str) -> tuple:
        pattern = re.compile(
            r'<{3,4}\s*SEARCH\s*\n(.*?)\n={3,4}\s*\n(.*?)\n>{3,4}\s*REPLACE',
            re.DOTALL)
        matches = list(pattern.finditer(diff_text))
        if not matches:
            pattern2 = re.compile(
                r'```\s*(?:찾을|search|before)[^\n]*\n(.*?)```\s*\n'
                r'```\s*(?:바꿀|replace|after)[^\n]*\n(.*?)```',
                re.DOTALL | re.IGNORECASE)
            matches = list(pattern2.finditer(diff_text))
        if not matches:
            return None, "SEARCH/REPLACE 패턴 없음"

        result = original
        changes = []
        for m in matches:
            search_text = m.group(1).strip()
            replace_text = m.group(2).strip()

            if search_text in result:
                result = result.replace(search_text, replace_text, 1)
                preview = search_text[:50].replace('\n', '↵')
                changes.append(f"교체: '{preview}...'")
            else:
                # 공백 무시 매칭
                normalized = re.sub(r'\s+', r'\\s+', re.escape(search_text.strip()))
                match = re.search(normalized, result)
                if match:
                    result = result[:match.start()] + replace_text + result[match.end():]
                    changes.append(f"교체(공백무시): '{search_text[:30]}...'")
                else:
                    changes.append(f"⚠ 미발견: '{search_text[:50]}...'")

        if result != original:
            return result, '\n'.join(changes)
        return None, "변경 없음: " + '\n'.join(changes)

    @staticmethod
    def _apply_line_range(original: str, diff_text: str) -> tuple:
        lines = original.split('\n')
        pattern = re.compile(
            r'(?:REPLACE|MODIFY|UPDATE|변경|수정)\s+(?:줄|line|L)?\s*(\d+)\s*[-~]\s*(\d+)\s*:?\s*\n'
            r'(.*?)(?:\nEND|\n---|\Z)',
            re.IGNORECASE | re.DOTALL)
        matches = sorted(pattern.finditer(diff_text),
                         key=lambda m_: int(m_.group(1)), reverse=True)
        if not matches:
            return None, "줄번호 범위 패턴 없음"
        changes = []
        for m in matches:
            s, e = int(m.group(1)) - 1, int(m.group(2))
            new_lines = m.group(3).rstrip().split('\n')
            if s < len(lines) and e <= len(lines):
                old_count = e - s
                lines[s:e] = new_lines
                changes.append(f"줄 {s+1}-{e}: {old_count}줄→{len(new_lines)}줄")
        return '\n'.join(lines), '\n'.join(changes)

    @staticmethod
    def _apply_full_replace(original: str, diff_text: str) -> tuple:
        m = re.search(r'```\w*\n(.*?)```', diff_text, re.DOTALL)
        if m:
            return m.group(1).rstrip(), "전체 코드 교체"
        stripped = diff_text.strip()
        if len(stripped.split('\n')) > 3:
            return stripped, "전체 코드 교체(블록 없음)"
        return None, "코드 블록 없음"


# ════════════════════════════════════════════════════════════════
#  4. MultiFileApplyDialog - 멀티파일 적용 대화상자
# ════════════════════════════════════════════════════════════════

class MultiFileApplyDialog:
    def __init__(self, parent, diff_blocks, file_resolver, on_complete=None):
        self.parent = parent
        self.diff_blocks = diff_blocks
        self.file_resolver = file_resolver
        self.on_complete = on_complete
        self.results = []
        self._build_ui()

    def _build_ui(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title(f"🔧 멀티파일 Diff 적용 — {len(self.diff_blocks)}개 파일")
        self.win.geometry("900x650")
        self.win.configure(bg='#1e1e2e')
        self.win.grab_set()

        # 상단
        summary = tk.Frame(self.win, bg='#181825')
        summary.pack(fill='x')
        tk.Label(summary, text=f"📦 {len(self.diff_blocks)}개 파일에 대한 수정사항",
                 font=('맑은 고딕', 12, 'bold'), bg='#181825', fg='#cdd6f4',
                 padx=12, pady=8).pack(side='left')

        # 메인: 좌(리스트) / 우(미리보기)
        main = tk.PanedWindow(self.win, orient=tk.HORIZONTAL, bg='#1e1e2e', sashwidth=4)
        main.pack(fill='both', expand=True, padx=8, pady=4)

        left = tk.Frame(main, bg='#1e1e2e')
        main.add(left, width=280)
        tk.Label(left, text="파일 목록", font=('맑은 고딕', 10, 'bold'),
                 bg='#1e1e2e', fg='#cdd6f4', pady=4).pack(fill='x')

        self.file_listbox = tk.Listbox(
            left, font=('Consolas', 10), bg='#313244', fg='#cdd6f4',
            selectbackground='#585b70', relief='flat')
        self.file_listbox.pack(fill='both', expand=True)
        self.file_listbox.bind('<<ListboxSelect>>', self._on_select)

        for i, block in enumerate(self.diff_blocks):
            full = self.file_resolver(block['file'])
            icon = "📄" if full and os.path.isfile(full) else "⚠️"
            self.file_listbox.insert(
                tk.END, f" {icon} {block['file']}  [{block['diff_type']}]")

        right = tk.Frame(main, bg='#1e1e2e')
        main.add(right, width=580)
        self.preview_label = tk.Label(right, text="파일을 선택하세요",
                                      font=('맑은 고딕', 10), bg='#1e1e2e', fg='#a6adc8',
                                      anchor='w', padx=8, pady=4)
        self.preview_label.pack(fill='x')

        self.preview_text = scrolledtext.ScrolledText(
            right, wrap=tk.NONE, font=('Consolas', 10),
            bg='#1e1e2e', fg='#cdd6f4', relief='flat', padx=8, pady=8)
        self.preview_text.pack(fill='both', expand=True)
        for tag, cfg in [
            ('add', {'foreground': '#a6e3a1', 'background': '#1a3a1a'}),
            ('del', {'foreground': '#f38ba8', 'background': '#3a1a1a'}),
            ('hdr', {'foreground': '#89b4fa', 'font': ('Consolas', 10, 'bold')}),
            ('info', {'foreground': '#f9e2af'}),
        ]:
            self.preview_text.tag_configure(tag, **cfg)

        # 버튼
        btn_frame = tk.Frame(self.win, bg='#1e1e2e')
        btn_frame.pack(fill='x', padx=8, pady=8)
        tk.Button(btn_frame, text="✅ 전체 적용 + 저장",
                  font=('맑은 고딕', 11, 'bold'), bg='#a6e3a1', fg='#1e1e2e',
                  relief='flat', padx=16, pady=8, cursor='hand2',
                  command=self._apply_all).pack(side='left', expand=True, fill='x', padx=2)
        tk.Button(btn_frame, text="▶ 선택 파일만 적용",
                  font=('맑은 고딕', 11, 'bold'), bg='#89b4fa', fg='#1e1e2e',
                  relief='flat', padx=16, pady=8, cursor='hand2',
                  command=self._apply_selected).pack(side='left', expand=True, fill='x', padx=2)
        tk.Button(btn_frame, text="취소",
                  font=('맑은 고딕', 11), bg='#45475a', fg='#cdd6f4',
                  relief='flat', padx=16, pady=8,
                  command=self.win.destroy).pack(side='left', expand=True, fill='x', padx=2)

        self.result_label = tk.Label(self.win, text="", font=('맑은 고딕', 10),
                                     bg='#1e1e2e', fg='#a6e3a1', anchor='w', padx=12, pady=4)
        self.result_label.pack(fill='x')

        if self.diff_blocks:
            self.file_listbox.select_set(0)
            self._on_select(None)

    def _on_select(self, event):
        sel = self.file_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        block = self.diff_blocks[idx]
        full_path = self.file_resolver(block['file'])

        found = bool(full_path and os.path.isfile(full_path))
        self.preview_label.config(
            text=f"📄 {block['file']} | {block['diff_type']} | "
                 f"{'✅ 발견' if found else '⚠️ 미발견'}")

        self.preview_text.config(state='normal')
        self.preview_text.delete('1.0', tk.END)

        if found:
            original = self._read_file(full_path)
            if original is None:
                self.preview_text.insert(tk.END, "파일 읽기 실패\n", 'del')
                self.preview_text.config(state='disabled')
                return

            new_content, msg = MultiFileDiffEngine.apply_single_diff(original, block)
            if new_content is not None:
                orig_lines = original.split('\n')
                new_lines = new_content.split('\n')
                diff_output = list(difflib.unified_diff(
                    orig_lines, new_lines,
                    fromfile=f'원본: {block["file"]}',
                    tofile=f'수정: {block["file"]}', lineterm=''))

                self.preview_text.insert(tk.END, f"✅ 적용 가능: {msg}\n\n", 'info')
                for line in diff_output:
                    if line.startswith(('+++', '---', '@@')):
                        self.preview_text.insert(tk.END, line + '\n', 'hdr')
                    elif line.startswith('+'):
                        self.preview_text.insert(tk.END, line + '\n', 'add')
                    elif line.startswith('-'):
                        self.preview_text.insert(tk.END, line + '\n', 'del')
                    else:
                        self.preview_text.insert(tk.END, line + '\n')

                added = sum(1 for l in diff_output if l.startswith('+') and not l.startswith('+++'))
                removed = sum(1 for l in diff_output if l.startswith('-') and not l.startswith('---'))
                self.preview_text.insert(tk.END, f"\n📊 +{added}줄, -{removed}줄\n", 'info')
            else:
                self.preview_text.insert(tk.END, f"❌ 적용 불가: {msg}\n", 'del')
        else:
            self.preview_text.insert(tk.END, f"⚠️ 파일 미발견: {block['file']}\n\n", 'del')
            self.preview_text.insert(tk.END, "Diff 내용:\n", 'info')
            self.preview_text.insert(tk.END, block['content'] + '\n')

        self.preview_text.config(state='disabled')

    def _apply_all(self):
        if not messagebox.askyesno("확인",
                                   f"{len(self.diff_blocks)}개 파일에 수정 적용합니다.\n"
                                   f".bak 백업이 생성됩니다.\n\n계속?", parent=self.win):
            return
        self.results = []
        ok, fail = 0, 0
        for i, block in enumerate(self.diff_blocks):
            r = self._apply_one(block)
            self.results.append(r)
            icon = '✅' if r['status'] == 'success' else '❌'
            self.file_listbox.delete(i)
            self.file_listbox.insert(i, f" {icon} {block['file']}  [{block['diff_type']}]")
            if r['status'] == 'success':
                self.file_listbox.itemconfig(i, fg='#a6e3a1')
                ok += 1
            else:
                self.file_listbox.itemconfig(i, fg='#f38ba8')
                fail += 1

        msg = f"✅ 성공: {ok}  ❌ 실패: {fail}"
        self.result_label.config(text=msg, fg='#a6e3a1' if fail == 0 else '#f9e2af')
        if self.on_complete:
            self.on_complete(self.results)
        messagebox.showinfo("적용 완료", msg, parent=self.win)

    def _apply_selected(self):
        sel = self.file_listbox.curselection()
        if not sel:
            messagebox.showwarning("경고", "파일을 선택하세요.", parent=self.win)
            return
        idx = sel[0]
        block = self.diff_blocks[idx]
        r = self._apply_one(block)
        icon = '✅' if r['status'] == 'success' else '❌'
        self.file_listbox.delete(idx)
        self.file_listbox.insert(idx, f" {icon} {block['file']}  [{block['diff_type']}]")
        color = '#a6e3a1' if r['status'] == 'success' else '#f38ba8'
        self.file_listbox.itemconfig(idx, fg=color)
        self.result_label.config(text=f"{icon} {r['file']}: {r['message']}", fg=color)

    def _apply_one(self, block: dict) -> dict:
        full_path = self.file_resolver(block['file'])
        if not full_path or not os.path.isfile(full_path):
            return {'file': block['file'], 'status': 'fail', 'message': '파일 미발견'}
        original = self._read_file(full_path)
        if original is None:
            return {'file': block['file'], 'status': 'fail', 'message': '읽기 실패'}
        new_content, msg = MultiFileDiffEngine.apply_single_diff(original, block)
        if new_content is None:
            return {'file': block['file'], 'status': 'fail', 'message': msg}

        # 백업
        try:
            with open(full_path + '.bak', 'w', encoding='utf-8') as f:
                f.write(original)
        except Exception:
            pass
        # 저장
        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return {'file': block['file'], 'status': 'success', 'message': msg}
        except Exception as e:
            return {'file': block['file'], 'status': 'fail', 'message': str(e)}

    @staticmethod
    def _read_file(fp):
        for enc in ['utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin-1']:
            try:
                with open(fp, 'r', encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return None


# ════════════════════════════════════════════════════════════════
#  5. GitHubUploader
# ════════════════════════════════════════════════════════════════

class GitHubUploader:
    def __init__(self, log_callback=None):
        self.log = log_callback or print

    def check_git(self):
        try:
            return subprocess.run(['git', '--version'], capture_output=True, timeout=10).returncode == 0
        except Exception:
            return False

    def check_gh_cli(self):
        try:
            return subprocess.run(['gh', '--version'], capture_output=True, timeout=10).returncode == 0
        except Exception:
            return False

    def check_gh_auth(self):
        try:
            return subprocess.run(['gh', 'auth', 'status'], capture_output=True, timeout=10).returncode == 0
        except Exception:
            return False

    def run_cmd(self, cmd, cwd=None):
        self.log(f"  > {' '.join(cmd)}")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                               timeout=60, encoding='utf-8', errors='replace')
            if r.stdout.strip():
                self.log(f"    {r.stdout.strip()}")
            if r.returncode != 0 and r.stderr.strip():
                self.log(f"    ⚠ {r.stderr.strip()}")
            return r
        except Exception as e:
            self.log(f"    ❌ {e}")
            return None

    def create_and_push(self, files, project_path, repo_name,
                        private=True, description="", progress_cb=None):
        tmp_dir = os.path.join(tempfile.gettempdir(), f'projectscan_{repo_name}')
        try:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir)
            os.makedirs(tmp_dir)
            if progress_cb:
                progress_cb(10, "파일 복사 중...")

            for rp, fp, sz in files:
                dest = os.path.join(tmp_dir, rp)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(fp, dest)
            self.log(f"✅ {len(files)}개 파일 복사 완료")

            with open(os.path.join(tmp_dir, '.gitignore'), 'w') as f:
                f.write("bin/\nobj/\n.vs/\n*.exe\n*.dll\n*.pdb\n*.user\n*.suo\n"
                        "*.env\nnode_modules/\n__pycache__/\n")

            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            with open(os.path.join(tmp_dir, 'README.md'), 'w', encoding='utf-8') as f:
                f.write(f"# {repo_name}\n\nUploaded via ProjectScan ({now})\n"
                        f"Files: {len(files)}\n")

            if progress_cb:
                progress_cb(30, "git 초기화...")
            self.run_cmd(['git', 'init'], cwd=tmp_dir)
            self.run_cmd(['git', 'branch', '-M', 'main'], cwd=tmp_dir)
            self.run_cmd(['git', 'add', '.'], cwd=tmp_dir)
            self.run_cmd(['git', 'commit', '-m',
                          f'Initial commit - {len(files)} files from ProjectScan'], cwd=tmp_dir)

            if progress_cb:
                progress_cb(50, "GitHub 리포 생성...")
            vis = '--private' if private else '--public'
            cmd = ['gh', 'repo', 'create', repo_name, vis, '--source=.', '--push']
            if description:
                cmd.extend(['--description', description])
            result = self.run_cmd(cmd, cwd=tmp_dir)

            if result and result.returncode == 0:
                url = ""
                for line in (result.stdout + result.stderr).split('\n'):
                    urls = re.findall(r'https://github\.com/[^\s]+', line)
                    if urls:
                        url = urls[0]
                        break
                if not url:
                    api_r = self.run_cmd(
                        ['gh', 'repo', 'view', repo_name, '--json', 'url'], cwd=tmp_dir)
                    if api_r and api_r.returncode == 0:
                        try:
                            url = json.loads(api_r.stdout).get('url', '')
                        except Exception:
                            pass
                if progress_cb:
                    progress_cb(100, "완료!")
                self.log(f"\n🎉 업로드 성공: {url}")
                return True, url
            else:
                err = result.stderr if result else "알 수 없는 오류"
                self.log(f"\n❌ 업로드 실패: {err}")
                return False, str(err)
        except Exception as e:
            self.log(f"\n❌ 예외: {e}")
            return False, str(e)
        finally:
            try:
                if os.path.exists(tmp_dir):
                    shutil.rmtree(tmp_dir)
            except Exception:
                pass
# ════════════════════════════════════════════════════════════════
#  6. ProjectScan - 메인 앱
# ════════════════════════════════════════════════════════════════

class ProjectScan:
    def __init__(self, root):
        self.root = root
        self.root.title("📂 ProjectScan Pro — AI 멀티파일 코드 수정 워크스테이션")
        self.root.geometry("1350x950")
        self.root.configure(bg="#1e1e2e")
        self.root.minsize(1000, 700)

        # 변수
        self.project_path = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="프로젝트 폴더를 선택하세요")
        self.max_file_size = tk.IntVar(value=100)
        self.source_only = tk.BooleanVar(value=False)
        self.attach_file = tk.BooleanVar(value=True)
        self.attach_checked = tk.BooleanVar(value=False)

        self.tree_item_map = {}   # tree iid -> (rel_path, full_path, size)
        self.path_map = {}        # rel_path -> full_path (멀티파일 diff 경로 해석용)

        self.uploader = GitHubUploader(log_callback=self.append_log)

        # 확장자 정의
        self.source_only_extensions = {
            '.c', '.cpp', '.cxx', '.cc', '.h', '.hpp', '.hxx', '.inl',
            '.cs', '.vb', '.fs', '.fsi', '.fsx',
            '.py', '.java', '.go', '.rs', '.rb', '.php',
            '.js', '.jsx', '.ts', '.tsx', '.swift', '.kt', '.scala', '.sql',
        }
        self.all_code_extensions = {
            '.c', '.cpp', '.cxx', '.cc', '.h', '.hpp', '.hxx', '.inl',
            '.cs', '.vb', '.fs', '.fsi', '.fsx',
            '.xaml', '.cshtml', '.razor', '.aspx',
            '.py', '.java', '.go', '.rs', '.rb', '.php',
            '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte',
            '.html', '.css', '.scss', '.less',
            '.swift', '.kt', '.scala', '.r',
            '.sql', '.sh', '.bash', '.bat', '.cmd', '.ps1',
            '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg',
            '.xml', '.md', '.txt', '.rc', '.def', '.idl',
            '.sln', '.vcxproj', '.csproj', '.vbproj', '.fsproj',
        }
        self.default_excludes = [
            'node_modules', '.git', '__pycache__', '.vs', '.vscode', '.idea',
            'bin', 'obj', 'x64', 'x86', 'ARM', 'ARM64',
            'Debug', 'Release', 'RelWithDebInfo', 'MinSizeRel',
            'ipch', '.nuget', 'packages', 'TestResults',
            'dist', 'build', 'out', '.next', '.venv', 'venv', 'env',
            '*.pyc', '*.pyo', '*.exe', '*.dll', '*.so', '*.dylib',
            '*.pdb', '*.ilk', '*.obj', '*.o', '*.lib', '*.exp', '*.idb',
            '*.tlog', '*.recipe', '*.cache', '*.log',
            '*.suo', '*.user', '*.ncb', '*.sdf', '*.db', '*.opendb',
            '*.ipch', '*.aps',
            '*.jpg', '*.jpeg', '*.png', '*.gif', '*.ico', '*.svg', '*.bmp',
            '*.mp3', '*.mp4', '*.avi', '*.mov', '*.pdf',
            '*.zip', '*.tar', '*.gz', '*.rar', '*.7z',
            '*.lock', 'package-lock.json', 'yarn.lock',
            '*.min.js', '*.min.css', '*.map',
            '.DS_Store', 'Thumbs.db', '*.bak',
            '*.resources', '*.resx', '*.props', '*.targets',
        ]
        self.sensitive_patterns = [
            '*.env', '.env', '.env.*', 'appsettings.Development.json',
            'secrets.json', 'credentials.*',
            '*password*', '*secret*', '*token*', '*apikey*',
            '*.pem', '*.key', '*.pfx', '*.p12',
            'id_rsa', 'id_rsa.*', 'id_ed25519', 'id_ed25519.*',
        ]
        self.vs_project_extensions = ['.vcxproj', '.csproj', '.vbproj', '.fsproj']

        self._setup_styles()
        self._create_widgets()

    # ──────────────────── 스타일 ────────────────────

    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('Title.TLabel', font=('맑은 고딕', 14, 'bold'),
                    foreground='#cdd6f4', background='#1e1e2e')
        s.configure('Info.TLabel', font=('맑은 고딕', 9),
                    foreground='#a6adc8', background='#1e1e2e')
        s.configure('Status.TLabel', font=('맑은 고딕', 10),
                    foreground='#a6e3a1', background='#1e1e2e')
        s.configure('TCheckbutton', font=('맑은 고딕', 9),
                    foreground='#cdd6f4', background='#1e1e2e')
        s.configure('Custom.Treeview', background='#313244', foreground='#cdd6f4',
                    fieldbackground='#313244', font=('Consolas', 10), rowheight=20)
        s.configure('Custom.Treeview.Heading', background='#45475a', foreground='#cdd6f4',
                    font=('맑은 고딕', 9, 'bold'))
        s.map('Custom.Treeview', background=[('selected', '#585b70')])

    # ──────────────────── UI 생성 ────────────────────

    def _create_widgets(self):
        # ═══ 툴바 ═══
        toolbar = tk.Frame(self.root, bg='#181825')
        toolbar.pack(fill='x')

        tk.Button(toolbar, text="📁 폴더", font=('맑은 고딕', 9),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=8, pady=4,
                  command=self.select_folder).pack(side='left', padx=2, pady=3)
        self.folder_label = tk.Label(toolbar, text="선택되지 않음",
                                     font=('맑은 고딕', 9), bg='#181825', fg='#a6adc8')
        self.folder_label.pack(side='left', padx=5)

        tk.Button(toolbar, text="🔍 폴더스캔", font=('맑은 고딕', 9),
                  bg='#89b4fa', fg='#1e1e2e', relief='flat', padx=8, pady=4,
                  command=self.scan_folder).pack(side='left', padx=2, pady=3)
        tk.Button(toolbar, text="🏗️ VS스캔", font=('맑은 고딕', 9),
                  bg='#f38ba8', fg='#1e1e2e', relief='flat', padx=8, pady=4,
                  command=self.scan_vs_project).pack(side='left', padx=2, pady=3)

        ttk.Checkbutton(toolbar, text="소스Only", variable=self.source_only,
                        style='TCheckbutton',
                        command=self._on_source_only_changed).pack(side='left', padx=8)

        tk.Label(toolbar, text="Max(KB):", font=('맑은 고딕', 9),
                 bg='#181825', fg='#a6adc8').pack(side='left')
        tk.Spinbox(toolbar, from_=10, to=500, width=4,
                   textvariable=self.max_file_size,
                   font=('Consolas', 9), bg='#313244', fg='#cdd6f4').pack(side='left', padx=2)

        self.vs_info_label = tk.Label(toolbar, text="", font=('맑은 고딕', 9),
                                      bg='#181825', fg='#f38ba8')
        self.vs_info_label.pack(side='right', padx=8)

        # ═══ 메인 3단 분할 ═══
        main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                                   bg='#1e1e2e', sashwidth=4, sashrelief='flat')
        main_pane.pack(fill='both', expand=True, padx=4, pady=4)

        # ── 좌: 파일트리 ──
        left = tk.Frame(main_pane, bg='#1e1e2e')
        main_pane.add(left, width=260)

        tree_header = tk.Frame(left, bg='#181825')
        tree_header.pack(fill='x')
        tk.Label(tree_header, text="📁 파일트리", font=('맑은 고딕', 9, 'bold'),
                 bg='#181825', fg='#cdd6f4', padx=6, pady=3).pack(side='left')
        self.tree_count_label = tk.Label(tree_header, text="",
                                         font=('맑은 고딕', 8), bg='#181825', fg='#6c7086')
        self.tree_count_label.pack(side='right', padx=4)

        tree_btns = tk.Frame(left, bg='#1e1e2e')
        tree_btns.pack(fill='x', pady=2)
        for txt, cmd in [
            ("✅All", self._tree_check_all), ("⬜None", self._tree_uncheck_all),
            (".c/.cpp", lambda: self._tree_check_ext({'.c', '.cpp', '.cxx', '.cc'})),
            (".h", lambda: self._tree_check_ext({'.h', '.hpp', '.hxx'})),
            (".cs", lambda: self._tree_check_ext({'.cs'})),
            (".vb", lambda: self._tree_check_ext({'.vb'})),
        ]:
            tk.Button(tree_btns, text=txt, font=('맑은 고딕', 8), bg='#45475a',
                      fg='#cdd6f4', relief='flat', padx=3, pady=0,
                      command=cmd).pack(side='left', padx=1)

        tree_container = tk.Frame(left, bg='#313244')
        tree_container.pack(fill='both', expand=True)
        tree_scrollbar = ttk.Scrollbar(tree_container, orient='vertical')
        tree_scrollbar.pack(side='right', fill='y')

        self.file_tree = CheckboxTreeview(
            tree_container, columns=('size', 'ext'),
            style='Custom.Treeview', yscrollcommand=tree_scrollbar.set)
        self.file_tree.pack(fill='both', expand=True)
        tree_scrollbar.config(command=self.file_tree.yview)

        self.file_tree.heading('#0', text='파일', anchor='w')
        self.file_tree.heading('size', text='크기', anchor='e')
        self.file_tree.heading('ext', text='확장자', anchor='c')
        self.file_tree.column('#0', width=170, minwidth=100)
        self.file_tree.column('size', width=55, minwidth=40, anchor='e')
        self.file_tree.column('ext', width=45, minwidth=30, anchor='c')
        self.file_tree.bind('<Double-1>', self._on_tree_double_click)

        # ── 중앙: 편집기 ──
        center = tk.Frame(main_pane, bg='#1e1e2e')
        main_pane.add(center, width=480)

        self.editor = CodeEditor(center)
        self.editor.pack(fill='both', expand=True)

        editor_btns = tk.Frame(center, bg='#1e1e2e')
        editor_btns.pack(fill='x', pady=(2, 0))
        tk.Button(editor_btns, text="💾 저장", font=('맑은 고딕', 9, 'bold'),
                  bg='#a6e3a1', fg='#1e1e2e', relief='flat', padx=8, pady=3,
                  command=self._save_file).pack(side='left', padx=2)
        tk.Button(editor_btns, text="↩ 되돌리기", font=('맑은 고딕', 9),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=8, pady=3,
                  command=self._revert_file).pack(side='left', padx=2)
        tk.Button(editor_btns, text="📋 줄번호복사", font=('맑은 고딕', 9),
                  bg='#89b4fa', fg='#1e1e2e', relief='flat', padx=8, pady=3,
                  command=self._copy_with_line_numbers).pack(side='right', padx=2)

        # ── 우측: 탭 (프롬프트 / Diff / GitHub) ──
        right = tk.Frame(main_pane, bg='#1e1e2e')
        main_pane.add(right, width=460)

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill='both', expand=True)

        # ─── 탭1: 💬 프롬프트 ───
        tab_prompt = tk.Frame(self.notebook, bg='#1e1e2e')
        self.notebook.add(tab_prompt, text=' 💬 프롬프트 ')

        tk.Label(tab_prompt, text="💬 AI에게 보낼 프롬프트 작성",
                 font=('맑은 고딕', 10, 'bold'), bg='#1e1e2e', fg='#cdd6f4'
                 ).pack(fill='x', padx=6, pady=(6, 2))

        attach_frame = tk.Frame(tab_prompt, bg='#1e1e2e')
        attach_frame.pack(fill='x', padx=6, pady=2)
        ttk.Checkbutton(attach_frame, text="현재 파일 첨부(줄번호)",
                        variable=self.attach_file, style='TCheckbutton').pack(side='left')
        ttk.Checkbutton(attach_frame, text="체크파일 전체 첨부",
                        variable=self.attach_checked, style='TCheckbutton').pack(side='left', padx=(12, 0))
        self.attach_info_label = tk.Label(attach_frame, text="", font=('맑은 고딕', 8),
                                          bg='#1e1e2e', fg='#6c7086')
        self.attach_info_label.pack(side='right')

        tk.Label(tab_prompt,
                 text="💡 멀티파일 수정 시 === FILE: path === 형식 반환 요청 권장",
                 font=('맑은 고딕', 8), bg='#1e1e2e', fg='#f9e2af', anchor='w'
                 ).pack(fill='x', padx=6)

        self.prompt_text = scrolledtext.ScrolledText(
            tab_prompt, wrap=tk.WORD, font=('맑은 고딕', 11),
            bg='#313244', fg='#cdd6f4', insertbackground='#f5e0dc',
            relief='flat', padx=10, pady=8, height=7)
        self.prompt_text.pack(fill='both', expand=True, padx=6, pady=4)

        # 템플릿 버튼
        tpl_frame = tk.Frame(tab_prompt, bg='#1e1e2e')
        tpl_frame.pack(fill='x', padx=6, pady=2)
        tk.Label(tpl_frame, text="템플릿:", font=('맑은 고딕', 8),
                 bg='#1e1e2e', fg='#6c7086').pack(side='left')
        templates = [
            ("단일 수정",
             "아래 코드에서 에러/개선이 필요합니다.\n\n[설명]\n\n"
             "줄번호를 참고하여 수정 부분만 반환해주세요.\n"
             "형식: <<<< SEARCH ... ==== ... >>>> REPLACE"),
            ("멀티파일",
             "아래 파일들에서 다음 수정이 필요합니다.\n\n[설명]\n\n"
             "여러 파일 수정 시 아래 형식으로 반환:\n\n"
             "=== FILE: 상대경로/파일명 ===\n"
             "<<<< SEARCH\n찾을 코드\n====\n바꿀 코드\n>>>> REPLACE\n"
             "=== END FILE ==="),
            ("에러 수정",
             "아래 코드에서 다음 에러가 발생합니다.\n\n[에러 메시지]\n\n"
             "수정 부분만 SEARCH/REPLACE 형식으로 반환:\n"
             "<<<< SEARCH\n원본\n====\n수정\n>>>> REPLACE"),
            ("리뷰",
             "아래 코드를 리뷰해주세요.\n줄번호와 파일명 포함하여 알려주세요."),
        ]
        for name, template in templates:
            tk.Button(tpl_frame, text=name, font=('맑은 고딕', 8),
                      bg='#45475a', fg='#cdd6f4', relief='flat', padx=5, pady=1,
                      command=lambda t=template: self._set_template(t)
                      ).pack(side='left', padx=1)

        # 복사 버튼
        tk.Button(tab_prompt, text="📋 프롬프트 + 첨부 → 클립보드 복사",
                  font=('맑은 고딕', 11, 'bold'), bg='#cba6f7', fg='#1e1e2e',
                  relief='flat', padx=20, pady=8, cursor='hand2',
                  command=self._copy_prompt).pack(fill='x', padx=6, pady=(4, 6))

        # ─── 탭2: 🔧 Diff 적용 ───
        tab_diff = tk.Frame(self.notebook, bg='#1e1e2e')
        self.notebook.add(tab_diff, text=' 🔧 Diff 적용 ')

        tk.Label(tab_diff, text="🔧 AI의 수정 결과를 붙여넣기",
                 font=('맑은 고딕', 10, 'bold'), bg='#1e1e2e', fg='#cdd6f4'
                 ).pack(fill='x', padx=6, pady=(6, 2))
        tk.Label(tab_diff,
                 text="📌 단일: SEARCH/REPLACE · unified diff · 줄범위 · 전체코드\n"
                      "📌 멀티: === FILE: path === ... === END FILE === 블록",
                 font=('맑은 고딕', 8), bg='#1e1e2e', fg='#6c7086', anchor='w', justify='left'
                 ).pack(fill='x', padx=6)

        self.diff_text = scrolledtext.ScrolledText(
            tab_diff, wrap=tk.WORD, font=('Consolas', 10),
            bg='#313244', fg='#cdd6f4', insertbackground='#f5e0dc',
            relief='flat', padx=10, pady=8, height=10)
        self.diff_text.pack(fill='both', expand=True, padx=6, pady=4)

        self.diff_result_label = tk.Label(tab_diff, text="", font=('맑은 고딕', 9),
                                          bg='#1e1e2e', fg='#a6adc8', anchor='w',
                                          wraplength=420)
        self.diff_result_label.pack(fill='x', padx=6, pady=2)

        diff_btns = tk.Frame(tab_diff, bg='#1e1e2e')
        diff_btns.pack(fill='x', padx=6, pady=(2, 4))

        tk.Button(diff_btns, text="🔍 분석 (파일 감지 + 미리보기)",
                  font=('맑은 고딕', 10, 'bold'), bg='#f9e2af', fg='#1e1e2e',
                  relief='flat', padx=12, pady=6, cursor='hand2',
                  command=self._analyze_diff).pack(fill='x', pady=2)
        tk.Button(diff_btns, text="✅ 현재 파일에 적용 (단일 파일)",
                  font=('맑은 고딕', 10, 'bold'), bg='#a6e3a1', fg='#1e1e2e',
                  relief='flat', padx=12, pady=6, cursor='hand2',
                  command=self._apply_single_diff).pack(fill='x', pady=2)
        tk.Button(diff_btns, text="📦 멀티파일 일괄 적용 + 저장",
                  font=('맑은 고딕', 10, 'bold'), bg='#89b4fa', fg='#1e1e2e',
                  relief='flat', padx=12, pady=6, cursor='hand2',
                  command=self._apply_multi_diff).pack(fill='x', pady=2)

        # ─── 탭3: 🚀 GitHub ───
        tab_github = tk.Frame(self.notebook, bg='#1e1e2e')
        self.notebook.add(tab_github, text=' 🚀 GitHub ')

        # 합치기 섹션
        merge_section = tk.LabelFrame(tab_github, text=" 📄 일괄 합치기 + 복사 ",
                                      font=('맑은 고딕', 9, 'bold'),
                                      bg='#1e1e2e', fg='#cdd6f4', padx=8, pady=6)
        merge_section.pack(fill='x', padx=6, pady=6)
        tk.Button(merge_section, text="📄 체크된 파일 → 하나로 합쳐서 복사",
                  font=('맑은 고딕', 10, 'bold'), bg='#a6e3a1', fg='#1e1e2e',
                  relief='flat', padx=12, pady=6, cursor='hand2',
                  command=self._merge_and_copy).pack(fill='x')
        self.merge_info_label = tk.Label(merge_section, text="",
                                         font=('맑은 고딕', 8), bg='#1e1e2e', fg='#6c7086')
        self.merge_info_label.pack(fill='x', pady=(4, 0))

        # GitHub 섹션
        gh_section = tk.LabelFrame(tab_github, text=" 🚀 GitHub 업로드 ",
                                   font=('맑은 고딕', 9, 'bold'),
                                   bg='#1e1e2e', fg='#cdd6f4', padx=8, pady=6)
        gh_section.pack(fill='x', padx=6, pady=6)

        gh_row = tk.Frame(gh_section, bg='#1e1e2e')
        gh_row.pack(fill='x', pady=2)
        tk.Label(gh_row, text="리포명:", font=('맑은 고딕', 9),
                 bg='#1e1e2e', fg='#a6adc8').pack(side='left')
        self.repo_name_var = tk.StringVar()
        tk.Entry(gh_row, textvariable=self.repo_name_var, font=('Consolas', 10),
                 bg='#45475a', fg='#f5e0dc', insertbackground='#f5e0dc',
                 width=22, relief='flat').pack(side='left', padx=4)
        self.private_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(gh_row, text="Private", variable=self.private_var,
                        style='TCheckbutton').pack(side='left', padx=4)

        self.gh_upload_btn = tk.Button(
            gh_section, text="🚀 GitHub 업로드",
            font=('맑은 고딕', 10, 'bold'), bg='#f38ba8', fg='#1e1e2e',
            relief='flat', padx=12, pady=6, cursor='hand2',
            command=self._upload_to_github)
        self.gh_upload_btn.pack(fill='x', pady=4)

        tk.Label(gh_section, text="⚠ git + gh CLI 필요 | 민감파일 자동 제외",
                 font=('맑은 고딕', 8), bg='#1e1e2e', fg='#f9e2af').pack(fill='x')
        self.gh_status_label = tk.Label(gh_section, text="", font=('맑은 고딕', 9),
                                        bg='#1e1e2e', fg='#a6adc8')
        self.gh_status_label.pack(fill='x', pady=2)

        # 로그
        log_section = tk.LabelFrame(tab_github, text=" 로그 ",
                                    font=('맑은 고딕', 9), bg='#1e1e2e', fg='#6c7086',
                                    padx=4, pady=4)
        log_section.pack(fill='both', expand=True, padx=6, pady=6)
        self.log_text = scrolledtext.ScrolledText(
            log_section, wrap=tk.WORD, font=('Consolas', 9),
            bg='#11111b', fg='#a6e3a1', relief='flat', padx=6, pady=4, height=6)
        self.log_text.pack(fill='both', expand=True)

        # ═══ 하단 ═══
        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(self.root, variable=self.progress_var, maximum=100).pack(fill='x', padx=4)

        status_bar = tk.Frame(self.root, bg='#11111b')
        status_bar.pack(fill='x', side='bottom')
        ttk.Label(status_bar, textvariable=self.status_var,
                  style='Status.TLabel').pack(padx=10, pady=4)

    # ──────────────────── 이벤트 핸들러 ────────────────────

    def _on_tree_double_click(self, event):
        item = self.file_tree.identify_row(event.y)
        if not item or item not in self.tree_item_map:
            return
        if self.editor.is_modified:
            if not messagebox.askyesno("확인", "현재 파일이 수정됨.\n저장하지 않고 열까요?"):
                return
        rel_path, full_path, size = self.tree_item_map[item]
        if self.editor.load_file(full_path):
            self.status_var.set(f"📄 {rel_path} ({self._format_size(size)})")
            line_count = len(self.editor.get_content().split('\n'))
            self.attach_info_label.config(text=f"📄 {os.path.basename(full_path)} | {line_count}줄")
            self.notebook.select(0)

    def _set_template(self, template):
        self.prompt_text.delete('1.0', tk.END)
        self.prompt_text.insert('1.0', template)

    def _save_file(self):
        if self.editor.save_file():
            self.status_var.set(f"✅ 저장: {self.editor.current_file}")

    def _revert_file(self):
        if self.editor.current_file and messagebox.askyesno("확인", "원본으로 되돌릴까요?"):
            self.editor.load_file(self.editor.current_file)
            self.status_var.set("↩ 원본으로 되돌림")

    def _copy_with_line_numbers(self):
        if not self.editor.current_file:
            messagebox.showwarning("경고", "열린 파일이 없습니다.")
            return
        fn = os.path.basename(self.editor.current_file)
        ext = os.path.splitext(fn)[1].lstrip('.')
        text = f"📄 파일: {fn}\n```{ext}\n{self.editor.get_content_with_line_numbers()}\n```"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set(f"✅ 줄번호 포함 복사: {fn}")

    # ──────────── 프롬프트 복사 ────────────

    def _copy_prompt(self):
        prompt = self.prompt_text.get('1.0', 'end-1c').strip()
        if not prompt:
            messagebox.showwarning("경고", "프롬프트를 작성해주세요.")
            return

        result = prompt + "\n\n"

        # 현재 파일 첨부
        if self.attach_file.get() and self.editor.current_file:
            fn = os.path.basename(self.editor.current_file)
            # 상대경로 찾기
            display_name = fn
            for iid, (rp, fp, sz) in self.tree_item_map.items():
                if fp == self.editor.current_file:
                    display_name = rp
                    break
            ext = os.path.splitext(fn)[1].lstrip('.')
            result += f"---\n📄 파일: {display_name}\n"
            result += f"```{ext}\n{self.editor.get_content_with_line_numbers()}\n```\n\n"

        # 체크된 파일 전체 첨부
        if self.attach_checked.get():
            checked = self._get_checked_files()
            if self.attach_file.get() and self.editor.current_file:
                checked = [(rp, fp, sz) for rp, fp, sz in checked
                           if fp != self.editor.current_file]
            if checked:
                result += f"---\n📦 추가 첨부 ({len(checked)}개)\n\n"
                for rp, fp, sz in checked:
                    content = self._read_file(fp)
                    if content is None:
                        continue
                    ext = os.path.splitext(rp)[1].lstrip('.')
                    lines = content.split('\n')
                    w = len(str(len(lines)))
                    numbered = '\n'.join(f"{str(i).rjust(w)}| {l}" for i, l in enumerate(lines, 1))
                    result += f"### 📄 {rp}\n```{ext}\n{numbered}\n```\n\n"

        self.root.clipboard_clear()
        self.root.clipboard_append(result)
        tokens = len(result) // 4
        self.status_var.set(f"✅ 복사 완료 (약 {tokens:,}토큰)")
        messagebox.showinfo("복사 완료",
                            f"클립보드 복사!\n약 {tokens:,}토큰 | {len(result):,}자\n\n"
                            f"AI 채팅에 Ctrl+V")

    # ──────────── Diff 분석/적용 ────────────

    def _analyze_diff(self):
        diff_input = self.diff_text.get('1.0', 'end-1c').strip()
        if not diff_input:
            messagebox.showwarning("경고", "AI 수정 결과를 붙여넣어주세요.")
            return

        blocks = MultiFileDiffEngine.parse_multi_file_diff(diff_input)

        if len(blocks) > 1:
            found = sum(1 for b in blocks if self._resolve_path(b['file']))
            names = ", ".join(os.path.basename(b['file']) for b in blocks[:5])
            if len(blocks) > 5:
                names += f" 외 {len(blocks)-5}개"
            self.diff_result_label.config(
                text=f"📦 {len(blocks)}개 파일 감지 (프로젝트 내 {found}개 발견)\n"
                     f"파일: {names}\n→ '멀티파일 일괄 적용' 클릭",
                fg='#89b4fa')
        elif len(blocks) == 1:
            b = blocks[0]
            found = "✅" if self._resolve_path(b['file']) else "⚠️"
            self.diff_result_label.config(
                text=f"📄 단일 파일: {b['file']} [{b['diff_type']}] {found}\n"
                     f"→ '현재 파일에 적용' 또는 '멀티파일 적용' 사용",
                fg='#a6e3a1')
        else:
            self.diff_result_label.config(
                text="파일 구분 없음 → 현재 열린 파일에 직접 적용 가능\n"
                     "→ '현재 파일에 적용' 버튼",
                fg='#f9e2af')

    def _apply_single_diff(self):
        if not self.editor.current_file:
            messagebox.showwarning("경고", "먼저 파일을 열어주세요.")
            return
        diff_input = self.diff_text.get('1.0', 'end-1c').strip()
        if not diff_input:
            messagebox.showwarning("경고", "Diff를 붙여넣어주세요.")
            return

        original = self.editor.get_content()
        blocks = MultiFileDiffEngine.parse_multi_file_diff(diff_input)

        if blocks:
            # 현재 파일에 맞는 블록 찾기
            cur_base = os.path.basename(self.editor.current_file).lower()
            target = None
            for b in blocks:
                if os.path.basename(b['file']).lower() == cur_base:
                    target = b
                    break
            if not target:
                target = blocks[0]
            new_content, msg = MultiFileDiffEngine.apply_single_diff(original, target)
        else:
            fake = {'file': '', 'diff_type': 'unknown', 'content': diff_input}
            new_content, msg = MultiFileDiffEngine.apply_single_diff(original, fake)

        if new_content is None:
            self.diff_result_label.config(text=f"❌ {msg}", fg='#f38ba8')
            messagebox.showwarning("적용 실패", msg)
        else:
            self.editor.set_content(new_content)
            self.diff_result_label.config(text=f"✅ {msg}", fg='#a6e3a1')
            self.status_var.set("✅ Diff 적용 완료 — 💾 저장 필요")

    def _apply_multi_diff(self):
        diff_input = self.diff_text.get('1.0', 'end-1c').strip()
        if not diff_input:
            messagebox.showwarning("경고", "Diff를 붙여넣어주세요.")
            return

        blocks = MultiFileDiffEngine.parse_multi_file_diff(diff_input)
        if not blocks:
            if self.editor.current_file:
                self._apply_single_diff()
            else:
                messagebox.showwarning("경고", "파일 구분을 감지하지 못했습니다.")
            return

        def on_complete(results):
            ok = sum(1 for r in results if r['status'] == 'success')
            fail = sum(1 for r in results if r['status'] == 'fail')
            self.status_var.set(f"멀티파일 적용: ✅{ok} ❌{fail}")
            if self.editor.current_file:
                for r in results:
                    full = self._resolve_path(r['file'])
                    if full and os.path.normpath(full) == os.path.normpath(self.editor.current_file):
                        self.editor.load_file(self.editor.current_file)
                        break

        MultiFileApplyDialog(self.root, blocks, self._resolve_path, on_complete)

    def _resolve_path(self, rel_path: str):
        """상대경로 → 프로젝트 내 실제 절대경로"""
        rel_norm = rel_path.replace('\\', '/').strip()

        # 1. path_map 직접 매칭
        for key, full in self.path_map.items():
            if key.replace('\\', '/') == rel_norm:
                return full

        # 2. 프로젝트 루트 기준
        project = self.project_path.get()
        if project:
            full = os.path.normpath(os.path.join(project, rel_path))
            if os.path.isfile(full):
                return full

        # 3. 파일명만으로
        basename = os.path.basename(rel_path).lower()
        for key, full in self.path_map.items():
            if os.path.basename(key).lower() == basename:
                return full

        # 4. 부분 경로
        parts = rel_norm.split('/')
        for key, full in self.path_map.items():
            key_parts = key.replace('\\', '/').split('/')
            if len(parts) <= len(key_parts) and key_parts[-len(parts):] == parts:
                return full

        return None

    # ──────────── 유틸리티 ────────────

    def _should_exclude(self, path, name):
        for p in self.default_excludes:
            if fnmatch.fnmatch(name, p) or name == p:
                return True
        return False

    def _is_sensitive(self, rel_path):
        name = os.path.basename(rel_path).lower()
        for p in self.sensitive_patterns:
            if fnmatch.fnmatch(name, p.lower()):
                return True
        return False

    def _is_target_file(self, filename):
        _, ext = os.path.splitext(filename)
        exts = self.source_only_extensions if self.source_only.get() else self.all_code_extensions
        return ext.lower() in exts

    def _format_size(self, size):
        if size >= 1048576:
            return f"{size/1048576:.1f}MB"
        if size >= 1024:
            return f"{size/1024:.1f}KB"
        return f"{size}B"

    def _read_file(self, filepath):
        for enc in ['utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin-1']:
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return None

    def append_log(self, text):
        def _do():
            self.log_text.insert(tk.END, text + "\n")
            self.log_text.see(tk.END)
        self.root.after(0, _do)

    # ──────────── 트리뷰 ────────────

    def select_folder(self):
        folder = filedialog.askdirectory(title="프로젝트 폴더")
        if folder:
            self.project_path.set(folder)
            self.folder_label.config(text=folder)
            self.repo_name_var.set(os.path.basename(folder))
            self.status_var.set(f"프로젝트: {folder}")
            sln, proj = self._detect_vs_projects(folder)
            if sln or proj:
                self.vs_info_label.config(text=f"🏗️ {len(sln)}sln, {len(proj)}proj")
            else:
                self.vs_info_label.config(text="")

    def _clear_tree(self):
        for item in self.file_tree.get_children(''):
            self.file_tree.delete(item)
        self.file_tree._checked.clear()
        self.file_tree._unchecked.clear()
        self.tree_item_map.clear()
        self.path_map.clear()

    def _populate_tree(self, file_list, base_path):
        self._clear_tree()
        folder_nodes = {}
        file_list.sort(key=lambda x: x[0].lower())

        for rel_path, full_path, size in file_list:
            parts = rel_path.replace('\\', '/').split('/')
            filename = parts[-1]
            folders = parts[:-1]

            parent_iid = ''
            current_folder = ''
            for folder_name in folders:
                current_folder = f"{current_folder}/{folder_name}" if current_folder else folder_name
                if current_folder not in folder_nodes:
                    node = self.file_tree.insert(
                        parent_iid, 'end', text=f'📁 {folder_name}',
                        values=('', ''), open=True, checked=True)
                    folder_nodes[current_folder] = node
                parent_iid = folder_nodes[current_folder]

            _, ext = os.path.splitext(filename)
            sensitive = self._is_sensitive(rel_path)
            display = f"⚠️{filename}" if sensitive else filename
            file_iid = self.file_tree.insert(
                parent_iid, 'end', text=display,
                values=(self._format_size(size), ext.lower()),
                checked=not sensitive)

            self.tree_item_map[file_iid] = (rel_path, full_path, size)
            self.path_map[rel_path] = full_path

        self.tree_count_label.config(text=f"{len(file_list)}개")
        self.status_var.set(f"로드: {len(file_list)}개 — 더블클릭으로 열기")

    def _tree_check_all(self):
        self.file_tree.check_all()

    def _tree_uncheck_all(self):
        self.file_tree.uncheck_all()

    def _tree_check_ext(self, ext_set):
        self.file_tree.uncheck_all()
        for iid, (rp, fp, sz) in self.tree_item_map.items():
            _, ext = os.path.splitext(rp)
            if ext.lower() in ext_set:
                self.file_tree._unchecked.discard(iid)
                self.file_tree._checked.add(iid)
                self.file_tree._update_display(iid)
                self.file_tree._update_parent(iid)

    def _get_checked_files(self):
        return [info for iid, info in self.tree_item_map.items()
                if self.file_tree.is_checked(iid)]

    def _on_source_only_changed(self):
        if hasattr(self, '_last_scan_data'):
            mode, data = self._last_scan_data
            if mode == 'folder':
                self._do_folder_scan(data)
            elif mode == 'vs':
                self._filter_and_populate(data)

    # ──────────── 스캔 ────────────

    def scan_folder(self):
        project = self.project_path.get()
        if not project:
            messagebox.showwarning("경고", "폴더를 선택하세요!")
            return
        self.status_var.set("스캔 중...")
        self.root.update()
        self._last_scan_data = ('folder', project)
        self._do_folder_scan(project)

    def _do_folder_scan(self, path):
        files = []
        max_size = self.max_file_size.get() * 1024
        for root_dir, dirs, fnames in os.walk(path):
            dirs[:] = [d for d in dirs if not self._should_exclude(root_dir, d)]
            for f in fnames:
                if self._should_exclude(root_dir, f) or not self._is_target_file(f):
                    continue
                full_path = os.path.join(root_dir, f)
                rel_path = os.path.relpath(full_path, path)
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    continue
                if size <= max_size:
                    files.append((rel_path, full_path, size))
        self._populate_tree(files, path)

    def _detect_vs_projects(self, folder):
        sln_files, proj_files = [], []
        try:
            entries = os.listdir(folder)
        except PermissionError:
            return sln_files, proj_files
        for entry in entries:
            full = os.path.join(folder, entry)
            if os.path.isfile(full):
                if entry.endswith('.sln'):
                    sln_files.append(full)
                for ext in self.vs_project_extensions:
                    if entry.endswith(ext):
                        proj_files.append(full)
            elif os.path.isdir(full) and not self._should_exclude(folder, entry):
                try:
                    for sub in os.listdir(full):
                        sub_full = os.path.join(full, sub)
                        if os.path.isfile(sub_full):
                            for ext in self.vs_project_extensions:
                                if sub.endswith(ext):
                                    proj_files.append(sub_full)
                except PermissionError:
                    pass
        return sln_files, proj_files

    def _parse_sln(self, sln_path):
        sln_dir = os.path.dirname(sln_path)
        paths = []
        pat = re.compile(r'Project\("[^"]*"\)\s*=\s*"[^"]*"\s*,\s*"([^"]+)"\s*,\s*"[^"]*"')
        content = self._read_file(sln_path) or ""
        for m in pat.finditer(content):
            full = os.path.normpath(os.path.join(sln_dir, m.group(1).replace('\\', os.sep)))
            if os.path.isfile(full):
                for ext in self.vs_project_extensions:
                    if full.endswith(ext):
                        paths.append(full)
                        break
        return paths

    def _parse_project(self, proj_path):
        proj_dir = os.path.dirname(proj_path)
        sources = []
        try:
            tree = ET.parse(proj_path)
            root_el = tree.getroot()
        except ET.ParseError:
            return sources
        ns = ''
        m = re.match(r'\{(.*)\}', root_el.tag)
        if m:
            ns = m.group(1)
        for tag in ['ClCompile', 'ClInclude', 'Compile', 'Content', 'None',
                     'Page', 'ApplicationDefinition', 'Resource', 'EmbeddedResource']:
            elems = root_el.iter(f'{{{ns}}}{tag}') if ns else root_el.iter(tag)
            for el in elems:
                inc = el.get('Include')
                if inc:
                    full = os.path.normpath(os.path.join(proj_dir, inc.replace('\\', os.sep)))
                    if os.path.isfile(full):
                        sources.append(full)
        if root_el.get('Sdk') and not sources:
            sources = self._glob_sdk(proj_dir, proj_path)
        return sources

    def _glob_sdk(self, proj_dir, proj_path):
        files = []
        ext_map = {'.csproj': {'.cs'}, '.fsproj': {'.fs'}, '.vbproj': {'.vb'}}
        exts = ext_map.get(os.path.splitext(proj_path)[1], {'.cs', '.cpp', '.h'})
        skip = {'bin', 'obj', 'Debug', 'Release', '.vs', 'x64', 'x86',
                'packages', 'node_modules', '.git'}
        for root_dir, dirs, fnames in os.walk(proj_dir):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in fnames:
                if os.path.splitext(f)[1].lower() in exts:
                    files.append(os.path.join(root_dir, f))
        return files

    def scan_vs_project(self):
        project = self.project_path.get()
        if not project:
            messagebox.showwarning("경고", "폴더를 선택하세요!")
            return
        self.status_var.set("VS 프로젝트 분석 중...")
        self.root.update()
        slns, direct_projs = self._detect_vs_projects(project)
        all_proj = set()
        for sln in slns:
            for p in self._parse_sln(sln):
                all_proj.add(p)
        for p in direct_projs:
            all_proj.add(p)
        if not all_proj:
            messagebox.showinfo("미발견", "VS 프로젝트 파일을 찾지 못했습니다.")
            return
        all_src = set()
        for proj in all_proj:
            for src in self._parse_project(proj):
                all_src.add(os.path.normpath(src))
        self._last_scan_data = ('vs', (project, all_src))
        self._filter_and_populate((project, all_src))

    def _filter_and_populate(self, data):
        project, all_src = data
        max_size = self.max_file_size.get() * 1024
        exts = self.source_only_extensions if self.source_only.get() else self.all_code_extensions
        result = []
        for full_path in sorted(all_src):
            _, ext = os.path.splitext(full_path)
            if ext.lower() not in exts:
                continue
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue
            if size <= max_size:
                result.append((os.path.relpath(full_path, project), full_path, size))
        self._populate_tree(result, project)

    # ──────────── 합치기 / GitHub ────────────

    def _merge_and_copy(self):
        checked = self._get_checked_files()
        if not checked:
            messagebox.showwarning("경고", "체크된 파일이 없습니다.")
            return
        project = self.project_path.get()
        self.status_var.set(f"합치는 중... ({len(checked)}개)")
        self.root.update()

        r = f"# 프로젝트 스캔 결과\n# 경로: {project}\n"
        r += f"# 시간: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        r += f"# 파일: {len(checked)}개\n\n"
        r += "## 파일 목록\n```\n"
        for rp, fp, sz in checked:
            r += f"  {rp} ({self._format_size(sz)})\n"
        r += "```\n\n"
        r += ("## 수정 시 아래 형식으로 반환해주세요\n```\n"
              "=== FILE: 상대경로/파일명 ===\n"
              "<<<< SEARCH\n원본 코드\n====\n수정 코드\n>>>> REPLACE\n"
              "=== END FILE ===\n```\n\n")
        r += "## 파일 내용\n\n"

        for i, (rp, fp, sz) in enumerate(checked, 1):
            content = self._read_file(fp)
            if content is None:
                content = "[읽기 실패]"
            ext = os.path.splitext(rp)[1].lstrip('.')
            lines = content.split('\n')
            w = len(str(len(lines)))
            numbered = '\n'.join(f"{str(j).rjust(w)}| {line}" for j, line in enumerate(lines, 1))
            r += f"### [{i}/{len(checked)}] 📄 {rp}\n```{ext}\n{numbered}\n```\n\n"

        self.root.clipboard_clear()
        self.root.clipboard_append(r)
        tokens = len(r) // 4
        self.merge_info_label.config(text=f"✅ {len(checked)}개 | ~{tokens:,}토큰")
        self.status_var.set(f"✅ 복사 완료 ({len(checked)}개, ~{tokens:,}토큰)")
        messagebox.showinfo("복사 완료",
                            f"{len(checked)}개 파일 복사됨!\n~{tokens:,}토큰 | {len(r):,}자\n\n"
                            f"AI 채팅에 Ctrl+V\n\n💡 AI 수정결과 → Diff 적용 탭에 붙여넣기 → 멀티파일 적용")

    def _upload_to_github(self):
        repo_name = self.repo_name_var.get().strip()
        if not repo_name:
            messagebox.showwarning("경고", "리포명을 입력하세요.")
            return
        if not re.match(r'^[a-zA-Z0-9._-]+$', repo_name):
            messagebox.showwarning("경고", "리포명: 영문/숫자/하이픈/밑줄/점만")
            return

        checked = self._get_checked_files()
        if not checked:
            messagebox.showwarning("경고", "업로드할 파일이 없습니다.")
            return

        # 민감파일 확인
        sensitive = [rp for rp, fp, sz in checked if self._is_sensitive(rp)]
        if sensitive:
            msg = "⚠ 민감 파일 감지:\n" + "\n".join(f"  • {s}" for s in sensitive[:10])
            if len(sensitive) > 10:
                msg += f"\n  ... 외 {len(sensitive)-10}개"
            result = messagebox.askyesnocancel("민감 파일", msg + "\n\n제외하고 업로드?")
            if result is None:
                return
            if result:
                checked = [(rp, fp, sz) for rp, fp, sz in checked if not self._is_sensitive(rp)]
                if not checked:
                    messagebox.showinfo("알림", "제외 후 파일 없음")
                    return

        self.log_text.delete('1.0', tk.END)
        self.notebook.select(2)  # GitHub 탭

        # 사전 체크
        for check_fn, name, help_msg in [
            (self.uploader.check_git, "git", "설치: https://git-scm.com/"),
            (self.uploader.check_gh_cli, "gh CLI", "설치: https://cli.github.com/"),
            (self.uploader.check_gh_auth, "gh 인증", "실행: gh auth login"),
        ]:
            if not check_fn():
                self.append_log(f"❌ {name} 확인 실패 — {help_msg}")
                messagebox.showerror("오류", f"{name} 필요\n{help_msg}")
                return
            self.append_log(f"✅ {name} 확인")

        self.gh_upload_btn.config(state='disabled', text="⏳ 업로드 중...", bg='#6c7086')
        self.progress_var.set(0)

        def do_upload():
            def progress_cb(pct, msg):
                self.root.after(0, lambda: self.progress_var.set(pct))
                self.root.after(0, lambda: self.status_var.set(f"⏳ {msg}"))

            success, result = self.uploader.create_and_push(
                files=checked, project_path=self.project_path.get(),
                repo_name=repo_name, private=self.private_var.get(),
                description=f"ProjectScan ({len(checked)} files)",
                progress_cb=progress_cb)

            def on_done():
                self.gh_upload_btn.config(state='normal', text="🚀 GitHub 업로드", bg='#f38ba8')
                if success:
                    self.progress_var.set(100)
                    self.gh_status_label.config(text=f"✅ {result}", fg='#a6e3a1')
                    self.status_var.set(f"✅ 업로드 완료: {result}")
                    if messagebox.askyesno("성공", f"📎 {result}\n\nURL을 클립보드에 복사?"):
                        self.root.clipboard_clear()
                        self.root.clipboard_append(result)
                        self.status_var.set(f"✅ URL 복사됨: {result}")
                else:
                    self.progress_var.set(0)
                    self.gh_status_label.config(text="❌ 실패", fg='#f38ba8')
                    messagebox.showerror("실패", f"오류: {result}")

            self.root.after(0, on_done)

        threading.Thread(target=do_upload, daemon=True).start()


# ════════════════════════════════════════════════════════════════
#  메인 실행
# ════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    root = tk.Tk()
    app = ProjectScan(root)
    root.mainloop()
