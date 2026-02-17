import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import os
import fnmatch


class ProjectScan:
    def __init__(self, root):
        self.root = root
        self.root.title("📂 ProjectScan — 프로젝트 스캔 도구")
        self.root.geometry("900x700")
        self.root.configure(bg="#1e1e2e")

        self.project_path = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="프로젝트 폴더를 선택하세요")
        self.include_content = tk.BooleanVar(value=True)
        self.max_file_size = tk.IntVar(value=50)
        self.token_count = tk.IntVar(value=0)

        self.default_excludes = [
            'node_modules', '.git', '__pycache__', '.next', 'dist',
            'build', '.venv', 'venv', 'env', '.env', '.idea', '.vscode',
            '*.pyc', '*.pyo', '*.exe', '*.dll', '*.so', '*.dylib',
            '*.jpg', '*.jpeg', '*.png', '*.gif', '*.ico', '*.svg',
            '*.mp3', '*.mp4', '*.avi', '*.mov', '*.pdf',
            '*.zip', '*.tar', '*.gz', '*.rar',
            '*.lock', 'package-lock.json', 'yarn.lock',
            '*.min.js', '*.min.css', '*.map',
            '.DS_Store', 'Thumbs.db','*.bak',
            '.patch_backup', '*.bak', '*.bmp', '*.log', '*.dylib', '*.bmp', '*.pdb',
            '*.bmp','*.exp', '*.lib', '*.resx','*.resources','*.props', '*.targets','*.cache',
			'*.tlog', '*.recipe', '*.ilk', '*.obj', '*.idb' ,'*.json'
        ]

        self.code_extensions = [
            '.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.scss',
            '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.go', '.rs',
            '.rb', '.php', '.swift', '.kt', '.scala', '.r', '.R',
            '.sql', '.sh', '.bash', '.bat', '.cmd', '.ps1',
            '.json', '.jsonc', '.yaml', '.yml', '.toml', '.ini', '.cfg',
            '.xml', '.md', '.txt', '.env.example', '.gitignore',
            '.dockerfile', 'Dockerfile', '.dockerignore',
            'Makefile', 'CMakeLists.txt', '.vue', '.svelte', '*.vb'
        ]

        self.setup_styles()
        self.create_widgets()

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

    def create_widgets(self):
        # 제목
        title_frame = tk.Frame(self.root, bg='#1e1e2e')
        title_frame.pack(fill='x', padx=20, pady=(15, 5))
        ttk.Label(title_frame, text="📂 ProjectScan", style='Title.TLabel').pack(side='left')
        ttk.Label(title_frame, text="프로젝트를 스캔해서 AI에게 보내기",
                  style='Info.TLabel').pack(side='left', padx=(15, 0))

        # 프로젝트 폴더 선택
        folder_frame = tk.Frame(self.root, bg='#1e1e2e')
        folder_frame.pack(fill='x', padx=20, pady=5)

        tk.Button(folder_frame, text="📁 프로젝트 폴더 선택",
                  font=('맑은 고딕', 10), bg='#45475a', fg='#cdd6f4',
                  relief='flat', padx=10, pady=5,
                  command=self.select_folder).pack(side='left')

        self.folder_label = ttk.Label(folder_frame, text="선택되지 않음", style='Info.TLabel')
        self.folder_label.pack(side='left', padx=(10, 0))

        ttk.Checkbutton(folder_frame, text="파일 내용 포함",
                        variable=self.include_content,
                        style='TCheckbutton').pack(side='right')

        # 옵션
        opt_frame = tk.Frame(self.root, bg='#1e1e2e')
        opt_frame.pack(fill='x', padx=20, pady=5)

        ttk.Label(opt_frame, text="최대 파일 크기(KB):", style='Info.TLabel').pack(side='left')
        size_spin = tk.Spinbox(opt_frame, from_=10, to=500, width=5,
                               textvariable=self.max_file_size,
                               font=('Consolas', 10), bg='#313244', fg='#cdd6f4')
        size_spin.pack(side='left', padx=5)

        # 스캔 모드 버튼
        mode_frame = tk.Frame(self.root, bg='#1e1e2e')
        mode_frame.pack(fill='x', padx=20, pady=10)

        tk.Button(mode_frame, text="🔍 구조만 스캔\n(폴더/파일 목록)",
                  font=('맑은 고딕', 11, 'bold'), bg='#89b4fa', fg='#1e1e2e',
                  relief='flat', padx=20, pady=10, cursor='hand2',
                  command=lambda: self.scan('structure')).pack(side='left', expand=True, fill='x', padx=(0, 5))

        tk.Button(mode_frame, text="📄 전체 스캔\n(구조 + 파일 내용)",
                  font=('맑은 고딕', 11, 'bold'), bg='#a6e3a1', fg='#1e1e2e',
                  relief='flat', padx=20, pady=10, cursor='hand2',
                  command=lambda: self.scan('full')).pack(side='left', expand=True, fill='x', padx=5)

        tk.Button(mode_frame, text="🎯 선택 스캔\n(특정 파일만)",
                  font=('맑은 고딕', 11, 'bold'), bg='#f9e2af', fg='#1e1e2e',
                  relief='flat', padx=20, pady=10, cursor='hand2',
                  command=lambda: self.scan('select')).pack(side='left', expand=True, fill='x', padx=(5, 0))

        # 결과 영역
        result_frame = tk.Frame(self.root, bg='#1e1e2e')
        result_frame.pack(fill='both', expand=True, padx=20, pady=5)

        result_header = tk.Frame(result_frame, bg='#1e1e2e')
        result_header.pack(fill='x')
        ttk.Label(result_header, text="📋 스캔 결과", style='Info.TLabel').pack(side='left')
        self.token_label = ttk.Label(result_header, text="", style='Info.TLabel')
        self.token_label.pack(side='right')

        self.result_text = scrolledtext.ScrolledText(
            result_frame, wrap=tk.WORD, font=('Consolas', 10),
            bg='#313244', fg='#cdd6f4', insertbackground='#f5e0dc',
            relief='flat', padx=10, pady=10
        )
        self.result_text.pack(fill='both', expand=True, pady=(5, 0))

        # 복사 버튼
        copy_frame = tk.Frame(self.root, bg='#1e1e2e')
        copy_frame.pack(fill='x', padx=20, pady=10)

        tk.Button(copy_frame, text="📋 클립보드에 복사 → AI 채팅에 붙여넣기",
                  font=('맑은 고딕', 13, 'bold'), bg='#cba6f7', fg='#1e1e2e',
                  relief='flat', padx=30, pady=10, cursor='hand2',
                  command=self.copy_to_clipboard).pack(fill='x')

        # 상태바
        status_frame = tk.Frame(self.root, bg='#11111b')
        status_frame.pack(fill='x', side='bottom')
        ttk.Label(status_frame, textvariable=self.status_var,
                  style='Status.TLabel').pack(padx=10, pady=5)

    def select_folder(self):
        folder = filedialog.askdirectory(title="프로젝트 폴더 선택")
        if folder:
            self.project_path.set(folder)
            self.folder_label.config(text=folder)
            self.status_var.set(f"프로젝트: {folder}")

    def should_exclude(self, path, name):
        for pattern in self.default_excludes:
            if fnmatch.fnmatch(name, pattern):
                return True
            if name == pattern:
                return True
        return False

    def is_code_file(self, filename):
        if filename in ['Dockerfile', 'Makefile', 'CMakeLists.txt', '.gitignore', '.env.example']:
            return True
        _, ext = os.path.splitext(filename)
        return ext.lower() in self.code_extensions

    def get_file_tree(self, path, prefix="", max_depth=5, current_depth=0):
        if current_depth >= max_depth:
            return prefix + "... (깊이 제한)\n"

        result = ""
        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            return prefix + "... (접근 불가)\n"

        dirs = []
        files = []
        for entry in entries:
            if self.should_exclude(path, entry):
                continue
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                dirs.append(entry)
            elif os.path.isfile(full):
                files.append(entry)

        items = dirs + files
        for i, entry in enumerate(items):
            is_last = (i == len(items) - 1)
            connector = "└── " if is_last else "├── "
            full = os.path.join(path, entry)

            if os.path.isdir(full):
                result += f"{prefix}{connector}📁 {entry}/\n"
                next_prefix = prefix + ("    " if is_last else "│   ")
                result += self.get_file_tree(full, next_prefix, max_depth, current_depth + 1)
            else:
                size = os.path.getsize(full)
                size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
                result += f"{prefix}{connector}{entry} ({size_str})\n"

        return result

    def get_code_files(self, path):
        code_files = []
        for root_dir, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not self.should_exclude(root_dir, d)]

            for f in files:
                if self.should_exclude(root_dir, f):
                    continue
                if not self.is_code_file(f):
                    continue

                full_path = os.path.join(root_dir, f)
                rel_path = os.path.relpath(full_path, path)
                size = os.path.getsize(full_path)

                if size <= self.max_file_size.get() * 1024:
                    code_files.append((rel_path, full_path, size))

        return code_files

    def read_file_safe(self, filepath):
        encodings = ['utf-8', 'cp949', 'euc-kr', 'latin-1']
        for enc in encodings:
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return "[읽기 실패: 인코딩 문제]"

    def scan(self, mode):
        project = self.project_path.get()
        if not project:
            messagebox.showwarning("경고", "프로젝트 폴더를 먼저 선택하세요!")
            return

        self.result_text.delete('1.0', tk.END)
        self.status_var.set("스캔 중...")
        self.root.update()

        result = f"# 프로젝트 스캔 결과\n"
        result += f"# 경로: {project}\n"
        result += f"# 시간: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        if mode == 'structure':
            result += "## 프로젝트 구조\n```\n"
            result += self.get_file_tree(project)
            result += "```\n"

            self.show_result_and_copy(result)

        elif mode == 'full':
            result += "## 프로젝트 구조\n```\n"
            result += self.get_file_tree(project)
            result += "```\n\n"

            code_files = self.get_code_files(project)
            result += f"## 파일 내용 ({len(code_files)}개 파일)\n\n"

            for rel_path, full_path, size in code_files:
                content = self.read_file_safe(full_path)
                ext = os.path.splitext(rel_path)[1].lstrip('.')
                result += f"### 📄 {rel_path}\n"
                result += f"```{ext}\n{content}\n```\n\n"

            self.show_result_and_copy(result)

        elif mode == 'select':
            code_files = self.get_code_files(project)
            self.show_file_selector(code_files)

    def show_file_selector(self, code_files):
        selector = tk.Toplevel(self.root)
        selector.title("파일 선택")
        selector.geometry("600x500")
        selector.configure(bg='#1e1e2e')
        selector.grab_set()

        ttk.Label(selector, text="스캔할 파일을 선택하세요:",
                  style='Info.TLabel').pack(padx=10, pady=10)

        btn_frame = tk.Frame(selector, bg='#1e1e2e')
        btn_frame.pack(fill='x', padx=10)

        list_frame = tk.Frame(selector, bg='#1e1e2e')
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')

        listbox = tk.Listbox(list_frame, selectmode=tk.MULTIPLE,
                             font=('Consolas', 10), bg='#313244', fg='#cdd6f4',
                             selectbackground='#585b70', relief='flat',
                             yscrollcommand=scrollbar.set)
        listbox.pack(fill='both', expand=True)
        scrollbar.config(command=listbox.yview)

        for rel_path, full_path, size in code_files:
            size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
            listbox.insert(tk.END, f"{rel_path} ({size_str})")

        def select_all():
            listbox.select_set(0, tk.END)

        def select_none():
            listbox.select_clear(0, tk.END)

        tk.Button(btn_frame, text="전체 선택", bg='#45475a', fg='#cdd6f4',
                  relief='flat', command=select_all).pack(side='left', padx=2)
        tk.Button(btn_frame, text="전체 해제", bg='#45475a', fg='#cdd6f4',
                  relief='flat', command=select_none).pack(side='left', padx=2)

        def confirm():
            indices = listbox.curselection()
            selected = []
            for i in indices:
                selected.append(code_files[i])
            selector.destroy()

            if selected:
                project = self.project_path.get()
                result = f"# 프로젝트 스캔 결과\n"
                result += f"# 경로: {project}\n"
                result += f"# 시간: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                result += f"## 선택된 파일 내용 ({len(selected)}개)\n\n"

                for rel_path, full_path, size in selected:
                    content = self.read_file_safe(full_path)
                    ext = os.path.splitext(rel_path)[1].lstrip('.')
                    result += f"### 📄 {rel_path}\n"
                    result += f"```{ext}\n{content}\n```\n\n"

                self.show_result_and_copy(result)
            else:
                self.status_var.set("파일을 선택하지 않았습니다")

        def cancel():
            selector.destroy()
            self.status_var.set("취소됨")

        ok_frame = tk.Frame(selector, bg='#1e1e2e')
        ok_frame.pack(fill='x', padx=10, pady=10)
        tk.Button(ok_frame, text="✅ 확인", font=('맑은 고딕', 11, 'bold'),
                  bg='#a6e3a1', fg='#1e1e2e', relief='flat', padx=20, pady=8,
                  command=confirm).pack(side='left', expand=True, fill='x', padx=(0, 5))
        tk.Button(ok_frame, text="취소", font=('맑은 고딕', 11),
                  bg='#45475a', fg='#cdd6f4', relief='flat', padx=20, pady=8,
                  command=cancel).pack(side='left', expand=True, fill='x', padx=(5, 0))

        selector.wait_window()

    def show_result_and_copy(self, result):
        """결과를 표시하고 자동으로 클립보드에 복사"""
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert('1.0', result)

        estimated_tokens = len(result) // 4
        self.token_label.config(text=f"약 {estimated_tokens:,}토큰 | {len(result):,}자")

        self.root.clipboard_clear()
        self.root.clipboard_append(result)

        self.status_var.set(f"✅ 클립보드 복사 완료 (약 {estimated_tokens:,}토큰) → AI 채팅에 Ctrl+V")
        messagebox.showinfo("복사 완료",
                            f"클립보드에 복사되었습니다!\n"
                            f"약 {estimated_tokens:,}토큰 | {len(result):,}자\n\n"
                            f"AI 채팅창에 Ctrl+V로 붙여넣으세요.")

    def copy_to_clipboard(self):
        content = self.result_text.get('1.0', tk.END).strip()
        if not content:
            messagebox.showwarning("경고", "복사할 내용이 없습니다")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.status_var.set("✅ 클립보드에 복사됨 → AI 채팅에 Ctrl+V")
        messagebox.showinfo("완료", "클립보드에 복사되었습니다!\n\nAI 채팅창에 Ctrl+V로 붙여넣으세요.")


if __name__ == '__main__':
    root = tk.Tk()
    app = ProjectScan(root)
    root.mainloop()
