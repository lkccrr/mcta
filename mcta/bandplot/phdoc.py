"""mt.ph v / V —— 查询随 mcta 附带的 phonopy 本地用法词库。

数据文件 ``mcta/bandplot/phonopy_docs.json`` 收录 phonopy 命令行工具、
命令行选项与配置标签的用法：

* 英文原文：摘自 phonopy 官方文档 https://phonopy.github.io/phonopy/ 的
  相应小节；
* 中文：与英文原文对应的译文。

查询时每条词条先给一行该词条所在在线文档页面的标题与版本号，空一行后
是英文原文，再空一行是中文翻译；全程只读本地文件、不访问网络。
需要换词库时可用环境变量 ``MT_PH_DOCS`` 指向自己的 JSON（格式同附带的
词库）。

    mt.ph v                        列出全部可查询的命令 / 选项 / 标签
    mt.ph V --dim BAND_LABELS      查阅这些词的用法（英文原文 + 中文翻译）
    mt.ph v --all                  打印整份词库
    mt.ph v --path                 打印词库文件路径
"""

import json
import os
import re

BASE = "https://phonopy.github.io/phonopy/"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "phonopy_docs.json")
ENV_FILE = "MT_PH_DOCS"

GROUPS = (
    ("tool", "命令行工具"),
    ("option", "命令行选项"),
    ("tag", "配置文件标签"),
    ("concept", "其它条目"),
)
GROUP_ORDER = {name: index for index, (name, _) in enumerate(GROUPS)}
MAX_HITS = 3


# ------------------------------------------------------------------ 词库 ---
def _data_path():
    override = os.environ.get(ENV_FILE)
    return override if override else DATA_FILE


def _load(path):
    """返回 (entries, meta)；meta 可能是空 dict（自定义词库可不带）。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        print("ERROR: 无法读取本地 phonopy 词库：%s（%s）" % (path, error))
        return None, None
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        print("ERROR: 本地词库内容为空或格式不对：%s" % path)
        return None, None
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return entries, meta


def _key(word):
    """归一化：去前导横线、非字母数字转空格、小写。"""
    text = re.sub(r"^[-\s]+", "", str(word).lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _score(entry, key):
    """精确命中优先；短词只认精确命中，避免 -t 误命中 thermal。"""
    if not key:
        return 0
    keys = {_key(item) for item in entry.get("keys", [])}
    keys.add(_key(entry.get("name", "")))
    score = 0
    for candidate in keys:
        if candidate == key:
            score = max(score, 100)
        elif len(key) >= 3 and candidate.startswith(key):
            score = max(score, 70)
        elif len(key) >= 4 and key in candidate:
            score = max(score, 50)
    words = key.split()
    if len(words) > 1 and all(word in _key(entry.get("name", "")).split()
                              for word in words):
        score = max(score, 60)
    return score


def _rank(entries, word):
    key = _key(word)
    ranked = []
    for entry in entries:
        score = _score(entry, key)
        if score:
            ranked.append((-score,
                           GROUP_ORDER.get(entry.get("group"), 99),
                           entry.get("name", "").lower(), entry))
    ranked.sort(key=lambda item: item[:3])
    if ranked:
        top = -ranked[0][0]
        # 只保留与最佳命中接近的结果，避免 "band" 带出一堆 BAND_* 标签
        ranked = [item for item in ranked if -item[0] >= max(70, top - 25)]
    picked, seen = [], set()
    for _, _, _, entry in ranked:
        if entry["name"] in seen:
            continue
        seen.add(entry["name"])
        picked.append(entry)
        if len(picked) == MAX_HITS:
            break
    return picked


# ------------------------------------------------------------------ 输出 ---
def _doc_line(entry, meta):
    """词条所在在线文档页面的标题与版本号（如 "Setting tags — Phonopy v.4.10.0"）。

    优先取 meta["page_titles"][页面名]（按词条 URL 推断页面）；
    拿不到时退回 meta 的总标题 + 版本号。
    """
    url = entry.get("url") or ""
    page = ""
    if url.startswith(BASE):
        page = url[len(BASE):].split("#")[0]
        if page.endswith(".html"):
            page = page[:-5]
    titles = meta.get("page_titles") or {}
    title = titles.get(page)
    if title:
        return title
    version = meta.get("doc_version")
    base_title = meta.get("title") or "phonopy"
    if version:
        return "%s v.%s" % (base_title, version)
    return base_title


def _columns(items):
    width = min(48, max(len(item) for item in items) + 3)
    cols = max(1, 100 // width)
    for start in range(0, len(items), cols):
        print("  " + "".join("%-*s" % (width, item[:width - 1])
                             for item in items[start:start + cols]))


def _show(entry, meta):
    """单个词条：标题行 -> 空行 -> 英文原文 -> 空行 -> 中文翻译。"""
    label = dict(GROUPS).get(entry.get("group"), "其它条目")
    print("[%s] %s" % (label, entry["name"]))
    print(_doc_line(entry, meta))
    print()
    print(entry.get("en", "").strip())
    if entry.get("truncated"):
        print("（英文在此截断，完整内容见在线文档对应小节。）")
    print()
    print(entry.get("zh", "").strip())
    print()


def _list(entries, meta):
    print("phonopy 本地用法词库：%s" % _data_path())
    source = meta.get("source") or BASE
    title = meta.get("title") or "phonopy"
    version = meta.get("doc_version")
    line = "来源：%s" % source
    if version:
        line = "%s — %s v.%s" % (line, title, version)
    elif title:
        line = "%s — %s" % (line, title)
    print(line)
    if os.environ.get(ENV_FILE):
        print("（自定义词库来自环境变量 %s）" % ENV_FILE)
    known = {name for name, _ in GROUPS}
    others = sorted({entry["name"] for entry in entries
                     if entry.get("group") not in known}, key=str.lower)
    for group, label in GROUPS:
        items = sorted({entry["name"] for entry in entries
                        if entry.get("group") == group}, key=str.lower)
        if items:
            print("\n%s（%d 项）：" % (label, len(items)))
            _columns(items)
    if others:
        print("\n其它条目（%d 项）：" % len(others))
        _columns(others)
    print("\n用法：mt.ph v <词> [<词> ...]  查用法，英文/中文")
    print("      mt.ph v --all            打印整份词库")
    print("      mt.ph v --path           显示词库文件路径")
    print("      mt.ph V ...              大小写均可")
    return 0


def _lookup(word, entries, meta):
    print("=== %s ===" % word)
    picked = _rank(entries, word)
    if not picked:
        print("本地词库未收录该词。用 mt.ph v 查看全部条目，")
        print("或把新词条按同样格式补进 %s" % _data_path())
        print()
        return False
    for entry in picked:
        _show(entry, meta)
    return True


def _help():
    print("用法：mt.ph v [词 ...] [--all | --path]（v / V 均可）")
    print("  不带词：列出本地词库收录的全部命令 / 选项 / 标签")
    print("  带词：查用法；在线文档标题与版本号，")
    print("        英文/中文")
    print("        例：mt.ph v --dim BAND_LABELS phonopy-init")
    print("  --all    打印整份本地词库")
    print("  --path   打印词库文件路径")
    print("  -h       显示本帮助（要查 phonopy 的 -h 选项，把 -h 放在其它词之后）")
    print()
    print("词库文件：%s" % _data_path())
    print("可用环境变量 %s 指向自定义 JSON；运行时不联网。" % ENV_FILE)
    print("英文原文摘自 phonopy 官方文档：%s" % BASE)


def run(argv):
    """mt.ph v / V 的入口；argv 为 v/V 之后的所有 token，返回退出码。"""
    argv = [item for item in (argv or []) if item != "--"]
    path = _data_path()
    if argv and argv[0] in ("-h", "--help"):
        _help()
        return 0
    if "--refresh" in argv:
        print("提示：词库已保存在本地，--refresh 不再需要；"
              "要更新内容请直接编辑 %s" % path)
        argv = [item for item in argv if item != "--refresh"]
    if "--path" in argv:
        print(path)
        return 0
    if "--all" in argv:
        entries, meta = _load(path)
        if entries is None:
            return 1
        print("phonopy 本地用法词库：%s（%d 条）" % (path, len(entries)))
        print()
        for entry in entries:
            _show(entry, meta)
        return 0
    entries, meta = _load(path)
    if entries is None:
        return 1
    words = [item for item in argv if item not in ("--all", "--path")]
    if not words:
        return _list(entries, meta)
    found = False
    for word in words:
        found = _lookup(word, entries, meta) or found
    return 0 if found else 1
