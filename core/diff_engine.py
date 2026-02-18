#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_engine.py - Line-number based diff parser and engine for ProjectScan v6.1
Supports: REPLACE, DELETE, INSERT, CREATE FILE, DELETE FILE
With brace-balance validation for C#, VB, Java, etc.

v6.1 fixes:
  - C# verbatim string (@"...") support
  - C# interpolated string ($"...", $@"...") brace exclusion
  - Proper char literal ('x') handling separate from strings
  - Multi-language comment styles (C#, Java, Go, Rust, etc.)
"""

import os
import re
import shutil
from .encoding_handler import EncodingHandler, TextNormalizer


# ============================================================
#  Brace Balance Utilities
# ============================================================

BRACE_LANGUAGES = {
    '.cs', '.vb', '.java', '.js', '.ts', '.jsx', '.tsx',
    '.go', '.rs', '.swift', '.kt', '.cpp', '.c', '.h', '.hpp',
}


def strip_strings_and_comments(text):
    """
    Remove string literals and comments for accurate brace counting.

    Handles:
      - C/C++/Java/C#/JS single-line (//) and block comments (/* */)
      - Double-quoted strings with backslash escapes ("...")
      - Single-quoted char literals ('x') - treated as 1-3 char tokens
      - C# verbatim strings (@"..." where "" is escape, not \\)
      - C# interpolated strings ($"...{expr}..." - braces inside are KEPT)
      - C# verbatim interpolated ($@"..." or @$"...")
      - Template literals (`...`) for JS/TS
    """
    result = []
    i = 0
    length = len(text)

    in_block_comment = False
    in_line_comment = False

    while i < length:
        c = text[i]

        # === Inside block comment ===
        if in_block_comment:
            if c == '*' and i + 1 < length and text[i + 1] == '/':
                in_block_comment = False
                i += 2
                continue
            if c == '\n':
                result.append(c)
            i += 1
            continue

        # === Inside line comment ===
        if in_line_comment:
            if c == '\n':
                in_line_comment = False
                result.append(c)
            i += 1
            continue

        # === Check for comment start ===
        if c == '/' and i + 1 < length:
            if text[i + 1] == '*':
                in_block_comment = True
                i += 2
                continue
            if text[i + 1] == '/':
                in_line_comment = True
                i += 2
                continue

        # === C# verbatim / interpolated string detection ===
        if c in ('@', '$') and i + 1 < length:
            is_verbatim = False
            is_interpolated = False
            quote_start = -1

            if c == '@' and text[i + 1] == '"':
                is_verbatim = True
                quote_start = i + 2
            elif c == '$' and text[i + 1] == '"':
                is_interpolated = True
                quote_start = i + 2
            elif c == '$' and i + 2 < length and text[i + 1] == '@' and text[i + 2] == '"':
                is_verbatim = True
                is_interpolated = True
                quote_start = i + 3
            elif c == '@' and i + 2 < length and text[i + 1] == '$' and text[i + 2] == '"':
                is_verbatim = True
                is_interpolated = True
                quote_start = i + 3

            if is_verbatim or is_interpolated:
                i = quote_start
                interp_depth = 0
                while i < length:
                    sc = text[i]
                    if is_verbatim:
                        if sc == '"':
                            if i + 1 < length and text[i + 1] == '"':
                                i += 2
                                continue
                            else:
                                i += 1
                                break
                    else:
                        if sc == '\\':
                            i += 2
                            continue
                        if sc == '"' and interp_depth == 0:
                            i += 1
                            break

                    if is_interpolated:
                        if sc == '{':
                            if i + 1 < length and text[i + 1] == '{':
                                i += 2
                                continue
                            else:
                                interp_depth += 1
                                result.append(sc)
                                i += 1
                                continue
                        if sc == '}':
                            if i + 1 < length and text[i + 1] == '}':
                                i += 2
                                continue
                            else:
                                interp_depth -= 1
                                result.append(sc)
                                i += 1
                                continue
                        # Inside interpolated expression: keep all code characters
                        if interp_depth > 0:
                            # Handle nested strings inside expressions
                            if sc == '"':
                                i += 1
                                while i < length:
                                    nc = text[i]
                                    if nc == '\\':
                                        i += 2
                                        continue
                                    if nc == '"':
                                        i += 1
                                        break
                                    i += 1
                                continue
                            result.append(sc)
                            i += 1
                            continue

                    if sc == '\n':
                        result.append(sc)
                    i += 1

                continue

        # === Regular double-quoted string ===
        if c == '"':
            i += 1
            while i < length:
                sc = text[i]
                if sc == '\\':
                    i += 2
                    continue
                if sc == '"':
                    i += 1
                    break
                if sc == '\n':
                    result.append(sc)
                i += 1
            continue

        # === Char literal (single quote) ===
        if c == "'":
            found_close = False
            scan = i + 1
            limit = min(i + 6, length)
            while scan < limit:
                if text[scan] == '\\':
                    scan += 2
                    continue
                if text[scan] == "'":
                    found_close = True
                    i = scan + 1
                    break
                if text[scan] == '\n':
                    break
                scan += 1
            if found_close:
                continue
            else:
                result.append(c)
                i += 1
                continue

        # === JS/TS template literal ===
        if c == '`':
            i += 1
            while i < length:
                sc = text[i]
                if sc == '\\':
                    i += 2
                    continue
                if sc == '`':
                    i += 1
                    break
                if sc == '$' and i + 1 < length and text[i + 1] == '{':
                    result.append('{')
                    i += 2
                    depth = 1
                    while i < length and depth > 0:
                        tc = text[i]
                        if tc == '{':
                            depth += 1
                            result.append(tc)
                        elif tc == '}':
                            depth -= 1
                            result.append(tc)
                        elif tc == '\n':
                            result.append(tc)
                        i += 1
                    continue
                if sc == '\n':
                    result.append(sc)
                i += 1
            continue

        # === Normal character - keep it ===
        result.append(c)
        i += 1

    return ''.join(result)


def check_brace_balance(text):
    """Check {}, (), [] balance. Returns (ok, message)."""
    cleaned = strip_strings_and_comments(text)
    pairs = {'{': '}', '(': ')', '[': ']'}
    close_to_open = {v: k for k, v in pairs.items()}
    stack = []
    line_num = 1
    for ch in cleaned:
        if ch == '\n':
            line_num += 1
            continue
        if ch in pairs:
            stack.append((ch, line_num))
        elif ch in close_to_open:
            expected_open = close_to_open[ch]
            if not stack:
                return False, (
                    "unexpected '%s' at line ~%d with no matching '%s'"
                    % (ch, line_num, expected_open))
            top_ch, top_line = stack[-1]
            if top_ch != expected_open:
                return False, (
                    "mismatched '%s' at line ~%d, "
                    "expected closing for '%s' opened at line ~%d"
                    % (ch, line_num, top_ch, top_line))
            stack.pop()
    if stack:
        unclosed = ["'%s' at line ~%d" % (ch, ln) for ch, ln in stack[-5:]]
        return False, "%d unclosed bracket(s): %s" % (len(stack), ', '.join(unclosed))
    opens = cleaned.count('{')
    closes = cleaned.count('}')
    return True, "braces balanced: %d open, %d close" % (opens, closes)


def is_brace_language(filepath):
    """Return True if file extension is a brace-based language."""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in BRACE_LANGUAGES


# ============================================================
#  LineDiffParser
# ============================================================

class LineDiffParser:
    RE_FILE_START = re.compile(r'^\s*={2,}\s*FILE:\s*(.+?)\s*={2,}\s*$')
    RE_FILE_END = re.compile(r'^\s*={2,}\s*END\s+FILE\s*={2,}\s*$')
    RE_CREATE_FILE = re.compile(r'^\s*={2,}\s*CREATE\s+FILE:\s*(.+?)\s*={2,}\s*$')
    RE_DELETE_FILE = re.compile(r'^\s*={2,}\s*DELETE\s+FILE:\s*(.+?)\s*={2,}\s*$')
    RE_CMD_REPLACE = re.compile(
        r'^\s*@@\s*(\d+)\s*-\s*(\d+)\s+REPLACE\s*$', re.IGNORECASE)
    RE_CMD_DELETE = re.compile(
        r'^\s*@@\s*(\d+)\s+DELETE\s+(\d+)\s*$', re.IGNORECASE)
    RE_CMD_INSERT = re.compile(
        r'^\s*@@\s*(\d+)\s+INSERT\s*$', re.IGNORECASE)
    RE_CMD_END = re.compile(
        r'^\s*@@\s*END\s*$', re.IGNORECASE)

    def parse(self, text):
        if not text or not text.strip():
            return {}, []
        text = TextNormalizer.full(text)
        lines = text.split('\n')

        file_ops = self._parse_file_ops(lines)

        file_blocks = self._split_files(lines)
        if not file_blocks:
            cmds = self._parse_commands(lines)
            if cmds:
                return {'__current_file__': cmds}, file_ops
            return {}, file_ops

        result = {}
        for fp, block_lines in file_blocks.items():
            cmds = self._parse_commands(block_lines)
            if cmds:
                if fp in result:
                    result[fp].extend(cmds)
                else:
                    result[fp] = cmds
        return result, file_ops

    def _parse_file_ops(self, lines):
        ops = []
        i = 0
        while i < len(lines):
            m = self.RE_CREATE_FILE.match(lines[i])
            if m:
                fp = m.group(1).strip().strip('`\'"')
                content_lines = []
                i += 1
                while i < len(lines):
                    if self.RE_FILE_END.match(lines[i]):
                        i += 1
                        break
                    content_lines.append(lines[i])
                    i += 1
                ops.append({
                    'op': 'create',
                    'path': fp,
                    'content': '\n'.join(content_lines),
                })
                continue
            m = self.RE_DELETE_FILE.match(lines[i])
            if m:
                fp = m.group(1).strip().strip('`\'"')
                ops.append({'op': 'delete', 'path': fp})
                i += 1
                continue
            i += 1
        return ops

    def _split_files(self, lines):
        blocks = {}
        headers = []
        for i, line in enumerate(lines):
            if self.RE_CREATE_FILE.match(line) or self.RE_DELETE_FILE.match(line):
                continue
            m = self.RE_FILE_START.match(line)
            if m:
                fp = m.group(1).strip().strip('`\'"')
                headers.append((i, fp))
        if not headers:
            return {}
        for hi, (hline, fp) in enumerate(headers):
            start = hline + 1
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
        commands = []
        i = 0
        while i < len(lines):
            line = lines[i]
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


# ============================================================
#  LineDiffEngine
# ============================================================

class LineDiffEngine:

    def __init__(self):
        self.parser = LineDiffParser()
        self._current_filepath = None

    def parse(self, text):
        return self.parser.parse(text)

    def analyze(self, diff_text, path_map=None):
        parsed, file_ops = self.parser.parse(diff_text)
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
        if not parsed and not file_ops:
            fmt = 'unrecognized'
        elif file_ops and not parsed:
            fmt = 'file_ops_only'
        elif '__current_file__' in parsed:
            fmt = 'single_file'
        elif len(parsed) == 1:
            fmt = 'single_file_named'
        else:
            fmt = 'multi_file'
        return {'file_count': len(parsed), 'files': files,
                'total_changes': tc, 'format': fmt,
                'file_ops': file_ops}

    def apply_to_content(self, original, commands):
        if not commands:
            return original, ["[!] no changes"]
        file_lines = original.split('\n')
        orig_count = len(file_lines)
        msgs = []
        ok = 0
        errors = 0

        do_brace = (self._current_filepath is not None
                    and is_brace_language(self._current_filepath))

        sorted_cmds = sorted(
            commands,
            key=lambda c: c.get('start', c.get('after', 0)),
            reverse=True)
        for cmd in sorted_cmds:
            ctype = cmd['type']
            if ctype == 'replace':
                s = cmd['start'] - 1
                e = cmd['end']
                if s < 0:
                    s = 0
                if e > len(file_lines):
                    e = len(file_lines)
                if s > len(file_lines):
                    msgs.append(
                        "[X] REPLACE %d-%d: start(%d) > file length(%d)"
                        % (cmd['start'], cmd['end'], cmd['start'], len(file_lines)))
                    errors += 1
                    continue
                new_lines = cmd['content'].split('\n')
                is_full = (cmd['start'] <= 1 and cmd['end'] >= orig_count)
                if is_full and orig_count > 10 and len(new_lines) < orig_count * 0.1:
                    msgs.append(
                        "[BLOCK] REPLACE %d-%d: full replace would reduce %d -> %d lines"
                        % (cmd['start'], cmd['end'], orig_count, len(new_lines)))
                    errors += 1
                    continue
                old_count = e - s
                saved_old = file_lines[s:e]
                file_lines[s:e] = new_lines

                # Brace balance check after this REPLACE
                if do_brace:
                    joined = '\n'.join(file_lines)
                    brace_ok, brace_msg = check_brace_balance(joined)
                    if not brace_ok:
                        # Rollback
                        file_lines[s:s + len(new_lines)] = saved_old
                        msgs.append(
                            "[BLOCK] REPLACE %d-%d: brace imbalance - %s"
                            % (cmd['start'], cmd['end'], brace_msg))
                        msgs.append(
                            "[ROLLBACK] REPLACE %d-%d reverted due to brace imbalance"
                            % (cmd['start'], cmd['end']))
                        errors += 1
                        continue

                ok += 1
                msgs.append(
                    "[OK] REPLACE %d-%d (%dlines -> %dlines)"
                    % (cmd['start'], cmd['end'], old_count, len(new_lines)))

            elif ctype == 'delete':
                s = cmd['start'] - 1
                count = cmd['count']
                if s < 0:
                    s = 0
                if s >= len(file_lines):
                    msgs.append(
                        "[X] DELETE %d: start(%d) > file length(%d)"
                        % (cmd['start'], cmd['start'], len(file_lines)))
                    errors += 1
                    continue
                e = min(s + count, len(file_lines))
                actual = e - s
                del file_lines[s:e]
                ok += 1
                msgs.append(
                    "[OK] DELETE %d x%d (%dlines removed)"
                    % (cmd['start'], count, actual))

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
                    "[OK] INSERT after %d (%dlines added)"
                    % (cmd['after'], len(new_lines)))

        msgs.insert(0, "Result: %d ok, %d errors / %d total" % (ok, errors, len(commands)))

        result = '\n'.join(file_lines)
        orig_len = len(original.strip())
        result_len = len(result.strip())
        if orig_len > 200 and result_len < orig_len * 0.1:
            pct = result_len * 100 // orig_len if orig_len > 0 else 0
            msgs.append("[BLOCK] result is only %d%% of original -> keeping original" % pct)
            return original, msgs

        # Final brace balance check on complete result
        if do_brace:
            brace_ok, brace_msg = check_brace_balance(result)
            if not brace_ok:
                msgs.append("[BLOCK] FINAL brace check failed: " + brace_msg)
                msgs.append("[BLOCK] entire patch rejected - keeping original file")
                return original, msgs
            else:
                msgs.append("[BRACE OK] " + brace_msg)

        return result, msgs

    def resolve_and_apply_all(self, diff_text, path_map, project_path=None):
        parsed, file_ops = self.parser.parse(diff_text)
        results = []

        for fop in file_ops:
            if fop['op'] == 'create':
                fp = fop['path']
                if project_path:
                    full_path = os.path.join(project_path, fp.replace('/', os.sep))
                else:
                    full_path = fp
                try:
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    if os.path.isfile(full_path):
                        bp = full_path + '.bak'
                        n = 1
                        while os.path.exists(bp):
                            bp = full_path + '.bak' + str(n)
                            n += 1
                        shutil.copy2(full_path, bp)
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(fop['content'])
                    results.append({
                        'filepath': fp, 'resolved_path': full_path,
                        'success': True, 'new_content': fop['content'],
                        'messages': ["[CREATED] " + fp],
                        'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                except Exception as e:
                    results.append({
                        'filepath': fp, 'resolved_path': full_path,
                        'success': False, 'new_content': None,
                        'messages': ["[X] create error: " + str(e)],
                        'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})

            elif fop['op'] == 'delete':
                fp = fop['path']
                rp = self._resolve(fp, path_map) if path_map else None
                if rp is None and project_path:
                    cand = os.path.join(project_path, fp.replace('/', os.sep))
                    if os.path.exists(cand):
                        rp = cand
                if rp and os.path.exists(rp):
                    try:
                        if os.path.isdir(rp):
                            bp = rp + '_deleted_bak'
                            if os.path.exists(bp):
                                shutil.rmtree(bp)
                            shutil.copytree(rp, bp)
                            shutil.rmtree(rp)
                            results.append({
                                'filepath': fp, 'resolved_path': rp,
                                'success': True, 'new_content': None,
                                'messages': [
                                    "[DELETED FOLDER] " + fp,
                                    "[BACKUP] " + os.path.basename(bp)],
                                'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                        else:
                            bp = rp + '.deleted_bak'
                            shutil.copy2(rp, bp)
                            os.remove(rp)
                            results.append({
                                'filepath': fp, 'resolved_path': rp,
                                'success': True, 'new_content': None,
                                'messages': [
                                    "[DELETED] " + fp,
                                    "[BACKUP] " + os.path.basename(bp)],
                                'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                    except Exception as e:
                        results.append({
                            'filepath': fp, 'resolved_path': rp,
                            'success': False, 'new_content': None,
                            'messages': ["[X] delete error: " + str(e)],
                            'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                else:
                    results.append({
                        'filepath': fp, 'resolved_path': None,
                        'success': False, 'new_content': None,
                        'messages': ["[X] not found for delete: " + fp],
                        'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})

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
                    'messages': ["[X] not found: " + fp],
                    'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                continue
            try:
                content, enc, bom, le = EncodingHandler.read_file(rp)
            except Exception as e:
                results.append({
                    'filepath': fp, 'resolved_path': rp,
                    'success': False, 'new_content': None,
                    'messages': ["[X] read error: " + str(e)],
                    'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                continue

            self._current_filepath = rp
            new_c, msgs = self.apply_to_content(content, cmds)
            self._current_filepath = None

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
        saved, failed, skipped, created, deleted = 0, 0, 0, 0, 0
        brace_blocked = 0
        for r in results:
            if any('[CREATED]' in m for m in r['messages']):
                if r['success']:
                    created += 1
                    if r.get('resolved_path', '').endswith('.py'):
                        try:
                            import py_compile
                            py_compile.compile(r['resolved_path'], doraise=True)
                            r['messages'].append("[SYNTAX OK]")
                        except py_compile.PyCompileError as pe:
                            r['messages'].append("[SYNTAX ERROR] " + str(pe))
                            r['syntax_error'] = True
                else:
                    failed += 1
                continue
            if any("[DELETED" in m for m in r["messages"]):
                if r['success']:
                    deleted += 1
                else:
                    failed += 1
                continue

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
                    bp = r['resolved_path'] + '.bak' + str(n)
                    n += 1
                shutil.copy2(r['resolved_path'], bp)

                fext = os.path.splitext(r['resolved_path'])[1].lower()
                if fext in BRACE_LANGUAGES:
                    brace_ok, brace_msg = check_brace_balance(r['new_content'])
                    if not brace_ok:
                        r['messages'].append("[BLOCK] pre-save brace check FAILED: " + brace_msg)
                        r['messages'].append("[BLOCK] file NOT saved - brace imbalance detected")
                        r['success'] = False
                        brace_blocked += 1
                        failed += 1
                        continue

                EncodingHandler.write_file(
                    r['resolved_path'], r['new_content'],
                    r['encoding'], r['has_bom'], r['line_ending'])
                r['messages'].append("[SAVED] backup: " + os.path.basename(bp))
                saved += 1
                if r['resolved_path'].endswith('.py'):
                    try:
                        import py_compile
                        py_compile.compile(r['resolved_path'], doraise=True)
                        r['messages'].append("[SYNTAX OK]")
                    except py_compile.PyCompileError as pe:
                        r['messages'].append("[SYNTAX ERROR] " + str(pe))
                        r['syntax_error'] = True
            except Exception as e:
                r['messages'].append("[X] save error: " + str(e))
                r['success'] = False
                failed += 1
        return results, {
            'total': len(results), 'saved': saved,
            'failed': failed, 'skipped': skipped,
            'created': created, 'deleted': deleted,
            'brace_blocked': brace_blocked}

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
