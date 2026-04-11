# 订单提取 + 询价生成 稳定性分析

> 日期: 2026-04-08
> 问题: 读取订单不稳定, 生成询价单不稳定

---

## 根因诊断

不稳定的本质是: **LLM 调用的结果不可预测, 但代码假设它总是正确的。**

当前管道的每一步都有"快乐路径"(LLM 返回完美 JSON) 和"现实路径"(LLM 返回残缺/错误/格式异常的数据)。代码只处理了快乐路径, 现实路径全部走 silent fallback (空字典、空列表、默认值), 错误被吞掉, 用户看到的是"成功了但结果不对"。

---

## 两类不稳定的具体表现

### A. 订单提取不稳定

| 症状 | 根因 | 代码位置 |
|------|------|---------|
| 提取出 0 个产品但状态显示 "ready" | `products: []` 被 silent accept, 无产品数校验 | `order_processor.py:820` |
| metadata 缺字段 (po_number/delivery_date = None) | `normalize_metadata({})` 返回全 None dict, 不报错 | `order_processor.py:26-77` |
| 同一份 PDF 提取两次结果不同 | Gemini Vision 非确定性 + 无结果缓存 | `order_processor.py:189-205` |
| LLM 返回无效 JSON | 2 次重试后 raise, 但错误信息无 LLM 原始输出 | `order_processor.py:200-205` |
| 缺 delivery_date 时跳过匹配但不报错 | `skipped_reason` 存了但 status 仍 = "ready" | `order_processor.py:584-593` |

### B. 询价生成不稳定

| 症状 | 根因 | 代码位置 |
|------|------|---------|
| Excel 单元格填错位置 | LLM header mapping 非确定性, 无 cell ref 校验 | `inquiry_agent.py:860-874` |
| 产品行公式错误 (SUM 范围不对) | `openpyxl.insert_rows` 不更新公式引用, 正则替换有 bug | `inquiry_agent.py:1115-1129` |
| Template engine 失败但用户不知道 | 静默 fallback 到 LLM 路径, 无日志给用户 | `inquiry_agent.py:732-752` |
| 金额列显示 0 | 价格字段 `or 0` fallback | `inquiry_agent.py:1333` |
| 日期格式不一致 | annotation enforcement 10 种格式但无 post-validation | `inquiry_agent.py:1031-1053` |

---

## Agent 系统能做什么

关键洞察: **提取和生成管道完全在 agent 循环之外运行**。Agent 只能触发它们, 不能观察或干预过程。但 agent 可以在管道前后做事:

```
          管道之前          管道内部 (当前)        管道之后
         ──────────      ──────────────────    ──────────────
Agent 能做:               Agent 不能做:         Agent 能做:
- 预检查输入              - 提取逻辑            - 验证输出
- 补充缺失上下文          - 匹配逻辑            - 自动修正
                          - Excel 生成          - 告知用户具体问题
```

**三层修复策略:**

### 层 1: 管道内部防御 (代码级, 不需要 agent)
在 pipeline 内部加入校验, 让错误**早暴露、不 silent**。

### 层 2: 管道后验证 (利用 agent 工具)
Agent 在生成后用 `manage_order` 和 `modify_excel` 验证和修正。

### 层 3: 提取结果缓存 + 模板覆盖率 (长期)
减少 LLM 依赖, 提高确定性路径覆盖率。

---

## 具体改动计划

### P0: 管道内部防御 (今天做)

1. **提取后产品数校验**: 提取出 0 个产品 → 状态设为 error, 不设为 ready
2. **metadata 完整性校验**: 缺 delivery_date 时状态设为 error, 附上缺失字段列表
3. **LLM 原始输出保存**: JSON 解析失败时, 把 LLM 原始文本存入 order.extraction_data.raw_response
4. **路径标记**: 询价生成后标记用了哪条路径 (template_engine / llm_mapping / generic)
5. **formula 列验证**: 写入 Excel 后检查公式是否为有效 Excel 公式

### P1: 管道后验证 (本周做)
6. **新增 verify_extraction 工具**: agent 可以对比提取结果和原始文件
7. **新增 verify_inquiry 工具**: agent 可以读取生成的 Excel 检查关键单元格

### P2: 长期
8. 为所有活跃供应商模板补全 zone_config → 100% 走确定性路径
9. 提取结果缓存: 同一模板+相似文件 → 复用上次成功的提取 schema
