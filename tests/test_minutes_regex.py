# -*- coding: utf-8 -*-
from __future__ import annotations

import time

from core.ir.builder import model_to_partial_ir
from core.recognize.minutes_regex import extract_minutes_fields, try_recognize_minutes

SAMPLE = """000038
秘密★1年
特急
江州市人民政府专题会议纪要
第7期
全市冬季道路交通安全专项整治工作会议纪要
11月11日下午，市长张明远主持召开全市冬季道路交通安全专项整治工作专题会议，听取市交通运输局、市公安局交通管理局汇报，研究部署下一步工作。现将议定事项纪要如下。
一、总体要求
（一）工作目标
1. 事故总量下降。专项整治期间，全市道路交通事故起数、死亡人数同比分别下降10%以上。
2. 重点隐患清零。高速公路、国省道团雾多发路段和事故多发点段的警示标志、防护设施，于12月10日前全部补齐。
（二）时间安排
本次专项整治自2026年11月15日起至2027年2月28日止，分排查、整治、巩固三个阶段推进。
二、重点任务
（一）强化路面管控
1. 交警部门要在团雾、结冰多发路段增设流动巡逻组，恶劣天气期间实行24小时值守。
2. 交通运输部门要督促客运企业落实动态监控，对超速、疲劳驾驶即时预警处置。
（二）深化源头治理
1. 对全市"两客一危"车辆开展一次全面检查，不合格车辆一律停运整改。
2. 对冬季施工路段，施工单位要按规定设置警示标志，夜间加设反光设施。
三、工作要求
各县（区）人民政府、市政府有关部门要压实责任，主要负责同志要亲自调度。市政府办公室要会同市应急管理局开展暗访督查，每月通报一次。
附件：1. 全市冬季道路交通安全专项整治重点路段清单
2. 专项整治工作联系表
出席：张明远（市长）、李国强（副市长）、王建华（副市长）、陈立新（副市长）、周海涛（秘书长）
列席：市交通运输局局长何建国、市公安局交通管理局局长徐立群、市应急管理局局长郑国庆、市气象局局长黄志远、市财政局局长孙丽华、市市场监督管理局局长林伟东
（此件发至县团级）
抄送：市委办公室、市人大常委会办公室、市政协办公室、市纪委监委、各县（区）人民政府
江州市人民政府办公室　　2026年11月13日印发
"""


def test_minutes_regex_fast_and_fields():
    t0 = time.perf_counter()
    f = extract_minutes_fields(SAMPLE)
    assert time.perf_counter() - t0 < 1.0

    assert f["header"]["copy_number"] == "000038"
    assert f["header"]["secret_level"] == "秘密"
    assert f["header"]["retention_period"] == "1年"
    assert f["header"]["urgency"] == "特急"
    assert f["header"]["issuing_org_header"] == "江州市人民政府专题会议纪要"
    assert f["header"]["issue_no"] == "第7期"
    assert f["main"]["title"] == "全市冬季道路交通安全专项整治工作会议纪要"
    assert "一、总体要求" in f["body_blocks"]
    assert f["main"]["attendance"] and "张明远" in f["main"]["attendance"]
    assert "、" in f["main"]["attendance"]
    assert f["main"]["liexi"] and "何建国" in f["main"]["liexi"]
    assert f["main"]["note"] and "县团级" in f["main"]["note"]
    assert f["footer"]["cc_recipients"] and "市委办公室" in f["footer"]["cc_recipients"]
    assert f["footer"]["print_org"] == "江州市人民政府办公室"
    assert f["footer"]["print_date"] == "2026年11月13日"
    assert f["main"]["attachment_caption"]
    assert "重点路段清单" in f["main"]["attachment_caption"]

    model = try_recognize_minutes(SAMPLE)
    assert model is not None
    ir = model_to_partial_ir(model, source_text=SAMPLE)
    assert ir.is_minutes()
    assert ir.issue_no == "第7期"
    assert ir.attendance
    assert ir.missing_required() == []
