# -*- coding: utf-8 -*-
"""txt100 v2：原文+金标；评文种路由、字段准确率、正文切分。"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SDK = ROOT / "third_party" / "govdoc-sdk"
TXT100 = Path(r"E:\red head\Red Head Helper\examples\txt100")
OUT = ROOT / "examples" / "out" / "txt100_eval_v2.json"
ROWS = ROOT / "examples" / "out" / "txt100_eval_v2_rows.json"

SEP = "====================【字段标注（正确答案）】===================="

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SDK))

from core.recognize.onnx_recognizer import OnnxFieldRecognizer  # noqa: E402
import doc_kind  # noqa: E402

FOLDER_TO_KIND = {
    "通用": doc_kind.KIND_GENERAL,
    "纪要": doc_kind.KIND_MINUTES,
    "命令": doc_kind.KIND_ORDER,
    "信函": doc_kind.KIND_LETTER,
}

# 金标键 -> SDK 字段名（特殊键单独处理）
GOLD_KEY_MAP = {
    "发文机关标志": "发文机关标志",
    "发文机关标志（纪要标志）": "发文机关标志",
    "发文字号": "发文字号",
    "标题": "标题",
    "主送机关": "主送机关",
    "发文机关署名": "发文机关署名",
    "成文日期": "成文日期",
    "附注": "附注",
    "抄送机关": "抄送机关",
    "份号": "份号",
    "紧急程度": "紧急程度",
    "附件说明": "附件说明",
    "期号": "期号",
    "出席人员": "出席",
    "列席人员": "列席",
    "请假人员": "请假",
    "令号": "令号",
}


def flat(s: str) -> str:
    t = (s or "").replace("\u3000", "").replace("\n", "").replace("\r", "").replace(" ", "")
    t = t.replace("：", ":").replace("〔", "[").replace("〕", "]")
    t = t.replace("（", "(").replace("）", ")")
    return t.strip()


def parse_file(path: Path) -> tuple[str, dict[str, str]]:
    raw = path.read_text(encoding="utf-8-sig")
    if SEP not in raw:
        return raw.strip(), {}
    body, gold_raw = raw.split(SEP, 1)
    gold: dict[str, str] = {}
    lines = gold_raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if "：" not in ln:
            i += 1
            continue
        key, val = ln.split("：", 1)
        key = key.strip()
        if not key or len(key) > 24:
            i += 1
            continue
        # 跳过正文结构行误解析
        if key.startswith(("一", "二", "三", "四", "五", "（", "(")):
            i += 1
            continue
        if key == "正文":
            parts = [val] if val.strip() else []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                # 下一字段行：短键 + 冒号，且不是缩进正文
                if (
                    "：" in nxt
                    and not nxt.startswith(("　", " ", "\t"))
                    and len(nxt.split("：", 1)[0].strip()) <= 24
                    and not nxt.split("：", 1)[0].strip().startswith(("一", "二", "三", "（", "("))
                ):
                    k2 = nxt.split("：", 1)[0].strip()
                    if k2 in GOLD_KEY_MAP or k2 in (
                        "印发机关和印发日期",
                        "密级与保密期限",
                        "签发人",
                        "正文",
                    ):
                        break
                parts.append(nxt)
                i += 1
            gold["正文"] = "\n".join(parts).strip()
            continue
        gold[key] = val.strip()
        i += 1
    return body.strip(), gold


def split_secret(s: str) -> tuple[str, str]:
    s = (s or "").strip()
    if "★" in s:
        a, b = s.split("★", 1)
        return a.strip(), b.strip()
    if s in ("绝密", "机密", "秘密"):
        return s, ""
    return s, ""


def split_print(s: str) -> tuple[str, str]:
    """印发机关和印发日期：机关 + 日期 + 印发"""
    s = (s or "").strip()
    m = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", s)
    if not m:
        return s.replace("印发", "").strip(), ""
    date = re.sub(r"\s+", "", m.group(1))
    org = s[: m.start()].strip()
    return org, date


def split_order_signer(s: str) -> tuple[str, str]:
    """市长　魏卫星 / 市长 魏卫星"""
    s = (s or "").strip()
    parts = re.split(r"[\u3000\s]+", s, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return s, ""


def pred_fields(model, sdk_result: dict, kind: str) -> dict[str, str]:
    """从 ModelOutput + sdk_result 取可比较的扁平字段。"""
    out: dict[str, str] = {}
    h, m, f = model.header, model.main, model.footer
    out["发文机关标志"] = (h.org_mark or "").replace("\n", "")
    out["发文字号"] = h.doc_number or ""
    out["标题"] = m.title or ""
    out["主送机关"] = (m.recipient or "").rstrip("：:")
    out["发文机关署名"] = (f.org_signature or "").replace("\n", "")
    out["成文日期"] = f.date or ""
    out["附注"] = f.note or ""
    out["抄送机关"] = getattr(model, "_sdk_cc", "") or ""
    out["份号"] = h.copy_number or ""
    out["紧急程度"] = h.urgency or ""
    out["密级"] = h.secret_level or ""
    out["保密期限"] = h.secret_period or ""
    out["附件说明"] = (m.attachment_caption or "").replace("\n", "")
    out["印发机关"] = f.print_org or ""
    out["印发日期"] = f.print_date or ""
    out["期号"] = getattr(model, "_minutes_issue_no", "") or ""
    out["出席"] = getattr(model, "_minutes_attendance", "") or ""
    out["列席"] = getattr(model, "_minutes_liexi", "") or ""
    out["请假"] = getattr(model, "_minutes_leave", "") or ""
    out["令号"] = getattr(model, "_order_no", "") or ""
    # 签署：职务列表 + 姓名字段
    titles = getattr(model, "_order_signers", None) or []
    out["签署职务"] = "、".join(titles) if isinstance(titles, list) else str(titles or "")
    name_items = sdk_result.get("签署姓名") or []
    out["签署姓名"] = flat("".join(x.get("text", "") for x in name_items))
    out["正文"] = "\n".join(m.body_blocks or [])
    # 签发人（命令金标）合成
    if out["签署职务"] or out["签署姓名"]:
        out["签发人"] = (out["签署职务"] + "　" + out["签署姓名"]).strip("　")
    return out


def values_equal(field: str, gold_v: str, pred_v: str) -> bool:
    g, p = flat(gold_v), flat(pred_v)
    # Office「文　件」→「文件」
    g = re.sub(r"文[\s\u3000]*件", "文件", g)
    p = re.sub(r"文[\s\u3000]*件", "文件", p)
    if field in ("主送机关",):
        g, p = g.rstrip(":"), p.rstrip(":")
    if field in ("抄送机关",):
        g = re.sub(r"^抄送:", "", g).rstrip("。.")
        p = re.sub(r"^抄送:", "", p).rstrip("。.")
    if field in ("发文机关标志", "发文机关署名"):
        # 金标常用顿号；SDK 联合行文用换行（flat 后无分隔）。去「文件」后再比。
        g2 = g.replace("文件", "").replace("、", "").replace("，", "").replace(",", "")
        p2 = p.replace("文件", "").replace("、", "").replace("，", "").replace(",", "")
        if g2 == p2 and bool(g2):
            return True
        def org_parts(x: str) -> list[str]:
            t = x.replace("文件", "") if field == "发文机关标志" else x
            return [p0 for p0 in re.split(r"[、，,；;]", t) if p0]

        if org_parts(g) == org_parts(p) and bool(org_parts(g)):
            return True
    if field == "发文机关标志":
        # 信函无「文件」；通用可有可无
        g2, p2 = g.replace("文件", ""), p.replace("文件", "")
        if g2 == p2:
            return True
    if g == p:
        return True
    # 出席等：顿号/逗号归一后再比
    if field in ("出席", "列席", "请假", "出席人员", "列席人员"):
        def parts(x):
            return sorted(re.split(r"[、，,；;]", x) if x else [])
        return parts(g) == parts(p) and bool(g)
    # 包含关系且长度接近（半截值）
    if g and p and (g in p or p in g):
        longer, shorter = (g, p) if len(g) >= len(p) else (p, g)
        if len(shorter) >= max(4, int(len(longer) * 0.85)):
            return True
    return False


def body_scores(gold: str, pred: str) -> dict:
    g, p = flat(gold), flat(pred)
    if not g and not p:
        return {"exact": 1.0, "ratio": 1.0, "f1": 1.0, "empty_gold": True}
    if not g:
        return {"exact": 0.0, "ratio": 0.0, "f1": 0.0, "empty_gold": True}
    exact = 1.0 if g == p else 0.0
    ratio = SequenceMatcher(None, g, p).ratio() if (g or p) else 1.0
    cg, cp = Counter(g), Counter(p)
    overlap = sum((cg & cp).values())
    prec = overlap / sum(cp.values()) if cp else 0.0
    rec = overlap / sum(cg.values()) if cg else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return {
        "exact": exact,
        "ratio": round(ratio, 4),
        "f1": round(f1, 4),
        "empty_gold": False,
        "pred_empty": not bool(p),
        "gold_in_pred": g in p if p else False,
        "pred_in_gold": p in g if p else False,
    }


def gold_to_compare_items(gold: dict) -> list[tuple[str, str, str]]:
    """返回 [(sdk_field_or_label, gold_value, compare_key)]"""
    items = []
    for k, v in gold.items():
        if k == "正文" or not str(v).strip():
            continue
        if k == "密级与保密期限":
            sec, per = split_secret(v)
            if sec:
                items.append(("密级", sec, "密级"))
            if per:
                items.append(("保密期限", per, "保密期限"))
            continue
        if k == "印发机关和印发日期":
            org, date = split_print(v)
            if org:
                items.append(("印发机关", org, "印发机关"))
            if date:
                items.append(("印发日期", date, "印发日期"))
            continue
        if k == "签发人":
            job, name = split_order_signer(v)
            if job:
                items.append(("签署职务", job, "签署职务"))
            if name:
                items.append(("签署姓名", name, "签署姓名"))
            continue
        sdk = GOLD_KEY_MAP.get(k)
        if sdk:
            items.append((sdk, v, sdk))
    return items


def main() -> int:
    rec = OnnxFieldRecognizer(
        SDK / "model.onnx",
        SDK / "vocab.txt",
        sdk_root=SDK,
    )
    t0 = time.perf_counter()
    by_kind: dict = {}
    rows: list = []
    kind_conf = Counter()
    n_err = 0

    for folder in ("通用", "纪要", "命令", "信函"):
        expect = FOLDER_TO_KIND[folder]
        files = sorted((TXT100 / folder).glob("*.txt"))
        st = {
            "n": 0,
            "kind_ok": 0,
            "field_ok": 0,
            "field_n": 0,
            "field_by": defaultdict(lambda: [0, 0]),  # ok, n
            "body_exact": 0,
            "body_n": 0,
            "body_f1_sum": 0.0,
            "body_ratio_sum": 0.0,
            "body_pred_empty": 0,
            "samples_field_miss": [],
            "samples_body_bad": [],
        }
        for fp in files:
            st["n"] += 1
            try:
                text, gold = parse_file(fp)
                model = rec.recognize(text)
                detected = rec._last_doc_kind or ""
                sdk = rec._last_sdk_result or {}
                preds = pred_fields(model, sdk, detected)
            except Exception:
                n_err += 1
                rows.append({"folder": folder, "file": fp.name, "error": traceback.format_exc(limit=1)})
                continue

            kind_ok = detected == expect
            if kind_ok:
                st["kind_ok"] += 1
            else:
                kind_conf[(expect, detected)] += 1

            miss = []
            for sdk_f, gv, ck in gold_to_compare_items(gold):
                pv = preds.get(sdk_f, "")
                st["field_n"] += 1
                st["field_by"][ck][1] += 1
                ok = values_equal(ck, gv, pv)
                if ok:
                    st["field_ok"] += 1
                    st["field_by"][ck][0] += 1
                else:
                    miss.append({"field": ck, "gold": gv[:80], "pred": (pv or "")[:80]})

            if miss and len(st["samples_field_miss"]) < 6:
                st["samples_field_miss"].append({"file": fp.name, "detected": detected, "miss": miss[:6]})

            gb = gold.get("正文", "")
            if gb.strip():
                bs = body_scores(gb, preds.get("正文", ""))
                st["body_n"] += 1
                st["body_exact"] += int(bs["exact"])
                st["body_f1_sum"] += bs["f1"]
                st["body_ratio_sum"] += bs["ratio"]
                if bs.get("pred_empty"):
                    st["body_pred_empty"] += 1
                if bs["f1"] < 0.85 and len(st["samples_body_bad"]) < 6:
                    st["samples_body_bad"].append({
                        "file": fp.name,
                        "f1": bs["f1"],
                        "ratio": bs["ratio"],
                        "gold_head": flat(gb)[:60],
                        "pred_head": flat(preds.get("正文", ""))[:60],
                    })

            rows.append({
                "folder": folder,
                "file": fp.name,
                "expect": expect,
                "detected": detected,
                "kind_ok": kind_ok,
                "field_miss_n": len(miss),
                "body": body_scores(gb, preds.get("正文", "")) if gb.strip() else None,
            })

            done = sum(by_kind[k]["n"] for k in by_kind) + st["n"] if by_kind else st["n"]
            # progress across folders
            total_done = sum(
                len(list((TXT100 / x).glob("*.txt")))
                for x in ("通用", "纪要", "命令", "信函")
                if x < folder  # wrong
            )
        # fix progress: recount
        by_kind[folder] = st
        elapsed = time.perf_counter() - t0
        print(
            f"[{folder}] n={st['n']} kind={st['kind_ok']/st['n']:.2%} "
            f"field={st['field_ok']}/{st['field_n']} "
            f"body_exact={st['body_exact']}/{st['body_n']} ({elapsed:.0f}s)",
            flush=True,
        )

    elapsed = time.perf_counter() - t0
    report = {
        "source": str(TXT100),
        "engine": "OnnxFieldRecognizer + govdoc-sdk v5 postprocess",
        "n_docs": sum(by_kind[k]["n"] for k in by_kind),
        "elapsed_sec": round(elapsed, 1),
        "n_errors": n_err,
        "kind_routing": {
            k: {
                "acc": round(by_kind[k]["kind_ok"] / by_kind[k]["n"], 4) if by_kind[k]["n"] else 0,
                "ok": by_kind[k]["kind_ok"],
                "n": by_kind[k]["n"],
            }
            for k in by_kind
        },
        "kind_confusions": [
            {"expect": a, "got": b, "n": n} for (a, b), n in kind_conf.most_common()
        ],
        "by_kind": {},
        "note": (
            "字段：仅对金标中出现的字段计分；命中=归一化后相等或近全长包含。"
            "正文：字符级 F1 / SequenceMatcher ratio / exact。"
        ),
    }
    for k, st in by_kind.items():
        report["by_kind"][k] = {
            "n": st["n"],
            "kind_acc": round(st["kind_ok"] / st["n"], 4) if st["n"] else 0,
            "field_acc": round(st["field_ok"] / st["field_n"], 4) if st["field_n"] else 0,
            "field_ok": st["field_ok"],
            "field_n": st["field_n"],
            "field_by": {
                f: {
                    "acc": round(ok / n, 4) if n else 0,
                    "ok": ok,
                    "n": n,
                }
                for f, (ok, n) in sorted(st["field_by"].items())
            },
            "body_exact_rate": round(st["body_exact"] / st["body_n"], 4) if st["body_n"] else None,
            "body_mean_f1": round(st["body_f1_sum"] / st["body_n"], 4) if st["body_n"] else None,
            "body_mean_ratio": round(st["body_ratio_sum"] / st["body_n"], 4) if st["body_n"] else None,
            "body_n": st["body_n"],
            "body_pred_empty": st["body_pred_empty"],
            "samples_field_miss": st["samples_field_miss"],
            "samples_body_bad": st["samples_body_bad"],
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ROWS.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT, flush=True)
    print(json.dumps({
        "elapsed_sec": report["elapsed_sec"],
        "kind_routing": report["kind_routing"],
        "field_body": {
            k: {
                "field_acc": report["by_kind"][k]["field_acc"],
                "body_mean_f1": report["by_kind"][k]["body_mean_f1"],
                "body_exact_rate": report["by_kind"][k]["body_exact_rate"],
            }
            for k in report["by_kind"]
        },
        "n_errors": n_err,
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
