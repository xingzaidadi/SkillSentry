#!/usr/bin/env python3
"""
SkillSentry — 飞书多维表格（Bitable）与本地 JSON 双向同步脚本。

用法：
    python3 sync_cases.py pull        --skill <name> [--config path]
    python3 sync_cases.py push-cases  --skill <name> [--session-dir path] [--config path]
    python3 sync_cases.py push-run    --session-dir <path> [--config path]
    python3 sync_cases.py mark-stale  --skill <name> [--config path]
    python3 sync_cases.py init        --skill <name> [--config path]
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─────────────────────────────────────────────
# 路径常量
# ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
INPUTS_DIR = SKILL_ROOT / "inputs"
TOKEN_CACHE = Path("/tmp/feishu_tenant_token.json")
DEFAULT_CONFIG = SKILL_ROOT / "config.json"
MAX_BATCH = 500  # 飞书 Bitable API 单批上限

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def load_config(config_path: str | None) -> dict:
    """加载配置文件。"""
    p = Path(config_path) if config_path else DEFAULT_CONFIG
    if not p.exists():
        print(f"❌ 配置文件不存在：{p}")
        print("请先配置 config.json，参考指南")
        sys.exit(1)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _now_iso() -> str:
    """返回当前时间 ISO 8601 字符串（+08:00）。"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat()


def _ms_to_iso(ms: int | float | None) -> str | None:
    """毫秒时间戳 → ISO 字符串 (+08:00)。"""
    if ms is None:
        return None
    tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(ms / 1000, tz=tz).isoformat()


def _iso_to_ms(iso_str: str | None) -> int | None:
    """ISO 字符串 → 毫秒时间戳。"""
    if iso_str is None:
        return None
    # 处理常见 ISO 格式
    s = iso_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def content_hash(prompt: str, expectations) -> str:
    """计算 content_hash = md5(prompt + json.dumps(expectations))"""
    raw = prompt + json.dumps(expectations, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def md5_file(filepath: str | Path) -> str:
    """计算文件的 MD5。"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────
# 飞书 API 层
# ─────────────────────────────────────────────

def get_tenant_token(cfg: dict) -> str:
    """获取 tenant_access_token（带缓存）。"""
    app_id = cfg["feishu"]["app_id"]
    app_secret = cfg["feishu"]["app_secret"]

    # 检查缓存
    if TOKEN_CACHE.exists():
        try:
            with open(TOKEN_CACHE, "r") as f:
                cached = json.load(f)
            if cached.get("expire", 0) > time.time() + 60:
                return cached["token"]
        except (json.JSONDecodeError, KeyError):
            pass

    # 请求新 token
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    if data.get("code") != 0:
        print(f"❌ 获取 token 失败：{data}")
        sys.exit(1)

    token = data["tenant_access_token"]
    expire = int(time.time()) + data.get("expire", 7200)

    with open(TOKEN_CACHE, "w") as f:
        json.dump({"token": token, "expire": expire}, f)

    return token


def _api_request(url: str, token: str, method: str = "POST", body: dict | None = None, retry_auth: bool = True, cfg: dict | None = None) -> dict:
    """通用飞书 API 请求，自动处理 401/429。"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        code = e.code
        resp_body = e.read().decode(errors="replace")

        if code == 401 and retry_auth and cfg:
            # Token 过期，刷新后重试
            if TOKEN_CACHE.exists():
                TOKEN_CACHE.unlink()
            new_token = get_tenant_token(cfg)
            return _api_request(url, new_token, method, body, retry_auth=False, cfg=cfg)

        if code == 429:
            # Rate limit
            retry_after = int(e.headers.get("Retry-After", "2"))
            print(f"⏳ 触发限流，等待 {retry_after}s 后重试…")
            time.sleep(retry_after)
            return _api_request(url, token, method, body, retry_auth=retry_auth, cfg=cfg)

        print(f"❌ API 错误 {code}：{resp_body}")
        sys.exit(1)


def bitable_search_records(cfg: dict, token: str, table_id: str, filter_obj: dict | None = None, page_token: str | None = None) -> dict:
    """查询 Bitable 记录。"""
    app_token = cfg["feishu"]["app_token"]
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    body: dict = {"page_size": 500}
    if filter_obj:
        body["filter"] = filter_obj
    if page_token:
        body["page_token"] = page_token
    return _api_request(url, token, body=body, cfg=cfg)


def bitable_create_records(cfg: dict, token: str, table_id: str, records: list[dict]) -> dict:
    """批量创建 Bitable 记录（分批，每批 ≤500）。"""
    app_token = cfg["feishu"]["app_token"]
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    results = []
    for i in range(0, len(records), MAX_BATCH):
        batch = records[i:i + MAX_BATCH]
        resp = _api_request(url, token, body={"records": [{"fields": r} for r in batch]}, cfg=cfg)
        results.append(resp)
    return results[-1] if results else {"code": 0}


def bitable_update_records(cfg: dict, token: str, table_id: str, records: list[dict]) -> dict:
    """批量更新 Bitable 记录（分批，每批 ≤500）。
    records: [{"record_id": "xxx", "fields": {...}}, ...]
    """
    app_token = cfg["feishu"]["app_token"]
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    results = []
    for i in range(0, len(records), MAX_BATCH):
        batch = records[i:i + MAX_BATCH]
        resp = _api_request(url, token, body={"records": batch}, cfg=cfg)
        results.append(resp)
    return results[-1] if results else {"code": 0}


def fetch_all_records(cfg: dict, token: str, table_id: str, filter_obj: dict | None = None) -> list[dict]:
    """分页拉取所有记录。"""
    items = []
    page_token = None
    while True:
        resp = bitable_search_records(cfg, token, table_id, filter_obj, page_token)
        if resp.get("code") != 0:
            print(f"❌ 查询记录失败：{resp}")
            sys.exit(1)
        data = resp.get("data", {})
        items.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return items


def _extract_fields(item: dict) -> dict:
    """从 Bitable record 中提取 fields。"""
    return item.get("fields", item)


def _bitable_record_to_json(fields: dict) -> dict:
    """Bitable fields → 本地 JSON 格式。"""
    result = {}
    # 直接复制文本/单选字段
    for key in ("case_id", "skill_name", "display_name", "type", "rule_ref",
                "prompt", "source", "priority", "status", "content_hash",
                "created_skill_hash", "last_run_result", "notes"):
        val = fields.get(key)
        if val is not None:
            result[key] = val

    # expectations: JSON 字符串 → 对象
    exp = fields.get("expectations")
    if exp and isinstance(exp, str):
        try:
            result["expectations"] = json.loads(exp)
        except json.JSONDecodeError:
            result["expectations"] = exp
    elif exp is not None:
        result["expectations"] = exp

    # last_run_date: 毫秒时间戳 → ISO 字符串
    lrd = fields.get("last_run_date")
    if lrd is not None:
        if isinstance(lrd, (int, float)):
            result["last_run_date"] = _ms_to_iso(lrd)
        else:
            result["last_run_date"] = str(lrd)

    return result


def _json_to_bitable_record(case: dict) -> dict:
    """本地 JSON 用例 → Bitable fields。"""
    fields = {}
    for key in ("case_id", "skill_name", "display_name", "type", "rule_ref",
                "prompt", "source", "priority", "status", "content_hash",
                "created_skill_hash", "last_run_result", "notes"):
        val = case.get(key)
        if val is not None:
            fields[key] = val

    # expectations: 对象 → JSON 字符串
    exp = case.get("expectations")
    if exp is not None:
        fields["expectations"] = json.dumps(exp, ensure_ascii=False) if not isinstance(exp, str) else exp

    # last_run_date: ISO 字符串 → 毫秒时间戳
    lrd = case.get("last_run_date")
    if lrd is not None:
        ms = _iso_to_ms(lrd)
        if ms is not None:
            fields["last_run_date"] = ms

    return fields


# ─────────────────────────────────────────────
# 命令实现
# ─────────────────────────────────────────────

def cmd_pull(args):
    """pull: 从飞书拉取用例到本地缓存。"""
    cfg = load_config(args.config)
    token = get_tenant_token(cfg)
    table_id = cfg["feishu"]["cases_table_id"]

    # 筛选条件：skill_name = X AND status in (active, needs_review)
    filter_obj = {
        "conjunction": "and",
        "conditions": [
            {"field_name": "skill_name", "operator": "is", "value": [args.skill]},
            {"field_name": "status", "operator": "is", "value": ["active", "needs_review"]},
        ]
    }

    items = fetch_all_records(cfg, token, table_id, filter_obj)

    cases = []
    active_count = 0
    review_count = 0
    for item in items:
        fields = _extract_fields(item)
        case = _bitable_record_to_json(fields)
        cases.append(case)
        st = case.get("status", "")
        if st == "active":
            active_count += 1
        elif st == "needs_review":
            review_count += 1

    # 保存到本地
    out_dir = INPUTS_DIR / args.skill
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "cases.cache.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    print(f"✅ 拉取完成：{active_count} 条 active 用例，{review_count} 条 needs_review 用例")
    print(f"   保存到：{out_file}")


def cmd_push_cases(args):
    """push-cases: 将 session 结果同步到 Bitable 用例表。"""
    cfg = load_config(args.config)
    token = get_tenant_token(cfg)
    table_id = cfg["feishu"]["cases_table_id"]

    # 定位 session 目录
    session_dir = _resolve_session_dir(args)

    # 读取 evals.json
    evals_file = session_dir / "evals.json"
    if not evals_file.exists():
        print(f"❌ 找不到 {evals_file}")
        sys.exit(1)
    with open(evals_file, "r", encoding="utf-8") as f:
        evals = json.load(f)

    eval_cases = evals if isinstance(evals, list) else evals.get("evals", evals.get("cases", []))

    # 读取各 eval-N/grading.json
    grading_map: dict[str, dict] = {}
    for item in session_dir.iterdir():
        if item.is_dir() and item.name.startswith("eval-"):
            grading_file = item / "grading.json"
            if grading_file.exists():
                with open(grading_file, "r", encoding="utf-8") as f:
                    grading_map[item.name] = json.load(f)

    # 拉取 Bitable 中已有的 case_id
    filter_obj = {
        "conjunction": "and",
        "conditions": [
            {"field_name": "skill_name", "operator": "is", "value": [args.skill]},
        ]
    }
    existing_items = fetch_all_records(cfg, token, table_id, filter_obj)
    existing_by_case_id: dict[str, dict] = {}
    for item in existing_items:
        fields = _extract_fields(item)
        cid = fields.get("case_id")
        if cid:
            existing_by_case_id[cid] = {"record_id": item.get("record_id"), "fields": fields}

    now_ms = int(time.time() * 1000)
    to_create = []
    to_update = []

    for idx, case in enumerate(eval_cases):
        case_id = case.get("case_id", f"eval-{idx}")
        prompt = case.get("prompt", "")
        expectations = case.get("expectations", [])
        ch = content_hash(prompt, expectations)

        # 查找 grading 结果
        eval_key = f"eval-{idx}"
        grading = grading_map.get(eval_key, {})
        last_run_result = grading.get("verdict") or grading.get("result")

        if case_id in existing_by_case_id:
            # 已有记录，更新
            rec = existing_by_case_id[case_id]
            update_fields = {"content_hash": ch}
            if last_run_result:
                update_fields["last_run_result"] = last_run_result
                update_fields["last_run_date"] = now_ms
            to_update.append({"record_id": rec["record_id"], "fields": update_fields})
        else:
            # 新记录
            fields = _json_to_bitable_record(case)
            fields["skill_name"] = args.skill
            fields["case_id"] = case_id
            fields["content_hash"] = ch
            fields["status"] = "pending_review"
            if last_run_result:
                fields["last_run_result"] = last_run_result
                fields["last_run_date"] = now_ms
            to_create.append(fields)

    # 执行批量操作
    if to_create:
        bitable_create_records(cfg, token, table_id, to_create)
    if to_update:
        bitable_update_records(cfg, token, table_id, to_update)

    print(f"✅ 同步完成：{len(to_update)} 条更新，{len(to_create)} 条新建")


def cmd_push_run(args):
    """push-run: 写入运行记录到 Bitable。"""
    cfg = load_config(args.config)
    token = get_tenant_token(cfg)
    table_id = cfg["feishu"]["run_history_table_id"]

    session_dir = Path(args.session_dir).resolve()
    if not session_dir.is_dir():
        # 尝试在 sessions 目录下查找
        alt = SKILL_ROOT / "sessions" / args.session_dir
        if alt.is_dir():
            session_dir = alt
        else:
            print(f"❌ session 目录不存在：{session_dir}")
            sys.exit(1)

    run_id = session_dir.name

    # 读取 evals.json 获取用例列表
    evals_file = session_dir / "evals.json"
    if not evals_file.exists():
        print(f"❌ 找不到 {evals_file}")
        sys.exit(1)
    with open(evals_file, "r", encoding="utf-8") as f:
        evals = json.load(f)
    eval_cases = evals if isinstance(evals, list) else evals.get("evals", evals.get("cases", []))

    # 读取各 grading.json 计算通过率
    total = 0
    passed = 0
    golden_total = 0
    golden_passed = 0
    case_results = []

    for idx, case in enumerate(eval_cases):
        eval_key = f"eval-{idx}"
        grading_file = session_dir / eval_key / "grading.json"
        total += 1
        is_golden = case.get("priority") == "P0" or case.get("source") == "golden"

        if grading_file.exists():
            with open(grading_file, "r", encoding="utf-8") as f:
                grading = json.load(f)
            verdict = grading.get("verdict") or grading.get("result", "")
            is_pass = verdict.upper() in ("PASS", "CONDITIONAL PASS", "TRUE")
        else:
            verdict = "SKIP"
            is_pass = False

        if is_pass:
            passed += 1
        if is_golden:
            golden_total += 1
            if is_pass:
                golden_passed += 1

        case_results.append({
            "case_id": case.get("case_id", f"eval-{idx}"),
            "verdict": verdict,
            "priority": case.get("priority"),
        })

    pass_rate_overall = passed / total if total > 0 else 0
    pass_rate_exact = pass_rate_overall  # 精确通过率 = 综合通过率（简化）
    pass_rate_golden = golden_passed / golden_total if golden_total > 0 else 0

    # 判定 verdict
    if pass_rate_overall >= 0.95:
        verdict = "PASS"
    elif pass_rate_overall >= 0.7:
        verdict = "CONDITIONAL PASS"
    else:
        verdict = "FAIL"

    # 判定 grade
    if pass_rate_overall >= 0.98:
        grade = "S"
    elif pass_rate_overall >= 0.9:
        grade = "A"
    elif pass_rate_overall >= 0.8:
        grade = "B"
    elif pass_rate_overall >= 0.6:
        grade = "C"
    elif pass_rate_overall >= 0.4:
        grade = "D"
    else:
        grade = "F"

    # 读取 baseline.snapshot.json 获取 skill_hash / skill_label
    skill_name = _infer_skill_name(session_dir, eval_cases)
    baseline_file = INPUTS_DIR / skill_name / "baseline.snapshot.json"
    skill_hash = ""
    skill_label = ""
    if baseline_file.exists():
        with open(baseline_file, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        skill_hash = baseline.get("skill_hash", "")
        skill_label = baseline.get("skill_label", "")

    # mode 从 session 目录名或 evals.json 推断
    mode = "standard"
    if isinstance(evals, dict):
        mode = evals.get("mode", mode)

    ran_at_ms = int(time.time() * 1000)

    fields = {
        "run_id": run_id,
        "skill_name": skill_name,
        "skill_hash": skill_hash,
        "skill_label": skill_label,
        "mode": mode,
        "grade": grade,
        "verdict": verdict,
        "pass_rate_overall": pass_rate_overall,
        "pass_rate_exact": pass_rate_exact,
        "pass_rate_golden": pass_rate_golden,
        "delta": "N/A",
        "case_set_snapshot": json.dumps(case_results, ensure_ascii=False),
        "comparable_to": "",
        "workspace_path": str(session_dir),
        "ran_at": ran_at_ms,
    }

    bitable_create_records(cfg, token, table_id, [fields])
    print(f"✅ 运行记录已写入：{run_id} | {verdict} | grade={grade} | pass_rate={pass_rate_overall:.1%}")


def cmd_mark_stale(args):
    """mark-stale: SKILL.md 变更后标记过期用例。"""
    cfg = load_config(args.config)
    token = get_tenant_token(cfg)
    table_id = cfg["feishu"]["cases_table_id"]

    # 计算当前 SKILL.md 的 MD5
    skill_md = _resolve_skill_md(args.skill)
    if not skill_md.exists():
        print(f"❌ 找不到 SKILL.md：{skill_md}")
        sys.exit(1)
    current_hash = md5_file(skill_md)

    # 拉取该 skill 所有 active 用例
    filter_obj = {
        "conjunction": "and",
        "conditions": [
            {"field_name": "skill_name", "operator": "is", "value": [args.skill]},
            {"field_name": "status", "operator": "is", "value": ["active"]},
        ]
    }
    items = fetch_all_records(cfg, token, table_id, filter_obj)

    stale_records = []
    for item in items:
        fields = _extract_fields(item)
        created_hash = fields.get("created_skill_hash", "")
        if created_hash and created_hash != current_hash:
            stale_records.append({
                "record_id": item.get("record_id"),
                "fields": {"status": "needs_review"}
            })

    if stale_records:
        bitable_update_records(cfg, token, table_id, stale_records)

    print(f"✅ 标记完成：{len(stale_records)} 条用例需 Review（SKILL.md 已变更）")
    print(f"   当前 SKILL.md hash: {current_hash}")


def cmd_init(args):
    """init: 首次初始化，将本地用例导入 Bitable。"""
    cfg = load_config(args.config)
    token = get_tenant_token(cfg)
    table_id = cfg["feishu"]["cases_table_id"]

    cache_file = INPUTS_DIR / args.skill / "cases.cache.json"
    if not cache_file.exists():
        print(f"❌ 找不到本地缓存：{cache_file}")
        print("请先运行 pull 或手动准备 cases.cache.json")
        sys.exit(1)

    with open(cache_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    if not cases:
        print("⚠️ cases.cache.json 为空，无需导入")
        return

    records = []
    for case in cases:
        fields = _json_to_bitable_record(case)
        fields["status"] = "pending_review"
        fields["skill_name"] = args.skill
        records.append(fields)

    bitable_create_records(cfg, token, table_id, records)
    print(f"✅ 初始化完成：导入 {len(records)} 条用例")


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────

def _resolve_session_dir(args) -> Path:
    """解析 session 目录路径。"""
    if args.session_dir:
        p = Path(args.session_dir).resolve()
        if p.is_dir():
            return p
        alt = SKILL_ROOT / "sessions" / args.session_dir
        if alt.is_dir():
            return alt
        print(f"❌ session 目录不存在：{args.session_dir}")
        sys.exit(1)
    # 默认找最近的 session
    sessions_root = SKILL_ROOT / "sessions"
    if sessions_root.exists():
        dirs = sorted([d for d in sessions_root.iterdir() if d.is_dir()], reverse=True)
        if dirs:
            return dirs[0]
    print("❌ 未指定 --session-dir，且找不到默认 session 目录")
    sys.exit(1)


def _resolve_skill_md(skill_name: str) -> Path:
    """定位 SKILL.md 文件。"""
    # 尝试多个常见位置
    candidates = [
        Path.home() / ".openclaw" / "skills" / skill_name / "SKILL.md",
        SKILL_ROOT / "references" / skill_name / "SKILL.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # 返回默认路径，由调用方处理不存在的情况


def _infer_skill_name(session_dir: Path, eval_cases: list) -> str:
    """从 session 目录或用例推断 skill 名称。"""
    # 从 evals.json 的第一条用例
    if eval_cases:
        sn = eval_cases[0].get("skill_name")
        if sn:
            return sn
    # 从 session 目录名（去掉日期后缀）
    name = session_dir.name
    parts = name.rsplit("_", 1)
    return parts[0] if len(parts) > 1 else name


# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sync_cases",
        description="SkillSentry — 飞书多维表格与本地 JSON 双向同步",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # pull
    p_pull = sub.add_parser("pull", help="从飞书拉取用例到本地缓存")
    p_pull.add_argument("--skill", required=True, help="Skill 名称")
    p_pull.add_argument("--config", help="配置文件路径（默认 config.json）")

    # push-cases
    p_push = sub.add_parser("push-cases", help="将 session 结果同步到飞书用例表")
    p_push.add_argument("--skill", required=True, help="Skill 名称")
    p_push.add_argument("--session-dir", help="session 目录路径（默认最近的 session）")
    p_push.add_argument("--config", help="配置文件路径")

    # push-run
    p_run = sub.add_parser("push-run", help="写入运行记录到飞书")
    p_run.add_argument("--session-dir", required=True, help="session 目录路径")
    p_run.add_argument("--config", help="配置文件路径")

    # mark-stale
    p_stale = sub.add_parser("mark-stale", help="SKILL.md 变更后标记过期用例")
    p_stale.add_argument("--skill", required=True, help="Skill 名称")
    p_stale.add_argument("--config", help="配置文件路径")

    # init
    p_init = sub.add_parser("init", help="首次初始化，将本地用例导入飞书")
    p_init.add_argument("--skill", required=True, help="Skill 名称")
    p_init.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "pull": cmd_pull,
        "push-cases": cmd_push_cases,
        "push-run": cmd_push_run,
        "mark-stale": cmd_mark_stale,
        "init": cmd_init,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
