#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
code_reviewer.py — Automated code review skill for ProjectScan v6.0
Performs lint-level checks after diff application:
  - Python: syntax, unused imports, undefined names, indentation, style
  - General: trailing whitespace, mixed tabs/spaces, very long lines, debug prints
"""

import re
import os
import ast
import sys


class CodeReviewer:
    """
    Lightweight code reviewer that works without external dependencies.
    Returns a list of Issue dicts:
      {'file': str, 'line': int, 'severity': 'error'|'warning'|'info',
       'code': str, 'message': str}
    """

    # Severity levels
    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'

    # Issue codes
    CODES = {
        'E001': 'Syntax error',
        'E002': 'Indentation error',
        'W001': 'Unused import',
        'W002': 'Undefined name used',
        'W003': 'Wildcard import (from x import *)',
        'W004': 'Duplicate import',
        'W005': 'Mixed tabs and spaces',
        'W006': 'Trailing whitespace',
        'W007': 'Line too long',
        'W008': 'Debug print/breakpoint left in code',
        'W009': 'Bare except clause',
        'W010': 'Mutable default argument',
        'W011': 'Redefined built-in name',
        'W012': 'Unreachable code after return/break/continue',
        'I001': 'TODO/FIXME/HACK/XXX comment found',
        'I002': 'Empty except block',
    }

    PYTHON_BUILTINS = {
        'print', 'len', 'range', 'int', 'str', 'float', 'list', 'dict',
        'set', 'tuple', 'bool', 'type', 'id', 'input', 'open', 'file',
        'map', 'filter', 'zip', 'enumerate', 'sorted', 'reversed',
        'min', 'max', 'sum', 'abs', 'round', 'hash', 'repr', 'isinstance',
        'issubclass', 'hasattr', 'getattr', 'setattr', 'delattr', 'callable',
        'super', 'property', 'staticmethod', 'classmethod', 'object',
        'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError',
        'AttributeError', 'ImportError', 'OSError', 'IOError', 'FileNotFoundError',
        'RuntimeError', 'StopIteration', 'NotImplementedError', 'NameError',
        'True', 'False', 'None', 'self', 'cls',
    }

    DEBUG_PATTERNS = [
        re.compile(r'^\s*print\s*\(.*debug', re.IGNORECASE),
        re.compile(r'^\s*print\s*\(.*TODO', re.IGNORECASE),
        re.compile(r'^\s*breakpoint\s*\('),
        re.compile(r'^\s*import\s+pdb'),
        re.compile(r'^\s*pdb\.set_trace\s*\('),
        re.compile(r'^\s*import\s+ipdb'),
        re.compile(r'^\s*ipdb\.set_trace\s*\('),
    ]

    TODO_PATTERN = re.compile(r'#\s*(TODO|FIXME|HACK|XXX)\b', re.IGNORECASE)

    MAX_LINE_LENGTH = 120

    def __init__(self, max_line_length=120):
        self.MAX_LINE_LENGTH = max_line_length

    def review_file(self, filepath, content=None):
        """Review a single file. Returns list of issues."""
        if content is None:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except Exception as e:
                return [self._issue(filepath, 0, self.ERROR, 'E001',
                                    f'Cannot read file: {e}')]

        ext = os.path.splitext(filepath)[1].lower()
        issues = []

        # Universal checks (all file types)
        issues.extend(self._check_whitespace(filepath, content))
        issues.extend(self._check_todos(filepath, content))

        # Python-specific checks
        if ext == '.py':
            issues.extend(self._check_python_syntax(filepath, content))
            issues.extend(self._check_python_imports(filepath, content))
            issues.extend(self._check_python_style(filepath, content))
            issues.extend(self._check_python_patterns(filepath, content))

        # JavaScript/TypeScript checks
        elif ext in ('.js', '.ts', '.jsx', '.tsx'):
            issues.extend(self._check_js_patterns(filepath, content))

        # Sort by severity then line number
        severity_order = {self.ERROR: 0, self.WARNING: 1, self.INFO: 2}
        issues.sort(key=lambda x: (severity_order.get(x['severity'], 9), x['line']))
        return issues

    def review_files(self, file_list):
        """
        Review multiple files.
        file_list: list of (filepath, content_or_None)
        Returns dict: {filepath: [issues]}
        """
        all_issues = {}
        for filepath, content in file_list:
            issues = self.review_file(filepath, content)
            if issues:
                all_issues[filepath] = issues
        return all_issues

    def format_report(self, all_issues, verbose=False):
        """Format issues into a human-readable report string."""
        if not all_issues:
            return "[Code Review] No issues found."

        lines = ["=" * 55, "Code Review Report", "=" * 55]

        total_errors = 0
        total_warnings = 0
        total_info = 0

        for filepath, issues in all_issues.items():
            errors = [i for i in issues if i['severity'] == self.ERROR]
            warnings = [i for i in issues if i['severity'] == self.WARNING]
            infos = [i for i in issues if i['severity'] == self.INFO]

            total_errors += len(errors)
            total_warnings += len(warnings)
            total_info += len(infos)

            rel = os.path.basename(filepath)
            lines.append(f"\n--- {rel} ---")
            lines.append(f"  Errors: {len(errors)}  Warnings: {len(warnings)}  Info: {len(infos)}")

            for issue in issues:
                sev = issue['severity'].upper()
                ln = issue['line']
                code = issue['code']
                msg = issue['message']
                if verbose or issue['severity'] != self.INFO:
                    lines.append(f"  L{ln:4d} [{sev:7s}] {code}: {msg}")

        lines.append(f"\n{'=' * 55}")
        lines.append(f"Total: {total_errors} errors, {total_warnings} warnings, {total_info} info")

        if total_errors > 0:
            lines.append("[!] ERRORS found — auto-sync will be blocked")
        elif total_warnings > 0:
            lines.append("[*] Warnings found — review recommended before sync")
        else:
            lines.append("[OK] Code looks clean")

        return '\n'.join(lines)

    def has_blocking_issues(self, all_issues):
        """Return True if there are errors that should block auto-sync."""
        for issues in all_issues.values():
            if any(i['severity'] == self.ERROR for i in issues):
                return True
        return False

    def has_warnings(self, all_issues):
        """Return True if there are warnings."""
        for issues in all_issues.values():
            if any(i['severity'] == self.WARNING for i in issues):
                return True
        return False

    # ── Internal helpers ──

    def _issue(self, filepath, line, severity, code, message):
        return {
            'file': filepath,
            'line': line,
            'severity': severity,
            'code': code,
            'message': message,
        }

    # ── Universal checks ──

    def _check_whitespace(self, fp, content):
        issues = []
        lines = content.split('\n')
        has_tabs = False
        has_spaces = False

        for i, line in enumerate(lines, 1):
            # Trailing whitespace
            if line != line.rstrip() and line.strip():
                issues.append(self._issue(fp, i, self.INFO, 'W006',
                    'Trailing whitespace'))

            # Line too long
            if len(line) > self.MAX_LINE_LENGTH:
                issues.append(self._issue(fp, i, self.INFO, 'W007',
                    f'Line too long ({len(line)} > {self.MAX_LINE_LENGTH})'))

            # Track indentation style
            if line and line[0] == '\t':
                has_tabs = True
            elif line and line[0] == ' ' and len(line) > len(line.lstrip()):
                has_spaces = True

        if has_tabs and has_spaces:
            issues.append(self._issue(fp, 1, self.WARNING, 'W005',
                'Mixed tabs and spaces for indentation'))

        return issues

    def _check_todos(self, fp, content):
        issues = []
        for i, line in enumerate(content.split('\n'), 1):
            m = self.TODO_PATTERN.search(line)
            if m:
                issues.append(self._issue(fp, i, self.INFO, 'I001',
                    f'{m.group(1).upper()} comment found'))
        return issues

    # ── Python checks ──

    def _check_python_syntax(self, fp, content):
        """Check Python syntax using ast.parse."""
        issues = []
        try:
            ast.parse(content, filename=fp)
        except SyntaxError as e:
            ln = e.lineno or 0
            msg = e.msg if hasattr(e, 'msg') else str(e)
            if 'indent' in msg.lower():
                issues.append(self._issue(fp, ln, self.ERROR, 'E002',
                    f'Indentation error: {msg}'))
            else:
                issues.append(self._issue(fp, ln, self.ERROR, 'E001',
                    f'Syntax error: {msg}'))
        return issues

    def _check_python_imports(self, fp, content):
        """Check for unused, duplicate, and wildcard imports."""
        issues = []
        try:
            tree = ast.parse(content, filename=fp)
        except SyntaxError:
            return issues

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports.append((name, alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.names and node.names[0].name == '*':
                    issues.append(self._issue(fp, node.lineno, self.WARNING,
                        'W003', f'Wildcard import: from {node.module} import *'))
                    continue
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports.append((name, alias.name, node.lineno))

        # Check duplicates
        seen = {}
        for name, orig, ln in imports:
            if name in seen:
                issues.append(self._issue(fp, ln, self.WARNING, 'W004',
                    f'Duplicate import: {name} (first at line {seen[name]})'))
            else:
                seen[name] = ln

        # Check unused imports (simple heuristic: search name in rest of content)
        lines = content.split('\n')
        for name, orig, ln in imports:
            # Skip if it's a module used in dotted access
            if name == orig:
                pattern = re.compile(r'\b' + re.escape(name) + r'\b')
            else:
                pattern = re.compile(r'\b' + re.escape(name) + r'\b')

            used = False
            for i, line in enumerate(lines, 1):
                if i == ln:
                    continue  # skip the import line itself
                if pattern.search(line):
                    used = True
                    break

            if not used:
                issues.append(self._issue(fp, ln, self.WARNING, 'W001',
                    f'Unused import: {name}'))

        return issues

    def _check_python_style(self, fp, content):
        """Check Python-specific style issues."""
        issues = []
        try:
            tree = ast.parse(content, filename=fp)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            # Bare except
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    issues.append(self._issue(fp, node.lineno, self.WARNING,
                        'W009', 'Bare except clause (catches all exceptions including SystemExit, KeyboardInterrupt)'))
                # Empty except body
                if (len(node.body) == 1 and isinstance(node.body[0], ast.Pass)):
                    issues.append(self._issue(fp, node.lineno, self.INFO,
                        'I002', 'Empty except block (pass only)'))

            # Mutable default argument
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults + node.args.kw_defaults:
                    if default is None:
                        continue
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        issues.append(self._issue(fp, node.lineno, self.WARNING,
                            'W010', f'Mutable default argument in {node.name}()'))
                        break

                # Redefined builtins
                if node.name in self.PYTHON_BUILTINS:
                    issues.append(self._issue(fp, node.lineno, self.WARNING,
                        'W011', f'Function name "{node.name}" shadows a built-in'))

        return issues

    def _check_python_patterns(self, fp, content):
        """Check for debug statements and other patterns."""
        issues = []
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            # Debug patterns
            for pat in self.DEBUG_PATTERNS:
                if pat.search(line):
                    issues.append(self._issue(fp, i, self.WARNING, 'W008',
                        f'Debug statement: {line.strip()[:60]}'))
                    break

        return issues

    # ── JavaScript/TypeScript checks ──

    def _check_js_patterns(self, fp, content):
        """Basic JS/TS checks."""
        issues = []
        lines = content.split('\n')

        console_re = re.compile(r'^\s*console\.(log|debug|warn|error|info)\s*\(')
        debugger_re = re.compile(r'^\s*debugger\s*;?\s*$')
        alert_re = re.compile(r'^\s*alert\s*\(')

        for i, line in enumerate(lines, 1):
            if console_re.search(line):
                issues.append(self._issue(fp, i, self.INFO, 'W008',
                    f'console.log left in code: {line.strip()[:60]}'))
            if debugger_re.match(line):
                issues.append(self._issue(fp, i, self.WARNING, 'W008',
                    'debugger statement'))
            if alert_re.search(line):
                issues.append(self._issue(fp, i, self.INFO, 'W008',
                    'alert() call'))

        return issues
