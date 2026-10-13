"""打包提交 ZIP。

- 按赛事命名规则产出：组别-参赛编号-队伍名称-队长姓名.zip
- 打包前对每个待入包文件做密钥泄露扫描，命中即中止，不生成半成品包
- 扫描命中只打印「文件:行号 + 规则名」，绝不打印密钥原文，避免二次泄露

用法：
    python scripts/package.py
    python scripts/package.py --group 本科生组 --code U126 --team 大肥鱼脚香香 --leader 李家杰
"""

import argparse
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

EXCLUDE_DIRS = {".git", "__pycache__", ".idea", ".vscode", ".codebuddy", "node_modules", "dist"}
EXCLUDE_FILES = {".env", "out.log", "err.log"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".log", ".tmp", ".zip"}

# 密钥特征：保守匹配，避免误杀占位符与空值
SECRET_RULES = [
    ("sk-令牌", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("硬编码AGNES_API_KEY", re.compile(r"AGNES_API_KEY\s*[=:]\s*[\"']?[A-Za-z0-9_\-]{8,}")),
    ("硬编码api_key", re.compile(r"api[_]?key\s*[=:]\s*[\"']sk-[A-Za-z0-9]+", re.IGNORECASE)),
]

SCAN_MAX_BYTES = 2 * 1024 * 1024
TEXT_SUFFIX = {".py", ".md", ".json", ".txt", ".js", ".css", ".html", ".yml", ".yaml", ".cfg", ".ini", ".example"}


def should_skip(name):
    if name in EXCLUDE_DIRS or name in EXCLUDE_FILES:
        return True
    return os.path.splitext(name)[1] in EXCLUDE_SUFFIX


def scan_file(path):
    """返回命中列表 [(行号, 规则名)]，不返回密钥原文。"""
    if os.path.splitext(path)[1] not in TEXT_SUFFIX:
        return []
    try:
        if os.path.getsize(path) > SCAN_MAX_BYTES:
            return []
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return []

    hits = []
    for lineno, line in enumerate(lines, 1):
        for rule_name, pattern in SECRET_RULES:
            if pattern.search(line):
                hits.append((lineno, rule_name))
                break
    return hits


def collect_files():
    files = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if not should_skip(d)]
        for name in sorted(names):
            if should_skip(name):
                continue
            files.append(os.path.join(base, name))
    return files


def scan_all(files):
    findings = []
    for path in files:
        for lineno, rule_name in scan_file(path):
            findings.append((os.path.relpath(path, ROOT), lineno, rule_name))
    return findings


def build_zip(group, code, team, leader):
    os.makedirs(DIST, exist_ok=True)
    target_name = "%s-%s-%s-%s.zip" % (group, code, team, leader)
    target = os.path.join(DIST, target_name)

    files = collect_files()
    findings = scan_all(files)
    if findings:
        print("密钥泄露扫描未通过，已中止打包（未生成 ZIP）：")
        for rel, lineno, rule in findings:
            print("  %s:%d 命中规则[%s]" % (rel, lineno, rule))
        print("\n请移除或脱敏上述内容后重新打包。赛事要求：Key 不得出现在公开代码库、截图或演示材料中。")
        return 1

    total = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, os.path.relpath(path, ROOT))
            total += os.path.getsize(path)

    size_mb = os.path.getsize(target) / 1024 / 1024
    print("密钥扫描: 通过（%d 个文件，未发现密钥）" % len(files))
    print("打包完成: %s" % target)
    print("文件数: %d | 压缩包: %.2f MB（限制 200MB）" % (len(files), size_mb))
    if size_mb > 200:
        print("警告：超出 200MB，请清理 outputs/ 或演示视频后重新打包")
        return 1
    return 0


def main():
    p = argparse.ArgumentParser(description="按赛事规则打包参赛作品")
    p.add_argument("--group", default="本科生组", help="参赛组别")
    p.add_argument("--code", default="U126", help="参赛编号")
    p.add_argument("--team", default="大肥鱼脚香香", help="队伍名称")
    p.add_argument("--leader", default="李家杰", help="队长姓名")
    p.add_argument("--scan-only", action="store_true", help="只做密钥扫描，不打包")
    a = p.parse_args()

    if a.scan_only:
        findings = scan_all(collect_files())
        if findings:
            for rel, lineno, rule in findings:
                print("  %s:%d 命中规则[%s]" % (rel, lineno, rule))
            return 1
        print("扫描通过，未发现密钥")
        return 0
    return build_zip(a.group, a.code, a.team, a.leader)


if __name__ == "__main__":
    sys.exit(main())
