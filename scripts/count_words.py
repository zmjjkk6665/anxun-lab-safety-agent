"""统计提交文案字数：作品简介（≤50 字）与作品详情（≤5000 字）。"""

import io
import re

FENCE = chr(96) * 3

path = "docs/提交表单-可直接粘贴.md"
txt = io.open(path, encoding="utf-8").read()
blocks = re.findall(FENCE + r"\n(.*?)" + FENCE, txt, re.S)

labels = ["作品名称", "作品简介", "作品详情"]
for i, b in enumerate(blocks):
    s = b.strip()
    n = len(re.sub(r"\s", "", s))
    name = labels[i] if i < len(labels) else "其他 %d" % i
    print("%s: %d 字（不含空白）| %d 字符（含空白）| 限定 %s" % (
        name, n, len(s), "50" if name == "作品简介" else ("5000" if name == "作品详情" else "-")))
    print("   开头: %s" % s[:40].replace("\n", " "))
