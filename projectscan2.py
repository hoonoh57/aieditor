import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import os
import fnmatch
import re
import xml.etree.ElementTree as ET
import datetime


class CheckboxTreeview(ttk.Treeview):
    """체크박스가 포함된 트리뷰 위젯"""

    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._checked = set()
        self._unchecked = set()

        self.tag_configure('checked', image='')
        self.tag_configure('unchecked', image='')

        self.bind('<Button-1>', self._on_click)
        self.bind('<space>', self._on_space)

    def _on_click(self, event):
        region = self.identify_region(event.x, event.y)
        if region == 'tree' or region == 'image':
            item = self.identify_row(event.y)
            if item:
                self.toggle_check(item)

    def _on_space(self, event):
        item = self.focus()
        if item:
            self.toggle_check(item)

    def insert(self, parent, index, iid=None, **kw):
        checked = kw.pop('checked', False)
        item = super().insert(parent, index, iid=iid, **kw)
        if checked:
            self._checked.add(item)
        else:
            self._unchecked.add(item)
        self._update_check_display(item)
        return item

    def toggle_check(self, item):
        if item in self._checked:
            self._checked.discard(item)
            self._unchecked.add(item)
            # 자식 전부 해제
            for child in self._get_all_children(item):
                self._checked.discard(child)
                self._unchecked.add(child)
                self._update_check_display(child)
        else:
            self._unchecked.discard(item)
            self._checked.add(item)
            # 자식 전부 체크
            for child in self._get_all_children(item):
                self._unchecked.discard(child)
                self._checked.add(child)
                self._update_check_display(child)

        self._update_check_display(item)
        self._update_parent_check(item)

    def is_checked(self, item):
        return item in self._checked

    def _get_all_children(self, item):
        children = []
        for child in self.get_children(item):
            children.append(child)
            children.extend(self._get_all_children(child))
        return children

    def _update_parent_check(self, item):
        parent = self.parent(item)
        if not parent:
            return
        children = self.get_children(parent)
        checked_count = sum(1 for c in children if c in self._checked)
        if checked_count == len(children):
            self._unchecked.discard(parent)
            self._checked.add(parent)
        else:
            self._checked.discard(parent)
            self._unchecked.add(parent)
        self._update_check_display(parent)
        self._update_parent_check(parent)

    def _update_check_display(self, item):
        current_text = self.item(item, 'text')
        # 기존 체크 표시 제거
        clean = current_text
        if clean.startswith('☑ ') or clean.startswith('☐ '):
            clean = clean[2:]

        if item in self._checked:
            self.item(item, text=f'☑ {clean}')
        else:
            self.item(item, text=f'☐ {clean}')

    def check_all(self):
        for item in self._get_all_items():
            self._unchecked.discard(item)
            self._checked.add(item)
            self._update_check_display(item)

    def uncheck_all(self):
        for item in self._get_all_items():
            self._checked.discard(item)
            self._unchecked.add(item)
            self._update_check_display(item)

    def _get_all_items(self):
        items = []
        for item in self.get_children(''):
            items.append(item)
            items.extend(self._get_all_children(item))
        return items

    def get_checked_items(self):
        return list(self._checked)


class ProjectScan:
    def __init__(self, root):
        self.root = root
        self.root.title("📂 ProjectScan — Visual Studio 프로젝트 스캔 도구")
        self.root.geometry("1100x850")
        self.root.configure(bg="#1e1e2e")

        self.project_path = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="프로젝트 폴더를 선택하세요")
        self.max_file_size = tk.IntVar(value=100)
        self.source_only = tk.BooleanVar(value=False)

        # 트리뷰 아이템 → 파일 경로 매핑
        self.tree_item_map = {}  # iid -> (rel_path, full_path, size)

        # ── 소스Only 확장자 (순수 코드만) ──
        self.source_only_extensions = {
            '.c', '.cpp', '.cxx', '.cc',
            '.h', '.hpp', '.hxx', '.inl',
            '.cs', '.vb',
            '.fs', '.fsi', '.fsx',
            '.py', '.java', '.go', '.rs', '.rb', '.php',
            '.js', '.jsx', '.ts', '.tsx',
            '.swift', '.kt', '.scala',
            '.sql',
        }

        # ── 전체 코드 확장자 ──
        self.all_code_extensions = {
            '.c', '.cpp', '.cxx', '.cc', '.h', '.hpp', '.hxx', '.inl',
            '.cs', '.vb', '.fs', '.fsi', '.fsx',
            '.xaml', '.cshtml', '.razor', '.aspx', '.ascx', '.master',
            '.py', '.java', '.go', '.rs', '.rb', '.php',
            '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte',
            '.html', '.css', '.scss', '.less',
            '.swift', '.kt', '.scala', '.r',
            '.sql', '.sh', '.bash', '.bat', '.cmd', '.ps1',
            '.json', '.jsonc', '.yaml', '.yml', '.toml', '.ini', '.cfg',
            '.xml', '.md', '.txt', '.rc', '.def', '.idl',
            '.sln', '.vcxproj', '.csproj', '.vbproj', '.fsproj',
        }

        # ── 제외 목록 ──
        self.default_excludes = [
            'node_modules', '.git', '__pycache__', '.vs', '.vscode', '.idea',
            'bin', 'obj', 'x64', 'x86', 'ARM', 'ARM64',
            'Debug', 'Release', 'RelWithDebInfo', 'MinSizeRel',
            'ipch', '.nuget', 'packages', 'TestResults',
            'dist', 'build', 'out', '.next',
            '.venv', 'venv', 'env',
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

        self.vs_project_extensions = ['.vcxproj', '.csproj', '.vbproj', '.fsproj']

        self.setup_styles()
        self.create_widgets()

    # ════════════════════════ UI 구성 ════════════════════════

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        style.configure('Title.TLabel', font=('맑은 고딕', 16, 'bold'),
                        foreground='#cdd6f4', background='#1e1e2e')
        style.configure('Info.TLabel', font=('맑은 고딕', 10),
                        foreground='#a6adc8', background='#1e1e2e')
        style.configure('Status.TLabel', font=('맑은 고딕', 10),
                        foreground='#a6e3a1', background='#1e1e2e')
        style.configure('TCheckbutton', font=('맑은 고딕', 10),
                        foreground='#cdd6f4', background='#1e1e2e')

        style.configure('Custom.Treeview',
                        background='#313244',
                        foreground='#cdd6f4',
                        fieldbackground='#313244',
                        font=('Consolas', 10),
                        rowheight=22)
        style.configure('Custom.Treeview.Heading',
                        background='#45475a',
                        foreground='#cdd6f4',
                        font=('맑은 고딕', 10, 'bold'))
        style.map('Custom.Treeview',
                  background=[('selected', '#585b70')],
                  foreground=[('selected', '#f5e0dc')])

    def create_widgets(self):
        # ── 상단 제목 ──
        title_frame = tk.Frame(self.root, bg='#1e1e2e')
        title_frame.pack(fill='x', padx=20, pady=(12, 4))
        ttk.Label(title_frame, text="📂 ProjectScan",
                  style='Title.TLabel').pack(side='left')
        ttk.Label(title_frame,
                  text="Visual Studio 프로젝트 → AI 전달용 단일 파일",
                  style='Info.TLabel').pack(side='left', padx=(15, 0))

        # ── 폴더 선택 + 옵션 ──
        folder_frame = tk.Frame(self.root, bg='#1e1e2e')
        folder_frame.pack(fill='x', padx=20, pady=4)

        tk.Button(folder_frame, text="📁 폴더 선택",
                  font=('맑은 고딕', 10), bg='#45475a', fg='#cdd6f4',
                  relief='flat', padx=10, pady=4,
                  command=self.select_folder).pack(side='left')

        self.folder_label = ttk.Label(folder_frame, text="선택되지 않음",
                                      style='Info.TLabel')
        self.folder_label.pack(side='left', padx=(10, 0))

        # ── 옵션 행 ──
        opt_frame = tk.Frame(self.root, bg='#1e1e2e')
        opt_frame.pack(fill='x', padx=20, pady=4)

        ttk.Label(opt_frame, text="최대 파일 크기(KB):",
                  style='Info.TLabel').pack(side='left')
        tk.Spinbox(opt_frame, from_=10, to=500, width=5,
                   textvariable=self.max_file_size,
                   font=('Consolas', 10), bg='#313244', fg='#cdd6f4'
                   ).pack(side='left', padx=5)

        ttk.Checkbutton(opt_frame, text="소스Only (.c .cpp .h .cs .vb .py .java …)",
                        variable=self.source_only,
                        style='TCheckbutton',
                        command=self.on_source_only_changed
                        ).pack(side='left', padx=(20, 0))

        self.vs_info_label = ttk.Label(opt_frame, text="", style='Info.TLabel')
        self.vs_info_label.pack(side='right')

        # ── 스캔 버튼 행 ──
        btn_frame = tk.Frame(self.root, bg='#1e1e2e')
        btn_frame.pack(fill='x', padx=20, pady=8)

        tk.Button(btn_frame, text="🔍 폴더 기반 스캔",
                  font=('맑은 고딕', 10, 'bold'), bg='#89b4fa', fg='#1e1e2e',
                  relief='flat', padx=16, pady=8, cursor='hand2',
                  command=self.scan_folder).pack(side='left', expand=True, fill='x', padx=(0, 4))

        tk.Button(btn_frame, text="🏗️ VS 프로젝트 스캔 (.sln/.vcxproj)",
                  font=('맑은 고딕', 10, 'bold'), bg='#f38ba8', fg='#1e1e2e',
                  relief='flat', padx=16, pady=8, cursor='hand2',
                  command=self.scan_vs_project).pack(side='left', expand=True, fill='x', padx=(4, 0))

        # ════════ 메인 영역: 좌(트리) / 우(결과) ════════
        main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                                   bg='#1e1e2e', sashwidth=6,
                                   sashrelief='flat')
        main_pane.pack(fill='both', expand=True, padx=20, pady=4)

        # ── 좌측: 트리뷰 ──
        left_frame = tk.Frame(main_pane, bg='#1e1e2e')
        main_pane.add(left_frame, width=480)

        tree_header = tk.Frame(left_frame, bg='#1e1e2e')
        tree_header.pack(fill='x')
        ttk.Label(tree_header, text="📁 파일 트리 (클릭으로 체크)",
                  style='Info.TLabel').pack(side='left')
        self.tree_count_label = ttk.Label(tree_header, text="",
                                          style='Info.TLabel')
        self.tree_count_label.pack(side='right')

        tree_btn_frame = tk.Frame(left_frame, bg='#1e1e2e')
        tree_btn_frame.pack(fill='x', pady=(4, 2))

        tk.Button(tree_btn_frame, text="✅ 전체선택", font=('맑은 고딕', 9),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=6, pady=2,
                  command=self.tree_check_all).pack(side='left', padx=1)
        tk.Button(tree_btn_frame, text="⬜ 전체해제", font=('맑은 고딕', 9),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=6, pady=2,
                  command=self.tree_uncheck_all).pack(side='left', padx=1)
        tk.Button(tree_btn_frame, text=".c/.cpp", font=('맑은 고딕', 9),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=6, pady=2,
                  command=lambda: self.tree_check_by_ext({'.c', '.cpp', '.cxx', '.cc'})
                  ).pack(side='left', padx=1)
        tk.Button(tree_btn_frame, text=".h/.hpp", font=('맑은 고딕', 9),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=6, pady=2,
                  command=lambda: self.tree_check_by_ext({'.h', '.hpp', '.hxx', '.inl'})
                  ).pack(side='left', padx=1)
        tk.Button(tree_btn_frame, text=".cs", font=('맑은 고딕', 9),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=6, pady=2,
                  command=lambda: self.tree_check_by_ext({'.cs'})
                  ).pack(side='left', padx=1)
        tk.Button(tree_btn_frame, text=".vb", font=('맑은 고딕', 9),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=6, pady=2,
                  command=lambda: self.tree_check_by_ext({'.vb'})
                  ).pack(side='left', padx=1)
        tk.Button(tree_btn_frame, text=".py", font=('맑은 고딕', 9),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=6, pady=2,
                  command=lambda: self.tree_check_by_ext({'.py'})
                  ).pack(side='left', padx=1)

        tree_container = tk.Frame(left_frame, bg='#313244')
        tree_container.pack(fill='both', expand=True, pady=(2, 0))

        tree_scroll_y = ttk.Scrollbar(tree_container, orient='vertical')
        tree_scroll_y.pack(side='right', fill='y')
        tree_scroll_x = ttk.Scrollbar(tree_container, orient='horizontal')
        tree_scroll_x.pack(side='bottom', fill='x')

        self.file_tree = CheckboxTreeview(
            tree_container,
            columns=('size', 'ext'),
            style='Custom.Treeview',
            yscrollcommand=tree_scroll_y.set,
            xscrollcommand=tree_scroll_x.set
        )
        self.file_tree.pack(fill='both', expand=True)
        tree_scroll_y.config(command=self.file_tree.yview)
        tree_scroll_x.config(command=self.file_tree.xview)

        self.file_tree.heading('#0', text='파일명', anchor='w')
        self.file_tree.heading('size', text='크기', anchor='e')
        self.file_tree.heading('ext', text='확장자', anchor='center')
        self.file_tree.column('#0', width=300, minwidth=200)
        self.file_tree.column('size', width=70, minwidth=50, anchor='e')
        self.file_tree.column('ext', width=60, minwidth=40, anchor='center')

        # ── 우측: 결과 미리보기 ──
        right_frame = tk.Frame(main_pane, bg='#1e1e2e')
        main_pane.add(right_frame, width=500)

        result_header = tk.Frame(right_frame, bg='#1e1e2e')
        result_header.pack(fill='x')
        ttk.Label(result_header, text="📋 결과 미리보기",
                  style='Info.TLabel').pack(side='left')
        self.token_label = ttk.Label(result_header, text="",
                                     style='Info.TLabel')
        self.token_label.pack(side='right')

        self.result_text = scrolledtext.ScrolledText(
            right_frame, wrap=tk.WORD, font=('Consolas', 10),
            bg='#313244', fg='#cdd6f4', insertbackground='#f5e0dc',
            relief='flat', padx=10, pady=10
        )
        self.result_text.pack(fill='both', expand=True, pady=(4, 0))

        # ── 하단 버튼 ──
        bottom_frame = tk.Frame(self.root, bg='#1e1e2e')
        bottom_frame.pack(fill='x', padx=20, pady=8)

        tk.Button(bottom_frame, text="📄 선택 파일 → 하나로 합치기 (미리보기)",
                  font=('맑은 고딕', 11, 'bold'), bg='#a6e3a1', fg='#1e1e2e',
                  relief='flat', padx=20, pady=8, cursor='hand2',
                  command=self.merge_checked_files).pack(fill='x', pady=(0, 4))

        tk.Button(bottom_frame,
                  text="📋 클립보드에 복사 → AI 채팅에 붙여넣기 (Ctrl+V)",
                  font=('맑은 고딕', 13, 'bold'), bg='#cba6f7', fg='#1e1e2e',
                  relief='flat', padx=30, pady=10, cursor='hand2',
                  command=self.copy_to_clipboard).pack(fill='x')

        # ── 상태바 ──
        status_frame = tk.Frame(self.root, bg='#11111b')
        status_frame.pack(fill='x', side='bottom')
        ttk.Label(status_frame, textvariable=self.status_var,
                  style='Status.TLabel').pack(padx=10, pady=5)

    # ════════════════════ 폴더 선택 ════════════════════

    def select_folder(self):
        folder = filedialog.askdirectory(title="프로젝트 폴더 선택")
        if folder:
            self.project_path.set(folder)
            self.folder_label.config(text=folder)
            self.status_var.set(f"프로젝트: {folder}")
            sln_files, proj_files = self.detect_vs_projects(folder)
            if sln_files or proj_files:
                self.vs_info_label.config(
                    text=f"🏗️ 감지: {len(sln_files)} sln, {len(proj_files)} proj",
                    foreground='#f38ba8')
            else:
                self.vs_info_label.config(text="(VS 프로젝트 미감지)",
                                          foreground='#6c7086')

    # ════════════════════ 유틸리티 ════════════════════

    def should_exclude(self, path, name):
        for pattern in self.default_excludes:
            if fnmatch.fnmatch(name, pattern) or name == pattern:
                return True
        return False

    def is_target_file(self, filename):
        """소스Only 모드에 따라 대상 파일인지 판별"""
        _, ext = os.path.splitext(filename)
        ext = ext.lower()
        if self.source_only.get():
            return ext in self.source_only_extensions
        return ext in self.all_code_extensions

    def read_file_safe(self, filepath):
        encodings = ['utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin-1']
        for enc in encodings:
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return "[읽기 실패: 인코딩 문제]"

    def format_size(self, size):
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f}MB"
        if size >= 1024:
            return f"{size / 1024:.1f}KB"
        return f"{size}B"

    # ════════════════════ 트리뷰 조작 ════════════════════

    def clear_tree(self):
        for item in self.file_tree.get_children(''):
            self.file_tree.delete(item)
        self.file_tree._checked.clear()
        self.file_tree._unchecked.clear()
        self.tree_item_map.clear()

    def populate_tree(self, file_list, base_path):
        """
        file_list: [(rel_path, full_path, size), ...]
        트리 구조로 삽입
        """
        self.clear_tree()
        folder_nodes = {}  # rel_folder -> iid

        # 정렬: 폴더 경로 → 파일명
        file_list.sort(key=lambda x: x[0].lower())

        for rel_path, full_path, size in file_list:
            parts = rel_path.replace('\\', '/').split('/')
            filename = parts[-1]
            folders = parts[:-1]

            # 폴더 노드 생성
            parent_iid = ''
            current_folder = ''
            for folder_name in folders:
                current_folder = f"{current_folder}/{folder_name}" if current_folder else folder_name
                if current_folder not in folder_nodes:
                    node_iid = self.file_tree.insert(
                        parent_iid, 'end',
                        text=f'📁 {folder_name}',
                        values=('', ''),
                        open=True,
                        checked=True
                    )
                    folder_nodes[current_folder] = node_iid
                parent_iid = folder_nodes[current_folder]

            # 파일 노드 생성
            _, ext = os.path.splitext(filename)
            file_iid = self.file_tree.insert(
                parent_iid, 'end',
                text=filename,
                values=(self.format_size(size), ext.lower()),
                checked=True
            )
            self.tree_item_map[file_iid] = (rel_path, full_path, size)

        total = len(file_list)
        self.tree_count_label.config(text=f"{total}개 파일")
        self.status_var.set(f"트리뷰 로드 완료: {total}개 파일 — 체크박스로 선택 후 '합치기' 클릭")

    def tree_check_all(self):
        self.file_tree.check_all()

    def tree_uncheck_all(self):
        self.file_tree.uncheck_all()

    def tree_check_by_ext(self, ext_set):
        """특정 확장자만 체크, 나머지 해제"""
        self.file_tree.uncheck_all()
        for iid, (rel_path, full_path, size) in self.tree_item_map.items():
            _, ext = os.path.splitext(rel_path)
            if ext.lower() in ext_set:
                self.file_tree._unchecked.discard(iid)
                self.file_tree._checked.add(iid)
                self.file_tree._update_check_display(iid)
                # 부모도 업데이트
                self.file_tree._update_parent_check(iid)

    def get_checked_files(self):
        """체크된 파일만 반환"""
        checked = []
        for iid, file_info in self.tree_item_map.items():
            if self.file_tree.is_checked(iid):
                checked.append(file_info)
        return checked

    def on_source_only_changed(self):
        """소스Only 체크 변경 시 트리 다시 로드 (현재 데이터가 있으면)"""
        if hasattr(self, '_last_scan_data'):
            mode, data = self._last_scan_data
            if mode == 'folder':
                self._do_folder_scan(data)
            elif mode == 'vs':
                self._filter_and_populate(data)

    # ════════════════════ 폴더 기반 스캔 ════════════════════

    def scan_folder(self):
        project = self.project_path.get()
        if not project:
            messagebox.showwarning("경고", "프로젝트 폴더를 먼저 선택하세요!")
            return

        self.status_var.set("폴더 스캔 중...")
        self.root.update()

        self._last_scan_data = ('folder', project)
        self._do_folder_scan(project)

    def _do_folder_scan(self, path):
        code_files = []
        max_size = self.max_file_size.get() * 1024
        for root_dir, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not self.should_exclude(root_dir, d)]
            for f in files:
                if self.should_exclude(root_dir, f):
                    continue
                if not self.is_target_file(f):
                    continue
                full_path = os.path.join(root_dir, f)
                rel_path = os.path.relpath(full_path, path)
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    continue
                if size <= max_size:
                    code_files.append((rel_path, full_path, size))

        self.populate_tree(code_files, path)

    # ════════════════════ VS 프로젝트 스캔 ════════════════════

    def detect_vs_projects(self, folder):
        sln_files = []
        proj_files = []
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
            elif os.path.isdir(full) and not self.should_exclude(folder, entry):
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

    def parse_sln_for_projects(self, sln_path):
        sln_dir = os.path.dirname(sln_path)
        proj_paths = []
        pattern = re.compile(
            r'Project\("[^"]*"\)\s*=\s*"[^"]*"\s*,\s*"([^"]+)"\s*,\s*"[^"]*"'
        )
        content = self.read_file_safe(sln_path)
        for m in pattern.finditer(content):
            rel = m.group(1).replace('\\', os.sep)
            full = os.path.normpath(os.path.join(sln_dir, rel))
            if os.path.isfile(full):
                for ext in self.vs_project_extensions:
                    if full.endswith(ext):
                        proj_paths.append(full)
                        break
        return proj_paths

    def parse_project_file(self, proj_path):
        proj_dir = os.path.dirname(proj_path)
        source_files = []
        try:
            tree = ET.parse(proj_path)
            root_el = tree.getroot()
        except ET.ParseError:
            return source_files

        ns = ''
        m = re.match(r'\{(.*)\}', root_el.tag)
        if m:
            ns = m.group(1)

        include_tags = [
            'ClCompile', 'ClInclude', 'Compile', 'Content',
            'None', 'Page', 'ApplicationDefinition',
            'Resource', 'EmbeddedResource', 'TypeScriptCompile',
        ]

        for tag in include_tags:
            if ns:
                elements = root_el.iter(f'{{{ns}}}{tag}')
            else:
                elements = root_el.iter(tag)
            for el in elements:
                include = el.get('Include')
                if include:
                    rel = include.replace('\\', os.sep)
                    full = os.path.normpath(os.path.join(proj_dir, rel))
                    if os.path.isfile(full):
                        source_files.append(full)

        sdk = root_el.get('Sdk')
        if sdk and not source_files:
            source_files = self._glob_sdk_project(proj_dir, proj_path)

        return source_files

    def _glob_sdk_project(self, proj_dir, proj_path):
        files = []
        if proj_path.endswith('.csproj'):
            exts = {'.cs', '.cshtml', '.razor'}
        elif proj_path.endswith('.fsproj'):
            exts = {'.fs', '.fsi', '.fsx'}
        elif proj_path.endswith('.vbproj'):
            exts = {'.vb'}
        else:
            exts = {'.cs', '.cpp', '.h', '.c'}

        for root_dir, dirs, fnames in os.walk(proj_dir):
            dirs[:] = [d for d in dirs if d not in (
                'bin', 'obj', 'Debug', 'Release', '.vs', 'x64', 'x86',
                'packages', 'node_modules', '.git'
            )]
            for f in fnames:
                _, ext = os.path.splitext(f)
                if ext.lower() in exts:
                    files.append(os.path.join(root_dir, f))
        return files

    def scan_vs_project(self):
        project = self.project_path.get()
        if not project:
            messagebox.showwarning("경고", "프로젝트 폴더를 먼저 선택하세요!")
            return

        self.status_var.set("VS 프로젝트 분석 중...")
        self.root.update()

        sln_files, direct_proj = self.detect_vs_projects(project)
        all_proj = set()
        for sln in sln_files:
            for p in self.parse_sln_for_projects(sln):
                all_proj.add(p)
        for p in direct_proj:
            all_proj.add(p)

        if not all_proj:
            messagebox.showinfo("미발견",
                                ".sln / .vcxproj / .csproj 파일을 찾지 못했습니다.\n"
                                "'폴더 기반 스캔'을 이용해주세요.")
            self.status_var.set("VS 프로젝트 파일 미발견")
            return

        all_source = set()
        for proj in all_proj:
            for src in self.parse_project_file(proj):
                all_source.add(os.path.normpath(src))

        self._last_scan_data = ('vs', (project, all_source))
        self._filter_and_populate((project, all_source))

    def _filter_and_populate(self, data):
        project, all_source = data
        max_size = self.max_file_size.get() * 1024

        if self.source_only.get():
            target_exts = self.source_only_extensions
        else:
            target_exts = self.all_code_extensions

        result = []
        for full_path in sorted(all_source):
            _, ext = os.path.splitext(full_path)
            if ext.lower() not in target_exts:
                continue
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue
            if size > max_size:
                continue
            rel_path = os.path.relpath(full_path, project)
            result.append((rel_path, full_path, size))

        self.populate_tree(result, project)

    # ════════════════════ 합치기 & 복사 ════════════════════

    def merge_checked_files(self):
        """체크된 파일들을 하나의 텍스트로 합침"""
        checked = self.get_checked_files()
        if not checked:
            messagebox.showwarning("경고", "체크된 파일이 없습니다.\n"
                                   "트리뷰에서 파일을 체크해주세요.")
            return

        project = self.project_path.get()
        self.status_var.set(f"합치는 중... ({len(checked)}개 파일)")
        self.root.update()

        result = f"# 프로젝트 스캔 결과\n"
        result += f"# 경로: {project}\n"
        result += f"# 시간: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        result += f"# 파일 수: {len(checked)}개"
        if self.source_only.get():
            result += " (소스Only 모드)"
        result += "\n\n"

        # 파일 목록 요약
        result += "## 포함된 파일 목록\n```\n"
        for rel_path, full_path, size in checked:
            result += f"  {rel_path} ({self.format_size(size)})\n"
        result += "```\n\n"

        # 파일 내용
        result += f"## 파일 내용\n\n"
        for i, (rel_path, full_path, size) in enumerate(checked, 1):
            content = self.read_file_safe(full_path)
            ext = os.path.splitext(rel_path)[1].lstrip('.')
            result += f"### [{i}/{len(checked)}] 📄 {rel_path}\n"
            result += f"```{ext}\n{content}\n```\n\n"

        # 결과 표시
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert('1.0', result)

        estimated_tokens = len(result) // 4
        self.token_label.config(
            text=f"약 {estimated_tokens:,}토큰 | {len(result):,}자")
        self.status_var.set(
            f"합치기 완료: {len(checked)}개 파일 → "
            f"약 {estimated_tokens:,}토큰 | {len(result):,}자")

    def copy_to_clipboard(self):
        content = self.result_text.get('1.0', tk.END).strip()
        if not content:
            # 트리에 체크된 파일이 있으면 자동으로 합치기 먼저 실행
            checked = self.get_checked_files()
            if checked:
                self.merge_checked_files()
                content = self.result_text.get('1.0', tk.END).strip()
            if not content:
                messagebox.showwarning("경고", "복사할 내용이 없습니다.\n"
                                       "먼저 스캔 후 파일을 선택해주세요.")
                return

        self.root.clipboard_clear()
        self.root.clipboard_append(content)

        estimated_tokens = len(content) // 4
        self.status_var.set("✅ 클립보드 복사 완료 → AI 채팅에 Ctrl+V")
        messagebox.showinfo("복사 완료",
                            f"클립보드에 복사되었습니다!\n"
                            f"약 {estimated_tokens:,}토큰 | {len(content):,}자\n\n"
                            f"AI 채팅창에 Ctrl+V로 붙여넣으세요.")


if __name__ == '__main__':
    root = tk.Tk()
    app = ProjectScan(root)
    root.mainloop()
