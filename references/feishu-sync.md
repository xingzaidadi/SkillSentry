# 飞书同步详细流程（主编排执行时读取）

> 本文件是 SkillSentry 主编排器在飞书同步步骤时的详细执行流程。
> 被测 Skill 的 SKILL.md 不需要读取本文件。

config.json 不存在时，所有操作静默跳过并记录 `skipped_no_config`，不中断主流程。

---

## PULL（executor 执行前自动调用）

```
OpenClaw: feishu_app_bitable_app_table_record(action=list, app_token, table_id=cases_table_id, filter=...)
CLI:     POST /auth/v3/tenant_access_token/internal → token
         GET  /bitable/v1/apps/{app_token}/tables/{cases_table_id}/records
         filter: skill_name="{name}" AND status="active"
→ 写入 inputs_dir/cases.feishu.json
→ 与 evals.json 合并（飞书 human 用例优先）
→ 输出：「🔄 已从飞书同步 [N] 条用例」
```

**MARK_STALE（PULL 附带，hash 不匹配时）**：rule_ref 已删除 → status="stale"；仍存在 → status="needs_review"。

---

## PUSH-CASES（sentry-cases 完成后，Step 4.5，不可跳过）

```
1. 对 evals.json 中无 feishu_record_id 的用例：
   case_id = MD5(skill_name + rule_ref + prompt 前50字)
2. 查询飞书去重（case_id 已存在则跳过）
3. POST /bitable/.../records/batch_create → 推送新用例（status=pending_review）
4. 解析返回的 records 列表，提取每条 record_id
   按 case_id 匹配 evals.json 中对应用例，追加 feishu_record_id 字段
   覆盖写 evals.json（保留所有原有字段）
5. 更新 session.json sync.push_cases = "done"
→ 输出：「📤 PUSH-CASES：[N] 条新用例已推送飞书（pending_review）」
```

---

## PUSH-RESULTS（grader-report 完成后，Step 6.5，不可跳过）

```
1. 读取 evals.json，找出有 feishu_record_id 的用例
2. POST /bitable/.../records/batch_update → 更新 last_run_result + last_run_date
3. 更新 session.json sync.push_results = "done"
→ 输出：「✅ PUSH-RESULTS：更新 [N] 条用例结果」
```

**Step 7 前置校验**（报告前强制检查）：
```
sync.push_cases ≠ null AND sync.push_results ≠ null → 继续
任一为 null → ⛔ 阻断，输出缺失项，要求补执行
```

---

## PUSH-RUN（report 完成后，Step 7.5，不可跳过）

```
1. POST /bitable/.../tables/{run_history_table_id}/records
   fields: run_id, skill_name, skill_hash, mode, grade, verdict, pass_rate_overall, ran_at
2. 更新 session.json sync.push_run = "done"
→ 输出：「✅ PUSH-RUN：运行记录已写入飞书」
```
