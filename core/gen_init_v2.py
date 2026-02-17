import os

content = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProjectScan Core Modules
"""
from .encoding_handler import EncodingHandler, TextNormalizer
from .diff_engine import LineDiffParser, LineDiffEngine
from .github_sync import GitHubUploader
from .checkbox_tree import CheckboxTreeview
from .code_editor import CodeEditor
from .code_reviewer import CodeReviewer

__all__ = [
    'EncodingHandler', 'TextNormalizer',
    'LineDiffParser', 'LineDiffEngine',
    'GitHubUploader',
    'CheckboxTreeview',
    'CodeEditor',
    'CodeReviewer',
]
'''

path = os.path.join(r"E:\genspark\core", "__init__.py")
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print(f"Updated: {path}")
print(f"Size: {os.path.getsize(path)} bytes")
