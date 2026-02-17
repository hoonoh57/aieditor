#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
github_sync.py — GitHub Auto-Sync module for ProjectScan
Handles git init, commit, push, rollback.
"""

import os
import subprocess
import tempfile
import shutil
from datetime import datetime


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
        """Stage all, commit with message, force push to origin."""
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
