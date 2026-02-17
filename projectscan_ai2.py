#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProjectScan v5.1b — Line-number Diff + GitHub Auto-sync (push fix)
All modifications via line numbers. Includes GitHub commit/push after diff apply.
"""

import os
import re
import sys
import io
import json
import shutil
import difflib
import hashlib
import tempfile
import subprocess
import threading
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog

if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ════════════════════════════════════════════════════════════
#  1. EncodingHandler
# ════════════════════════════════════════════════════════════
class EncodingHandler:
    ENCODING_CANDIDATES = [
        'utf-8-sig', 'utf-8', 'cp949', 'euc-kr',
        'utf-16', 'shift_jis', 'gb2312', 'latin-1',
    ]

    @staticmethod
    def detect_encoding(file_path):
        try:
            with open(file_path, 'rb') as f:
                raw = f.read(4)
            if raw[:3] == b'\xef\xbb\xbf':
                return 'utf-8-sig'
            if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                return 'utf-16'
        except Exception:
            pass
        try:
            import chardet
            with open(file_path, 'rb') as f:
                data = f.read(min(os.path.getsize(file_path), 65536))
            det = chardet.detect(data)
            if det and det.get('confidence', 0) > 0.7:
                enc = det['encoding']
                if enc and enc.lower().replace('-', '') in ('euckr', 'iso2022kr'):
                    return 'cp949'
                if enc:
                    return enc.lower()
        except ImportError:
            pass
        for enc in EncodingHandler.ENCODING_CANDIDATES:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    f.read()
                return enc
            except (UnicodeDecodeError, UnicodeError):
                continue
        return 'latin-1'

    @staticmethod
    def read_file(file_path):
        encoding = EncodingHandler.detect_encoding(file_path)
        has_bom = encoding == 'utf-8-sig'
        with open(file_path, 'rb') as f:
            raw = f.read()
        crlf = raw.count(b'\r\n')
        lf = raw.count(b'\n') - crlf
        line_ending = '\r\n' if crlf > lf else '\n'
        for enc in ([encoding] + EncodingHandler.ENCODING_CANDIDATES):
            try:
                content = raw.decode(enc)
                encoding = enc
                has_bom = enc == 'utf-8-sig'
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            content = raw.decode('latin-1')
            encoding = 'latin-1'
        return content, encoding, has_bom, line_ending

    @staticmethod
    def write_file(file_path, content, encoding='utf-8',
                   has_bom=False, line_ending='\n'):
        norm = content.replace('\r\n', '\n').replace('\r', '\n')
        if line_ending == '\r\n':
            norm = norm.replace('\n', '\r\n')
        w_enc = ('utf-8-sig'
                 if (has_bom and encoding in ('utf-8', 'utf-8-sig'))
                 else encoding)
        with open(file_path, 'w', encoding=w_enc, newline='') as f:
            f.write(norm)


# ════════════════════════════════════════════════════════════
#  2. TextNormalizer
# ════════════════════════════════════════════════════════════
class TextNormalizer:
    INVISIBLE = ['\ufeff', '\u200b', '\u200c', '\u200d', '\u2060', '\ufffe']

    @staticmethod
    def normalize_line_endings(text):
        return text.replace('\r\n', '\n').replace('\r', '\n')

    @staticmethod
    def remove_invisible(text):
        for ch in TextNormalizer.INVISIBLE:
            text = text.replace(ch, '')
        return text

    @staticmethod
    def normalize_unicode(text):
        return unicodedata.normalize('NFC', text)

    @staticmethod
    def full(text):
        text = TextNormalizer.normalize_line_endings(text)
        text = TextNormalizer.remove_invisible(text)
        text = TextNormalizer.normalize_unicode(text)
        return text


# ════════════════════════════════════════════════════════════
#  3. LineDiffParser v5.0 — 줄번호 전용 파서
# ════════════════════════════════════════════════════════════
class LineDiffParser:
    """
    AI 응답 형식 (줄번호 전용):

    === FILE: path/file.js ===
    @@ 15-23 REPLACE
    새 코드
    @@ END
    @@ 50 DELETE 3
    @@ 60 INSERT
    삽입 코드
    @@ END
    === END FILE ===

    토큰 4개만 사용: === FILE:, @@ 숫자, @@ END, === END FILE ===
    """

    RE_FILE_START = re.compile(r'^\s*={2,}\s*FILE:\s*(.+?)\s*={2,}\s*$')
    RE_FILE_END = re.compile(r'^\s*={2,}\s*END\s+FILE\s*={2,}\s*$')

    # @@ 15-23 REPLACE  또는  @@ 15 - 23 REPLACE
    RE_CMD_REPLACE = re.compile(
        r'^\s*@@\s*(\d+)\s*-\s*(\d+)\s+REPLACE\s*$', re.IGNORECASE)
    # @@ 50 DELETE 3
    RE_CMD_DELETE = re.compile(
        r'^\s*@@\s*(\d+)\s+DELETE\s+(\d+)\s*$', re.IGNORECASE)
    # @@ 60 INSERT
    RE_CMD_INSERT = re.compile(
        r'^\s*@@\s*(\d+)\s+INSERT\s*$', re.IGNORECASE)
    # @@ END
    RE_CMD_END = re.compile(
        r'^\s*@@\s*END\s*$', re.IGNORECASE)

    def parse(self, text):
        """diff 텍스트 -> {filepath: [commands]}"""
        if not text or not text.strip():
            return {}

        text = TextNormalizer.full(text)
        lines = text.split('\n')

        # 1) 파일별로 분리
        file_blocks = self._split_files(lines)

        if not file_blocks:
            # 파일 헤더 없으면 전체를 현재 파일로
            cmds = self._parse_commands(lines)
            if cmds:
                return {'__current_file__': cmds}
            return {}

        result = {}
        for fp, block_lines in file_blocks.items():
            cmds = self._parse_commands(block_lines)
            if cmds:
                if fp in result:
                    result[fp].extend(cmds)
                else:
                    result[fp] = cmds
        return result

    def _split_files(self, lines):
        """파일 헤더로 블록 분리"""
        blocks = {}
        headers = []

        for i, line in enumerate(lines):
            m = self.RE_FILE_START.match(line)
            if m:
                fp = m.group(1).strip().strip('`\'"')
                headers.append((i, fp))

        if not headers:
            return {}

        # 각 헤더의 끝 찾기
        for hi, (hline, fp) in enumerate(headers):
            start = hline + 1

            # END FILE 찾기
            end_line = None
            next_header = headers[hi + 1][0] if hi + 1 < len(headers) else len(lines)

            for j in range(start, next_header):
                if self.RE_FILE_END.match(lines[j]):
                    end_line = j
                    break

            if end_line is None:
                end_line = next_header

            block = lines[start:end_line]

            if fp in blocks:
                blocks[fp].extend(block)
            else:
                blocks[fp] = block

        return blocks

    def _parse_commands(self, lines):
        """라인 리스트에서 @@ 명령 추출"""
        commands = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # @@ 15-23 REPLACE
            m = self.RE_CMD_REPLACE.match(line)
            if m:
                start_ln = int(m.group(1))
                end_ln = int(m.group(2))
                content_lines = []
                i += 1
                while i < len(lines):
                    if self.RE_CMD_END.match(lines[i]):
                        i += 1
                        break
                    # 다른 명령이나 파일 끝을 만나면 중단
                    if (self.RE_CMD_REPLACE.match(lines[i]) or
                        self.RE_CMD_DELETE.match(lines[i]) or
                        self.RE_CMD_INSERT.match(lines[i]) or
                        self.RE_FILE_END.match(lines[i]) or
                        self.RE_FILE_START.match(lines[i])):
                        break
                    content_lines.append(lines[i])
                    i += 1
                commands.append({
                    'type': 'replace',
                    'start': start_ln,
                    'end': end_ln,
                    'content': '\n'.join(content_lines),
                })
                continue

            # @@ 50 DELETE 3
            m = self.RE_CMD_DELETE.match(line)
            if m:
                start_ln = int(m.group(1))
                count = int(m.group(2))
                commands.append({
                    'type': 'delete',
                    'start': start_ln,
                    'count': count,
                })
                i += 1
                continue

            # @@ 60 INSERT
            m = self.RE_CMD_INSERT.match(line)
            if m:
                after_ln = int(m.group(1))
                content_lines = []
                i += 1
                while i < len(lines):
                    if self.RE_CMD_END.match(lines[i]):
                        i += 1
                        break
                    if (self.RE_CMD_REPLACE.match(lines[i]) or
                        self.RE_CMD_DELETE.match(lines[i]) or
                        self.RE_CMD_INSERT.match(lines[i]) or
                        self.RE_FILE_END.match(lines[i]) or
                        self.RE_FILE_START.match(lines[i])):
                        break
                    content_lines.append(lines[i])
                    i += 1
                commands.append({
                    'type': 'insert',
                    'after': after_ln,
                    'content': '\n'.join(content_lines),
                })
                continue

            i += 1

        return commands


# ════════════════════════════════════════════════════════════
#  4. LineDiffEngine v5.0 — 줄번호 전용 적용 엔진
# ════════════════════════════════════════════════════════════
class LineDiffEngine:

    def __init__(self):
        self.parser = LineDiffParser()

    def parse(self, text):
        return self.parser.parse(text)

    def analyze(self, diff_text, path_map=None):
        parsed = self.parser.parse(diff_text)
        files = []
        tc = 0
        for fp, cmds in parsed.items():
            found, rp = False, None
            if path_map and fp != '__current_file__':
                rp = self._resolve(fp, path_map)
                found = rp is not None

            rep_count = sum(1 for c in cmds if c['type'] == 'replace')
            del_count = sum(1 for c in cmds if c['type'] == 'delete')
            ins_count = sum(1 for c in cmds if c['type'] == 'insert')

            files.append({
                'path': fp, 'change_count': len(cmds),
                'rep_count': rep_count, 'del_count': del_count,
                'ins_count': ins_count,
                'found_in_project': found, 'resolved_path': rp})
            tc += len(cmds)

        if not parsed:
            fmt = 'unrecognized'
        elif '__current_file__' in parsed:
            fmt = 'single_file'
        elif len(parsed) == 1:
            fmt = 'single_file_named'
        else:
            fmt = 'multi_file'

        return {'file_count': len(parsed), 'files': files,
                'total_changes': tc, 'format': fmt}

    def apply_to_content(self, original, commands):
        """줄번호 명령을 원본에 적용"""
        if not commands:
            return original, ["[!] no changes"]

        file_lines = original.split('\n')
        orig_count = len(file_lines)
        msgs = []
        ok = 0
        errors = 0

        # 역순 정렬 — 뒤에서부터 적용해야 앞쪽 줄번호 불변
        sorted_cmds = sorted(
            commands,
            key=lambda c: c.get('start', c.get('after', 0)),
            reverse=True)

        for cmd in sorted_cmds:
            ctype = cmd['type']

            if ctype == 'replace':
                s = cmd['start'] - 1   # 0-based
                e = cmd['end']         # exclusive (0-based end = end_ln)
                if s < 0:
                    s = 0
                if e > len(file_lines):
                    e = len(file_lines)
                if s > len(file_lines):
                    msgs.append(
                        f"[X] REPLACE {cmd['start']}-{cmd['end']}: "
                        f"start({cmd['start']}) > file length({len(file_lines)})")
                    errors += 1
                    continue

                new_lines = cmd['content'].split('\n')

                # 안전장치: 전체교체(1~전체) 시 결과가 극단적으로 짧으면 차단
                is_full = (cmd['start'] <= 1 and cmd['end'] >= orig_count)
                if is_full and orig_count > 10 and len(new_lines) < orig_count * 0.1:
                    msgs.append(
                        f"[BLOCK] REPLACE {cmd['start']}-{cmd['end']}: "
                        f"full replace would reduce {orig_count} -> {len(new_lines)} lines")
                    errors += 1
                    continue

                old_count = e - s
                file_lines[s:e] = new_lines
                ok += 1
                msgs.append(
                    f"[OK] REPLACE {cmd['start']}-{cmd['end']} "
                    f"({old_count}lines -> {len(new_lines)}lines)")

            elif ctype == 'delete':
                s = cmd['start'] - 1
                count = cmd['count']
                if s < 0:
                    s = 0
                if s >= len(file_lines):
                    msgs.append(
                        f"[X] DELETE {cmd['start']}: "
                        f"start({cmd['start']}) > file length({len(file_lines)})")
                    errors += 1
                    continue
                e = min(s + count, len(file_lines))
                actual = e - s
                del file_lines[s:e]
                ok += 1
                msgs.append(
                    f"[OK] DELETE {cmd['start']} x{count} "
                    f"({actual}lines removed)")

            elif ctype == 'insert':
                pos = cmd['after']
                if pos < 0:
                    pos = 0
                if pos > len(file_lines):
                    pos = len(file_lines)
                new_lines = cmd['content'].split('\n')
                file_lines[pos:pos] = new_lines
                ok += 1
                msgs.append(
                    f"[OK] INSERT after {cmd['after']} "
                    f"({len(new_lines)}lines added)")

        msgs.insert(0, f"Result: {ok} ok, {errors} errors / {len(commands)} total")

        result = '\n'.join(file_lines)

        # 최종 안전: 원본 대비 10% 미만이면 차단
        orig_len = len(original.strip())
        result_len = len(result.strip())
        if orig_len > 200 and result_len < orig_len * 0.1:
            pct = result_len * 100 // orig_len if orig_len > 0 else 0
            msgs.append(f"[BLOCK] result is only {pct}% of original -> keeping original")
            return original, msgs

        return result, msgs

    def resolve_and_apply_all(self, diff_text, path_map, project_path=None):
        parsed = self.parser.parse(diff_text)
        results = []
        for fp, cmds in parsed.items():
            if fp == '__current_file__':
                results.append({
                    'filepath': fp, 'resolved_path': None,
                    'success': False, 'new_content': None,
                    'messages': ["file not specified -> use 'apply to current file'"],
                    'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                continue

            rp = self._resolve(fp, path_map)
            if rp is None and project_path:
                cand = os.path.join(project_path, fp.replace('/', os.sep))
                if os.path.isfile(cand):
                    rp = cand
            if rp is None:
                results.append({
                    'filepath': fp, 'resolved_path': None,
                    'success': False, 'new_content': None,
                    'messages': [f"[X] not found: {fp}"],
                    'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                continue

            try:
                content, enc, bom, le = EncodingHandler.read_file(rp)
            except Exception as e:
                results.append({
                    'filepath': fp, 'resolved_path': rp,
                    'success': False, 'new_content': None,
                    'messages': [f"[X] read error: {e}"],
                    'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                continue

            new_c, msgs = self.apply_to_content(content, cmds)
            any_ok = any('[OK]' in m for m in msgs)
            changed = new_c != content

            results.append({
                'filepath': fp, 'resolved_path': rp,
                'success': any_ok and changed,
                'new_content': new_c if changed else None,
                'messages': msgs, 'encoding': enc,
                'has_bom': bom, 'line_ending': le})

        return results

    def apply_and_save(self, diff_text, path_map, project_path=None):
        results = self.resolve_and_apply_all(diff_text, path_map, project_path)
        saved, failed, skipped = 0, 0, 0
        for r in results:
            if not r['success'] or r['new_content'] is None:
                if r['resolved_path']:
                    failed += 1
                else:
                    skipped += 1
                continue
            try:
                bp = r['resolved_path'] + '.bak'
                n = 1
                while os.path.exists(bp):
                    bp = f"{r['resolved_path']}.bak{n}"
                    n += 1
                shutil.copy2(r['resolved_path'], bp)
                EncodingHandler.write_file(
                    r['resolved_path'], r['new_content'],
                    r['encoding'], r['has_bom'], r['line_ending'])
                r['messages'].append(f"[SAVED] backup: {os.path.basename(bp)}")
                saved += 1
            except Exception as e:
                r['messages'].append(f"[X] save error: {e}")
                r['success'] = False
                failed += 1
        return results, {'total': len(results), 'saved': saved,
                         'failed': failed, 'skipped': skipped}

    def _resolve(self, fp, pm):
        if not fp or not pm:
            return None
        norm = fp.replace('\\', '/').strip('/')
        nl = norm.lower()
        for r, a in pm.items():
            if r.replace('\\', '/').strip('/') == norm:
                return a
        for r, a in pm.items():
            if r.replace('\\', '/').strip('/').lower() == nl:
                return a
        fn = nl.split('/')[-1]
        cands = [(r, a) for r, a in pm.items()
                 if r.replace('\\', '/').split('/')[-1].lower() == fn]
        if len(cands) == 1:
            return cands[0][1]
        if len(cands) > 1:
            best, bo = None, 0
            for r, a in cands:
                rp = r.replace('\\', '/').lower().split('/')
                np = nl.split('/')
                ov = sum(1 for x, y in zip(reversed(rp), reversed(np)) if x == y)
                if ov > bo:
                    bo, best = ov, a
            if best:
                return best
        for r, a in pm.items():
            rl = r.replace('\\', '/').lower()
            if rl.endswith(nl) or nl.endswith(rl):
                return a
        return None


# ════════════════════════════════════════════════════════════
#  5. CheckboxTreeview
# ════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════
#  6. CodeEditor
# ════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════
#  7. GitHubUploader
# ════════════════════════════════════════════════════════════
class GitHubUploader:
    GH_PATH = r'"C:\Program Files\GitHub CLI\gh.exe"'

    def __init__(self, log_cb=None):
        self.log = log_cb or print

    def run_cmd(self, cmd, cwd=None):
        self.log(f"$ {cmd}")
        try:
            r = subprocess.run(cmd, shell=True, cwd=cwd,
                               capture_output=True, timeout=60,
                               encoding='utf-8', errors='replace')
            out = r.stdout.strip() if r.stdout else ''
            err = r.stderr.strip() if r.stderr else ''
            if out:
                self.log(out)
            if r.returncode != 0 and err:
                self.log(f"WARN: {err}")
            return r.returncode == 0, out, err
        except Exception as e:
            self.log(f"ERROR: {e}")
            return False, '', str(e)

    def check_git(self):
        ok, *_ = self.run_cmd('git --version'); return ok

    def check_gh(self):
        ok, *_ = self.run_cmd(f'{self.GH_PATH} --version'); return ok

    def check_auth(self):
        ok, out, err = self.run_cmd(f'{self.GH_PATH} auth status')
        if ok:
            return True
        # gh auth status outputs to stderr even on success in some versions
        if err and ('Logged in' in err or 'logged in' in err.lower()):
            return True
        return ok

    def create_and_push(self, files, project_path, repo_name,
                        private=True, desc='', progress_cb=None):
        td = tempfile.mkdtemp(prefix='projectscan_')
        try:
            total = len(files) + 5
            step = 0
            def prog():
                nonlocal step; step += 1
                if progress_cb: progress_cb(step / total * 100)
            self.log(f"temp dir: {td}")
            for rel, full, *_ in files:
                dst = os.path.join(td, rel.replace('/', os.sep))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(full, dst)
            prog()
            with open(os.path.join(td, 'README.md'), 'w', encoding='utf-8') as f:
                f.write(f"# {repo_name}\n\n{desc}\n\nFiles: {len(files)}\n\nUploaded by ProjectScan\n")
            gi_path = os.path.join(td, '.gitignore')
            if not os.path.exists(gi_path):
                with open(gi_path, 'w', encoding='utf-8') as f:
                    f.write("*.bak\n*.bak*\n__pycache__/\n.vs/\n")
            prog()
            self.run_cmd('git init', cwd=td)
            self.run_cmd('git add -A', cwd=td)
            self.run_cmd('git commit -m "Initial commit by ProjectScan"', cwd=td)
            prog()
            vis = '--private' if private else '--public'
            self.log(f"visibility flag: {vis}")
            ok, out, err = self.run_cmd(
                f'{self.GH_PATH} repo create {repo_name} {vis} --source=. --push',
                cwd=td)
            prog()
            if ok:
                ok2, url, _ = self.run_cmd(
                    f'{self.GH_PATH} repo view {repo_name} --json url -q .url',
                    cwd=td)
                return True, url if ok2 else f"https://github.com/{repo_name}"
            return False, err
        except Exception as e:
            return False, str(e)
        finally:
            try:
                shutil.rmtree(td, ignore_errors=True)
            except Exception:
                pass

    def init_local_repo(self, project_path, repo_name):
        """Initialize local git repo and set remote if needed."""
        git_dir = os.path.join(project_path, '.git')
        if not os.path.isdir(git_dir):
            self.run_cmd('git init', cwd=project_path)
            gi_path = os.path.join(project_path, '.gitignore')
            if not os.path.exists(gi_path):
                with open(gi_path, 'w', encoding='utf-8') as f:
                    f.write("*.bak\n*.bak*\n__pycache__/\n.vs/\n")
            self.run_cmd('git add -A', cwd=project_path)
            self.run_cmd('git commit -m "init by ProjectScan"', cwd=project_path)
        ok, out, _ = self.run_cmd('git remote get-url origin', cwd=project_path)
        if not ok:
            ok_u, user, _ = self.run_cmd(
                f'{self.GH_PATH} api user -q .login')
            if ok_u and user:
                remote_url = f"https://github.com/{user}/{repo_name}.git"
            else:
                remote_url = f"https://github.com/{repo_name}.git"
            self.run_cmd(f'git remote add origin {remote_url}', cwd=project_path)
            self.log(f"remote set: {remote_url}")
        else:
            self.log(f"remote exists: {out}")

    def sync_push(self, project_path, message, progress_cb=None):
        """Stage all, commit with message, pull then push to origin."""
        # 1. Detect local branch name
        ok_br, br_out, _ = self.run_cmd(
            'git branch --show-current', cwd=project_path)
        branch = br_out.strip() if ok_br and br_out and br_out.strip() else 'master'
        self.log(f"sync_push: local branch = {branch}")

        if progress_cb:
            progress_cb(10)

        # 2. Stage all changes
        self.run_cmd('git add -A', cwd=project_path)
        ok_diff, out_diff, _ = self.run_cmd(
            'git diff --cached --stat', cwd=project_path)
        has_staged = bool(out_diff and out_diff.strip())

        # 3. Commit if staged changes exist
        if has_staged:
            if progress_cb:
                progress_cb(20)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            full_msg = f"{message} [{ts}]"
            safe_msg = full_msg.replace('"', '\\"')
            ok_c, _, err_c = self.run_cmd(
                f'git commit -m "{safe_msg}"', cwd=project_path)
            if not ok_c:
                self.log(f"commit failed: {err_c}")
                return False, "commit failed"
        else:
            full_msg = message
            self.log("no new staged changes")

        if progress_cb:
            progress_cb(30)

        # 4. Check if any local commits exist at all
        ok_any, any_out, _ = self.run_cmd(
            'git log --oneline -1', cwd=project_path)
        if not (ok_any and any_out and any_out.strip()):
            self.log("no commits exist, nothing to push")
            if progress_cb:
                progress_cb(100)
            return True, "(no commits)"

        # 5. Check for unpushed commits
        has_unpushed = False
        ok_log, log_out, _ = self.run_cmd(
            'git log --oneline @{u}..HEAD', cwd=project_path)
        if ok_log and log_out and log_out.strip():
            has_unpushed = True
        else:
            # No upstream yet — any local commit counts as unpushed
            has_unpushed = True

        if not has_staged and not has_unpushed:
            self.log("nothing to commit or push")
            if progress_cb:
                progress_cb(100)
            return True, "(no changes)"

        if progress_cb:
            progress_cb(40)

        # 6. Push (force push — no pull to avoid merge conflicts in files)
        self.log(f"pushing to origin/{branch}...")
        ok_p, out_p, err_p = self.run_cmd(
            f'git push -u origin {branch} --force', cwd=project_path)
        if progress_cb:
            progress_cb(100)
        if ok_p:
            self.log(f"pushed to {branch}: {full_msg}")
            return True, full_msg

        self.log(f"push failed: {err_p}")
        return False, err_p


# ════════════════════════════════════════════════════════════
#  8. ProjectScan v5.1b — Main Application
# ════════════════════════════════════════════════════════════
class ProjectScan:
    def __init__(self, root):
        self.root = root
        self.root.title("ProjectScan v5.1b")
        self.root.geometry("1350x950")
        self.root.configure(bg='#1e1e2e')

        self.project_path = tk.StringVar()
        self.status_var = tk.StringVar(value="ready")
        self.max_file_size = tk.IntVar(value=500)
        self.source_only = tk.BooleanVar(value=False)
        self.attach_file = tk.BooleanVar(value=False)
        self.repo_private = tk.BooleanVar(value=False)
        self.auto_sync = tk.BooleanVar(value=False)
        self.commit_msg_var = tk.StringVar(value="update by ProjectScan")
        self.all_files = []
        self._current_file_path = None

        self.source_only_ext = {
            '.c','.cpp','.cc','.cxx','.h','.hpp','.hxx','.cs','.vb','.fs',
            '.py','.java','.js','.ts','.jsx','.tsx','.go','.rs','.rb','.php',
            '.swift','.kt','.kts','.m','.mm','.lua','.r','.pl','.pm',
            '.sh','.bash','.bat','.ps1','.sql'}
        self.all_code_ext = self.source_only_ext | {
            '.xaml','.xml','.json','.yaml','.yml','.toml','.html','.htm',
            '.css','.scss','.less','.svg','.config','.ini','.cfg',
            '.properties','.env','.md','.txt','.rst','.csv','.sln',
            '.csproj','.vbproj','.fsproj','.vcxproj','.props','.targets',
            '.resx','.settings','.Designer.vb','.Designer.cs',
            '.razor','.cshtml','.vbhtml'}
        self.exclude_patterns = [
            'bin','obj','.vs','Debug','Release','x64','x86','node_modules',
            '__pycache__','.git','.svn','packages','.idea','*.dll','*.exe',
            '*.pdb','*.cache','*.suo','*.user','*.bak','*.log',
            'Thumbs.db','.DS_Store','*.o','*.obj']
        self.sensitive_patterns = [
            '*.env','.env','*.pem','*.key','*.pfx','id_rsa','*password*',
            '*secret*','appsettings.Development.json','secrets.json','web.config']

        self.diff_engine = LineDiffEngine()
        self.uploader = GitHubUploader()
        self._last_saved_files = []
        self._setup_styles()
        self._build_ui()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Dark.TFrame', background='#1e1e2e')
        style.configure('Dark.TLabel', background='#1e1e2e', foreground='#cdd6f4', font=('Consolas', 9))
        style.configure('Dark.TButton', background='#45475a', foreground='#cdd6f4', font=('Consolas', 9))
        style.configure('Dark.TCheckbutton', background='#1e1e2e', foreground='#cdd6f4', font=('Consolas', 9))
        style.configure('Accent.TButton', background='#89b4fa', foreground='#1e1e2e', font=('Consolas', 9, 'bold'))
        style.configure('Treeview', background='#181825', foreground='#cdd6f4', fieldbackground='#181825', font=('Consolas', 9))
        style.configure('Treeview.Heading', background='#313244', foreground='#cdd6f4', font=('Consolas', 9, 'bold'))

    def _build_ui(self):
        top = ttk.Frame(self.root, style='Dark.TFrame')
        top.pack(fill='x', padx=5, pady=3)
        ttk.Button(top, text="[Folder]", style='Dark.TButton', command=self._select_folder).pack(side='left', padx=2)
        ttk.Label(top, textvariable=self.project_path, style='Dark.TLabel').pack(side='left', padx=5, fill='x', expand=True)
        ttk.Label(top, text="MaxKB:", style='Dark.TLabel').pack(side='left')
        ttk.Spinbox(top, from_=10, to=5000, textvariable=self.max_file_size, width=6).pack(side='left', padx=2)
        ttk.Checkbutton(top, text="SrcOnly", variable=self.source_only, style='Dark.TCheckbutton').pack(side='left', padx=5)

        scan_bar = ttk.Frame(self.root, style='Dark.TFrame')
        scan_bar.pack(fill='x', padx=5, pady=2)
        ttk.Button(scan_bar, text="[Scan Folder]", style='Accent.TButton', command=self._scan_folder).pack(side='left', padx=2)
        ttk.Button(scan_bar, text="[Scan VS Project]", style='Accent.TButton', command=self._scan_vs).pack(side='left', padx=2)
        ttk.Button(scan_bar, text="[Check All]", style='Dark.TButton', command=lambda: self.tree.check_all()).pack(side='left', padx=2)
        ttk.Button(scan_bar, text="[Uncheck All]", style='Dark.TButton', command=lambda: self.tree.uncheck_all()).pack(side='left', padx=2)

        main = ttk.PanedWindow(self.root, orient='horizontal')
        main.pack(fill='both', expand=True, padx=5, pady=3)

        left = ttk.Frame(main, style='Dark.TFrame')
        self.tree = CheckboxTreeview(left, columns=('size',), show='tree headings')
        self.tree.heading('#0', text='File')
        self.tree.heading('size', text='Size')
        self.tree.column('size', width=70, anchor='e')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', self._on_tree_dblclick)
        main.add(left, weight=1)

        right = ttk.Frame(main, style='Dark.TFrame')
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill='both', expand=True)

        # Tab 1: Editor
        tab_edit = ttk.Frame(self.notebook, style='Dark.TFrame')
        self.code_editor = CodeEditor(tab_edit, bg='#1e1e2e')
        self.code_editor.pack(fill='both', expand=True)
        edit_btn = ttk.Frame(tab_edit, style='Dark.TFrame')
        edit_btn.pack(fill='x')
        ttk.Button(edit_btn, text="[Save]", style='Accent.TButton', command=self._save_file).pack(side='left', padx=2, pady=2)
        self.notebook.add(tab_edit, text=' Editor ')

        # Tab 2: Diff
        tab_diff = ttk.Frame(self.notebook, style='Dark.TFrame')
        ttk.Label(tab_diff, text="Paste AI diff below:", style='Dark.TLabel').pack(anchor='w', padx=3, pady=2)
        self.diff_text = scrolledtext.ScrolledText(tab_diff, bg='#181825', fg='#a6e3a1', font=('Consolas', 9), height=15, insertbackground='#f5e0dc')
        self.diff_text.pack(fill='both', expand=True, padx=3, pady=2)
        self.diff_log_label = ttk.Label(tab_diff, text="", style='Dark.TLabel', wraplength=500, justify='left')
        self.diff_log_label.pack(fill='x', padx=3, pady=2)
        diff_btns = ttk.Frame(tab_diff, style='Dark.TFrame')
        diff_btns.pack(fill='x', padx=3, pady=2)
        ttk.Button(diff_btns, text="[Analyze]", style='Dark.TButton', command=self._analyze_diff).pack(side='left', padx=2)
        ttk.Button(diff_btns, text="[Apply to Current]", style='Accent.TButton', command=self._apply_diff_current).pack(side='left', padx=2)
        ttk.Button(diff_btns, text="[Multi-file Apply+Save]", style='Accent.TButton', command=self._apply_multi_diff).pack(side='left', padx=2)
        self.notebook.add(tab_diff, text=' Diff ')

        # Tab 3: Prompt
        tab_prompt = ttk.Frame(self.notebook, style='Dark.TFrame')
        ttk.Label(tab_prompt, text="Prompt:", style='Dark.TLabel').pack(anchor='w', padx=3, pady=2)
        self.prompt_text = scrolledtext.ScrolledText(tab_prompt, bg='#181825', fg='#cdd6f4', font=('Consolas', 9), height=5, insertbackground='#f5e0dc')
        self.prompt_text.pack(fill='x', padx=3, pady=2)
        p_chk = ttk.Frame(tab_prompt, style='Dark.TFrame')
        p_chk.pack(fill='x', padx=3)
        ttk.Checkbutton(p_chk, text="Attach checked files", variable=self.attach_file, style='Dark.TCheckbutton').pack(side='left')
        ttk.Button(p_chk, text="[Copy to Clipboard]", style='Accent.TButton', command=self._merge_and_copy).pack(side='right', padx=2)
        ttk.Label(tab_prompt, text="Preview:", style='Dark.TLabel').pack(anchor='w', padx=3, pady=2)
        self.preview_text = scrolledtext.ScrolledText(tab_prompt, bg='#181825', fg='#6c7086', font=('Consolas', 9), state='disabled', insertbackground='#f5e0dc')
        self.preview_text.pack(fill='both', expand=True, padx=3, pady=2)
        self.notebook.add(tab_prompt, text=' Prompt ')

        # Tab 4: GitHub
        tab_gh = ttk.Frame(self.notebook, style='Dark.TFrame')
        gh_top = ttk.Frame(tab_gh, style='Dark.TFrame')
        gh_top.pack(fill='x', padx=3, pady=3)
        ttk.Label(gh_top, text="Repo:", style='Dark.TLabel').pack(side='left')
        self.repo_name_var = tk.StringVar()
        ttk.Entry(gh_top, textvariable=self.repo_name_var, width=25).pack(side='left', padx=3)
        ttk.Checkbutton(gh_top, text="Private", variable=self.repo_private, style='Dark.TCheckbutton').pack(side='left', padx=3)
        ttk.Button(gh_top, text="[New Repo]", style='Accent.TButton', command=self._upload_github).pack(side='left', padx=3)
        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(gh_top, variable=self.progress_var, maximum=100, length=150).pack(side='left', padx=5)
        gh_sync = ttk.Frame(tab_gh, style='Dark.TFrame')
        gh_sync.pack(fill='x', padx=3, pady=2)
        ttk.Label(gh_sync, text="Commit msg:", style='Dark.TLabel').pack(side='left')
        ttk.Entry(gh_sync, textvariable=self.commit_msg_var, width=40).pack(side='left', padx=3)
        ttk.Button(gh_sync, text="[Sync to GitHub]", style='Accent.TButton', command=self._sync_github).pack(side='left', padx=3)
        ttk.Button(gh_sync, text="[Rollback]", command=self._rollback_last).pack(side='left', padx=3)
        ttk.Checkbutton(gh_sync, text="Auto-sync after diff apply", variable=self.auto_sync, style='Dark.TCheckbutton').pack(side='left', padx=5)
        self.github_log = scrolledtext.ScrolledText(tab_gh, bg='#181825', fg='#a6e3a1', font=('Consolas', 9), state='disabled')
        self.github_log.pack(fill='both', expand=True, padx=3, pady=3)
        self.notebook.add(tab_gh, text=' GitHub ')

        main.add(right, weight=2)
        ttk.Label(self.root, textvariable=self.status_var, style='Dark.TLabel').pack(fill='x', padx=5, pady=2)

    # -- Folder/Scan --

    def _select_folder(self):
        p = filedialog.askdirectory()
        if p:
            self.project_path.set(p)
            self.status_var.set("folder: " + p)

    def _should_exclude(self, name):
        for pat in self.exclude_patterns:
            if pat.startswith('*') and name.lower().endswith(pat[1:].lower()):
                return True
            if name.lower() == pat.lower():
                return True
        return False

    def _is_target(self, path):
        ext = os.path.splitext(path)[1].lower()
        exts = self.source_only_ext if self.source_only.get() else self.all_code_ext
        return ext in exts

    def _format_size(self, size):
        if size < 1024: return f"{size} B"
        if size < 1024 * 1024: return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def _scan_folder(self):
        pp = self.project_path.get()
        if not pp:
            messagebox.showwarning("warning", "select folder first"); return
        self.all_files = []
        max_kb = self.max_file_size.get() * 1024
        for dirpath, dirnames, filenames in os.walk(pp):
            dirnames[:] = [d for d in dirnames if not self._should_exclude(d)]
            for fn in filenames:
                if self._should_exclude(fn): continue
                fp = os.path.join(dirpath, fn)
                if not self._is_target(fp): continue
                try: sz = os.path.getsize(fp)
                except OSError: continue
                if sz > max_kb: continue
                self.all_files.append((os.path.relpath(fp, pp), fp, sz))
        self._populate_tree()
        self.status_var.set(f"scan done: {len(self.all_files)} files")

    def _scan_vs(self):
        pp = self.project_path.get()
        if not pp:
            messagebox.showwarning("warning", "select folder first"); return
        projs = []
        for fn in os.listdir(pp):
            fp = os.path.join(pp, fn)
            if fn.endswith(('.csproj', '.vbproj', '.fsproj', '.vcxproj')):
                projs.append(fp)
        for dirpath, dirnames, filenames in os.walk(pp):
            dirnames[:] = [d for d in dirnames if not self._should_exclude(d)]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                if fn.endswith(('.csproj', '.vbproj', '.fsproj', '.vcxproj')):
                    if fp not in projs: projs.append(fp)
        if not projs:
            messagebox.showinfo("VS project", "no VS project found")
            self._scan_folder(); return

        self.all_files = []
        max_kb = self.max_file_size.get() * 1024
        collected = set()
        for proj_file in projs:
            proj_dir = os.path.dirname(proj_file)
            try:
                tree = ET.parse(proj_file)
                xroot = tree.getroot()
                ns = ''
                if xroot.tag.startswith('{'):
                    ns = xroot.tag.split('}')[0] + '}'
                for tag in ['Compile','Content','None','TypeScriptCompile',
                            'ClCompile','ClInclude','Page','Resource',
                            'ApplicationDefinition','EmbeddedResource']:
                    for elem in xroot.iter(f'{ns}{tag}'):
                        inc = elem.get('Include')
                        if inc:
                            fp = os.path.normpath(os.path.join(proj_dir, inc))
                            if os.path.isfile(fp) and fp not in collected and self._is_target(fp):
                                try: sz = os.path.getsize(fp)
                                except OSError: continue
                                if sz <= max_kb:
                                    self.all_files.append((os.path.relpath(fp, pp), fp, sz))
                                    collected.add(fp)
            except: continue
        if not self.all_files:
            self._scan_folder(); return
        self._populate_tree()
        self.status_var.set(f"VS scan: {len(self.all_files)} files")

    def _populate_tree(self):
        for item in self.tree.get_children(''): self.tree.delete(item)
        self.tree._checked.clear()
        folders = {}
        for rel, full, sz in sorted(self.all_files, key=lambda x: x[0]):
            parts = rel.replace('\\', '/').split('/')
            parent = ''
            for i, part in enumerate(parts[:-1]):
                key = '/'.join(parts[:i + 1])
                if key not in folders:
                    folders[key] = self.tree.insert_with_check(parent, 'end', text=part, checked=True, values=('',))
                parent = folders[key]
            fn = parts[-1]
            is_sens = any((p.startswith('*') and fn.lower().endswith(p[1:].lower())) or fn.lower() == p.lower() for p in self.sensitive_patterns)
            self.tree.insert_with_check(parent, 'end', text=('!! ' if is_sens else '') + fn, checked=not is_sens, values=(self._format_size(sz),))

    def _on_tree_dblclick(self, event):
        sel = self.tree.selection()
        if not sel: return
        txt = self.tree.item(sel[0], 'text')
        name = txt.lstrip('[v] [_] !! ').strip()
        for rel, full, sz in self.all_files:
            if rel.replace('\\', '/').endswith(name) or os.path.basename(rel) == name:
                self._current_file_path = full
                self.code_editor.load_file(full)
                self.notebook.select(0)
                self.status_var.set("opened: " + rel)
                return

    def _save_file(self):
        if self.code_editor.save_file():
            name = os.path.basename(self.code_editor.file_path)
            self.status_var.set("saved: " + name)

    # -- Diff --

    def _analyze_diff(self):
        dt = self.diff_text.get("1.0", tk.END).strip()
        if not dt:
            self.diff_log_label.config(text="[!] diff text empty"); return
        pm = {r: f for r, f, *_ in self.all_files}
        a = self.diff_engine.analyze(dt, pm)
        fmt_n = {'unrecognized': '[X] unrecognized', 'single_file': 'single file',
                 'single_file_named': 'single file (named)', 'multi_file': 'multi file'}
        lines = [f"Format: {fmt_n.get(a['format'], '?')}",
                 f"Files: {a['file_count']} | Changes: {a['total_changes']}"]
        for f in a['files']:
            st = '[OK]' if f['found_in_project'] else '[X]'
            detail = []
            if f.get('rep_count'): detail.append(f"replace:{f['rep_count']}")
            if f.get('del_count'): detail.append(f"delete:{f['del_count']}")
            if f.get('ins_count'): detail.append(f"insert:{f['ins_count']}")
            dtype = ' + '.join(detail) if detail else str(f['change_count'])
            lines.append(f"  {st} {f['path']} -- {dtype}")
        if a['format'] == 'single_file':
            lines.append("\n-> use 'Apply to Current'")
        elif a['format'] in ('single_file_named', 'multi_file'):
            lines.append("\n-> use 'Multi-file Apply+Save'")
        elif a['format'] == 'unrecognized':
            lines.append("\n-> check format: @@ N-M REPLACE ... @@ END")
        self.diff_log_label.config(text='\n'.join(lines))
        self.status_var.set(f"analyzed: {a['file_count']} files, {a['total_changes']} changes")

    def _apply_diff_current(self):
        dt = self.diff_text.get("1.0", tk.END).strip()
        if not dt:
            messagebox.showwarning("warning", "diff is empty"); return
        if not self._current_file_path:
            messagebox.showwarning("warning", "open a file first"); return
        parsed = self.diff_engine.parse(dt)
        if not parsed:
            messagebox.showerror("parse error",
                "no @@ commands found.\n\n"
                "Format:\n"
                "@@ 15-23 REPLACE\n"
                "new code...\n"
                "@@ END\n"
                "@@ 50 DELETE 3\n"
                "@@ 60 INSERT\n"
                "new code...\n"
                "@@ END"); return
        all_cmds = []
        for cmds in parsed.values():
            all_cmds.extend(cmds)
        if not all_cmds:
            messagebox.showwarning("warning", "no changes"); return
        content = self.code_editor.get_content()
        new_c, msgs = self.diff_engine.apply_to_content(content, all_cmds)
        log = '\n'.join(msgs)
        if any('[OK]' in m for m in msgs):
            self.code_editor.set_content(new_c)
            self.status_var.set("diff applied -- save needed")
        else:
            self.status_var.set("apply failed")
        self.diff_log_label.config(text=log[:600])
        messagebox.showinfo("Diff Result", log)

    def _apply_multi_diff(self):
        dt = self.diff_text.get("1.0", tk.END).strip()
        if not dt:
            messagebox.showwarning("warning", "diff is empty"); return
        pp = self.project_path.get()
        if not pp:
            messagebox.showwarning("warning", "select project folder first"); return
        pm = {r: f for r, f, *_ in self.all_files}

        parsed = self.diff_engine.parse(dt)

        if not parsed:
            # 디버그: 토큰 감지 정보
            text = TextNormalizer.full(dt)
            tlines = text.split('\n')
            found_file = sum(1 for l in tlines if LineDiffParser.RE_FILE_START.match(l))
            found_replace = sum(1 for l in tlines if LineDiffParser.RE_CMD_REPLACE.match(l.strip()))
            found_delete = sum(1 for l in tlines if LineDiffParser.RE_CMD_DELETE.match(l.strip()))
            found_insert = sum(1 for l in tlines if LineDiffParser.RE_CMD_INSERT.match(l.strip()))
            found_end = sum(1 for l in tlines if LineDiffParser.RE_CMD_END.match(l.strip()))

            messagebox.showerror("parse error",
                f"No @@ commands found.\n\n"
                f"Tokens detected:\n"
                f"  === FILE: {found_file}\n"
                f"  @@ N-M REPLACE: {found_replace}\n"
                f"  @@ N DELETE: {found_delete}\n"
                f"  @@ N INSERT: {found_insert}\n"
                f"  @@ END: {found_end}\n"
                f"\nExpected format:\n"
                f"=== FILE: path/file.js ===\n"
                f"@@ 15-23 REPLACE\n"
                f"new code\n"
                f"@@ END\n"
                f"=== END FILE ===")
            return

        a = self.diff_engine.analyze(dt, pm)

        if a['total_changes'] == 0:
            messagebox.showwarning("warning", "no valid changes"); return

        # Confirmation dialog
        fl_lines = []
        for f in a['files']:
            st = '[OK]' if f['found_in_project'] else '[X]'
            tags = []
            if f.get('rep_count'): tags.append(f"R:{f['rep_count']}")
            if f.get('del_count'): tags.append(f"D:{f['del_count']}")
            if f.get('ins_count'): tags.append(f"I:{f['ins_count']}")
            fl_lines.append(f"  {st} {f['path']} ({'+'.join(tags)})")

        msg = f"{a['file_count']} files, {a['total_changes']} changes\n\n"
        msg += '\n'.join(fl_lines) + '\n'

        nf = sum(1 for f in a['files'] if not f['found_in_project'] and f['path'] != '__current_file__')
        if nf:
            msg += f"\n[!] {nf} files not found\n"
        msg += "\nProceed? (.bak backup will be created)"

        if not messagebox.askyesno("Multi-file Apply", msg):
            return

        results, summary = self.diff_engine.apply_and_save(dt, pm, pp)

        log_lines = ["=" * 55, "Multi-file Diff Result",
            f"saved:{summary['saved']} failed:{summary['failed']} skipped:{summary['skipped']}",
            "=" * 55]
        for r in results:
            log_lines.append(f"\n{r['filepath']}")
            if r['resolved_path']:
                log_lines.append(f"   -> {r['resolved_path']}")
            for m in r['messages']:
                log_lines.append(f"   {m}")
        log = '\n'.join(log_lines)

        self.notebook.select(3)
        self.github_log.config(state=tk.NORMAL)
        self.github_log.delete("1.0", tk.END)
        self.github_log.insert("1.0", log)
        self.github_log.config(state=tk.DISABLED)

        if self._current_file_path:
            for r in results:
                if r['resolved_path'] == self._current_file_path and r['success']:
                    try:
                        c, *_ = EncodingHandler.read_file(self._current_file_path)
                        self.code_editor.set_content(c)
                    except: pass
                    break
        self._last_saved_files = [r['filepath'] for r in results if r['success']]
        messagebox.showinfo("Done",
            f"Saved: {summary['saved']}\nFailed: {summary['failed']}\nSkipped: {summary['skipped']}")
        self.status_var.set(f"multi: saved {summary['saved']} failed {summary['failed']}")
        if self.auto_sync.get() and summary['saved'] > 0:
            file_list = ', '.join(self._last_saved_files[:5])
            if len(self._last_saved_files) > 5:
                file_list += f" +{len(self._last_saved_files)-5} more"
            msg = f"diff applied: {file_list}"
            self.commit_msg_var.set(msg)
            self.root.after(500, self._do_sync)

    # -- Prompt --

    def _get_checked_files(self):
        checked = self.tree.get_checked()
        result = []
        for rel, full, sz in self.all_files:
            fn = os.path.basename(rel)
            for cid in checked:
                txt = self.tree.item(cid, 'text')
                # strip checkbox prefix and warning prefix
                clean = txt
                for prefix in ['[v] ', '[_] ', '!! ']:
                    if clean.startswith(prefix):
                        clean = clean[len(prefix):]
                clean = clean.strip()
                if clean == fn:
                    result.append((rel, full, sz)); break
        return result

    def _merge_and_copy(self):
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        parts = []
        if prompt:
            parts.append(prompt)
            parts.append("")

        if self.attach_file.get():
            files = self._get_checked_files()
            if not files:
                messagebox.showwarning("warning", "no files checked"); return

            parts.append("---")
            parts.append(f"Attached files ({len(files)})")
            parts.append("")
            parts.append("When modifying files, use ONLY this line-number format:")
            parts.append("")
            parts.append("```")
            parts.append("=== FILE: relative/path/file.ext ===")
            parts.append("@@ 15-23 REPLACE")
            parts.append("new code for lines 15 to 23")
            parts.append("@@ END")
            parts.append("@@ 50 DELETE 3")
            parts.append("@@ 60 INSERT")
            parts.append("code to insert after line 60")
            parts.append("@@ END")
            parts.append("=== END FILE ===")
            parts.append("```")
            parts.append("")
            parts.append("Rules:")
            parts.append("- Line numbers refer to the ORIGINAL file (shown as N| prefix)")
            parts.append("- @@ START-END REPLACE : replace lines START through END with new content")
            parts.append("- @@ N DELETE COUNT : delete COUNT lines starting from line N")
            parts.append("- @@ N INSERT : insert new content AFTER line N (use 0 to insert at top)")
            parts.append("- Each REPLACE/INSERT block must end with @@ END")
            parts.append("- Do NOT use SEARCH/REPLACE blocks. Use ONLY @@ line commands.")
            parts.append("- After making changes, state the REASON for each modification so it can be used as a GitHub commit message.")
            parts.append("---")

            for i, (rel, full, sz) in enumerate(files, 1):
                try:
                    content, *_ = EncodingHandler.read_file(full)
                except Exception:
                    content = "(read error)"
                ext = os.path.splitext(rel)[1].lstrip('.')
                parts.append(f"### File {i}: {rel}")
                parts.append(f"```{ext}")
                for ln_num, line in enumerate(content.split('\n'), 1):
                    parts.append(f"{ln_num:4d}| {line}")
                parts.append("```")
                parts.append("")

        if not parts:
            messagebox.showwarning("warning", "enter prompt or attach files"); return

        result = '\n'.join(parts)
        self.root.clipboard_clear()
        self.root.clipboard_append(result)

        self.preview_text.config(state='normal')
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", result)
        self.preview_text.config(state='disabled')

        chars = len(result)
        tokens = chars // 4
        messagebox.showinfo("Copied",
            f"Clipboard copied\n\nChars: {chars:,}\nTokens (est): {tokens:,}")
        self.status_var.set(f"copied: {chars:,} chars, ~{tokens:,} tokens")

    # -- GitHub --

    def _upload_github(self):
        rn = self.repo_name_var.get().strip()
        if not rn:
            messagebox.showwarning("warning", "enter repo name"); return
        files = self._get_checked_files()
        if not files:
            messagebox.showwarning("warning", "select files to upload"); return
        pp = self.project_path.get()
        if not pp:
            messagebox.showwarning("warning", "select project folder first"); return

        self.notebook.select(3)
        self.github_log.config(state='normal')
        self.github_log.delete("1.0", tk.END)
        self.github_log.config(state='disabled')

        def log_cb(msg):
            self.github_log.config(state='normal')
            self.github_log.insert(tk.END, msg + '\n')
            self.github_log.see(tk.END)
            self.github_log.config(state='disabled')

        self.uploader.log = log_cb

        if not self.uploader.check_git():
            messagebox.showerror("error", "Git not installed"); return
        if not self.uploader.check_gh():
            messagebox.showerror("error", "GitHub CLI needed"); return
        if not self.uploader.check_auth():
            messagebox.showerror("error", "GitHub auth needed. Run: gh auth login"); return

        def do_upload():
            ok, result = self.uploader.create_and_push(
                files, pp, rn, private=self.repo_private.get(),
                progress_cb=lambda v: self.progress_var.set(v))
            self.root.after(0, lambda: self._upload_done(ok, result))

        self.status_var.set("uploading...")
        threading.Thread(target=do_upload, daemon=True).start()

    def _upload_done(self, ok, result):
        self.progress_var.set(100 if ok else 0)
        if ok:
            self.status_var.set("upload done: " + result)
            if messagebox.askyesno("success", f"Upload done!\n{result}\n\nCopy URL?"):
                self.root.clipboard_clear()
                self.root.clipboard_append(result)
        else:
            self.status_var.set("upload failed")
            messagebox.showerror("failed", "Upload failed:\n" + result)

    def _sync_github(self):
        rn = self.repo_name_var.get().strip()
        if not rn:
            messagebox.showwarning("warning", "enter repo name"); return
        pp = self.project_path.get()
        if not pp:
            messagebox.showwarning("warning", "select project folder first"); return
        msg = self.commit_msg_var.get().strip()
        if not msg:
            msg = "update by ProjectScan"
        self._do_sync()

    def _do_sync(self):
        rn = self.repo_name_var.get().strip()
        pp = self.project_path.get()
        if not rn or not pp:
            self.status_var.set("sync: need repo name and project path")
            return
        msg = self.commit_msg_var.get().strip() or "update by ProjectScan"
        self.notebook.select(3)

        def log_cb(text):
            self.github_log.config(state='normal')
            self.github_log.insert(tk.END, text + '\n')
            self.github_log.see(tk.END)
            self.github_log.config(state='disabled')

        self.uploader.log = log_cb
        self.github_log.config(state='normal')
        self.github_log.insert(tk.END, f"\n{'='*40}\nSync: {msg}\n{'='*40}\n")
        self.github_log.config(state='disabled')

        def do_work():
            self.uploader.init_local_repo(pp, rn)
            ok, result = self.uploader.sync_push(
                pp, msg,
                progress_cb=lambda v: self.progress_var.set(v))
            self.root.after(0, lambda: self._sync_done(ok, result))

        self.status_var.set("syncing to GitHub...")
        threading.Thread(target=do_work, daemon=True).start()

    def _sync_done(self, ok, result):
        self.progress_var.set(100 if ok else 0)
        if ok:
            self.status_var.set(f"sync done: {result}")
            self.github_log.config(state='normal')
            self.github_log.insert(tk.END, f"\n[OK] {result}\n")
            self.github_log.config(state='disabled')
        else:
            self.status_var.set("sync failed")
            self.github_log.config(state='normal')
            self.github_log.insert(tk.END, f"\n[FAIL] {result}\n")
            self.github_log.config(state='disabled')
            messagebox.showerror("Sync Failed", result)

    def _rollback_last(self):
        """Rollback to the previous git commit and force push."""
        pp = self.project_path.get()
        if not pp:
            messagebox.showwarning("warning", "select project folder first")
            return
        # Show recent commits for confirmation
        ok, log_out, _ = self.uploader.run_cmd(
            'git log --oneline -5', cwd=pp)
        if not ok or not log_out:
            messagebox.showerror("error", "no git history found")
            return
        confirm = messagebox.askyesno(
            "Rollback",
            f"Recent commits:\n\n{log_out}\n\nRollback to previous commit?\n"
            "(current commit will be undone)")
        if not confirm:
            return

        def log_cb(text):
            self.github_log.config(state='normal')
            self.github_log.insert(tk.END, text + '\n')
            self.github_log.see(tk.END)
            self.github_log.config(state='disabled')

        self.uploader.log = log_cb
        self.github_log.config(state='normal')
        self.github_log.insert(tk.END, f"\n{'='*40}\nRollback\n{'='*40}\n")
        self.github_log.config(state='disabled')

        def do_rollback():
            # Reset to previous commit (keeps nothing from current)
            ok_r, _, err_r = self.uploader.run_cmd(
                'git reset --hard HEAD~1', cwd=pp)
            if not ok_r:
                self.root.after(0, lambda: self._rollback_done(False, err_r))
                return
            # Get branch name
            ok_br, br_out, _ = self.uploader.run_cmd(
                'git branch --show-current', cwd=pp)
            branch = br_out.strip() if ok_br and br_out and br_out.strip() else 'master'
            # Force push the rollback
            ok_p, _, err_p = self.uploader.run_cmd(
                f'git push -u origin {branch} --force', cwd=pp)
            if ok_p:
                self.root.after(0, lambda: self._rollback_done(True, "rollback complete"))
            else:
                self.root.after(0, lambda: self._rollback_done(False, err_p))

        threading.Thread(target=do_rollback, daemon=True).start()

    def _rollback_done(self, ok, result):
        if ok:
            self.status_var.set("rollback done")
            self.github_log.config(state='normal')
            self.github_log.insert(tk.END, f"\n[OK] {result}\n")
            self.github_log.config(state='disabled')
            messagebox.showinfo("Rollback", "Rollback complete.\nReload files to see changes.")
        else:
            self.status_var.set("rollback failed")
            self.github_log.config(state='normal')
            self.github_log.insert(tk.END, f"\n[FAIL] {result}\n")
            self.github_log.config(state='disabled')
            messagebox.showerror("Rollback Failed", result)


# ════════════════════════════════════════════════════════════
if __name__ == '__main__':
    root = tk.Tk()
    app = ProjectScan(root)
    root.mainloop()