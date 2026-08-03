# 飞书同步详细流程（主编排执行时读取）

> 本文件是 SkillSentry 主编排器在飞书同步步骤时的详细执行流程。
> 被测 Skill 的 SKILL.md 不需要读取本文件。

config.json 不存在时，所有操作静默跳过并记录 `skipped_no_config`，不中断主流程。

---

## PULL（executor 执行前自动调用）

```
OpenClaw: feishu_bitable_app_table_record(action=list, app_token, table_id=cases_table_id, filter=...)
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
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | SkillSentry 工程执行组件 |
| 当前文件 | `SkillSentry_repo\references\feishu-sync.md` |
| 学习重点 | feishu-sync |
| 阅读目标 | 看懂这份资料解决什么问题、为什么重要、怎么落地、面试时怎么讲。 |

### 背景、痛点、举措、收益

| 维度 | 内容 |
|---|---|
| 背景 | SkillSentry 需要把分析、执行、比较、评分、报告和同步拆成可维护组件。 |
| 痛点 | 如果所有逻辑混在一起，难以定位失败、复用组件、扩展平台或设置门禁。 |
| 举措 | 按组件职责拆分输入、处理、输出和失败处理，并用契约文档约束交互。 |
| 收益 | 工程链路更清晰，便于调试、扩展、自动化和团队协作。 |

### 面试话术怎么回答

> SkillSentry 的工程设计核心是职责拆分：执行组件产生日志和结果，评分组件给出结构化判断，报告组件服务决策，比较组件用于回归和横评。

### 具体案例是什么

executor 负责跑样本，grader 负责按 rubric 打分，report 负责把结果转成可读报告，comparator 负责跨版本或跨 Agent 对比。

### 专业术语解释

| 中文术语 | 英文术语 | 专业解释 | 白话解释 |
|---|---|---|---|
| Executor | Executor | 负责运行评测任务并采集结果的组件。 | 执行器。 |
| Grader | Grader | 根据规则或模型判断输出质量的评分组件。 | 评分器。 |
| Comparator | Comparator | 比较不同版本、平台或运行结果差异的组件。 | 对比器。 |

### 复习抓手

1. 先用一句话说清这个文件的主题。
2. 再用“背景—痛点—举措—收益”解释它为什么重要。
3. 最后补一个 SkillSentry 或业务场景案例，证明你不是只背概念。
