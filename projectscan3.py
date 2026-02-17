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


# ════════════════════════════════════════════════════════════
#  1. CheckboxTreeview
# ════════════════════════════════════════════════════════════

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
        (self._checked if checked else self._unchecked).add(item)
        self._update_display(item)
        return item

    def toggle_check(self, item):
        was = item in self._checked
        for node in [item] + self._all_children(item):
            self._checked.discard(node); self._unchecked.discard(node)
            (self._unchecked if was else self._checked).add(node)
            self._update_display(node)
        self._update_parent(item)

    def is_checked(self, item): return item in self._checked

    def _all_children(self, item):
        ch = []
        for c in self.get_children(item):
            ch.append(c); ch.extend(self._all_children(c))
        return ch

    def _update_parent(self, item):
        p = self.parent(item)
        if not p: return
        kids = self.get_children(p)
        n = sum(1 for c in kids if c in self._checked)
        self._checked.discard(p); self._unchecked.discard(p)
        (self._checked if n == len(kids) else self._unchecked).add(p)
        self._update_display(p); self._update_parent(p)

    def _update_display(self, item):
        t = self.item(item, 'text')
        if t[:2] in ('☑ ', '☐ '): t = t[2:]
        self.item(item, text=f"{'☑' if item in self._checked else '☐'} {t}")

    def check_all(self):
        for it in self._all_items():
            self._unchecked.discard(it); self._checked.add(it); self._update_display(it)

    def uncheck_all(self):
        for it in self._all_items():
            self._checked.discard(it); self._unchecked.add(it); self._update_display(it)

    def _all_items(self):
        items = []
        for it in self.get_children(''):
            items.append(it); items.extend(self._all_children(it))
        return items


# ════════════════════════════════════════════════════════════
#  2. CodeEditor
# ════════════════════════════════════════════════════════════

class CodeEditor(tk.Frame):
    KEYWORDS = {
        'vb': r'\b(Public|Private|Protected|Sub|Function|End|If|Then|Else|ElseIf|'
              r'For|Each|Next|While|Do|Loop|Select|Case|With|Try|Catch|Finally|'
              r'Return|Dim|As|New|Class|Module|Imports|Namespace|Inherits|'
              r'Interface|Enum|Property|Get|Set|Shared|Static|Overrides|'
              r'ByVal|ByRef|Optional|Event|Delegate|Of|Is|Nothing|True|False|'
              r'And|Or|Not|AndAlso|OrElse|String|Integer|Long|Double|Boolean|'
              r'Object|Me|MyBase|Handles|Async|Await|Using)\b',
        'cs': r'\b(using|namespace|class|struct|interface|enum|delegate|'
              r'public|private|protected|internal|static|readonly|const|'
              r'abstract|sealed|virtual|override|async|await|'
              r'void|int|long|float|double|decimal|bool|char|string|object|'
              r'var|null|true|false|this|base|new|'
              r'if|else|switch|case|for|foreach|while|do|break|continue|return|'
              r'try|catch|finally|throw|lock|using|yield|in|out|ref)\b',
        'cpp': r'\b(auto|break|case|char|const|continue|default|do|double|else|'
               r'enum|float|for|if|int|long|return|short|sizeof|static|struct|'
               r'switch|typedef|unsigned|void|volatile|while|class|namespace|'
               r'using|public|private|protected|virtual|override|template|'
               r'new|delete|this|throw|try|catch|nullptr|bool|true|false|'
               r'inline|const_cast|dynamic_cast|static_cast|include|define)\b',
        'py': r'\b(False|None|True|and|as|assert|async|await|break|class|continue|'
              r'def|del|elif|else|except|finally|for|from|global|if|import|in|is|'
              r'lambda|not|or|pass|raise|return|try|while|with|yield)\b',
        'default': r'\b(if|else|for|while|return|class|function|var|let|const|'
                   r'import|export|new|this|null|true|false|void|int|string)\b',
    }

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.configure(bg='#1e1e2e')
        self._current_file = None
        self._original_content = ""
        self._modified = False
        self._language = 'default'

        self.header = tk.Frame(self, bg='#181825')
        self.header.pack(fill='x')
        self.file_label = tk.Label(self.header, text="파일을 선택하세요",
                                   font=('맑은 고딕', 10), bg='#181825', fg='#a6adc8',
                                   anchor='w', padx=8, pady=4)
        self.file_label.pack(side='left', fill='x', expand=True)
        self.modified_label = tk.Label(self.header, text="",
                                       font=('맑은 고딕', 9), bg='#181825', fg='#f38ba8', padx=8)
        self.modified_label.pack(side='right')

        ef = tk.Frame(self, bg='#1e1e2e')
        ef.pack(fill='both', expand=True)

        self.line_numbers = tk.Text(ef, width=5, padx=4, pady=8, takefocus=0,
                                    border=0, state='disabled', bg='#181825', fg='#6c7086',
                                    font=('Consolas', 11), relief='flat',
                                    selectbackground='#181825', cursor='arrow')
        self.line_numbers.pack(side='left', fill='y')

        sb = ttk.Scrollbar(ef, orient='vertical')
        sb.pack(side='right', fill='y')

        self.text = tk.Text(ef, wrap='none', font=('Consolas', 11),
                            bg='#1e1e2e', fg='#cdd6f4', insertbackground='#f5e0dc',
                            selectbackground='#45475a', relief='flat',
                            padx=8, pady=8, undo=True, tabs=('4c',))
        self.text.pack(side='left', fill='both', expand=True)
        sb.config(command=self._on_scroll)
        self.text.config(yscrollcommand=self._on_text_scroll)

        hsc = ttk.Scrollbar(self, orient='horizontal', command=self.text.xview)
        hsc.pack(fill='x')
        self.text.config(xscrollcommand=hsc.set)

        for tag, cfg in [
            ('keyword', {'foreground': '#cba6f7'}),
            ('string', {'foreground': '#a6e3a1'}),
            ('comment', {'foreground': '#6c7086', 'font': ('Consolas', 11, 'italic')}),
            ('number', {'foreground': '#fab387'}),
            ('diff_add', {'background': '#1a3a1a', 'foreground': '#a6e3a1'}),
            ('diff_del', {'background': '#3a1a1a', 'foreground': '#f38ba8'}),
            ('current_line', {'background': '#313244'}),
        ]:
            self.text.tag_configure(tag, **cfg)

        self.text.bind('<<Modified>>', self._on_modified)
        self.text.bind('<KeyRelease>', self._on_key)
        self.text.bind('<ButtonRelease-1>', self._update_cur_line)

        self.status = tk.Frame(self, bg='#11111b')
        self.status.pack(fill='x')
        self.pos_label = tk.Label(self.status, text="줄 1, 열 1",
                                  font=('Consolas', 9), bg='#11111b', fg='#6c7086', padx=8)
        self.pos_label.pack(side='right')
        self.lang_label = tk.Label(self.status, text="",
                                   font=('Consolas', 9), bg='#11111b', fg='#89b4fa', padx=8)
        self.lang_label.pack(side='left')

    def _on_scroll(self, *a):
        self.text.yview(*a); self.line_numbers.yview(*a)

    def _on_text_scroll(self, f, l):
        self.line_numbers.yview_moveto(f)

    def _on_modified(self, e=None):
        if self.text.edit_modified():
            self._modified = (self.text.get('1.0', 'end-1c') != self._original_content)
            self.modified_label.config(text="● 수정됨" if self._modified else "")
            self.text.edit_modified(False)

    def _on_key(self, e=None):
        self._update_lines(); self._update_cur_line(); self._update_pos()
        if e and e.keysym not in ('Shift_L', 'Shift_R', 'Control_L', 'Control_R'):
            self._highlight_line()

    def _update_pos(self):
        p = self.text.index(tk.INSERT)
        l, c = p.split('.')
        self.pos_label.config(text=f"줄 {l}, 열 {int(c)+1}")

    def _update_cur_line(self, e=None):
        self.text.tag_remove('current_line', '1.0', 'end')
        ln = self.text.index(tk.INSERT).split('.')[0]
        self.text.tag_add('current_line', f'{ln}.0', f'{ln}.end+1c')
        self.text.tag_lower('current_line')
        self._update_pos()

    def _update_lines(self):
        self.line_numbers.config(state='normal')
        self.line_numbers.delete('1.0', 'end')
        n = int(self.text.index('end-1c').split('.')[0])
        w = max(4, len(str(n))+1)
        self.line_numbers.config(width=w)
        self.line_numbers.insert('1.0', '\n'.join(str(i).rjust(w-1) for i in range(1, n+1)))
        self.line_numbers.config(state='disabled')

    def _detect_lang(self, fp):
        m = {'.vb':'vb','.cs':'cs','.cpp':'cpp','.cxx':'cpp','.cc':'cpp',
             '.c':'cpp','.h':'cpp','.hpp':'cpp','.py':'py'}
        return m.get(os.path.splitext(fp)[1].lower(), 'default')

    def _highlight_all(self):
        content = self.text.get('1.0', 'end-1c')
        for t in ('keyword','string','comment','number'):
            self.text.tag_remove(t, '1.0', 'end')
        if not content.strip(): return
        kw = self.KEYWORDS.get(self._language, self.KEYWORDS['default'])
        for m in re.finditer(kw, content):
            self.text.tag_add('keyword', f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        sp = r'"[^"\n]*"' if self._language == 'vb' else r'(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'
        for m in re.finditer(sp, content):
            self.text.tag_add('string', f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        cp = {"vb": r"'[^\n]*", "py": r"#[^\n]*"}.get(self._language, r'//[^\n]*|/\*[\s\S]*?\*/')
        for m in re.finditer(cp, content):
            self.text.tag_add('comment', f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in re.finditer(r'\b\d+\.?\d*\b', content):
            self.text.tag_add('number', f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    def _highlight_line(self):
        ln = self.text.index(tk.INSERT).split('.')[0]
        ls, le = f"{ln}.0", f"{ln}.end"
        lt = self.text.get(ls, le)
        for t in ('keyword','string','comment','number'):
            self.text.tag_remove(t, ls, le)
        kw = self.KEYWORDS.get(self._language, self.KEYWORDS['default'])
        for m in re.finditer(kw, lt):
            self.text.tag_add('keyword', f"{ln}.{m.start()}", f"{ln}.{m.end()}")
        sp = r'"[^"\n]*"' if self._language == 'vb' else r'(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'
        for m in re.finditer(sp, lt):
            self.text.tag_add('string', f"{ln}.{m.start()}", f"{ln}.{m.end()}")
        cp = {"vb": r"'[^\n]*", "py": r"#[^\n]*"}.get(self._language, r'//[^\n]*')
        for m in re.finditer(cp, lt):
            self.text.tag_add('comment', f"{ln}.{m.start()}", f"{ln}.{m.end()}")
        for m in re.finditer(r'\b\d+\.?\d*\b', lt):
            self.text.tag_add('number', f"{ln}.{m.start()}", f"{ln}.{m.end()}")

    def load_file(self, filepath):
        content = self._read(filepath)
        if content is None: return False
        self._current_file = filepath
        self._original_content = content
        self._modified = False
        self._language = self._detect_lang(filepath)
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', content)
        self.text.edit_modified(False); self.text.edit_reset()
        self.file_label.config(text=f"📄 {os.path.basename(filepath)}")
        self.modified_label.config(text="")
        self.lang_label.config(text=self._language.upper())
        self._update_lines(); self._highlight_all()
        self.text.mark_set(tk.INSERT, '1.0'); self.text.see('1.0')
        self._update_cur_line()
        return True

    def get_content(self): return self.text.get('1.0', 'end-1c')

    def set_content(self, content):
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', content)
        self._update_lines(); self._highlight_all()

    def get_content_with_line_numbers(self):
        c = self.get_content()
        lines = c.split('\n')
        w = len(str(len(lines)))
        return '\n'.join(f"{str(i).rjust(w)}| {l}" for i, l in enumerate(lines, 1))

    def save_file(self):
        if not self._current_file: return False
        try:
            with open(self._current_file, 'w', encoding='utf-8') as f:
                f.write(self.get_content())
            self._original_content = self.get_content()
            self._modified = False
            self.modified_label.config(text="✅ 저장됨")
            self.after(2000, lambda: self.modified_label.config(
                text="" if not self._modified else "● 수정됨"))
            return True
        except Exception as e:
            messagebox.showerror("저장 실패", str(e)); return False

    @property
    def current_file(self): return self._current_file
    @property
    def is_modified(self): return self._modified

    def _read(self, fp):
        for enc in ['utf-8','utf-8-sig','cp949','euc-kr','latin-1']:
            try:
                with open(fp, 'r', encoding=enc) as f: return f.read()
            except (UnicodeDecodeError, UnicodeError): continue
        return None


# ════════════════════════════════════════════════════════════
#  3. MultiFileDiffEngine - 멀티파일 Diff 파싱 & 적용
# ════════════════════════════════════════════════════════════

class MultiFileDiffEngine:
    """
    AI가 반환하는 여러 파일에 걸친 수정사항을 파싱하고 순차 적용.

    지원 형식:
    ──────────────────────────────────────────────
    형식 1) FILE 블록 형식
        === FILE: path/to/file.vb ===
        (내부에 unified diff / SEARCH-REPLACE / 줄범위 / 전체코드)
        === END FILE ===

    형식 2) Unified diff (git diff 스타일)
        --- a/path/to/file.vb
        +++ b/path/to/file.vb
        @@ -10,5 +10,7 @@
        ...

    형식 3) 마크다운 코드블록 + 파일경로
        ### 📄 path/to/file.vb
        ```vb
        (전체 또는 부분 코드)
        ```

    형식 4) SEARCH/REPLACE + 파일 지정
        === FILE: path/to/file.vb ===
        <<<< SEARCH
        old code
        ====
        new code
        >>>> REPLACE
        === END FILE ===
    ──────────────────────────────────────────────
    """

    @classmethod
    def parse_multi_file_diff(cls, diff_text: str) -> list:
        """
        멀티파일 diff를 파싱.
        반환: [{'file': rel_path, 'diff_type': str, 'content': str}, ...]
        """
        blocks = []

        # 방법 1: === FILE: ... === 블록
        file_block_pattern = re.compile(
            r'===\s*FILE:\s*(.+?)\s*===\s*\n(.*?)\n\s*===\s*END\s*FILE\s*===',
            re.DOTALL | re.IGNORECASE
        )
        for m in file_block_pattern.finditer(diff_text):
            filepath = m.group(1).strip().strip('"\'`')
            content = m.group(2).strip()
            dtype = cls._detect_diff_type(content)
            blocks.append({'file': cls._normalize_path(filepath),
                           'diff_type': dtype, 'content': content})

        if blocks:
            return blocks

        # 방법 2: git unified diff (--- a/ ... +++ b/ ...)
        git_diff_pattern = re.compile(
            r'---\s+a/(.+?)\n\+\+\+\s+b/(.+?)\n((?:@@.*?(?:\n|$)(?:[ +\-].*?\n|\\.*?\n)*)+)',
            re.DOTALL
        )
        for m in git_diff_pattern.finditer(diff_text):
            filepath = m.group(2).strip()
            content = f"--- a/{m.group(1)}\n+++ b/{filepath}\n{m.group(3)}"
            blocks.append({'file': cls._normalize_path(filepath),
                           'diff_type': 'unified', 'content': content})

        if blocks:
            return blocks

        # 방법 3: 마크다운 ### 📄 파일명 + 코드블록
        md_pattern = re.compile(
            r'###?\s*📄?\s*(.+?)\s*\n\s*```\w*\n(.*?)```',
            re.DOTALL
        )
        for m in md_pattern.finditer(diff_text):
            filepath = m.group(1).strip().strip('`*')
            content = m.group(2).strip()
            dtype = cls._detect_diff_type(content)
            if dtype == 'unknown':
                dtype = 'full_replace'
            blocks.append({'file': cls._normalize_path(filepath),
                           'diff_type': dtype, 'content': content})

        if blocks:
            return blocks

        # 방법 4: 파일경로 헤더 + 다양한 형식
        header_pattern = re.compile(
            r'(?:^|\n)(?:파일|File|FILE)[\s:：]+(.+?)(?:\n|$)(.*?)(?=(?:\n(?:파일|File|FILE)[\s:：])|$)',
            re.DOTALL | re.IGNORECASE
        )
        for m in header_pattern.finditer(diff_text):
            filepath = m.group(1).strip().strip('"\'`')
            content = m.group(2).strip()
            if content:
                dtype = cls._detect_diff_type(content)
                blocks.append({'file': cls._normalize_path(filepath),
                               'diff_type': dtype, 'content': content})

        return blocks

    @staticmethod
    def _normalize_path(path: str) -> str:
        """경로 정규화"""
        path = path.replace('\\', '/')
        # 앞의 a/ b/ 제거
        if path.startswith(('a/', 'b/')):
            path = path[2:]
        return path.strip().strip('`').strip('"').strip("'")

    @staticmethod
    def _detect_diff_type(content: str) -> str:
        if re.search(r'^@@\s*-\d+', content, re.MULTILINE):
            return 'unified'
        if re.search(r'<{3,4}\s*SEARCH', content, re.IGNORECASE):
            return 'search_replace'
        if re.search(r'(?:REPLACE|MODIFY|UPDATE|변경|수정)\s+(?:줄|line|L)?\s*\d+\s*[-~]\s*\d+',
                      content, re.IGNORECASE):
            return 'line_range'
        if re.search(r'```\w*\n', content):
            return 'full_replace'
        # 코드처럼 보이면 전체 교체
        lines = content.strip().split('\n')
        if len(lines) > 3:
            return 'full_replace'
        return 'unknown'

    @classmethod
    def apply_single_diff(cls, original: str, diff_block: dict) -> tuple:
        """
        단일 파일에 diff 적용.
        반환: (new_content, message) or (None, error_message)
        """
        dtype = diff_block['diff_type']
        content = diff_block['content']

        if dtype == 'unified':
            return cls._apply_unified(original, content)
        elif dtype == 'search_replace':
            return cls._apply_search_replace(original, content)
        elif dtype == 'line_range':
            return cls._apply_line_range(original, content)
        elif dtype == 'full_replace':
            return cls._apply_full_replace(original, content)
        else:
            # 자동 감지 재시도
            for method in [cls._apply_unified, cls._apply_search_replace,
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
            rm, add = [], []
            for dl in h['lines']:
                if dl.startswith('-'):   rm.append(dl[1:])
                elif dl.startswith('+'): add.append(dl[1:])
                elif dl.startswith(' '): rm.append(dl[1:]); add.append(dl[1:])
            end = start + len(rm)
            if end <= len(lines):
                lines[start:end] = add
                changes.append(f"줄 {h['start']}: -{len([l for l in h['lines'] if l.startswith('-')])} "
                               f"+{len([l for l in h['lines'] if l.startswith('+')])}")
        return '\n'.join(lines), '\n'.join(changes) if changes else "변경 적용"

    @staticmethod
    def _apply_search_replace(original: str, diff_text: str) -> tuple:
        pattern = re.compile(
            r'<{3,4}\s*SEARCH\s*\n(.*?)\n={3,4}\s*\n(.*?)\n>{3,4}\s*REPLACE',
            re.DOTALL
        )
        matches = list(pattern.finditer(diff_text))
        if not matches:
            pattern2 = re.compile(
                r'```\s*(?:찾을|search|before)[^\n]*\n(.*?)```\s*\n'
                r'```\s*(?:바꿀|replace|after)[^\n]*\n(.*?)```',
                re.DOTALL | re.IGNORECASE
            )
            matches = list(pattern2.finditer(diff_text))
        if not matches:
            return None, "SEARCH/REPLACE 패턴 없음"
        result = original
        changes = []
        for m in matches:
            search, replace = m.group(1).strip(), m.group(2).strip()
            if search in result:
                result = result.replace(search, replace, 1)
                changes.append(f"교체: '{search[:40]}...'")
            else:
                norm = re.sub(r'\s+', r'\\s+', re.escape(search.strip()))
                match = re.search(norm, result)
                if match:
                    result = result[:match.start()] + replace + result[match.end():]
                    changes.append(f"교체(공백무시): '{search[:30]}...'")
                else:
                    changes.append(f"⚠ 미발견: '{search[:40]}...'")
        return (result, '\n'.join(changes)) if result != original else (None, '\n'.join(changes))

    @staticmethod
    def _apply_line_range(original: str, diff_text: str) -> tuple:
        lines = original.split('\n')
        pattern = re.compile(
            r'(?:REPLACE|MODIFY|UPDATE|변경|수정)\s+(?:줄|line|L)?\s*(\d+)\s*[-~]\s*(\d+)\s*:?\s*\n'
            r'(.*?)(?:\nEND|\n---|\Z)',
            re.IGNORECASE | re.DOTALL
        )
        matches = sorted(pattern.finditer(diff_text),
                         key=lambda m: int(m.group(1)), reverse=True)
        if not matches:
            return None, "줄번호 범위 패턴 없음"
        changes = []
        for m in matches:
            s, e = int(m.group(1))-1, int(m.group(2))
            nl = m.group(3).rstrip().split('\n')
            if s < len(lines) and e <= len(lines):
                lines[s:e] = nl
                changes.append(f"줄 {s+1}-{e}: {e-s}줄→{len(nl)}줄")
        return '\n'.join(lines), '\n'.join(changes)

    @staticmethod
    def _apply_full_replace(original: str, diff_text: str) -> tuple:
        m = re.search(r'```\w*\n(.*?)```', diff_text, re.DOTALL)
        if m:
            return m.group(1).rstrip(), "전체 코드 교체"
        # 코드블록 없으면 전체를 코드로 간주
        stripped = diff_text.strip()
        if len(stripped.split('\n')) > 3:
            return stripped, "전체 코드 교체(블록 없음)"
        return None, "코드 블록 없음"


# ════════════════════════════════════════════════════════════
#  4. MultiFileApplyDialog - 멀티파일 적용 대화상자
# ════════════════════════════════════════════════════════════

class MultiFileApplyDialog:
    """여러 파일의 diff를 미리보기하고 순차 적용하는 대화상자"""

    def __init__(self, parent, diff_blocks, file_resolver, on_complete=None):
        """
        diff_blocks: [{'file': path, 'diff_type': str, 'content': str}, ...]
        file_resolver: fn(rel_path) -> full_path or None
        on_complete: fn(results) 콜백
        """
        self.parent = parent
        self.diff_blocks = diff_blocks
        self.file_resolver = file_resolver
        self.on_complete = on_complete
        self.results = []  # [{'file', 'status', 'message', 'backup'}, ...]

        self._build_ui()

    def _build_ui(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title(f"🔧 멀티파일 Diff 적용 — {len(self.diff_blocks)}개 파일")
        self.win.geometry("900x650")
        self.win.configure(bg='#1e1e2e')
        self.win.grab_set()

        # ── 상단 요약 ──
        summary = tk.Frame(self.win, bg='#181825')
        summary.pack(fill='x')
        tk.Label(summary, text=f"📦 {len(self.diff_blocks)}개 파일에 대한 수정사항",
                 font=('맑은 고딕', 12, 'bold'), bg='#181825', fg='#cdd6f4',
                 padx=12, pady=8).pack(side='left')

        # ── 메인: 좌(파일목록) / 우(미리보기) ──
        main = tk.PanedWindow(self.win, orient=tk.HORIZONTAL,
                              bg='#1e1e2e', sashwidth=4)
        main.pack(fill='both', expand=True, padx=8, pady=4)

        # 좌: 파일 목록
        left = tk.Frame(main, bg='#1e1e2e')
        main.add(left, width=280)

        tk.Label(left, text="파일 목록", font=('맑은 고딕', 10, 'bold'),
                 bg='#1e1e2e', fg='#cdd6f4', pady=4).pack(fill='x')

        list_frame = tk.Frame(left, bg='#313244')
        list_frame.pack(fill='both', expand=True)

        self.file_listbox = tk.Listbox(list_frame, font=('Consolas', 10),
                                       bg='#313244', fg='#cdd6f4',
                                       selectbackground='#585b70', relief='flat')
        self.file_listbox.pack(fill='both', expand=True)
        self.file_listbox.bind('<<ListboxSelect>>', self._on_select)

        # 파일별 상태 아이콘
        self.file_status = {}  # index -> status
        for i, block in enumerate(self.diff_blocks):
            fname = os.path.basename(block['file'])
            full = self.file_resolver(block['file'])
            status_icon = "📄" if full and os.path.isfile(full) else "⚠️"
            self.file_listbox.insert(tk.END,
                                     f" {status_icon} {block['file']}  [{block['diff_type']}]")
            self.file_status[i] = 'pending'

        # 우: 미리보기
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

        # ── 하단 버튼 ──
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

        # 결과 표시
        self.result_label = tk.Label(self.win, text="",
                                     font=('맑은 고딕', 10), bg='#1e1e2e', fg='#a6e3a1',
                                     anchor='w', padx=12, pady=4)
        self.result_label.pack(fill='x')

        # 첫 번째 파일 자동 선택
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
        self.preview_label.config(
            text=f"📄 {block['file']}  |  형식: {block['diff_type']}  |  "
                 f"{'파일존재 ✅' if full_path and os.path.isfile(full_path) else '파일미발견 ⚠️'}")

        self.preview_text.config(state='normal')
        self.preview_text.delete('1.0', tk.END)

        if full_path and os.path.isfile(full_path):
            # 원본 읽기
            original = self._read_file(full_path)
            if original is None:
                self.preview_text.insert(tk.END, "파일 읽기 실패\n", 'del')
                return

            # diff 적용 시도
            new_content, msg = MultiFileDiffEngine.apply_single_diff(original, block)

            if new_content is not None:
                # unified diff 표시
                orig_lines = original.split('\n')
                new_lines = new_content.split('\n')
                diff_lines = list(difflib.unified_diff(
                    orig_lines, new_lines,
                    fromfile=f'원본: {block["file"]}',
                    tofile=f'수정: {block["file"]}',
                    lineterm=''
                ))

                self.preview_text.insert(tk.END, f"✅ 적용 가능: {msg}\n\n", 'info')

                for line in diff_lines:
                    if line.startswith('+++') or line.startswith('---') or line.startswith('@@'):
                        self.preview_text.insert(tk.END, line + '\n', 'hdr')
                    elif line.startswith('+'):
                        self.preview_text.insert(tk.END, line + '\n', 'add')
                    elif line.startswith('-'):
                        self.preview_text.insert(tk.END, line + '\n', 'del')
                    else:
                        self.preview_text.insert(tk.END, line + '\n')

                # 변경 통계
                added = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
                removed = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))
                self.preview_text.insert(tk.END,
                                         f"\n📊 +{added}줄 추가, -{removed}줄 삭제\n", 'info')
            else:
                self.preview_text.insert(tk.END, f"❌ 적용 불가: {msg}\n", 'del')
        else:
            self.preview_text.insert(tk.END,
                                     f"⚠️ 파일을 찾을 수 없습니다: {block['file']}\n\n", 'del')
            self.preview_text.insert(tk.END, "Diff 내용:\n", 'info')
            self.preview_text.insert(tk.END, block['content'] + '\n')

        self.preview_text.config(state='disabled')

    def _apply_all(self):
        """모든 파일에 diff 적용"""
        if not messagebox.askyesno("확인",
                                   f"{len(self.diff_blocks)}개 파일에 수정을 적용합니다.\n"
                                   f"각 파일에 .bak 백업이 생성됩니다.\n\n계속할까요?",
                                   parent=self.win):
            return

        self.results = []
        success_count = 0
        fail_count = 0

        for i, block in enumerate(self.diff_blocks):
            result = self._apply_one(i, block)
            self.results.append(result)
            if result['status'] == 'success':
                success_count += 1
            else:
                fail_count += 1
            # 리스트 업데이트
            self._update_list_item(i, result['status'])

        msg = f"✅ 성공: {success_count}  ❌ 실패: {fail_count}"
        self.result_label.config(text=msg,
                                 fg='#a6e3a1' if fail_count == 0 else '#f9e2af')

        if self.on_complete:
            self.on_complete(self.results)

        messagebox.showinfo("적용 완료", msg, parent=self.win)

    def _apply_selected(self):
        """선택된 파일만 적용"""
        sel = self.file_listbox.curselection()
        if not sel:
            messagebox.showwarning("경고", "파일을 선택하세요.", parent=self.win)
            return

        idx = sel[0]
        block = self.diff_blocks[idx]
        result = self._apply_one(idx, block)
        self._update_list_item(idx, result['status'])

        if result['status'] == 'success':
            self.result_label.config(text=f"✅ {result['file']}: {result['message']}",
                                     fg='#a6e3a1')
        else:
            self.result_label.config(text=f"❌ {result['file']}: {result['message']}",
                                     fg='#f38ba8')

    def _apply_one(self, index: int, block: dict) -> dict:
        """단일 파일에 diff 적용 + 저장"""
        full_path = self.file_resolver(block['file'])
        if not full_path or not os.path.isfile(full_path):
            return {'file': block['file'], 'status': 'fail',
                    'message': '파일 미발견', 'backup': None}

        original = self._read_file(full_path)
        if original is None:
            return {'file': block['file'], 'status': 'fail',
                    'message': '읽기 실패', 'backup': None}

        new_content, msg = MultiFileDiffEngine.apply_single_diff(original, block)
        if new_content is None:
            return {'file': block['file'], 'status': 'fail',
                    'message': msg, 'backup': None}

        # 백업
        backup_path = full_path + '.bak'
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(original)
        except Exception:
            backup_path = None

        # 저장
        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return {'file': block['file'], 'status': 'success',
                    'message': msg, 'backup': backup_path}
        except Exception as e:
            return {'file': block['file'], 'status': 'fail',
                    'message': str(e), 'backup': backup_path}

    def _update_list_item(self, index, status):
        """리스트 아이템의 상태 아이콘 업데이트"""
        block = self.diff_blocks[index]
        icon = {'success': '✅', 'fail': '❌', 'pending': '📄'}.get(status, '📄')
        self.file_listbox.delete(index)
        self.file_listbox.insert(index,
                                 f" {icon} {block['file']}  [{block['diff_type']}]")
        # 색상
        if status == 'success':
            self.file_listbox.itemconfig(index, fg='#a6e3a1')
        elif status == 'fail':
            self.file_listbox.itemconfig(index, fg='#f38ba8')

    @staticmethod
    def _read_file(fp):
        for enc in ['utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin-1']:
            try:
                with open(fp, 'r', encoding=enc) as f: return f.read()
            except (UnicodeDecodeError, UnicodeError): continue
        return None


# ════════════════════════════════════════════════════════════
#  5. GitHubUploader
# ════════════════════════════════════════════════════════════

class GitHubUploader:
    def __init__(self, log_callback=None):
        self.log = log_callback or print

    def check_git(self):
        try: return subprocess.run(['git','--version'], capture_output=True, timeout=10).returncode == 0
        except: return False

    def check_gh_cli(self):
        try: return subprocess.run(['gh','--version'], capture_output=True, timeout=10).returncode == 0
        except: return False

    def check_gh_auth(self):
        try: return subprocess.run(['gh','auth','status'], capture_output=True, timeout=10).returncode == 0
        except: return False

    def run_cmd(self, cmd, cwd=None):
        self.log(f"  > {' '.join(cmd)}")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                               timeout=60, encoding='utf-8', errors='replace')
            if r.stdout.strip(): self.log(f"    {r.stdout.strip()}")
            if r.returncode != 0 and r.stderr.strip(): self.log(f"    ⚠ {r.stderr.strip()}")
            return r
        except Exception as e:
            self.log(f"    ❌ {e}"); return None

    def create_and_push(self, files, project_path, repo_name,
                        private=True, description="", progress_cb=None):
        tmp = os.path.join(tempfile.gettempdir(), f'projectscan_{repo_name}')
        try:
            if os.path.exists(tmp): shutil.rmtree(tmp)
            os.makedirs(tmp)
            if progress_cb: progress_cb(10, "파일 복사 중...")
            for rp, fp, sz in files:
                d = os.path.join(tmp, rp)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(fp, d)
            with open(os.path.join(tmp, '.gitignore'), 'w') as f:
                f.write("bin/\nobj/\n.vs/\n*.exe\n*.dll\n*.pdb\n*.user\n*.suo\n*.env\n")
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            with open(os.path.join(tmp, 'README.md'), 'w', encoding='utf-8') as f:
                f.write(f"# {repo_name}\n\nUploaded via ProjectScan ({now})\nFiles: {len(files)}\n")
            if progress_cb: progress_cb(30, "git init...")
            self.run_cmd(['git','init'], cwd=tmp)
            self.run_cmd(['git','branch','-M','main'], cwd=tmp)
            self.run_cmd(['git','add','.'], cwd=tmp)
            self.run_cmd(['git','commit','-m',f'Initial commit - {len(files)} files'], cwd=tmp)
            if progress_cb: progress_cb(50, "GitHub 리포 생성...")
            vis = '--private' if private else '--public'
            cmd = ['gh','repo','create',repo_name,vis,'--source=.','--push']
            if description: cmd.extend(['--description', description])
            r = self.run_cmd(cmd, cwd=tmp)
            if r and r.returncode == 0:
                url = ""
                for line in (r.stdout+r.stderr).split('\n'):
                    urls = re.findall(r'https://github\.com/[^\s]+', line)
                    if urls: url = urls[0]; break
                if not url:
                    api = self.run_cmd(['gh','repo','view',repo_name,'--json','url'], cwd=tmp)
                    if api and api.returncode == 0:
                        try: url = json.loads(api.stdout).get('url','')
                        except: pass
                if progress_cb: progress_cb(100, "완료!")
                return True, url
            return False, r.stderr if r else "알 수 없는 오류"
        except Exception as e:
            return False, str(e)
        finally:
            try:
                if os.path.exists(tmp): shutil.rmtree(tmp)
            except: pass


# ════════════════════════════════════════════════════════════
#  6. ProjectScan 메인 앱
# ════════════════════════════════════════════════════════════

class ProjectScan:
    def __init__(self, root):
        self.root = root
        self.root.title("📂 ProjectScan Pro — AI 멀티파일 코드 수정 워크스테이션")
        self.root.geometry("1350x950")
        self.root.configure(bg="#1e1e2e")
        self.root.minsize(1000, 700)

        self.project_path = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="프로젝트 폴더를 선택하세요")
        self.max_file_size = tk.IntVar(value=100)
        self.source_only = tk.BooleanVar(value=False)
        self.attach_file = tk.BooleanVar(value=True)
        self.attach_checked = tk.BooleanVar(value=False)

        self.tree_item_map = {}
        # rel_path → full_path 역매핑 (멀티파일 diff에서 사용)
        self.path_map = {}

        self.uploader = GitHubUploader(log_callback=self.append_log)

        self.source_only_extensions = {
            '.c','.cpp','.cxx','.cc','.h','.hpp','.hxx','.inl',
            '.cs','.vb','.fs','.fsi','.fsx',
            '.py','.java','.go','.rs','.rb','.php',
            '.js','.jsx','.ts','.tsx','.swift','.kt','.scala','.sql',
        }
        self.all_code_extensions = {
            '.c','.cpp','.cxx','.cc','.h','.hpp','.hxx','.inl',
            '.cs','.vb','.fs','.fsi','.fsx',
            '.xaml','.cshtml','.razor','.aspx',
            '.py','.java','.go','.rs','.rb','.php',
            '.js','.jsx','.ts','.tsx','.vue','.svelte',
            '.html','.css','.scss','.less',
            '.swift','.kt','.scala','.r',
            '.sql','.sh','.bash','.bat','.cmd','.ps1',
            '.json','.yaml','.yml','.toml','.ini','.cfg',
            '.xml','.md','.txt','.rc','.def','.idl',
            '.sln','.vcxproj','.csproj','.vbproj','.fsproj',
        }
        self.default_excludes = [
            'node_modules','.git','__pycache__','.vs','.vscode','.idea',
            'bin','obj','x64','x86','ARM','ARM64',
            'Debug','Release','RelWithDebInfo','MinSizeRel',
            'ipch','.nuget','packages','TestResults',
            'dist','build','out','.next','.venv','venv','env',
            '*.pyc','*.pyo','*.exe','*.dll','*.so','*.dylib',
            '*.pdb','*.ilk','*.obj','*.o','*.lib','*.exp','*.idb',
            '*.tlog','*.recipe','*.cache','*.log',
            '*.suo','*.user','*.ncb','*.sdf','*.db','*.opendb',
            '*.ipch','*.aps',
            '*.jpg','*.jpeg','*.png','*.gif','*.ico','*.svg','*.bmp',
            '*.mp3','*.mp4','*.avi','*.mov','*.pdf',
            '*.zip','*.tar','*.gz','*.rar','*.7z',
            '*.lock','package-lock.json','yarn.lock',
            '*.min.js','*.min.css','*.map',
            '.DS_Store','Thumbs.db','*.bak',
            '*.resources','*.resx','*.props','*.targets',
        ]
        self.sensitive_patterns = [
            '*.env','.env','.env.*','appsettings.Development.json',
            'secrets.json','credentials.*',
            '*password*','*secret*','*token*','*apikey*',
            '*.pem','*.key','*.pfx','*.p12',
            'id_rsa','id_rsa.*','id_ed25519','id_ed25519.*',
        ]
        self.vs_project_extensions = ['.vcxproj','.csproj','.vbproj','.fsproj']

        self.setup_styles()
        self.create_widgets()

    def setup_styles(self):
        s = ttk.Style(); s.theme_use('clam')
        s.configure('Title.TLabel', font=('맑은 고딕',14,'bold'), foreground='#cdd6f4', background='#1e1e2e')
        s.configure('Info.TLabel', font=('맑은 고딕',9), foreground='#a6adc8', background='#1e1e2e')
        s.configure('Status.TLabel', font=('맑은 고딕',10), foreground='#a6e3a1', background='#1e1e2e')
        s.configure('TCheckbutton', font=('맑은 고딕',9), foreground='#cdd6f4', background='#1e1e2e')
        s.configure('Custom.Treeview', background='#313244', foreground='#cdd6f4',
                    fieldbackground='#313244', font=('Consolas',10), rowheight=20)
        s.configure('Custom.Treeview.Heading', background='#45475a', foreground='#cdd6f4',
                    font=('맑은 고딕',9,'bold'))
        s.map('Custom.Treeview', background=[('selected','#585b70')])

    # ════════════════════ UI 생성 ════════════════════

    def create_widgets(self):
        # ── 툴바 ──
        toolbar = tk.Frame(self.root, bg='#181825')
        toolbar.pack(fill='x')

        tk.Button(toolbar, text="📁 폴더", font=('맑은 고딕',9), bg='#45475a', fg='#cdd6f4',
                  relief='flat', padx=8, pady=4, command=self.select_folder).pack(side='left', padx=2, pady=3)
        self.folder_label = tk.Label(toolbar, text="선택되지 않음", font=('맑은 고딕',9),
                                     bg='#181825', fg='#a6adc8')
        self.folder_label.pack(side='left', padx=5)
        tk.Button(toolbar, text="🔍 폴더스캔", font=('맑은 고딕',9), bg='#89b4fa', fg='#1e1e2e',
                  relief='flat', padx=8, pady=4, command=self.scan_folder).pack(side='left', padx=2, pady=3)
        tk.Button(toolbar, text="🏗️ VS스캔", font=('맑은 고딕',9), bg='#f38ba8', fg='#1e1e2e',
                  relief='flat', padx=8, pady=4, command=self.scan_vs_project).pack(side='left', padx=2, pady=3)
        ttk.Checkbutton(toolbar, text="소스Only", variable=self.source_only,
                        style='TCheckbutton', command=self.on_source_only_changed).pack(side='left', padx=8)
        tk.Label(toolbar, text="Max(KB):", font=('맑은 고딕',9), bg='#181825', fg='#a6adc8').pack(side='left')
        tk.Spinbox(toolbar, from_=10, to=500, width=4, textvariable=self.max_file_size,
                   font=('Consolas',9), bg='#313244', fg='#cdd6f4').pack(side='left', padx=2)
        self.vs_info_label = tk.Label(toolbar, text="", font=('맑은 고딕',9),
                                      bg='#181825', fg='#f38ba8')
        self.vs_info_label.pack(side='right', padx=8)

        # ── 메인 3단 분할 ──
        self.main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                                        bg='#1e1e2e', sashwidth=4)
        self.main_pane.pack(fill='both', expand=True, padx=4, pady=4)

        # ═══ 좌: 트리뷰 ═══
        left = tk.Frame(self.main_pane, bg='#1e1e2e')
        self.main_pane.add(left, width=260)

        th = tk.Frame(left, bg='#181825')
        th.pack(fill='x')
        tk.Label(th, text="📁 파일트리", font=('맑은 고딕',9,'bold'), bg='#181825',
                 fg='#cdd6f4', padx=6, pady=3).pack(side='left')
        self.tree_count_label = tk.Label(th, text="", font=('맑은 고딕',8),
                                         bg='#181825', fg='#6c7086')
        self.tree_count_label.pack(side='right', padx=4)

        tb = tk.Frame(left, bg='#1e1e2e'); tb.pack(fill='x', pady=2)
        for txt, cmd in [("✅All",self.tree_check_all),("⬜None",self.tree_uncheck_all),
            (".c/.cpp",lambda:self.tree_check_by_ext({'.c','.cpp','.cxx','.cc'})),
            (".h",lambda:self.tree_check_by_ext({'.h','.hpp','.hxx'})),
            (".cs",lambda:self.tree_check_by_ext({'.cs'})),
            (".vb",lambda:self.tree_check_by_ext({'.vb'}))]:
            tk.Button(tb, text=txt, font=('맑은 고딕',8), bg='#45475a', fg='#cdd6f4',
                      relief='flat', padx=3, pady=0, command=cmd).pack(side='left', padx=1)

        tc = tk.Frame(left, bg='#313244'); tc.pack(fill='both', expand=True)
        sy = ttk.Scrollbar(tc, orient='vertical'); sy.pack(side='right', fill='y')
        self.file_tree = CheckboxTreeview(tc, columns=('size','ext'),
                                          style='Custom.Treeview', yscrollcommand=sy.set)
        self.file_tree.pack(fill='both', expand=True)
        sy.config(command=self.file_tree.yview)
        self.file_tree.heading('#0', text='파일', anchor='w')
        self.file_tree.heading('size', text='크기', anchor='e')
        self.file_tree.heading('ext', text='확장자', anchor='c')
        self.file_tree.column('#0', width=170, minwidth=100)
        self.file_tree.column('size', width=55, minwidth=40, anchor='e')
        self.file_tree.column('ext', width=45, minwidth=30, anchor='c')
        self.file_tree.bind('<Double-1>', self._on_tree_dblclick)

        # ═══ 중앙: 편집기 ═══
        center = tk.Frame(self.main_pane, bg='#1e1e2e')
        self.main_pane.add(center, width=480)
        self.editor = CodeEditor(center)
        self.editor.pack(fill='both', expand=True)
        eb = tk.Frame(center, bg='#1e1e2e'); eb.pack(fill='x', pady=(2,0))
        tk.Button(eb, text="💾 저장", font=('맑은 고딕',9,'bold'), bg='#a6e3a1', fg='#1e1e2e',
                  relief='flat', padx=8, pady=3, command=self._save).pack(side='left', padx=2)
        tk.Button(eb, text="↩ 되돌리기", font=('맑은 고딕',9), bg='#45475a', fg='#cdd6f4',
                  relief='flat', padx=8, pady=3, command=self._revert).pack(side='left', padx=2)
        tk.Button(eb, text="📋 줄번호복사", font=('맑은 고딕',9), bg='#89b4fa', fg='#1e1e2e',
                  relief='flat', padx=8, pady=3, command=self._copy_numbered).pack(side='right', padx=2)

        # ═══ 우측: 프롬프트/Diff/GitHub 탭 ═══
        right = tk.Frame(self.main_pane, bg='#1e1e2e')
        self.main_pane.add(right, width=460)
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill='both', expand=True)

        # ── 탭1: 💬 프롬프트 ──
        tp = tk.Frame(self.nb, bg='#1e1e2e')
        self.nb.add(tp, text=' 💬 프롬프트 ')

        ph = tk.Frame(tp, bg='#1e1e2e'); ph.pack(fill='x', padx=6, pady=(6,2))
        tk.Label(ph, text="💬 AI에게 보낼 프롬프트", font=('맑은 고딕',10,'bold'),
                 bg='#1e1e2e', fg='#cdd6f4').pack(side='left')

        # 첨부 옵션
        af = tk.Frame(tp, bg='#1e1e2e'); af.pack(fill='x', padx=6, pady=2)
        ttk.Checkbutton(af, text="현재 파일 첨부(줄번호)", variable=self.attach_file,
                        style='TCheckbutton').pack(side='left')
        ttk.Checkbutton(af, text="체크된 파일 전체 첨부", variable=self.attach_checked,
                        style='TCheckbutton').pack(side='left', padx=(12,0))
        self.attach_info = tk.Label(af, text="", font=('맑은 고딕',8),
                                    bg='#1e1e2e', fg='#6c7086')
        self.attach_info.pack(side='right')

        # 멀티파일 수정 요청 시 안내
        tk.Label(tp, text="💡 여러 파일 수정 시 AI에게 === FILE: 경로 === 형식으로 반환을 요청하세요",
                 font=('맑은 고딕',8), bg='#1e1e2e', fg='#f9e2af', anchor='w').pack(fill='x', padx=6)

        self.prompt_text = scrolledtext.ScrolledText(tp, wrap=tk.WORD, font=('맑은 고딕',11),
            bg='#313244', fg='#cdd6f4', insertbackground='#f5e0dc', relief='flat', padx=10, pady=8, height=7)
        self.prompt_text.pack(fill='both', expand=True, padx=6, pady=4)

        # 템플릿 버튼
        tpl = tk.Frame(tp, bg='#1e1e2e'); tpl.pack(fill='x', padx=6, pady=2)
        tk.Label(tpl, text="템플릿:", font=('맑은 고딕',8), bg='#1e1e2e', fg='#6c7086').pack(side='left')
        templates = [
            ("단일 수정", "아래 코드에서 에러/개선이 필요합니다.\n\n[설명]\n\n"
                        "줄번호를 참고하여 수정 부분만 반환해주세요.\n"
                        "형식: <<<< SEARCH ... ==== ... >>>> REPLACE"),
            ("멀티파일 수정",
             "아래 파일들에서 다음 수정이 필요합니다.\n\n[설명]\n\n"
             "여러 파일에 걸친 수정이 필요하면 아래 형식으로 반환해주세요:\n\n"
             "=== FILE: 상대경로/파일명.확장자 ===\n"
             "<<<< SEARCH\n찾을 코드\n====\n바꿀 코드\n>>>> REPLACE\n"
             "=== END FILE ===\n\n"
             "=== FILE: 상대경로/파일명2.확장자 ===\n"
             "<<<< SEARCH\n찾을 코드\n====\n바꿀 코드\n>>>> REPLACE\n"
             "=== END FILE ==="),
            ("에러 수정",
             "아래 코드에서 다음 에러가 발생합니다.\n\n[에러 메시지]\n\n"
             "여러 파일의 수정이 필요한 경우 각 파일별로 구분하여 반환:\n"
             "=== FILE: path ===\n수정내용\n=== END FILE ==="),
            ("코드 리뷰", "아래 코드를 리뷰해주세요.\n줄번호와 파일명을 포함하여 알려주세요."),
        ]
        for name, tmpl in templates:
            tk.Button(tpl, text=name, font=('맑은 고딕',8), bg='#45475a', fg='#cdd6f4',
                      relief='flat', padx=5, pady=1,
                      command=lambda t=tmpl: self._set_template(t)).pack(side='left', padx=1)

        # 복사 버튼
        pb = tk.Frame(tp, bg='#1e1e2e'); pb.pack(fill='x', padx=6, pady=(4,6))
        tk.Button(pb, text="📋 프롬프트 + 첨부 → 클립보드 복사",
                  font=('맑은 고딕',11,'bold'), bg='#cba6f7', fg='#1e1e2e',
                  relief='flat', padx=20, pady=8, cursor='hand2',
                  command=self._copy_prompt).pack(fill='x')

        # ── 탭2: 🔧 Diff 적용 ──
        td = tk.Frame(self.nb, bg='#1e1e2e')
        self.nb.add(td, text=' 🔧 Diff 적용 ')

        tk.Label(td, text="🔧 AI의 수정 결과를 붙여넣기",
                 font=('맑은 고딕',10,'bold'), bg='#1e1e2e', fg='#cdd6f4'
                 ).pack(fill='x', padx=6, pady=(6,2))

        tk.Label(td, text="📌 단일파일: unified diff / SEARCH-REPLACE / 줄범위 / 전체코드\n"
                          "📌 멀티파일: === FILE: path === ... === END FILE === 블록으로 자동 분리",
                 font=('맑은 고딕',8), bg='#1e1e2e', fg='#6c7086', anchor='w', justify='left'
                 ).pack(fill='x', padx=6)

        self.diff_text = scrolledtext.ScrolledText(td, wrap=tk.WORD, font=('Consolas',10),
            bg='#313244', fg='#cdd6f4', insertbackground='#f5e0dc', relief='flat', padx=10, pady=8, height=10)
        self.diff_text.pack(fill='both', expand=True, padx=6, pady=4)

        self.diff_result_label = tk.Label(td, text="", font=('맑은 고딕',9),
                                          bg='#1e1e2e', fg='#a6adc8', anchor='w', wraplength=400)
        self.diff_result_label.pack(fill='x', padx=6, pady=2)

        db = tk.Frame(td, bg='#1e1e2e'); db.pack(fill='x', padx=6, pady=(2,4))

        tk.Button(db, text="🔍 분석 (파일 감지 + 미리보기)",
                  font=('맑은 고딕',10,'bold'), bg='#f9e2af', fg='#1e1e2e',
                  relief='flat', padx=12, pady=6, cursor='hand2',
                  command=self._analyze_diff).pack(fill='x', pady=2)

        tk.Button(db, text="✅ 현재 파일에 적용 (단일 파일)",
                  font=('맑은 고딕',10,'bold'), bg='#a6e3a1', fg='#1e1e2e',
                  relief='flat', padx=12, pady=6, cursor='hand2',
                  command=self._apply_single).pack(fill='x', pady=2)

        tk.Button(db, text="📦 멀티파일 일괄 적용 + 저장",
                  font=('맑은 고딕',10,'bold'), bg='#89b4fa', fg='#1e1e2e',
                  relief='flat', padx=12, pady=6, cursor='hand2',
                  command=self._apply_multi).pack(fill='x', pady=2)

        # ── 탭3: 🚀 GitHub ──
        tg = tk.Frame(self.nb, bg='#1e1e2e')
        self.nb.add(tg, text=' 🚀 GitHub ')

        # 합치기
        ms = tk.LabelFrame(tg, text=" 📄 일괄 합치기+복사 ", font=('맑은 고딕',9,'bold'),
                           bg='#1e1e2e', fg='#cdd6f4', padx=8, pady=6)
        ms.pack(fill='x', padx=6, pady=6)
        tk.Button(ms, text="📄 체크된 파일 → 하나로 합쳐서 복사",
                  font=('맑은 고딕',10,'bold'), bg='#a6e3a1', fg='#1e1e2e',
                  relief='flat', padx=12, pady=6, command=self.merge_and_copy).pack(fill='x')
        self.merge_info = tk.Label(ms, text="", font=('맑은 고딕',8), bg='#1e1e2e', fg='#6c7086')
        self.merge_info.pack(fill='x', pady=(4,0))

        # GitHub
        gs = tk.LabelFrame(tg, text=" 🚀 GitHub 업로드 ", font=('맑은 고딕',9,'bold'),
                           bg='#1e1e2e', fg='#cdd6f4', padx=8, pady=6)
        gs.pack(fill='x', padx=6, pady=6)
        gr = tk.Frame(gs, bg='#1e1e2e'); gr.pack(fill='x', pady=2)
        tk.Label(gr, text="리포명:", font=('맑은 고딕',9), bg='#1e1e2e', fg='#a6adc8').pack(side='left')
        self.repo_name_var = tk.StringVar()
        tk.Entry(gr, textvariable=self.repo_name_var, font=('Consolas',10), bg='#45475a',
                 fg='#f5e0dc', insertbackground='#f5e0dc', width=22, relief='flat').pack(side='left', padx=4)
        self.private_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(gr, text="Private", variable=self.private_var,
                        style='TCheckbutton').pack(side='left', padx=4)
        self.gh_btn = tk.Button(gs, text="🚀 GitHub 업로드", font=('맑은 고딕',10,'bold'),
                                bg='#f38ba8', fg='#1e1e2e', relief='flat', padx=12, pady=6,
                                cursor='hand2', command=self.upload_to_github)
        self.gh_btn.pack(fill='x', pady=4)
        tk.Label(gs, text="⚠ git+gh CLI 필요 | 민감파일 자동제외",
                 font=('맑은 고딕',8), bg='#1e1e2e', fg='#f9e2af').pack(fill='x')
        self.gh_status = tk.Label(gs, text="", font=('맑은 고딕',9), bg='#1e1e2e', fg='#a6adc8')
        self.gh_status.pack(fill='x', pady=2)

        # 로그
        ls = tk.LabelFrame(tg, text=" 로그 ", font=('맑은 고딕',9), bg='#1e1e2e', fg='#6c7086', padx=4, pady=4)
        ls.pack(fill='both', expand=True, padx=6, pady=6)
        self.log_text = scrolledtext.ScrolledText(ls, wrap=tk.WORD, font=('Consolas',9),
            bg='#11111b', fg='#a6e3a1', relief='flat', padx=6, pady=4, height=6)
        self.log_text.pack(fill='both', expand=True)

        # 프로그레스/상태
        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(self.root, variable=self.progress_var, maximum=100).pack(fill='x', padx=4)
        sf = tk.Frame(self.root, bg='#11111b'); sf.pack(fill='x', side='bottom')
        ttk.Label(sf, textvariable=self.status_var, style='Status.TLabel').pack(padx=10, pady=4)

    # ════════════════════ 이벤트 핸들러 ════════════════════

    def _on_tree_dblclick(self, event):
        item = self.file_tree.identify_row(event.y)
        if not item or item not in self.tree_item_map: return
        if self.editor.is_modified:
            if not messagebox.askyesno("확인", "현재 파일이 수정됨. 저장하지 않고 열까요?"): return
        rp, fp, sz = self.tree_item_map[item]
        if self.editor.load_file(fp):
            self.status_var.set(f"📄 {rp} ({self.format_size(sz)})")
            lc = len(self.editor.get_content().split('\n'))
            self.attach_info.config(text=f"📄 {os.path.basename(fp)} | {lc}줄")
            self.nb.select(0)

    def _set_template(self, t):
        self.prompt_text.delete('1.0', tk.END)
        self.prompt_text.insert('1.0', t)

    def _save(self):
        if self.editor.save_file():
            self.status_var.set(f"✅ 저장: {self.editor.current_file}")

    def _revert(self):
        if self.editor.current_file and messagebox.askyesno("확인", "원본으로 되돌릴까요?"):
            self.editor.load_file(self.editor.current_file)

    def _copy_numbered(self):
        if not self.editor.current_file:
            messagebox.showwarning("경고", "열린 파일이 없습니다."); return
        fn = os.path.basename(self.editor.current_file)
        ext = os.path.splitext(fn)[1].lstrip('.')
        txt = f"📄 파일: {fn}\n```{ext}\n{self.editor.get_content_with_line_numbers()}\n```"
        self.root.clipboard_clear(); self.root.clipboard_append(txt)
        self.status_var.set(f"✅ 줄번호 포함 복사: {fn}")

    # ── 프롬프트 복사 ──

    def _copy_prompt(self):
        prompt = self.prompt_text.get('1.0', 'end-1c').strip()
        if not prompt:
            messagebox.showwarning("경고", "프롬프트를 작성해주세요."); return

        result = prompt + "\n\n"

        # 단일 파일 첨부
        if self.attach_file.get() and self.editor.current_file:
            fn = os.path.basename(self.editor.current_file)
            rp = None
            for iid, (rel, fp, sz) in self.tree_item_map.items():
                if fp == self.editor.current_file:
                    rp = rel; break
            display_name = rp or fn
            ext = os.path.splitext(fn)[1].lstrip('.')
            result += f"---\n📄 파일: {display_name}\n"
            result += f"```{ext}\n{self.editor.get_content_with_line_numbers()}\n```\n\n"

        # 체크된 파일 전체 첨부
        if self.attach_checked.get():
            checked = self.get_checked_files()
            # 이미 첨부한 파일 제외
            if self.attach_file.get() and self.editor.current_file:
                checked = [(rp,fp,sz) for rp,fp,sz in checked if fp != self.editor.current_file]
            if checked:
                result += f"---\n📦 추가 첨부 파일 ({len(checked)}개)\n\n"
                for rp, fp, sz in checked:
                    content = self._read_file(fp)
                    if content is None: continue
                    ext = os.path.splitext(rp)[1].lstrip('.')
                    lines = content.split('\n')
                    w = len(str(len(lines)))
                    numbered = '\n'.join(f"{str(i).rjust(w)}| {l}" for i,l in enumerate(lines,1))
                    result += f"### 📄 {rp}\n```{ext}\n{numbered}\n```\n\n"

        self.root.clipboard_clear(); self.root.clipboard_append(result)
        tokens = len(result) // 4
        self.status_var.set(f"✅ 복사 완료 (약 {tokens:,}토큰)")
        messagebox.showinfo("복사 완료",
                            f"클립보드 복사 완료!\n약 {tokens:,}토큰 | {len(result):,}자\n\n"
                            f"AI 채팅에 Ctrl+V로 붙여넣으세요.")

    # ── Diff 분석/적용 ──

    def _analyze_diff(self):
        """붙여넣은 diff를 분석하여 단일/멀티 파일 판별"""
        diff_input = self.diff_text.get('1.0', 'end-1c').strip()
        if not diff_input:
            messagebox.showwarning("경고", "AI의 수정 결과를 붙여넣어주세요."); return

        blocks = MultiFileDiffEngine.parse_multi_file_diff(diff_input)

        if len(blocks) > 1:
            # 멀티파일
            self.diff_result_label.config(
                text=f"📦 {len(blocks)}개 파일 감지: " +
                     ", ".join(os.path.basename(b['file']) for b in blocks),
                fg='#89b4fa')

            # 파일 존재 여부 확인
            found = sum(1 for b in blocks if self._resolve_path(b['file']))
            self.diff_result_label.config(
                text=f"📦 {len(blocks)}개 파일 감지 (프로젝트 내 {found}개 발견)\n"
                     f"→ '멀티파일 일괄 적용' 버튼을 클릭하세요",
                fg='#89b4fa')

        elif len(blocks) == 1:
            b = blocks[0]
            self.diff_result_label.config(
                text=f"📄 단일 파일: {b['file']} [{b['diff_type']}]\n"
                     f"→ '현재 파일에 적용' 또는 '멀티파일 일괄 적용' 사용",
                fg='#a6e3a1')
        else:
            # 파일 구분 없음 → 현재 편집기 파일에 적용 시도
            self.diff_result_label.config(
                text="파일 구분 없음 → 현재 열린 파일에 직접 적용 가능\n"
                     "→ '현재 파일에 적용' 버튼 사용",
                fg='#f9e2af')

    def _apply_single(self):
        """현재 편집기 파일에 단일 diff 적용"""
        if not self.editor.current_file:
            messagebox.showwarning("경고", "먼저 파일을 열어주세요."); return

        diff_input = self.diff_text.get('1.0', 'end-1c').strip()
        if not diff_input:
            messagebox.showwarning("경고", "Diff를 붙여넣어주세요."); return

        original = self.editor.get_content()

        # 블록 파싱 시도
        blocks = MultiFileDiffEngine.parse_multi_file_diff(diff_input)
        if blocks:
            # 첫 번째 블록 또는 현재 파일에 해당하는 블록 사용
            target_block = None
            cur_base = os.path.basename(self.editor.current_file).lower()
            for b in blocks:
                if os.path.basename(b['file']).lower() == cur_base:
                    target_block = b; break
            if not target_block:
                target_block = blocks[0]

            new_content, msg = MultiFileDiffEngine.apply_single_diff(original, target_block)
        else:
            # 직접 적용
            fake_block = {'file': '', 'diff_type': 'unknown', 'content': diff_input}
            new_content, msg = MultiFileDiffEngine.apply_single_diff(original, fake_block)

        if new_content is None:
            self.diff_result_label.config(text=f"❌ {msg}", fg='#f38ba8')
            messagebox.showwarning("적용 실패", msg)
        else:
            self.editor.set_content(new_content)
            self.diff_result_label.config(text=f"✅ {msg}", fg='#a6e3a1')
            self.status_var.set("✅ Diff 적용 완료 — 💾 저장 필요")

    def _apply_multi(self):
        """멀티파일 일괄 적용"""
        diff_input = self.diff_text.get('1.0', 'end-1c').strip()
        if not diff_input:
            messagebox.showwarning("경고", "Diff를 붙여넣어주세요."); return

        blocks = MultiFileDiffEngine.parse_multi_file_diff(diff_input)
        if not blocks:
            # 파일 구분 없으면 현재 파일에 적용
            if self.editor.current_file:
                self._apply_single()
            else:
                messagebox.showwarning("경고", "파일 구분을 감지하지 못했습니다.")
            return

        # 멀티파일 적용 대화상자
        def resolve(rel_path):
            return self._resolve_path(rel_path)

        def on_complete(results):
            success = sum(1 for r in results if r['status'] == 'success')
            fail = sum(1 for r in results if r['status'] == 'fail')
            self.status_var.set(f"멀티파일 적용: ✅{success} ❌{fail}")
            # 현재 편집기 파일이 수정됐으면 다시 로드
            if self.editor.current_file:
                for r in results:
                    full = self._resolve_path(r['file'])
                    if full and os.path.normpath(full) == os.path.normpath(self.editor.current_file):
                        self.editor.load_file(self.editor.current_file)
                        break

        MultiFileApplyDialog(self.root, blocks, resolve, on_complete)

    def _resolve_path(self, rel_path: str):
        """상대경로를 프로젝트 내 실제 경로로 변환"""
        rel_normalized = rel_path.replace('\\', '/').strip()

        # 1. path_map에서 직접 찾기
        for key, full in self.path_map.items():
            if key.replace('\\', '/') == rel_normalized:
                return full

        # 2. 프로젝트 루트 기준
        project = self.project_path.get()
        if project:
            full = os.path.normpath(os.path.join(project, rel_path))
            if os.path.isfile(full):
                return full

        # 3. 파일명만으로 검색
        basename = os.path.basename(rel_path).lower()
        for key, full in self.path_map.items():
            if os.path.basename(key).lower() == basename:
                return full

        # 4. 부분 경로 매칭
        parts = rel_normalized.split('/')
        for key, full in self.path_map.items():
            key_parts = key.replace('\\', '/').split('/')
            if len(parts) <= len(key_parts):
                if key_parts[-len(parts):] == parts:
                    return full

        return None

    # ════════════════════ 유틸리티 ════════════════════

    def should_exclude(self, path, name):
        for p in self.default_excludes:
            if fnmatch.fnmatch(name, p) or name == p: return True
        return False

    def is_sensitive(self, rel_path):
        name = os.path.basename(rel_path).lower()
        for p in self.sensitive_patterns:
            if fnmatch.fnmatch(name, p.lower()): return True
        return False

    def is_target_file(self, filename):
        _, ext = os.path.splitext(filename)
        return ext.lower() in (self.source_only_extensions if self.source_only.get() else self.all_code_extensions)

    def format_size(self, sz):
        if sz >= 1048576: return f"{sz/1048576:.1f}MB"
        if sz >= 1024: return f"{sz/1024:.1f}KB"
        return f"{sz}B"

    def _read_file(self, fp):
        for enc in ['utf-8','utf-8-sig','cp949','euc-kr','latin-1']:
            try:
                with open(fp, 'r', encoding=enc) as f: return f.read()
            except (UnicodeDecodeError, UnicodeError): continue
        return None

    def append_log(self, text):
        def _do():
            self.log_text.insert(tk.END, text+"\n"); self.log_text.see(tk.END)
        self.root.after(0, _do)

    # ════════════════════ 트리뷰 ════════════════════

    def select_folder(self):
        folder = filedialog.askdirectory(title="프로젝트 폴더")
        if folder:
            self.project_path.set(folder)
            self.folder_label.config(text=folder)
            self.repo_name_var.set(os.path.basename(folder))
            self.status_var.set(f"프로젝트: {folder}")
            sln, proj = self.detect_vs_projects(folder)
            self.vs_info_label.config(
                text=f"🏗️ {len(sln)}sln, {len(proj)}proj" if sln or proj else "")

    def clear_tree(self):
        for it in self.file_tree.get_children(''): self.file_tree.delete(it)
        self.file_tree._checked.clear(); self.file_tree._unchecked.clear()
        self.tree_item_map.clear(); self.path_map.clear()

    def populate_tree(self, file_list, base_path):
        self.clear_tree()
        folder_nodes = {}
        file_list.sort(key=lambda x: x[0].lower())
        for rp, fp, sz in file_list:
            parts = rp.replace('\\','/').split('/')
            fn = parts[-1]; folders = parts[:-1]
            parent = ''; cur = ''
            for fd in folders:
                cur = f"{cur}/{fd}" if cur else fd
                if cur not in folder_nodes:
                    node = self.file_tree.insert(parent, 'end', text=f'📁 {fd}',
                                                 values=('',''), open=True, checked=True)
                    folder_nodes[cur] = node
                parent = folder_nodes[cur]
            _, ext = os.path.splitext(fn)
            sens = self.is_sensitive(rp)
            fid = self.file_tree.insert(parent, 'end',
                                        text=f"⚠️{fn}" if sens else fn,
                                        values=(self.format_size(sz), ext.lower()),
                                        checked=not sens)
            self.tree_item_map[fid] = (rp, fp, sz)
            self.path_map[rp] = fp  # 역매핑 등록

        self.tree_count_label.config(text=f"{len(file_list)}개")
        self.status_var.set(f"로드: {len(file_list)}개 — 더블클릭으로 열기")

    def tree_check_all(self): self.file_tree.check_all()
    def tree_uncheck_all(self): self.file_tree.uncheck_all()

    def tree_check_by_ext(self, ext_set):
        self.file_tree.uncheck_all()
        for iid, (rp,fp,sz) in self.tree_item_map.items():
            _, ext = os.path.splitext(rp)
            if ext.lower() in ext_set:
                self.file_tree._unchecked.discard(iid); self.file_tree._checked.add(iid)
                self.file_tree._update_display(iid); self.file_tree._update_parent(iid)

    def get_checked_files(self):
        return [info for iid, info in self.tree_item_map.items() if self.file_tree.is_checked(iid)]

    def on_source_only_changed(self):
        if hasattr(self, '_last_scan_data'):
            mode, data = self._last_scan_data
            if mode == 'folder': self._do_folder_scan(data)
            elif mode == 'vs': self._filter_and_populate(data)

    # ════════════════════ 스캔 ════════════════════

    def scan_folder(self):
        p = self.project_path.get()
        if not p: messagebox.showwarning("경고","폴더를 선택하세요!"); return
        self.status_var.set("스캔 중..."); self.root.update()
        self._last_scan_data = ('folder', p)
        self._do_folder_scan(p)

    def _do_folder_scan(self, path):
        files = []; mx = self.max_file_size.get() * 1024
        for rd, dirs, fnames in os.walk(path):
            dirs[:] = [d for d in dirs if not self.should_exclude(rd, d)]
            for f in fnames:
                if self.should_exclude(rd,f) or not self.is_target_file(f): continue
                fp = os.path.join(rd, f); rp = os.path.relpath(fp, path)
                try: sz = os.path.getsize(fp)
                except OSError: continue
                if sz <= mx: files.append((rp, fp, sz))
        self.populate_tree(files, path)

    def detect_vs_projects(self, folder):
        sln, proj = [], []
        try: entries = os.listdir(folder)
        except PermissionError: return sln, proj
        for e in entries:
            fp = os.path.join(folder, e)
            if os.path.isfile(fp):
                if e.endswith('.sln'): sln.append(fp)
                for ext in self.vs_project_extensions:
                    if e.endswith(ext): proj.append(fp)
            elif os.path.isdir(fp) and not self.should_exclude(folder, e):
                try:
                    for s in os.listdir(fp):
                        sf = os.path.join(fp, s)
                        if os.path.isfile(sf):
                            for ext in self.vs_project_extensions:
                                if s.endswith(ext): proj.append(sf)
                except PermissionError: pass
        return sln, proj

    def parse_sln(self, sln_path):
        d = os.path.dirname(sln_path); paths = []
        pat = re.compile(r'Project\("[^"]*"\)\s*=\s*"[^"]*"\s*,\s*"([^"]+)"\s*,\s*"[^"]*"')
        c = self._read_file(sln_path) or ""
        for m in pat.finditer(c):
            full = os.path.normpath(os.path.join(d, m.group(1).replace('\\', os.sep)))
            if os.path.isfile(full):
                for ext in self.vs_project_extensions:
                    if full.endswith(ext): paths.append(full); break
        return paths

    def parse_proj(self, proj_path):
        d = os.path.dirname(proj_path); srcs = []
        try: tree = ET.parse(proj_path); root_el = tree.getroot()
        except ET.ParseError: return srcs
        ns = ''; m = re.match(r'\{(.*)\}', root_el.tag)
        if m: ns = m.group(1)
        for tag in ['ClCompile','ClInclude','Compile','Content','None','Page',
                     'ApplicationDefinition','Resource','EmbeddedResource']:
            for el in (root_el.iter(f'{{{ns}}}{tag}') if ns else root_el.iter(tag)):
                inc = el.get('Include')
                if inc:
                    full = os.path.normpath(os.path.join(d, inc.replace('\\', os.sep)))
                    if os.path.isfile(full): srcs.append(full)
        if root_el.get('Sdk') and not srcs: srcs = self._glob_sdk(d, proj_path)
        return srcs

    def _glob_sdk(self, d, pp):
        files = []
        em = {'.csproj':{'.cs'},'.fsproj':{'.fs'},'.vbproj':{'.vb'}}
        exts = em.get(os.path.splitext(pp)[1], {'.cs','.cpp','.h'})
        skip = {'bin','obj','Debug','Release','.vs','x64','x86','packages','node_modules','.git'}
        for rd, dirs, fnames in os.walk(d):
            dirs[:] = [dd for dd in dirs if dd not in skip]
            for f in fnames:
                if os.path.splitext(f)[1].lower() in exts: files.append(os.path.join(rd, f))
        return files

    def scan_vs_project(self):
        p = self.project_path.get()
        if not p: messagebox.showwarning("경고","폴더를 선택하세요!"); return
        self.status_var.set("VS 분석 중..."); self.root.update()
        slns, dprojs = self.detect_vs_projects(p)
        all_proj = set()
        for s in slns:
            for pp in self.parse_sln(s): all_proj.add(pp)
        for pp in dprojs: all_proj.add(pp)
        if not all_proj:
            messagebox.showinfo("미발견","VS 프로젝트 파일 미발견"); return
        all_src = set()
        for proj in all_proj:
            for src in self.parse_proj(proj): all_src.add(os.path.normpath(src))
        self._last_scan_data = ('vs', (p, all_src))
        self._filter_and_populate((p, all_src))

    def _filter_and_populate(self, data):
        project, all_src = data
        mx = self.max_file_size.get() * 1024
        exts = self.source_only_extensions if self.source_only.get() else self.all_code_extensions
        result = []
        for fp in sorted(all_src):
            _, ext = os.path.splitext(fp)
            if ext.lower() not in exts: continue
            try: sz = os.path.getsize(fp)
            except OSError: continue
            if sz <= mx: result.append((os.path.relpath(fp, project), fp, sz))
        self.populate_tree(result, project)

    # ════════════════════ 합치기/GitHub ════════════════════

    def merge_and_copy(self):
        checked = self.get_checked_files()
        if not checked: messagebox.showwarning("경고","체크된 파일 없음"); return
        project = self.project_path.get()
        self.status_var.set(f"합치는 중..."); self.root.update()
        r = f"# 프로젝트 스캔 결과\n# 경로: {project}\n"
        r += f"# 시간: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        r += f"# 파일: {len(checked)}개\n\n## 파일 목록\n```\n"
        for rp,fp,sz in checked:
            r += f"  {rp} ({self.format_size(sz)})\n"
        r += "```\n\n"
        r += "## 수정 시 아래 형식으로 반환해주세요\n```\n"
        r += "=== FILE: 상대경로/파일명 ===\n"
        r += "<<<< SEARCH\n원본 코드\n====\n수정 코드\n>>>> REPLACE\n"
        r += "=== END FILE ===\n```\n\n"
        r += "## 파일 내용\n\n"
        for i, (rp,fp,sz) in enumerate(checked, 1):
            content = self._read_file(fp)
            if content is None: content = "[읽기 실패]"
            ext = os.path.splitext(rp)[1].lstrip('.')
            lines = content.split('\n'); w = len(str(len(lines)))
            numbered = '\n'.join(f"{str(j).rjust(w)}| {l}" for j,l in enumerate(lines,1))
            r += f"### [{i}/{len(checked)}] 📄 {rp}\n```{ext}\n{numbered}\n```\n\n"
        self.root.clipboard_clear(); self.root.clipboard_append(r)
        tokens = len(r) // 4
        self.merge_info.config(text=f"✅ {len(checked)}개 | ~{tokens:,}토큰")
        self.status_var.set(f"✅ 복사 완료 ({len(checked)}개, ~{tokens:,}토큰)")
        messagebox.showinfo("복사 완료",
            f"{len(checked)}개 파일 복사됨!\n~{tokens:,}토큰 | {len(r):,}자\n\n"
            f"AI 채팅에 Ctrl+V\n\n💡 AI가 수정결과를 반환하면\nDiff 적용 탭에 붙여넣기 → 멀티파일 적용")

    def upload_to_github(self):
        rn = self.repo_name_var.get().strip()
        if not rn: messagebox.showwarning("경고","리포명 입력"); return
        if not re.match(r'^[a-zA-Z0-9._-]+$', rn):
            messagebox.showwarning("경고","리포명: 영문/숫자/하이픈만"); return
        checked = self.get_checked_files()
        if not checked: messagebox.showwarning("경고","파일 없음"); return
        sens = [rp for rp,fp,sz in checked if self.is_sensitive(rp)]
        if sens:
            msg = "⚠ 민감파일:\n" + "\n".join(f"  • {s}" for s in sens[:10])
            r = messagebox.askyesnocancel("민감파일", msg+"\n\n제외하고 업로드?")
            if r is None: return
            if r: checked = [(rp,fp,sz) for rp,fp,sz in checked if not self.is_sensitive(rp)]
            if not checked: return
        self.log_text.delete('1.0', tk.END); self.nb.select(2)
        for fn, name, url in [(self.uploader.check_git,"git","https://git-scm.com/"),
                               (self.uploader.check_gh_cli,"gh CLI","https://cli.github.com/"),
                               (self.uploader.check_gh_auth,"gh auth",None)]:
            if not fn():
                msg = f"❌ {name} 필요" + (f"\n{url}" if url else "\ngh auth login 실행")
                self.append_log(msg); messagebox.showerror("오류",msg); return
            self.append_log(f"✅ {name}")
        self.gh_btn.config(state='disabled', text="⏳...", bg='#6c7086')
        self.progress_var.set(0)
        def do():
            def cb(p,m): self.root.after(0,lambda:self.progress_var.set(p))
            ok, res = self.uploader.create_and_push(checked, self.project_path.get(),
                rn, self.private_var.get(), f"ProjectScan ({len(checked)} files)", cb)
            def done():
                self.gh_btn.config(state='normal', text="🚀 GitHub 업로드", bg='#f38ba8')
                if ok:
                    self.progress_var.set(100); self.gh_status.config(text=f"✅ {res}", fg='#a6e3a1')
                    if messagebox.askyesno("성공",f"📎 {res}\n\nURL 복사?"):
                        self.root.clipboard_clear(); self.root.clipboard_append(res)
                else:
                    self.progress_var.set(0); messagebox.showerror("실패",res)
            self.root.after(0, done)
        threading.Thread(target=do, daemon=True).start()


if __name__ == '__main__':
    root = tk.Tk()
    app = ProjectScan(root)
    root.mainloop()
