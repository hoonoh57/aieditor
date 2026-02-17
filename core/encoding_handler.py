#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
encoding_handler.py — Encoding detection and text normalization for ProjectScan
"""

import os
import unicodedata


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
