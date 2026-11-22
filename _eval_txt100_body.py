# -*- coding: utf-8 -*-
"""txt100：只评正文切分（金标「正文」vs recognize body_blocks）。"""
from __future__ import annotations

import json
import sys
import time
import traceback
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SDK = ROOT / "third_party" / "govdoc-sdk"
TXT100 = Path(r"E:\red head\Red Head Helper\examples\txt100")
OUT = ROOT / "examples" / "out" / "txt100_body_eval.json"
ROWS = ROOT / "examples" / "out" / "txt100_body_eval_rows.json"

SEP = "====================【字段标注（正确答案）】===================="

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SDK))

from core.recognize.onnx_recognizer import OnnxFieldRecognizer  # noqa: E402


def flat(s: str) -> str:
    t = (s or "").replace("\u3000", "").replace("\n", "").replace("\r", "").replace(" ", "")
    t = t.replace("：", ":").replace("〔", "[").replace("〕", "]")
    t = t.replace("（", "(").replace("）", ")")
    return t.strip()


def parse_file(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8-sig")
    if SEP not in raw:
        return raw.strip(), ""
    body, gold_raw = raw.split(SEP, 1)
    gold_body = ""
    lines = gold_raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.startswith("正文："):
            i += 1
            continue
        parts = [ln.split("：", 1)[1]] if "：" in ln else []
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if (
                "：" in nxt
                and not nxt.startswith(("　", " ", "\t"))
                and len(nxt.split("：", 1)[0].strip()) <= 24
                and not nxt.split("：", 1)[0].strip().startswith(("一", "二", "三", "（", "("))
            ):
                break
            parts.append(nxt)
            i += 1
        gold_body = "\n".join(parts).strip()
        break
    return body.strip(), gold_body


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
    year_split = bool(p) and not p.startswith("20") and g.startswith("20") and (
        p.startswith(g[1:8]) if len(g) >= 8 else False
    )
    return {
        "exact": exact,
        "ratio": round(ratio, 4),
        "f1": round(f1, 4),
        "empty_gold": False,
        "pred_empty": not bool(p),
        "gold_in_pred": g in p if p else False,
        "pred_in_gold": p in g if p else False,
        "year_digit_eaten": year_split,
        "pred_head": (pred or "")[:40].replace("\n", "\\n"),
        "gold_head": (gold or "")[:40].replace("\n", "\\n"),
    }


def main() -> int:
    rec = OnnxFieldRecognizer(SDK / "model.onnx", SDK / "vocab.txt", sdk_root=SDK)
    t0 = time.perf_counter()
    by_kind: dict = {}
    rows: list = []
    n_err = 0

    for folder in ("通用", "纪要", "命令", "信函"):
        files = sorted((TXT100 / folder).glob("*.txt"))
        st = {
            "n": 0,
            "body_n": 0,
            "exact": 0,
            "f1_sum": 0.0,
            "ratio_sum": 0.0,
            "pred_empty": 0,
            "year_digit_eaten": 0,
            "f1_lt_95": 0,
            "samples_bad": [],
        }
        for fp in files:
            st["n"] += 1
            try:
                text, gold_body = parse_file(fp)
                model = rec.recognize(text)
                pred = "\n".join(model.main.body_blocks or [])
            except Exception:
                n_err += 1
                rows.append({"folder": folder, "file": fp.name, "error": traceback.format_exc(limit=1)})
                continue

            if not gold_body.strip():
                rows.append({"folder": folder, "file": fp.name, "skip": "no_gold_body"})
                continue

            bs = body_scores(gold_body, pred)
            st["body_n"] += 1
            st["exact"] += int(bs["exact"])
            st["f1_sum"] += bs["f1"]
            st["ratio_sum"] += bs["ratio"]
            if bs.get("pred_empty"):
                st["pred_empty"] += 1
            if bs.get("year_digit_eaten"):
                st["year_digit_eaten"] += 1
            if bs["f1"] < 0.95:
                st["f1_lt_95"] += 1
            if (bs["exact"] < 1 or bs["f1"] < 0.95) and len(st["samples_bad"]) < 8:
                st["samples_bad"].append(
                    {
                        "file": fp.name,
                        "f1": bs["f1"],
                        "exact": bs["exact"],
                        "year_digit_eaten": bs.get("year_digit_eaten"),
                        "gold_head": bs["gold_head"],
                        "pred_head": bs["pred_head"],
                        "gold_in_pred": bs["gold_in_pred"],
                        "pred_in_gold": bs["pred_in_gold"],
                    }
                )
            rows.append({"folder": folder, "file": fp.name, "body": bs})

        by_kind[folder] = st
        elapsed = time.perf_counter() - t0
        print(
            f"[{folder}] n={st['body_n']} exact={st['exact']}/{st['body_n']} "
            f"mean_f1={st['f1_sum']/st['body_n']:.4f} "
            f"f1<0.95={st['f1_lt_95']} year_eat={st['year_digit_eaten']} ({elapsed:.0f}s)",
            flush=True,
        )

    elapsed = time.perf_counter() - t0
    report = {
        "source": str(TXT100),
        "scope": "body_only",
        "n_docs": sum(by_kind[k]["n"] for k in by_kind),
        "elapsed_sec": round(elapsed, 1),
        "n_errors": n_err,
        "by_kind": {
            k: {
                "n": st["n"],
                "body_n": st["body_n"],
                "exact_rate": round(st["exact"] / st["body_n"], 4) if st["body_n"] else None,
                "mean_f1": round(st["f1_sum"] / st["body_n"], 4) if st["body_n"] else None,
                "mean_ratio": round(st["ratio_sum"] / st["body_n"], 4) if st["body_n"] else None,
                "pred_empty": st["pred_empty"],
                "year_digit_eaten": st["year_digit_eaten"],
                "f1_lt_95": st["f1_lt_95"],
                "samples_bad": st["samples_bad"],
            }
            for k, st in by_kind.items()
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ROWS.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT, flush=True)
    print(json.dumps(report["by_kind"], ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
