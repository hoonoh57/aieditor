#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_diff_engine.py - Comprehensive tests for diff_engine.py v6.1
Tests: strip_strings_and_comments, check_brace_balance, LineDiffParser, LineDiffEngine

Run:  cd E:\genspark && python -m tests.test_diff_engine
  or: cd E:\genspark && python tests/test_diff_engine.py
"""

import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.diff_engine import (
    strip_strings_and_comments,
    check_brace_balance,
    is_brace_language,
    LineDiffParser,
    LineDiffEngine,
)


# ============================================================
#  Test infrastructure
# ============================================================

_pass_count = 0
_fail_count = 0
_fail_details = []


def check(test_id, condition, description):
    global _pass_count, _fail_count
    if condition:
        _pass_count += 1
        print("  [PASS] %s: %s" % (test_id, description))
    else:
        _fail_count += 1
        _fail_details.append((test_id, description))
        print("  [FAIL] %s: %s" % (test_id, description))


def check_stripped(test_id, input_text, should_contain, should_not_contain, description):
    """Helper: strip input, verify presence/absence of substrings."""
    result = strip_strings_and_comments(input_text)
    ok = True
    for s in should_contain:
        if s not in result:
            ok = False
            break
    for s in should_not_contain:
        if s in result:
            ok = False
            break
    if not ok:
        global _fail_count
        _fail_count += 1
        _fail_details.append((test_id, description + " | result: " + repr(result[:200])))
        print("  [FAIL] %s: %s" % (test_id, description))
        print("         result: %s" % repr(result[:200]))
    else:
        global _pass_count
        _pass_count += 1
        print("  [PASS] %s: %s" % (test_id, description))


# ============================================================
#  Category 1: String handling
# ============================================================

def test_strings():
    print("\n=== Category 1: String handling ===")

    check_stripped("S1", 'x = "hello";',
        ['x = ', ';'], ['hello'],
        "basic string removed")

    check_stripped("S2", 'x = "{}";',
        ['x = ', ';'], ['{', '}'],
        "braces inside string removed")

    check_stripped("S3", r'x = "say \"hi\"";',
        ['x = ', ';'], ['say', 'hi'],
        "escaped quotes handled")

    check_stripped("S4", 'x = "연결된 API 없음";',
        ['x = ', ';'], ['연결된', 'API'],
        "Korean string removed")

    check_stripped("S5", 'x = "";',
        ['x = ', ';'], [],
        "empty string removed")

    check_stripped("S6", 'x = "a" + "b";',
        ['x = ', ' + ', ';'], ['a', 'b'],
        "concatenated strings removed")

    check_stripped("S7", 'Log("a: " + v + " b");',
        ['Log(', ' + v + ', ');'], [],
        "multiple strings in one line")

    # S8: string with parentheses inside
    check_stripped("S8", 'x = "func()";',
        ['x = ', ';'], ['func()'],
        "parentheses inside string removed")

    # S9: string with semicolons
    check_stripped("S9", 'x = "a;b;c";',
        ['x = ', ';'], ['a;b;c'],
        "semicolons inside string removed")

    # S10: many strings on one line (like the failing test case)
    line = '"[키움] 로그인 성공. 계좌: " + _kiwoom.GetFirstAccount() + " (총 " + n.ToString() + "개)"'
    result = strip_strings_and_comments(line)
    has_getfirst = '_kiwoom.GetFirstAccount()' in result
    has_tostring = 'n.ToString()' in result
    no_korean = '키움' not in result
    check("S10", has_getfirst and has_tostring and no_korean,
        "complex multi-string line with Korean")


# ============================================================
#  Category 2: C# verbatim strings
# ============================================================

def test_verbatim():
    print("\n=== Category 2: C# verbatim strings ===")

    check_stripped("V1", r'x = @"path\to\file";',
        ['x = ', ';'], ['path', 'file'],
        "basic verbatim string removed")

    check_stripped("V2", 'x = @"say ""hi""";',
        ['x = ', ';'], ['say', 'hi'],
        "verbatim with escaped quotes")

    check_stripped("V3", 'x = @"line1\nline2";',
        ['x = ', ';'], ['line1'],
        "verbatim preserves backslash (removed as string)")

    check_stripped("V4", 'x = @"{ }";',
        ['x = ', ';'], ['{', '}'],
        "braces inside verbatim removed")

    # V5: multi-line verbatim
    code = 'x = @"first line\nsecond line";'
    result = strip_strings_and_comments(code)
    check("V5", '{' not in result and '}' not in result,
        "multi-line verbatim no stray braces")

    # V6: verbatim with no special chars
    check_stripped("V6", 'x = @"simple";',
        ['x = ', ';'], ['simple'],
        "simple verbatim removed")


# ============================================================
#  Category 3: C# interpolated strings
# ============================================================

def test_interpolated():
    print("\n=== Category 3: C# interpolated strings ===")

    # I1: basic interpolated - braces should be KEPT
    code = 'x = $"count: {n}";'
    result = strip_strings_and_comments(code)
    check("I1", '{' in result and '}' in result,
        "interpolated braces kept: $\"count: {n}\"")

    # I2: interpolated + verbatim
    code = '$@"path {x}\\y"'
    result = strip_strings_and_comments(code)
    check("I2", '{' in result and '}' in result,
        "interpolated+verbatim braces kept")

    # I3: escaped {{ }} should NOT produce braces
    code = '$"literal {{brace}}"'
    result = strip_strings_and_comments(code)
    check("I3", '{' not in result and '}' not in result,
        "escaped {{ }} removed (not real braces)")

    # I4: nested expression
    code = '$"{obj.Method()}"'
    result = strip_strings_and_comments(code)
    check("I4", '{' in result and '}' in result and '(' in result and ')' in result,
        "nested expression braces and parens kept")

    # I5: @$ prefix (reverse order)
    code = '@$"path {x}\\y"'
    result = strip_strings_and_comments(code)
    check("I5", '{' in result and '}' in result,
        "@$ prefix braces kept")

    # I6: interpolated with no expressions
    code = '$"just a string"'
    result = strip_strings_and_comments(code)
    check("I6", '{' not in result and '}' not in result,
        "interpolated without expressions: no braces")


# ============================================================
#  Category 4: Char literals
# ============================================================

def test_char_literals():
    print("\n=== Category 4: Char literals ===")

    # C1: normal char
    code = "x = ';';"
    result = strip_strings_and_comments(code)
    check("C1", result.strip() == "x = ;",
        "char literal ';' removed")

    # C2: brace char - should NOT count as brace
    code = "x = '{';"
    result = strip_strings_and_comments(code)
    has_brace = '{' in result
    check("C2", not has_brace,
        "char literal '{' removed (not counted as brace)")

    # C3: escape char
    code = r"x = '\n';"
    result = strip_strings_and_comments(code)
    check("C3", 'x = ' in result and ';' in result,
        "escape char literal removed")

    # C4: apostrophe in non-char context (e.g., comments or identifiers)
    code = "// can't stop"
    result = strip_strings_and_comments(code)
    check("C4", "can" not in result,
        "apostrophe in comment: whole comment removed")

    # C5: closing brace char
    code = "x = '}';"
    result = strip_strings_and_comments(code)
    check("C5", '}' not in result,
        "char literal '}' removed")


# ============================================================
#  Category 5: Comments
# ============================================================

def test_comments():
    print("\n=== Category 5: Comments ===")

    # CM1: single-line comment with brace
    code = "x = 1; // comment {"
    result = strip_strings_and_comments(code)
    check("CM1", 'x = 1;' in result and '{' not in result,
        "single-line comment removed, brace gone")

    # CM2: block comment
    code = "/* { */ code"
    result = strip_strings_and_comments(code)
    check("CM2", 'code' in result and '{' not in result,
        "block comment removed, code kept")

    # CM3: comment with string pattern inside
    code = '// x = "{"'
    result = strip_strings_and_comments(code)
    check("CM3", '{' not in result and '"' not in result,
        "comment with string-like pattern fully removed")

    # CM4: Korean comment
    code = '// ★ 1단계: 초기화'
    result = strip_strings_and_comments(code)
    check("CM4", '★' not in result and '초기화' not in result,
        "Korean comment removed")

    # CM5: block comment spanning multiple lines
    code = "a = 1;\n/* comment\nspanning\nlines */\nb = 2;"
    result = strip_strings_and_comments(code)
    check("CM5", 'a = 1;' in result and 'b = 2;' in result and 'comment' not in result,
        "multi-line block comment removed")

    # CM6: comment after code on same line
    code = "int x = 5; /* inline */ int y = 6;"
    result = strip_strings_and_comments(code)
    check("CM6", 'int x = 5;' in result and 'int y = 6;' in result and 'inline' not in result,
        "inline block comment removed")


# ============================================================
#  Category 6: Brace balance on real C# patterns
# ============================================================

def test_brace_balance():
    print("\n=== Category 6: Brace balance checks ===")

    # F1: simple balanced
    code = "namespace A {\n  class B {\n    void M() { }\n  }\n}"
    ok, msg = check_brace_balance(code)
    check("F1", ok, "simple namespace/class/method balanced")

    # F2: with strings containing braces
    code = '''namespace A {
  class B {
    void M() {
      string x = "{}";
      string y = "{test}";
    }
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F2", ok, "strings with braces don't break balance")

    # F3: with Korean strings
    code = '''namespace Server32 {
  public class Dispatcher {
    void Init() {
      OnLog?.Invoke("[ERR] CybosPlus COM 초기화 실패: " + ex.Message);
      MessageBox.Show("Cybos 연결을 확인하세요!\\nCybosPlus를 먼저 실행 후 관리자 권한으로 다시 시작하세요.",
          "Cybos 연결 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F3", ok, "Korean strings with special chars balanced")

    # F4: missing closing brace
    code = "namespace A {\n  class B {\n    void M() { }\n  }\n"
    ok, msg = check_brace_balance(code)
    check("F4", not ok, "missing closing brace detected")

    # F5: extra closing brace
    code = "namespace A {\n  class B {\n    void M() { }\n  }\n}\n}"
    ok, msg = check_brace_balance(code)
    check("F5", not ok, "extra closing brace detected")

    # F6: interpolated string with braces
    code = '''class A {
  void M() {
    string s = $"value: {x + y}";
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F6", ok, "interpolated string braces balanced")

    # F7: verbatim string with braces
    code = '''class A {
  void M() {
    string s = @"test { } value";
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F7", ok, "verbatim string braces balanced")

    # F8: char literal with brace
    code = '''class A {
  void M() {
    char c = '{';
    char d = '}';
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F8", ok, "char literal braces balanced")

    # F9: comments with braces
    code = '''class A {
  // opening { in comment
  void M() {
    /* closing } in block comment */
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F9", ok, "comment braces don't affect balance")

    # F10: complex real-world pattern (like ServerDispatcher)
    code = '''namespace Server32 {
  public class ServerDispatcher {
    public async Task InitializeAsync() {
      try {
        _cybos = new CybosConnector();
      }
      catch (Exception ex) {
        OnLog?.Invoke("[ERR] CybosPlus COM 초기화 실패: " + ex.Message);
        MessageBox.Show("Cybos 연결을 확인하세요!\\nCybosPlus를 먼저 실행 후 관리자 권한으로 다시 시작하세요.",
            "Cybos 연결 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        Application.Exit();
        return;
      }
      if (!_cybos.IsConnected) {
        OnLog?.Invoke("[ERR] CybosPlus 미접속 상태");
      }
    }
    private async Task HandleOrder(uint seqNo, byte[] body) {
      using (var ms = new MemoryStream(body))
      using (var br = new BinaryReader(ms, Encoding.UTF8)) {
        OrderInfo result;
        if (source == "cybos" && _cybosOrder != null)
          result = _cybosOrder.SendOrder(code, orderType, price, qty);
        else
          result = new OrderInfo(
            orderNo: "", origOrderNo: "", code: code, name: "",
            type: orderType, condition: OrderCondition.Normal,
            state: OrderState.Rejected,
            orderPrice: price, orderQty: qty,
            execPrice: 0, execQty: 0, remainQty: qty,
            orderTime: DateTime.Now, execTime: DateTime.MinValue,
            accountNo: "", message: "연결된 API 없음");
      }
    }
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F10", ok, "complex real-world ServerDispatcher pattern balanced")

    # F11: switch/case
    code = '''class A {
  void M(int x) {
    switch (x) {
      case 1:
        break;
      case 2: {
        int y = x;
        break;
      }
      default:
        break;
    }
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F11", ok, "switch/case with braces balanced")

    # F12: lambda with braces
    code = '''class A {
  void M() {
    list.ForEach(x => { Console.WriteLine(x); });
    Action a = () => {
      int y = 0;
    };
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F12", ok, "lambda with braces balanced")

    # F13: ternary inside string concatenation (the actual failing case)
    code = '''class A {
  void M() {
    bool kiwoomOk = true;
    OnLog?.Invoke(kiwoomOk
        ? "[키움] 로그인 성공. 계좌: " + GetFirst() + " (총 " + n.ToString() + "개)"
        : "[키움] 로그인 실패 또는 타임아웃");
  }
}'''
    ok, msg = check_brace_balance(code)
    check("F13", ok, "ternary with multi-string concat balanced")


# ============================================================
#  Category 7: is_brace_language
# ============================================================

def test_is_brace_language():
    print("\n=== Category 7: is_brace_language ===")

    check("BL1", is_brace_language("test.cs"), ".cs is brace language")
    check("BL2", is_brace_language("test.java"), ".java is brace language")
    check("BL3", is_brace_language("test.js"), ".js is brace language")
    check("BL4", is_brace_language("test.ts"), ".ts is brace language")
    check("BL5", is_brace_language("test.cpp"), ".cpp is brace language")
    check("BL6", not is_brace_language("test.py"), ".py is NOT brace language")
    check("BL7", not is_brace_language("test.txt"), ".txt is NOT brace language")
    check("BL8", not is_brace_language("test.md"), ".md is NOT brace language")
    check("BL9", is_brace_language("test.vb"), ".vb is brace language")
    check("BL10", is_brace_language("Path/To/File.CS"),
        ".CS (uppercase) is brace language")


# ============================================================
#  Category 8: LineDiffParser
# ============================================================

def test_parser():
    print("\n=== Category 8: LineDiffParser ===")

    parser = LineDiffParser()

    # P1: single REPLACE
    diff = "@@ 5-7 REPLACE\nnew line 5\nnew line 6\nnew line 7\n@@ END"
    parsed, ops = parser.parse(diff)
    check("P1", '__current_file__' in parsed and len(parsed['__current_file__']) == 1,
        "single REPLACE parsed")
    if '__current_file__' in parsed and parsed['__current_file__']:
        cmd = parsed['__current_file__'][0]
        check("P1b", cmd['type'] == 'replace' and cmd['start'] == 5 and cmd['end'] == 7,
            "REPLACE range correct")

    # P2: DELETE
    diff = "@@ 10 DELETE 3"
    parsed, ops = parser.parse(diff)
    check("P2", '__current_file__' in parsed and parsed['__current_file__'][0]['type'] == 'delete',
        "DELETE parsed")

    # P3: INSERT
    diff = "@@ 20 INSERT\nnew line\n@@ END"
    parsed, ops = parser.parse(diff)
    check("P3", '__current_file__' in parsed and parsed['__current_file__'][0]['type'] == 'insert',
        "INSERT parsed")

    # P4: multi-file
    diff = """=== FILE: path/a.cs ===
@@ 1-2 REPLACE
new
@@ END
=== END FILE ===
=== FILE: path/b.cs ===
@@ 5-6 REPLACE
other
@@ END
=== END FILE ==="""
    parsed, ops = parser.parse(diff)
    check("P4", 'path/a.cs' in parsed and 'path/b.cs' in parsed,
        "multi-file parsed")

    # P5: CREATE FILE
    diff = """=== CREATE FILE: src/new.cs ===
using System;
class New { }
=== END FILE ==="""
    parsed, ops = parser.parse(diff)
    check("P5", len(ops) == 1 and ops[0]['op'] == 'create' and ops[0]['path'] == 'src/new.cs',
        "CREATE FILE parsed")
    check("P5b", 'class New' in ops[0]['content'],
        "CREATE FILE content correct")

    # P6: DELETE FILE
    diff = "=== DELETE FILE: old.cs ==="
    parsed, ops = parser.parse(diff)
    check("P6", len(ops) == 1 and ops[0]['op'] == 'delete' and ops[0]['path'] == 'old.cs',
        "DELETE FILE parsed")

    # P7: empty input
    parsed, ops = parser.parse("")
    check("P7", not parsed and not ops, "empty input returns empty")

    # P8: mixed REPLACE + DELETE in one file
    diff = """=== FILE: test.cs ===
@@ 10-12 REPLACE
replaced
@@ END
@@ 5 DELETE 2
=== END FILE ==="""
    parsed, ops = parser.parse(diff)
    check("P8", 'test.cs' in parsed and len(parsed['test.cs']) == 2,
        "mixed commands in one file")


# ============================================================
#  Category 9: LineDiffEngine.apply_to_content
# ============================================================

def test_apply_content():
    print("\n=== Category 9: apply_to_content ===")

    engine = LineDiffEngine()

    # D1: normal REPLACE (no brace change)
    original = "line1\nline2\nline3\nline4\nline5"
    cmds = [{'type': 'replace', 'start': 2, 'end': 3, 'content': 'new2\nnew3'}]
    engine._current_filepath = None  # no brace check
    result, msgs = engine.apply_to_content(original, cmds)
    check("D1", 'new2' in result and 'new3' in result and '[OK]' in msgs[1],
        "normal REPLACE applied")

    # D2: REPLACE that breaks braces should be blocked
    original = "class A {\n  void M() {\n    int x = 0;\n  }\n}"
    cmds = [{'type': 'replace', 'start': 3, 'end': 3,
             'content': '    int x = 0;\n  }'}]  # extra }
    engine._current_filepath = "test.cs"
    result, msgs = engine.apply_to_content(original, cmds)
    has_block = any('[BLOCK]' in m for m in msgs)
    has_rollback = any('[ROLLBACK]' in m for m in msgs)
    check("D2", has_block and has_rollback,
        "brace-breaking REPLACE blocked and rolled back")

    # D3: DELETE
    original = "line1\nline2\nline3\nline4\nline5"
    cmds = [{'type': 'delete', 'start': 2, 'count': 2}]
    engine._current_filepath = None
    result, msgs = engine.apply_to_content(original, cmds)
    lines = result.split('\n')
    check("D3", len(lines) == 3 and 'line1' in result and 'line4' in result,
        "DELETE removes correct lines")

    # D4: INSERT
    original = "line1\nline2\nline3"
    cmds = [{'type': 'insert', 'after': 1, 'content': 'inserted'}]
    engine._current_filepath = None
    result, msgs = engine.apply_to_content(original, cmds)
    lines = result.split('\n')
    check("D4", lines[1] == 'inserted' and len(lines) == 4,
        "INSERT adds line at correct position")

    # D5: multiple changes applied bottom-to-top
    original = "line1\nline2\nline3\nline4\nline5"
    cmds = [
        {'type': 'replace', 'start': 2, 'end': 2, 'content': 'new2'},
        {'type': 'replace', 'start': 4, 'end': 4, 'content': 'new4'},
    ]
    engine._current_filepath = None
    result, msgs = engine.apply_to_content(original, cmds)
    check("D5", 'new2' in result and 'new4' in result,
        "multiple REPLACE applied correctly (bottom-up)")

    # D6: REPLACE out of range
    original = "line1\nline2"
    cmds = [{'type': 'replace', 'start': 100, 'end': 105, 'content': 'x'}]
    engine._current_filepath = None
    result, msgs = engine.apply_to_content(original, cmds)
    has_error = any('[X]' in m for m in msgs)
    check("D6", has_error, "out-of-range REPLACE reports error")

    # D7: valid C# REPLACE preserves balance
    original = '''class A {
  void M() {
    int x = 0;
  }
}'''
    cmds = [{'type': 'replace', 'start': 3, 'end': 3, 'content': '    int x = 1;'}]
    engine._current_filepath = "test.cs"
    result, msgs = engine.apply_to_content(original, cmds)
    has_ok = any('[OK]' in m for m in msgs)
    has_brace_ok = any('[BRACE OK]' in m for m in msgs)
    check("D7", has_ok and has_brace_ok,
        "valid C# REPLACE passes brace check")

    engine._current_filepath = None


# ============================================================
#  Category 10: JS/TS template literals
# ============================================================

def test_template_literals():
    print("\n=== Category 10: JS/TS template literals ===")

    # T1: basic template literal
    code = "const s = `hello ${name}`;"
    result = strip_strings_and_comments(code)
    check("T1", 'name' not in result or '{' in result,
        "template literal processed")

    # T2: template with expression
    code = "const s = `count: ${a + b}`;"
    result = strip_strings_and_comments(code)
    check("T2", '{' in result and '}' in result,
        "template expression braces kept")

    # T3: nested template
    code = "const s = `${a ? `yes` : `no`}`;"
    result = strip_strings_and_comments(code)
    # this is a complex edge case, just verify no crash
    check("T3", True, "nested template literal no crash")


# ============================================================
#  Category 11: Edge cases
# ============================================================

def test_edge_cases():
    print("\n=== Category 11: Edge cases ===")

    # E1: empty string
    result = strip_strings_and_comments("")
    check("E1", result == "", "empty input returns empty")

    # E2: no strings or comments
    code = "int x = 5;"
    result = strip_strings_and_comments(code)
    check("E2", result == code, "code without strings unchanged")

    # E3: only comments
    code = "// just a comment"
    result = strip_strings_and_comments(code)
    check("E3", result.strip() == "", "only comment returns empty")

    # E4: string at end of file without newline
    code = 'x = "test"'
    result = strip_strings_and_comments(code)
    check("E4", 'x = ' in result and 'test' not in result,
        "string at EOF handled")

    # E5: @ not followed by quote (C# identifier like @class)
    code = 'int @class = 5;'
    result = strip_strings_and_comments(code)
    check("E5", '@class' in result and '5' in result,
        "@ as identifier prefix preserved")

    # E6: $ not followed by quote
    code = 'int $var = 5;'
    result = strip_strings_and_comments(code)
    check("E6", '$var' in result,
        "$ as identifier prefix preserved")

    # E7: unclosed string at EOF (defensive)
    code = 'x = "unclosed'
    result = strip_strings_and_comments(code)
    check("E7", True, "unclosed string at EOF no crash")

    # E8: unclosed block comment at EOF (defensive)
    code = 'x = 1; /* unclosed'
    result = strip_strings_and_comments(code)
    check("E8", True, "unclosed block comment at EOF no crash")

    # E9: Windows line endings (\r\n)
    code = "class A {\r\n  void M() {\r\n  }\r\n}"
    ok, msg = check_brace_balance(code)
    check("E9", ok, "Windows CRLF line endings handled")

    # E10: file with BOM
    code = "\ufeffclass A {\n  void M() {\n  }\n}"
    ok, msg = check_brace_balance(code)
    check("E10", ok, "UTF-8 BOM handled")


# ============================================================
#  Main
# ============================================================

def main():
    print("=" * 60)
    print("  diff_engine.py v6.1 - Comprehensive Test Suite")
    print("=" * 60)

    test_strings()
    test_verbatim()
    test_interpolated()
    test_char_literals()
    test_comments()
    test_brace_balance()
    test_is_brace_language()
    test_parser()
    test_apply_content()
    test_template_literals()
    test_edge_cases()

    print("\n" + "=" * 60)
    print("  RESULTS: %d passed, %d failed" % (_pass_count, _fail_count))
    print("=" * 60)

    if _fail_details:
        print("\nFailed tests:")
        for tid, desc in _fail_details:
            print("  [FAIL] %s: %s" % (tid, desc))

    if _fail_count == 0:
        print("\nALL TESTS PASSED")
    else:
        print("\n%d TEST(S) FAILED" % _fail_count)

    return _fail_count == 0


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
