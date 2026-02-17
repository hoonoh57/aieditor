import os

content = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_engine.py — Line-number based diff parser and engine for ProjectScan v6.0
Supports: REPLACE, DELETE, INSERT, CREATE FILE, DELETE FILE
"""

import os
import re
import shutil
from .encoding_handler import EncodingHandler, TextNormalizer


class LineDiffParser:
    """
    AI response format:

    === FILE: path/file.js ===
    @@ 15-23 REPLACE
    new code
    @@ END
    @@ 50 DELETE 3
    @@ 60 INSERT
    insert code
    @@ END
    === END FILE ===

    === CREATE FILE: src/utils/helper.py ===
    file content here
    === END FILE ===

    === DELETE FILE: old_module.py ===
    """

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

        # Extract file operations (CREATE / DELETE FILE)
        file_ops = self._parse_file_ops(lines)

        # Extract edit blocks
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
        """Parse CREATE FILE and DELETE FILE operations."""
        ops = []
        i = 0
        while i < len(lines):
            # === CREATE FILE: path ===
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

            # === DELETE FILE: path ===
            m = self.RE_DELETE_FILE.match(lines[i])
            if m:
                fp = m.group(1).strip().strip('`\'"')
                ops.append({
                    'op': 'delete',
                    'path': fp,
                })
                i += 1
                continue

            i += 1
        return ops

    def _split_files(self, lines):
        blocks = {}
        headers = []
        for i, line in enumerate(lines):
            # Skip CREATE FILE and DELETE FILE lines
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


class LineDiffEngine:

    def __init__(self):
        self.parser = LineDiffParser()

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
                        f"[X] REPLACE {cmd['start']}-{cmd['end']}: "
                        f"start({cmd['start']}) > file length({len(file_lines)})")
                    errors += 1
                    continue
                new_lines = cmd['content'].split('\n')
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
        orig_len = len(original.strip())
        result_len = len(result.strip())
        if orig_len > 200 and result_len < orig_len * 0.1:
            pct = result_len * 100 // orig_len if orig_len > 0 else 0
            msgs.append(f"[BLOCK] result is only {pct}% of original -> keeping original")
            return original, msgs
        return result, msgs

    def resolve_and_apply_all(self, diff_text, path_map, project_path=None):
        parsed, file_ops = self.parser.parse(diff_text)
        results = []

        # Process file operations first (CREATE / DELETE)
        for fop in file_ops:
            if fop['op'] == 'create':
                fp = fop['path']
                if project_path:
                    full_path = os.path.join(project_path, fp.replace('/', os.sep))
                else:
                    full_path = fp
                try:
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(fop['content'])
                    results.append({
                        'filepath': fp, 'resolved_path': full_path,
                        'success': True, 'new_content': fop['content'],
                        'messages': [f"[CREATED] {fp}"],
                        'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                except Exception as e:
                    results.append({
                        'filepath': fp, 'resolved_path': full_path,
                        'success': False, 'new_content': None,
                        'messages': [f"[X] create error: {e}"],
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
                        # Backup before delete
                        bp = rp + '.deleted_bak'
                        shutil.copy2(rp, bp)
                        os.remove(rp)
                        results.append({
                            'filepath': fp, 'resolved_path': rp,
                            'success': True, 'new_content': None,
                            'messages': [f"[DELETED] {fp}", f"[BACKUP] {os.path.basename(bp)}"],
                            'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                    except Exception as e:
                        results.append({
                            'filepath': fp, 'resolved_path': rp,
                            'success': False, 'new_content': None,
                            'messages': [f"[X] delete error: {e}"],
                            'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})
                else:
                    results.append({
                        'filepath': fp, 'resolved_path': None,
                        'success': False, 'new_content': None,
                        'messages': [f"[X] not found for delete: {fp}"],
                        'encoding': 'utf-8', 'has_bom': False, 'line_ending': '\n'})

        # Process edit commands
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
        saved, failed, skipped, created, deleted = 0, 0, 0, 0, 0
        for r in results:
            # Count created/deleted files
            if any('[CREATED]' in m for m in r['messages']):
                if r['success']:
                    created += 1
                    # Syntax check for created .py files
                    if r.get('resolved_path', '').endswith('.py'):
                        try:
                            import py_compile
                            py_compile.compile(r['resolved_path'], doraise=True)
                            r['messages'].append("[SYNTAX OK]")
                        except py_compile.PyCompileError as pe:
                            r['messages'].append(f"[SYNTAX ERROR] {pe}")
                            r['syntax_error'] = True
                else:
                    failed += 1
                continue
            if any('[DELETED]' in m for m in r['messages']):
                if r['success']:
                    deleted += 1
                else:
                    failed += 1
                continue

            # Normal edit operations
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
                if r['resolved_path'].endswith('.py'):
                    try:
                        import py_compile
                        py_compile.compile(r['resolved_path'], doraise=True)
                        r['messages'].append("[SYNTAX OK]")
                    except py_compile.PyCompileError as pe:
                        r['messages'].append(f"[SYNTAX ERROR] {pe}")
                        r['syntax_error'] = True
            except Exception as e:
                r['messages'].append(f"[X] save error: {e}")
                r['success'] = False
                failed += 1
        return results, {'total': len(results), 'saved': saved,
                         'failed': failed, 'skipped': skipped,
                         'created': created, 'deleted': deleted}

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
'''

path = os.path.join(r"E:\genspark\core", "diff_engine.py")
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print(f"Created: {path}")
print(f"Size: {os.path.getsize(path)} bytes")
print(f"Lines: {len(content.splitlines())}")
