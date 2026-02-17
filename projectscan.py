#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProjectScan v6.0 — Modular version with core package
Line-number Diff + GitHub Auto-sync
"""

import os
import re
import sys
import io
import json
import shutil
import hashlib
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog

# Fix console encoding
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Import from core package
from core import (
    EncodingHandler, TextNormalizer,
    LineDiffParser, LineDiffEngine,
    GitHubUploader,
    CheckboxTreeview,
    CodeEditor,
    CodeReviewer,
)


# ════════════════════════════════════════════════════════════
#  ProjectScan v6.0 — Main Application
# ════════════════════════════════════════════════════════════
class ProjectScan:
    def __init__(self, root):
        self.root = root
        self.root.title("ProjectScan v6.0")
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
        self.code_reviewer = CodeReviewer(max_line_length=120)
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

        # Tab 5: Code Review
        tab_review = ttk.Frame(self.notebook, style='Dark.TFrame')
        review_top = ttk.Frame(tab_review, style='Dark.TFrame')
        review_top.pack(fill='x', padx=3, pady=3)
        ttk.Button(review_top, text="[Review Current File]", style='Accent.TButton',
                    command=self._review_current).pack(side='left', padx=2)
        ttk.Button(review_top, text="[Review All Checked]", style='Dark.TButton',
                    command=self._review_checked).pack(side='left', padx=2)
        self.review_severity = tk.StringVar(value="all")
        ttk.Label(review_top, text="Show:", style='Dark.TLabel').pack(side='left', padx=(10,2))
        for val, txt in [("all","All"),("warnings","Warn+Err"),("errors","Errors")]:
            ttk.Radiobutton(review_top, text=txt, variable=self.review_severity,
                            value=val, command=self._filter_review).pack(side='left', padx=2)
        self.review_log = scrolledtext.ScrolledText(tab_review, bg='#181825', fg='#f9e2af',
            font=('Consolas', 9), state='disabled', insertbackground='#f5e0dc')
        self.review_log.pack(fill='both', expand=True, padx=3, pady=3)
        self._last_review_issues = {}
        self.notebook.add(tab_review, text=' Review ')

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
                 'single_file_named': 'single file (named)', 'multi_file': 'multi file',
                 'file_ops_only': 'file operations only'}
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
        parsed, file_ops = self.diff_engine.parse(dt)
        if not parsed and not file_ops:
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

        parsed, file_ops = self.diff_engine.parse(dt)

        if not parsed and not file_ops:
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

        if a['total_changes'] == 0 and not a.get('file_ops'):
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
            f"saved:{summary['saved']} failed:{summary['failed']} skipped:{summary['skipped']}"
            f" created:{summary.get('created',0)} deleted:{summary.get('deleted',0)}",
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
            f"Saved: {summary['saved']}\nCreated: {summary.get('created',0)}\n"
            f"Deleted: {summary.get('deleted',0)}\nFailed: {summary['failed']}\n"
            f"Skipped: {summary['skipped']}")
        self.status_var.set(
            f"multi: saved {summary['saved']} created {summary.get('created',0)} "
            f"deleted {summary.get('deleted',0)} failed {summary['failed']}")
        # Check for syntax errors before auto-sync
        has_syntax_error = any(r.get('syntax_error') for r in results)
        if has_syntax_error:
            messagebox.showwarning("Syntax Error",
                "Syntax errors detected in saved files.\n"
                "Auto-sync skipped to prevent pushing broken code.\n"
                "Fix errors and sync manually.")
            self.status_var.set("syntax error — auto-sync skipped")
            return

        # === Code Review after diff ===
        review_files = []
        for r in results:
            if r['success'] and r.get('resolved_path'):
                review_files.append((r['resolved_path'], None))
        if review_files:
            all_issues = self.code_reviewer.review_files(review_files)
            if all_issues:
                report = self.code_reviewer.format_report(all_issues, verbose=True)
                self._last_review_issues = all_issues
                self.review_log.config(state=tk.NORMAL)
                self.review_log.delete("1.0", tk.END)
                self.review_log.insert("1.0", report)
                self.review_log.config(state=tk.DISABLED)
                if self.code_reviewer.has_blocking_issues(all_issues):
                    self.notebook.select(4)
                    messagebox.showwarning("Code Review",
                        "Errors found in code review.\n"
                        "Auto-sync blocked. Fix errors first.")
                    self.status_var.set("review errors — auto-sync blocked")
                    return
                elif self.code_reviewer.has_warnings(all_issues):
                    self.notebook.select(4)

        if self.auto_sync.get() and (summary['saved'] > 0 or summary.get('created',0) > 0 or summary.get('deleted',0) > 0):
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
            parts.append("")
            parts.append("```")
            parts.append("=== FILE: relative/path/file.ext ===")
            parts.append("## CONTEXT: line 14 | old_code_before_change")
            parts.append("@@ 15-23 REPLACE")
            parts.append("new code for lines 15 to 23")
            parts.append("@@ END")
            parts.append("## VERIFY: line 24 | old_code_after_change")
            parts.append("@@ 50 DELETE 3")
            parts.append("@@ 60 INSERT")
            parts.append("code to insert after line 60")
            parts.append("@@ END")
            parts.append("=== END FILE ===")
            parts.append("```")
            parts.append("")
            parts.append("=== CRITICAL RULES (violations will cause code corruption) ===")
            parts.append("")
            parts.append("1. LINE NUMBER ACCURACY:")
            parts.append("   - Line numbers MUST match the ORIGINAL file exactly (shown as N| prefix)")
            parts.append("   - ALWAYS verify the line number by checking the content at that line")
            parts.append("   - If unsure about a line number, find the exact content first")
            parts.append("")
            parts.append("2. CONTEXT VERIFICATION (MANDATORY):")
            parts.append("   - Before each @@ command, add a ## CONTEXT comment showing the line BEFORE the change:")
            parts.append("     ## CONTEXT: line 14 | def existing_function():  ")
            parts.append("     @@ 15-23 REPLACE")
            parts.append("   - After each @@ END, add a ## VERIFY comment showing the line AFTER the change:")
            parts.append("     @@ END")
            parts.append("     ## VERIFY: line 24 | return result")
            parts.append("   - These comments prove you checked the correct location")
            parts.append("")
            parts.append("3. ORDERING & SAFETY:")
            parts.append("   - When making multiple changes to ONE file, list them from BOTTOM to TOP")
            parts.append("     (highest line numbers first) to prevent line-number drift")
            parts.append("   - NEVER modify more than 50 lines in a single REPLACE block")
            parts.append("   - If changing >50 lines, split into multiple smaller REPLACE blocks")
            parts.append("")
            parts.append("4. INDENTATION & SYNTAX:")
            parts.append("   - Preserve the EXACT indentation style of the original file (spaces vs tabs)")
            parts.append("   - For Python: ensure consistent indentation (4 spaces per level)")
            parts.append("   - The replacement code MUST be syntactically valid on its own")
            parts.append("   - Do NOT leave unclosed brackets, parentheses, or string literals")
            parts.append("")
            parts.append("5. COMPLETENESS:")
            parts.append("   - Include ALL lines in the replacement range, even unchanged ones")
            parts.append("   - Do NOT use '...' or '# rest unchanged' — write every line explicitly")
            parts.append("   - @@ START-END REPLACE : replace lines START through END with new content")
            parts.append("   - @@ N DELETE COUNT : delete COUNT lines starting from line N")
            parts.append("   - @@ N INSERT : insert new content AFTER line N (use 0 to insert at top)")
            parts.append("   - Each REPLACE/INSERT block must end with @@ END")
            parts.append("")
            parts.append("6. FORMAT:")
            parts.append("   - Do NOT use SEARCH/REPLACE blocks. Use ONLY @@ line commands")
            parts.append("   - After all changes, state the REASON for each modification")
            parts.append("   - The reason will be used as a GitHub commit message")
            parts.append("")
            parts.append("=== END RULES ===")
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

    # -- Code Review --

    def _review_current(self):
        """Review the currently open file."""
        if not self._current_file_path:
            messagebox.showwarning("warning", "open a file first")
            return
        content = self.code_editor.get_content()
        issues = self.code_reviewer.review_file(self._current_file_path, content)
        all_issues = {self._current_file_path: issues} if issues else {}
        self._last_review_issues = all_issues
        report = self.code_reviewer.format_report(all_issues, verbose=True)
        self.review_log.config(state=tk.NORMAL)
        self.review_log.delete("1.0", tk.END)
        self.review_log.insert("1.0", report)
        self.review_log.config(state=tk.DISABLED)
        self.notebook.select(4)
        cnt = len(issues) if issues else 0
        self.status_var.set(f"review: {cnt} issues in {os.path.basename(self._current_file_path)}")

    def _review_checked(self):
        """Review all checked files in the tree."""
        files = self._get_checked_files()
        if not files:
            messagebox.showwarning("warning", "no files checked")
            return
        file_list = [(full, None) for rel, full, sz in files]
        all_issues = self.code_reviewer.review_files(file_list)
        self._last_review_issues = all_issues
        report = self.code_reviewer.format_report(all_issues, verbose=True)
        self.review_log.config(state=tk.NORMAL)
        self.review_log.delete("1.0", tk.END)
        self.review_log.insert("1.0", report)
        self.review_log.config(state=tk.DISABLED)
        self.notebook.select(4)
        total = sum(len(v) for v in all_issues.values())
        self.status_var.set(f"review: {total} issues in {len(all_issues)} files")

    def _filter_review(self):
        """Re-display the last review with severity filter applied."""
        if not self._last_review_issues:
            return
        level = self.review_severity.get()
        filtered = {}
        for fp, issues in self._last_review_issues.items():
            if level == 'errors':
                fi = [i for i in issues if i['severity'] == 'error']
            elif level == 'warnings':
                fi = [i for i in issues if i['severity'] in ('error', 'warning')]
            else:
                fi = issues
            if fi:
                filtered[fp] = fi
        report = self.code_reviewer.format_report(filtered, verbose=True)
        self.review_log.config(state=tk.NORMAL)
        self.review_log.delete("1.0", tk.END)
        self.review_log.insert("1.0", report)
        self.review_log.config(state=tk.DISABLED)

# ════════════════════════════════════════════════════════════
if __name__ == '__main__':
    root = tk.Tk()
    app = ProjectScan(root)
    root.mainloop()
