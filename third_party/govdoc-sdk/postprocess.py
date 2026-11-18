# -*- coding: utf-8 -*-
"""模型输出后处理：用规则补齐模型漏抽的字段（fallback）。

设计原则：
    1. 只填空不覆盖：模型已给出结果的字段不动。
    2. 只认强格式：正则要求整行匹配或固定前后缀，宁缺勿错。
    3. 位置锚定：公文版式固定，用强字段（发文字号/成文日期/抄送/印发）
       划定版头、正文、版记区域，字段只在自己的区域里找。
    4. 噪声过滤：网页噪声行（首页/发布时间/网站地图…）不参与匹配。
    5. 全角归一：匹配时全角数字/括号转半角，返回原文（保留全角）。

用法：
    from postprocess import postprocess
    result = postprocess(model_result, text)
"""
import re

# ---------- 归一 ----------
_FW = str.maketrans("０１２３４５６７８９〔〕（）：．", "0123456789[]():.")


def _n(s):
    """匹配用归一：全角转半角、去首尾空白（含全角空格）。"""
    return s.translate(_FW).strip()


# ---------- 行工具 ----------
def _lines(text):
    """返回 [(行号, 原文, 归一后)]"""
    return [(i, ln, _n(ln)) for i, ln in enumerate(text.split("\n"))]


NOISE_RE = re.compile(
    r"(首页\s*[>＞]|当前位置|发布时间[：:]|来源[：:]|字体[：:]|【打印】|【关闭】"
    r"|网站地图|网站标识码|主办[：:]|访问量|阅读|分享到)"
)


def _is_noise(nline):
    return bool(NOISE_RE.search(nline))


# ---------- 版式锚点 ----------
ORG_TAIL = (r"(人民政府|党委|党组|人大|政协|纪委|监委|法院|检察院"
            r"|(局|厅|委|办|部|署|院|行|社|会|集团|公司|大学|学校|医院|银行"
            r"|督查室|指挥部|领导小组|办公室)([\u4e00-\u9fa5]{0,6})?)")

# 标题行：以"的X"文种结尾
TITLE_RE = re.compile(
    r"^[\u4e00-\u9fa5A-Za-z0-9（）()《》、\s]{6,}的"
    r"(?:若干|有关|实施|暂行|试行|补充)?"
    r"(通知|通报|公告|通告|报告|请示|批复|决定|意见|函|命令|纪要|办法|规划|方案)$"
)
# 发文机关标志行：机关名(+文件/函)，不含"关于"、不含文号括号
MARK_RE = re.compile(r"^[\u4e00-\u9fa5]{2,25}(文件|函)?$")
# 纪要类行：以「纪要」结尾，没有「的」字。版头与标题都长这样，只能按行序区分
MINUTES_TAIL_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9（）()《》、\s]{2,60}纪要$")
# 期号行：第23期 / 2026年第5期
ISSUE_RE = re.compile(r"^(?:\d{4}\s*年\s*)?第?\s*\d{1,3}\s*期$")
# 发文字号行：X〔YYYY〕N号（含全角、半角括号、"第"字）
DOCID_RE = re.compile(r"^[\u4e00-\u9fa5]{0,12}[〔\[]\s*\d{4}\s*[〕\]]\s*第?\s*\d+\s*号$")
# 版头行：文号后可能跟签发人（上行文版式），整行仍是合法版头
DOCID_LINE_RE = re.compile(r"^([\u4e00-\u9fa5]{0,12}[〔\[]\s*\d{4}\s*[〕\]]\s*第?\s*\d+\s*号)(\s*签发人\s*[：:].*)?$")
# 成文日期行（独立一行）：阿拉伯 / 汉字 / 点分
DATE_LINE_RE = re.compile(
    r"^(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|[〇一二三四五六七八九十]{2,5}年[一二三四五六七八九十]{1,4}月[一二三四五六七八九十]{1,5}日"
    r"|\d{4}\.\d{1,2}\.\d{1,2})$"
)
# 印发行：机关 + 日期 + 印发
PRINT_RE = re.compile(r"^(.{2,30}?)\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)\s*印\s*发?$")
# 抄送行
CC_RE = re.compile(r"^抄送[：:]\s*(.+?)\s*$")
# 附注行：（此件…）/（联系人…）
NOTE_RE = re.compile(r"^[（(](此件|联系人|联系方式).{1,80}[）)]$")
# 份号行：独立 6 位数字
COPYNO_RE = re.compile(r"^\d{6}$")
# 密级行：绝密/机密/秘密[★期限]
SEC_RE = re.compile(r"^(绝密|机密|秘密)(?:\s*[★＊*]\s*(\S{1,10}))?$")
# 紧急程度行
URG_RE = re.compile(r"^(特提|特急|加急|平急)(文件)?$")
# 主送机关行：以冒号结尾
MAIN_RE = re.compile(r"^([^：:]{2,60})[：:]$")
# 署名行：机关名结尾
SIG_RE = re.compile(r"^[\u4e00-\u9fa5（）()·]{2,30}" + ORG_TAIL + r"$")


def _minutes_anchors(lines):
    """纪要版式锚点：第一条以「纪要」结尾的行为版头，其后的第一条同类行为标题。

    版头与标题之间只允许夹份号、密级、期号、紧急程度行。夹了别的行（正文），
    说明第二处不是标题，返回标题 None。同字样本中两行文字相同，靠行序区分。
    返回 (版头行号, 标题行号)，找不到时为 None。
    """
    marks = [(i, nl) for i, raw, nl in lines
             if nl and not _is_noise(nl) and MINUTES_TAIL_RE.match(nl)]
    if not marks:
        return None, None
    mi = marks[0][0]
    if len(marks) < 2:
        return mi, None
    ti = marks[1][0]
    for i, raw, nl in lines:
        if i <= mi or i >= ti:
            continue
        if not nl:
            continue
        if not (ISSUE_RE.match(nl) or COPYNO_RE.match(nl) or SEC_RE.match(nl)
                or URG_RE.match(nl)):
            return mi, None
    return mi, ti


def _anchors(lines):
    """找版式锚点行号：标题、成文日期、印发、抄送。"""
    a = {"title": None, "date": None, "print": None, "cc": None, "docid": None}
    for i, raw, nl in lines:
        if _is_noise(nl) or not nl:
            continue
        if a["docid"] is None and DOCID_LINE_RE.match(nl):
            a["docid"] = i
        if a["title"] is None and TITLE_RE.match(nl) and "〔" not in nl and len(nl) >= 10:
            # 标志行短、标题行长；标题必含"的X"结尾
            a["title"] = i
        if a["date"] is None and DATE_LINE_RE.match(nl):
            a["date"] = i
        if a["print"] is None and PRINT_RE.match(nl):
            a["print"] = i
        if a["cc"] is None and CC_RE.match(nl):
            a["cc"] = i
    if a["title"] is None:
        _, ti = _minutes_anchors(lines)
        if ti is not None:
            a["title"] = ti
    return a


def _header_zone(lines, a):
    """版头区域行：标题行之前（无标题锚点时取前 10 个有效行）。"""
    stop = a["title"] if a["title"] is not None else 10**9
    out = []
    for t in lines:
        i, raw, nl = t
        if i >= stop or _is_noise(nl) or not nl:
            continue
        out.append(t)
    if a["title"] is None:
        out = out[:10]
    return out


def _tail_zone(lines, a):
    """正文之后区域行：标题行之后。"""
    start = a["title"] if a["title"] is not None else 0
    return [t for t in lines if t[0] > start and not _is_noise(t[2]) and t[2]]


# ---------- 各字段 fallback ----------

def fill_copyno(result, lines, a):
    """份号：版头区独立一行 6 位数字；粘连行则取行首 6 位数字。"""
    if result.get("份号"):
        return result
    for i, raw, nl in _header_zone(lines, a):
        if COPYNO_RE.match(nl):
            result["份号"] = [{"text": raw.strip(), "prob": 1.0, "source": "regex"}]
            return result
        m = re.match(r"^(\d{6})(?=[^\d])", nl)
        if m:
            # 归一化与原文等长（全角→半角一一对应），按位置取原文
            result["份号"] = [{"text": raw.strip()[m.start(1):m.end(1)],
                               "prob": 1.0, "source": "regex"}]
            return result
    return result


def fill_secret(result, lines, a):
    """密级 + 保密期限：版头区 密级[★期限] 行。"""
    if result.get("密级") and result.get("保密期限"):
        return result
    for i, raw, nl in _header_zone(lines, a):
        m = SEC_RE.match(nl)
        if m:
            if not result.get("密级"):
                result["密级"] = [{"text": m.group(1), "prob": 1.0, "source": "regex"}]
            if not result.get("保密期限") and m.group(2):
                result["保密期限"] = [{"text": m.group(2), "prob": 1.0, "source": "regex"}]
            break
    return result


def fill_urgency(result, lines, a):
    """紧急程度：版头区独立一行；粘连行则取行首（6位数字后）的紧急词。"""
    if result.get("紧急程度"):
        return result
    for i, raw, nl in _header_zone(lines, a):
        if URG_RE.match(nl):
            result["紧急程度"] = [{"text": raw.strip(), "prob": 1.0, "source": "regex"}]
            return result
        m = re.match(r"^(?:\d{6})?(特提|特急|加急|平急)(?:文件)?(?=[^\u4e00-\u9fa5]|[\u4e00-\u9fa5])", nl)
        if m and nl != m.group(0):  # 粘连行：紧急词后面还粘着别的内容
            result["紧急程度"] = [{"text": raw.strip()[m.start(1):m.end(1)],
                                   "prob": 1.0, "source": "regex"}]
            return result
    return result


def fill_mark(result, lines, a):
    """发文机关标志：标题行之前、机关名样式、短行、不含"关于"。"""
    # 纪要：版头就是第一条以「纪要」结尾的行；模型常把后缀截掉，按锚点改正
    mi, ti = _minutes_anchors(lines)
    if mi is not None and ti is not None:
        want = lines[mi][1].strip()
        cur = result.get("发文机关标志")
        if not cur or _flat(cur[0]["text"]) != want:
            result["发文机关标志"] = [{"text": want, "prob": 1.0, "source": "regex"}]
        return result
    if result.get("发文机关标志"):
        return result
    for i, raw, nl in _header_zone(lines, a):
        if (MARK_RE.match(nl) and "关于" not in nl and len(nl) <= 25
                and not DOCID_RE.match(nl) and not COPYNO_RE.match(nl)
                and not SEC_RE.match(nl) and not URG_RE.match(nl)
                and re.match(r"^[\u4e00-\u9fa5]{2,20}" + ORG_TAIL, nl)):
            result["发文机关标志"] = [{"text": raw.strip(), "prob": 1.0, "source": "regex"}]
            break
    return result


def fill_docid(result, lines, a):
    """发文字号：全行 X〔YYYY〕N号 样式；支持断行（本行+下一行）。"""
    if result.get("发文字号"):
        return result
    for k in range(len(lines)):
        i, raw, nl = lines[k]
        if _is_noise(nl):
            continue
        if DOCID_RE.match(nl):
            result["发文字号"] = [{"text": raw.strip(), "prob": 1.0, "source": "regex"}]
            return result
        m_line = DOCID_LINE_RE.match(nl)
        if m_line:  # 文号 + 签发人同行：只取文号
            result["发文字号"] = [{"text": m_line.group(1), "prob": 1.0, "source": "regex"}]
            return result
        if (k + 1 < len(lines) and nl and ("〔" in nl or "[" in nl)
                and DOCID_RE.match(nl + lines[k + 1][2])):
            result["发文字号"] = [{"text": raw.strip() + "\n" + lines[k + 1][1].strip(),
                                   "prob": 1.0, "source": "regex"}]
            return result
        # 粘连行：行内搜索文号片段（限版头区，格式极强不会误伤）
        if a["title"] is None or i < a["title"]:
            m = re.search(r"[\u4e00-\u9fa5]{2,12}[〔\[]\s*\d{4}\s*[〕\]]\s*第?\s*\d+\s*号", nl)
            if m:
                result["发文字号"] = [{"text": raw.strip()[m.start():m.end()],
                                       "prob": 1.0, "source": "regex"}]
                return result
    return result


def fill_title(result, lines, a):
    """标题：版式锚点式——标志行/文号行的下一行即标题；支持断行合并。"""
    mi, ti = _minutes_anchors(lines)
    cur = result.get("标题")
    if cur:
        # 纪要样本在 v3 里没训练过：模型给的标题不以「纪要」结尾，且能定位到纪要标题行 => 重建
        if not (ti is not None and not MINUTES_TAIL_RE.match(_flat(cur[0]["text"]))):
            return result
    # 纪要：标题以「纪要」结尾，没有「的」字，且与版头同字时文字完全相同，只能按行序取第二处
    mi, ti = _minutes_anchors(lines)
    if ti is not None:
        result["标题"] = [{"text": lines[ti][1].strip(), "prob": 1.0, "source": "regex"}]
        a["title"] = ti
        return result
    # 候选起点：文号行下一行 > 标志行下一行
    cands = []
    for k in range(len(lines)):
        i, raw, nl = lines[k]
        if _is_noise(nl) or not nl:
            continue
        if DOCID_RE.match(nl) and k + 1 < len(lines):
            cands.append(k + 1)
        elif (MARK_RE.match(nl) and "关于" not in nl and len(nl) >= 4
              and not COPYNO_RE.match(nl) and not SEC_RE.match(nl)
              and not URG_RE.match(nl) and k + 1 < len(lines)
              and re.match(r"^[\u4e00-\u9fa5]{2,20}" + ORG_TAIL, nl)):
            cands.append(k + 1)
    for k in cands:
        i, raw, nl = lines[k]
        if not nl:
            continue
        cand, end = nl, k
        if not TITLE_RE.match(cand) and k + 1 < len(lines):
            nxt = lines[k + 1][2]
            if nxt and TITLE_RE.match(nl + nxt):
                cand, end = nl + nxt, k + 1
        if TITLE_RE.match(cand) and len(cand) >= 10:
            text = "\n".join(lines[j][1] for j in range(k, end + 1))
            result["标题"] = [{"text": text, "prob": 1.0, "source": "regex"}]
            a["title"] = i  # 修正锚点
            return result
    # 兜底：全文扫描以"的X"结尾的长行
    for i, raw, nl in lines:
        if _is_noise(nl) or not nl or "〔" in nl or DOCID_RE.match(nl):
            continue
        if TITLE_RE.match(nl) and len(nl) >= 10:
            result["标题"] = [{"text": raw.strip(), "prob": 1.0, "source": "regex"}]
            a["title"] = i
            return result
    return result


def fill_main(result, lines, a):
    """主送机关：标题后第一个以冒号结尾的行（排除"…如下："）。"""
    if result.get("主送机关"):
        return result
    for i, raw, nl in _tail_zone(lines, a):
        m = MAIN_RE.match(nl)
        if m and not re.search(r"(如下|通知如下|报告如下|请示如下|公告|事项)$", m.group(1)):
            # 返回原文（去冒号），不返回归一化文本
            result["主送机关"] = [{"text": re.sub(r"[：:]\s*$", "", raw.strip()),
                                   "prob": 1.0, "source": "regex"}]
            return result
        # 主送在正文之前：遇到不以冒号结尾的长行说明已进入正文
        if len(nl) > 30:
            return result
    return result


def fill_date(result, lines, a):
    """成文日期：独立一行的日期（阿拉伯/汉字/点分），取最后一个非印发行日期；支持断行。"""
    if result.get("成文日期"):
        return result
    cand = None
    for k in range(len(lines)):
        i, raw, nl = lines[k]
        if _is_noise(nl) or PRINT_RE.match(nl):
            continue
        if DATE_LINE_RE.match(nl):
            cand = raw.strip()
        elif (k + 1 < len(lines) and nl and DATE_LINE_RE.match(nl + lines[k + 1][2])
              and len(nl) <= 12):
            cand = raw.strip() + "\n" + lines[k + 1][1].strip()
    if cand:
        result["成文日期"] = [{"text": cand, "prob": 1.0, "source": "regex"}]
    return result


def fill_sig(result, lines, a):
    """署名：成文日期行之前最近的机关名样式行；支持断行（短片段行+前行合并）。"""
    if result.get("发文机关署名"):
        return result
    date_idx = None
    for k in range(len(lines)):
        i, raw, nl = lines[k]
        if _is_noise(nl) or PRINT_RE.match(nl):
            continue
        if DATE_LINE_RE.match(nl):
            date_idx = i
        elif (k + 1 < len(lines) and nl and DATE_LINE_RE.match(nl + lines[k + 1][2])
              and len(nl) <= 12):
            date_idx = i
    if date_idx is None:
        # 无成文日期：用附注/抄送/印发行作边界，往前找机关样式行
        for i, raw, nl in lines:
            if _is_noise(nl) or not nl:
                continue
            if NOTE_RE.match(nl) or CC_RE.match(nl) or PRINT_RE.match(nl):
                date_idx = i
                break
    if date_idx is None:
        return result
    for k in range(len(lines) - 1, -1, -1):
        i, raw, nl = lines[k]
        if i >= date_idx or _is_noise(nl) or not nl:
            continue
        if SIG_RE.match(nl) and "关于" not in nl and len(nl) <= 30:
            # 断行署名：本行是短片段（如"运输局"），前行也是机关名片段 → 合并
            if (len(nl) <= 5 and k > 0
                    and re.fullmatch(r"[\u4e00-\u9fa5]{2,15}", _n(lines[k - 1][1]))):
                result["发文机关署名"] = [{"text": lines[k - 1][1].strip() + "\n" + raw.strip(),
                                           "prob": 1.0, "source": "regex"}]
            else:
                result["发文机关署名"] = [{"text": raw.strip(), "prob": 1.0, "source": "regex"}]
            return result
        # 断行署名：紧邻日期的是短片段行，其前一行才是完整机关样式 → 合并
        if (nl and len(nl) <= 8 and k > 0
                and SIG_RE.match(_n(lines[k - 1][1]))
                and "关于" not in _n(lines[k - 1][1])):
            result["发文机关署名"] = [{"text": lines[k - 1][1].strip() + "\n" + raw.strip(),
                                       "prob": 1.0, "source": "regex"}]
            return result
        break  # 紧邻日期前一行不是机关样式：不越界继续找，避免误抓正文
    return result


SIGNER_RE = re.compile(r"签发人[：:]\s*([\u4e00-\u9fff·]{2,16})\s*$")


def fill_signer(result, lines, a):
    """签发人：版头区「签发人：姓名」样式（上行文标志，与文号同行居右）。
    模型值被截断时（正则值以它开头且更长）用正则值替换。"""
    cur = result.get("签发人") or []
    for i, raw, nl in _header_zone(lines, a):
        m = SIGNER_RE.search(nl)
        if not m:
            continue
        val = m.group(1)
        if not cur:
            result["签发人"] = [{"text": val, "prob": 1.0, "source": "regex"}]
        else:
            old_val = _flat(cur[0]["text"])
            if val.startswith(old_val) and len(val) > len(old_val):
                result["签发人"] = [{"text": val,
                                     "prob": cur[0].get("probability", 1.0),
                                     "source": "regex"}]
        return result
    return result


def fill_note(result, lines, a):
    """附注：独立一行（此件…）/（联系人…）。"""
    if result.get("附注"):
        return result
    for i, raw, nl in _tail_zone(lines, a):
        if NOTE_RE.match(nl):
            result["附注"] = [{"text": raw.strip(), "prob": 1.0, "source": "regex"}]
            break
    return result


def fill_cc(result, lines, a):
    """抄送：抄送：开头的行。"""
    if result.get("抄送机关"):
        return result
    for i, raw, nl in lines:
        if _is_noise(nl):
            continue
        m = CC_RE.match(nl)
        if m:
            result["抄送机关"] = [{"text": m.group(1), "prob": 1.0, "source": "regex"}]
            break
    return result


def fill_print(result, lines, a):
    """印发机关 + 印发日期：X 日期印发 行。"""
    if result.get("印发机关") and result.get("印发日期"):
        return result
    for i, raw, nl in lines:
        if _is_noise(nl):
            continue
        m = PRINT_RE.match(nl)
        if m:
            if not result.get("印发机关"):
                result["印发机关"] = [{"text": m.group(1).strip(), "prob": 1.0, "source": "regex"}]
            if not result.get("印发日期"):
                result["印发日期"] = [{"text": m.group(2).replace(" ", ""), "prob": 1.0, "source": "regex"}]
            break
    return result


# ---------- 附件说明（逐行收块） ----------
ATT_HEAD_RE = re.compile(r"^附件\s*\d*\s*[：:]")
ATT_ITEM_RE = re.compile(r"^\d+\s*[.、]\s*")
ATT_STOP_RE = re.compile(r"^(?:\d{4}年\d{1,2}月\d{1,2}日|[（(]此件|抄送[：:]|印发)")


def fill_attachment_caption(result, text):
    """附件说明 fallback：逐行收集附件块。
    模型已抽出时做并集：只补模型漏掉的条目，不覆盖已有条目。"""
    have = {_n(x["text"]).replace("\n", "") for x in result.get("附件说明", [])}

    lines = text.split("\n")
    sig_texts = [_flat(x["text"]) for x in result.get("发文机关署名", []) if _flat(x["text"])]
    # 附件区终点：成文日期行、署名行之前
    end_idx = len(lines)
    for k, ln in enumerate(lines):
        nl = _n(ln)
        if DATE_LINE_RE.match(nl) and not PRINT_RE.match(nl):
            end_idx = min(end_idx, k)
    # 署名终点：最后一个日期行往前第一个机关样式行
    for k in range(end_idx - 1, -1, -1):
        nl = _n(lines[k])
        if SIG_RE.match(nl) and "关于" not in nl:
            # 粘连行（行尾=署名值、行首有前缀）不是纯署名行，跳过
            if any(nl.endswith(st) and len(nl) > len(st) for st in sig_texts):
                continue
            prev = _n(lines[k - 1]) if k > 0 else ""
            if ATT_HEAD_RE.match(prev) or ATT_ITEM_RE.match(prev) or (prev and not SIG_RE.match(prev)):
                end_idx = min(end_idx, k)
            break

    items = []
    i = 0
    while i < len(lines):
        m = ATT_HEAD_RE.match(_n(lines[i]))
        if not m:
            i += 1
            continue
        block = []
        j = i
        while j < len(lines):
            cur = lines[j].strip()
            nl = _n(cur)
            if j >= end_idx or ATT_STOP_RE.match(nl):
                break
            # 粘连行：行尾=模型署名值、行首有前缀 → 前缀并入附件条目后停止
            split_done = False
            for st in sig_texts:
                if nl.endswith(st) and len(nl) > len(st):
                    prefix = cur[: len(cur) - len(st)].strip()
                    if prefix:
                        block.append(prefix)
                    split_done = True
                    break
            if split_done:
                break
            # 遇到署名行（含断行署名的起始片段）即停
            # 断行片段要求：短、以机关名前缀成分结尾（如"松江市人民"），
            # 与下一行拼起来是完整署名；附件续行（如"及分工表"）不满足
            if ("关于" not in nl and len(nl) <= 30
                    and (SIG_RE.match(nl)
                         or (j + 1 < len(lines) and len(nl) <= 8
                             and re.search(r"(人民|政府|党委|党组|人大|政协|纪委|监委|法院|检察院|局|厅|委|办|部|署|院|行|社|会|集团|公司|大学|学校|医院|银行|督查|指挥|领导|办公|省|市|县|区|乡|镇)$", nl)
                             and SIG_RE.match(nl + _n(lines[j + 1]))))):
                break
            if not cur:
                # 空行：下一非空行仍是附件编号条目 → 跳过空行继续收
                nk = j + 1
                while nk < len(lines) and not lines[nk].strip():
                    nk += 1
                if nk < len(lines) and ATT_ITEM_RE.match(_n(lines[nk])):
                    j = nk
                    continue
                break
            block.append(cur)
            j += 1
        if not block:
            # 内层循环可能原地 break（如 i 已越过 end_idx），必须强制前进，否则死循环
            i = j if j > i else i + 1
            continue
        first = re.sub(r"^附件\s*\d*\s*[：:]", "", _n(block[0])).strip()
        raw_first = re.sub(r"^附件\s*\d*\s*[：:]", "", block[0]).strip()
        if raw_first:
            block[0] = raw_first
        else:
            block.pop(0)
        entries = []
        for ln in block:
            nln = _n(ln)
            is_item = ATT_ITEM_RE.match(nln) or ATT_HEAD_RE.match(nln)
            if is_item or not entries:
                if is_item:
                    entries.append(re.sub(r"^(附件\s*\d*\s*[：:]|\d+\s*[.、]\s*)", "", ln, count=1).strip())
                else:
                    entries.append(ln)
            else:
                entries[-1] += ln
        for e in entries:
            e = e.strip()
            if not e or e in ("附件", "附件：", "附件:"):
                continue
            if _n(e).replace("\n", "") in have:
                continue
            items.append({"text": e, "prob": 1.0, "source": "regex"})
        i = j

    if items:
        result.setdefault("附件说明", []).extend(items)
    return result


# ---------- 格式校验：模型输出明显违反格式时，视为未抽出，交给正则 ----------
VALIDATORS = {
    "份号": lambda s: re.fullmatch(r"\d{6}", s),
    "密级": lambda s: re.fullmatch(r"绝密|机密|秘密", s),
    "保密期限": lambda s: re.fullmatch(r"长期|\d{1,3}年|\d{1,3}个月", s),
    "紧急程度": lambda s: re.fullmatch(r"(?:特提|特急|加急|平急)(?:文件)?", s),
    # 前缀机关简称一般 ≤6 字；超长前缀多为误并了标志行
    "发文字号": lambda s: re.fullmatch(r"[\u4e00-\u9fa5]{0,6}[〔\[]\s*\d{4}\s*[〕\]]\s*第?\s*\d+\s*号", s),
    "成文日期": lambda s: DATE_LINE_RE.match(s),
    "印发日期": lambda s: re.fullmatch(r"\d{4}年\d{1,2}月\d{1,2}日", s),
    "附注": lambda s: NOTE_RE.match(s),
}


def _flat(s):
    return _n(s).replace("\n", "")


# ---------- 半截值修补：模型给了值但被截断/切断，按原文改正 ----------
ATT_FIELDS = ("出席", "列席", "请假")
ATT_LABELS = {"出席": "出席", "出席人员": "出席", "参会人员": "出席",
              "列席": "列席", "请假": "请假"}


def _line_of(text, pos):
    """返回 pos 所在行的 (行起始下标, 整行原文)。"""
    ls = text.rfind("\n", 0, pos) + 1
    le = text.find("\n", pos)
    return ls, text[ls:len(text) if le < 0 else le]


def repair_date(result, text):
    """成文日期：模型把「二〇二五年」截成「二五年」，按所在原文行改正。"""
    for x in result.get("成文日期", []):
        st, en = x.get("start"), x.get("end")
        if st is None or en is None:
            continue
        val = _n(x.get("text", ""))
        _, line = _line_of(text, st)
        nl = _n(line)
        if not val or not nl or nl == val or not nl.endswith(val):
            continue
        if not DATE_LINE_RE.match(nl):
            continue
        body = line.strip()
        x["text"] = body
        x["start"] = st - (len(nl) - len(val))
        x["end"] = x["start"] + len(body)
    return result


def repair_cc(result, text):
    """抄送机关：合并被切断的相邻片段，并补回行尾句号。"""
    items = result.get("抄送机关")
    if not items:
        return result
    merged = []
    for x in items:
        prev_end = merged[-1].get("end") if merged else None
        if prev_end is not None and x.get("start") is not None and prev_end == x["start"]:
            merged[-1]["text"] += x.get("text", "")
            merged[-1]["end"] = x.get("end")
        else:
            merged.append(dict(x))
    for x in merged:
        en = x.get("end")
        if en is None or not x.get("text"):
            continue
        if not _n(x["text"]).endswith("。") and text[en:en + 1] == "。":
            x["text"] += "。"
            x["end"] = en + 1
    result["抄送机关"] = merged
    return result


def repair_print(result, lines):
    """印发机关：模型截掉前半段（如「人民政府办公室」），按印发行改正。"""
    cur = result.get("印发机关") or []
    if not cur:
        return result
    for _, _, nl in lines:
        m = PRINT_RE.match(nl)
        if not m:
            continue
        org = m.group(1).strip()
        old = _n(cur[0].get("text", ""))
        if org and old and org != old and org.endswith(old):
            cur[0]["text"] = org
            cur[0].pop("start", None)
            cur[0].pop("end", None)
            cur[0]["source"] = "regex"
        break
    return result


def _label_at(text, pos):
    """pos 所在行的出席类标签（出席/列席/请假），无标签返回 None。"""
    _, line = _line_of(text, pos)
    s = line.strip()
    for lab in ("出席人员：", "参会人员：", "出席：", "列席：", "请假："):
        if s.startswith(lab):
            return ATT_LABELS[lab.rstrip("：")]
    return None


def repair_attend(result, text):
    """出席/列席/请假：拼回跨字段的断字碎片，并按行标签纠正字段归属。"""
    if not any(result.get(f) for f in ATT_FIELDS):
        return result
    for a in ("列席", "请假"):
        for x in list(result.get(a) or []):
            for b in ATT_FIELDS:
                if b == a:
                    continue
                for y in list(result.get(b) or []):
                    if (x.get("end") is not None and x["end"] == y.get("start")
                            and len(_n(y.get("text", ""))) <= 8):
                        x["text"] += y.get("text", "")
                        x["end"] = y.get("end")
                        result[b].remove(y)
    for f in ATT_FIELDS:
        for x in list(result.get(f) or []):
            st = x.get("start")
            if st is None:
                continue
            lab = _label_at(text, st)
            if lab and lab != f:
                result[f].remove(x)
                result.setdefault(lab, []).append(x)
    for f in ATT_FIELDS:
        if result.get(f):
            result[f].sort(key=lambda z: z.get("start") if z.get("start") is not None else 0)
    return result


def validate(result, text):
    """模型输出全部违反格式 => 删掉该字段（正则随后补正确值）。"""
    for f, ok in VALIDATORS.items():
        items = result.get(f)
        if not items:
            continue
        kept = [x for x in items if ok(_flat(x["text"]))]
        if not kept:
            del result[f]
        elif len(kept) != len(items):
            result[f] = kept
    # 发文机关标志：值出现在网页噪声行里 => 误抽，删掉
    noise_lines = [_n(ln) for ln in text.split("\n") if _is_noise(_n(ln))]
    for x in list(result.get("发文机关标志", [])):
        t = _flat(x["text"])
        if any(t and t in nl for nl in noise_lines):
            del result["发文机关标志"]
            break
    # 发文机关署名：落在版记印发行里 => 删掉。
    # 断行 PDF 里「印发」二字可能拆到下一行，所以看 span 之后 60 字符（去换行）。
    sigs = result.get("发文机关署名")
    if sigs:
        kept = []
        for x in sigs:
            st = x.get("start")
            if st is None:
                kept.append(x)
                continue
            window = text[st:st + 60].replace("\n", "")
            if "印发" in window:
                continue
            kept.append(x)
        if kept:
            result["发文机关署名"] = kept
        else:
            del result["发文机关署名"]
    # 印发日期：与成文日期同一 span（同文同位）=> 那是落款日期，不是版记印发日期，删掉
    yprq = result.get("印发日期")
    cw = result.get("成文日期")
    if yprq and cw:
        kept = [x for x in yprq
                if not any(x.get("start") == y.get("start") and x.get("end") == y.get("end")
                           for y in cw)]
        if kept:
            result["印发日期"] = kept
        else:
            del result["印发日期"]
    # 成文日期：多 span 时只留最靠后的——落款日期是全文最后一个日期，正文日期在前
    cwrq = result.get("成文日期")
    if cwrq and len(cwrq) > 1:
        result["成文日期"] = [max(cwrq, key=lambda x: x.get("start", 0))]
    # 发文字号：正文里引用的他文号是误抽，只保留标题之前的
    if len(result.get("发文字号", [])) > 1 and result.get("标题"):
        tstart = result["标题"][0].get("start")
        if tstart is not None:
            kept = [x for x in result["发文字号"] if x.get("start", 0) < tstart]
            if kept:
                result["发文字号"] = kept
    # 标题与标志同字、但全文只出现一处 => 模型把版头当标题，删掉
    tt, mks = result.get("标题"), result.get("发文机关标志")
    if tt and mks:
        t0, m0 = _flat(tt[0]["text"]), _flat(mks[0]["text"])
        if t0 and t0 == m0 and text.count(t0) < 2:
            del result["标题"]
        # 发文机关标志必须在标题之前；晚于标题的是署名或正文里的机关名误抽
        ts_, ms_ = tt[0].get("start"), mks[0].get("start")
        if ts_ is not None and ms_ is not None and ms_ > ts_:
            del result["发文机关标志"]
    return result


# ---------- 统一入口 ----------

def postprocess(result, text):
    """统一入口：先校验剔除畸形模型值，再按版式补齐所有 fallback 字段。"""
    result = validate(result, text)
    lines = _lines(text)
    a = _anchors(lines)
    # 模型已抽出标题但锚点没找到（断行）：用模型标题定位锚点
    if a["title"] is None and result.get("标题"):
        head = _n(result["标题"][0]["text"].split("\n")[0])
        mark = _n((result.get("发文机关标志") or [{}])[0].get("text", ""))
        hits = [i for i, raw, nl in lines if nl and nl == head]
        if hits:
            # 标题与标志同字时取最后一处，否则第一处就是标题
            a["title"] = hits[-1] if (mark and head == mark and len(hits) > 1) else hits[0]
    result = fill_title(result, lines, a)      # 标题先补：其他区域以它为界
    result = fill_copyno(result, lines, a)
    result = fill_secret(result, lines, a)
    result = fill_urgency(result, lines, a)
    result = fill_mark(result, lines, a)
    result = fill_docid(result, lines, a)
    result = fill_main(result, lines, a)
    result = fill_attachment_caption(result, text)
    result = fill_date(result, lines, a)
    # 纪要：落款日期是印发行之前最后一条独立日期行，模型常抓正文里的日期
    mi2, ti2 = _minutes_anchors(lines)
    if mi2 is not None:
        print_idx = next((i for i, raw, nl in lines if PRINT_RE.match(nl)), None)
        last = None
        for i, raw, nl in lines:
            if _is_noise(nl) or not nl:
                continue
            if print_idx is not None and i >= print_idx:
                continue
            if DATE_LINE_RE.match(nl):
                last = raw.strip()
        cur = result.get("成文日期")
        if last and (not cur or _flat(cur[0]["text"]) != last):
            result["成文日期"] = [{"text": last, "prob": 1.0, "source": "regex"}]
    result = fill_sig(result, lines, a)
    result = fill_note(result, lines, a)
    result = fill_signer(result, lines, a)
    result = fill_cc(result, lines, a)
    result = fill_print(result, lines, a)
    # 半截值修补：模型给了值但被截断/切断，用原文改正（fill_* 只补空字段，管不到这里）
    result = repair_date(result, text)
    result = repair_cc(result, text)
    result = repair_print(result, lines)
    result = repair_attend(result, text)
    # 附件说明：一行里用顿号列多个附件 => 拆成多条（每段 >= 6 字才拆，避免误拆机关名）
    atts = result.get("附件说明")
    if atts:
        split_out = []
        changed = False
        for x in atts:
            t = _flat(x["text"])
            if "、" in t and not t.startswith("附件"):
                parts = [p.strip() for p in t.split("、") if p.strip()]
                if 2 <= len(parts) <= 4 and all(len(p) >= 6 for p in parts):
                    split_out.extend({"text": p, "prob": 1.0, "source": "split"} for p in parts)
                    changed = True
                    continue
            split_out.append(x)
        if changed:
            seen, uniq = set(), []
            for x in split_out:
                t = _flat(x["text"])
                if t in seen:
                    continue
                seen.add(t)
                uniq.append(x)
            result["附件说明"] = uniq
    # 多值字段：断行碎片/半截值是完整值的子串 => 只留完整值
    for f in ("附件说明", "抄送机关"):
        items = result.get(f)
        if items and len(items) > 1:
            kept = []
            for x in items:
                tx = _flat(x["text"])
                if tx and any(tx != _flat(y["text"]) and tx in _flat(y["text"])
                              for y in items if y is not x):
                    continue
                kept.append(x)
            if kept:
                result[f] = kept
    # 「XX文件」粘连：版头与紧急程度后面紧跟「文件」，而值本身没带 => 补回
    for f in ("发文机关标志", "紧急程度"):
        for x in result.get(f, []):
            st, en, tx = x.get("start"), x.get("end"), x.get("text", "")
            if st is None or en is None or not tx:
                continue
            if not tx.endswith("文件") and text[en:en + 2] == "文件":
                x["text"] = tx + "文件"
                x["end"] = en + 2
    return result


if __name__ == "__main__":
    import json
    import sys

    text = open(sys.argv[1], encoding="utf-8").read().strip()
    result = json.load(open(sys.argv[2], encoding="utf-8"))
    if isinstance(result, list):
        result = result[0]
    out = postprocess(result, text)
    print(json.dumps([out], ensure_ascii=False, indent=2))
