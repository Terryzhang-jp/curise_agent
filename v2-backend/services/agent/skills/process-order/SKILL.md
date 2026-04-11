---
name: process-order
description: 处理新上传的订单 — 从提取到匹配到询价的端到端流程。当用户上传订单、说"处理这个订单"、"帮我提取"时触发。
---

# 订单处理流程

## 运行模式: 自动推进 + 异常暂停

正常情况下自动推进到下一步, 不等用户确认。
遇到以下异常时暂停, 报告问题, 等用户决策:
- 产品数 = 0 (提取失败)
- 关键元数据缺失 (无 PO号/船名/交货日期)
- 匹配率 < 80%
- 超过 5 个产品有数值验证警告
- 生成询价时缺必填字段 (blocking gap)

## Step 1: 提取订单数据

检查订单状态:
- 如果 status="extracted" → 已提取, 跳到 Step 2
- 如果 status="uploading"/"extracting" → 正在提取, 告知用户等待
- 如果 status="error" → 提取失败, 告知原因
- 如果 products 为空 → 调用 extract_order(order_id)

提取后检查:
- 产品数 > 0? → 继续 ✓
- 产品数 = 0? → **暂停**: "提取未识别到产品, 请检查文件格式"
- 缺 delivery_date? → **暂停**: "缺少交货日期, 请提供"
- 其他元数据缺失 → 记录警告但继续

## Step 2: 匹配产品

调用 match_products(order_id)

匹配后检查:
- 匹配率 ≥ 80%? → 自动继续, 报告结果 ✓
- 匹配率 < 80%? → **暂停**: "匹配率较低 (N%), 以下产品未匹配: [列表]. 要手动处理还是继续?"
- 缺 delivery_date 导致匹配跳过? → **暂停**: "需要交货日期才能匹配"

## Step 3: 检查询价就绪

调用 manage_inquiry(action="check", order_id)

就绪检查:
- 所有供应商 ready, 0 blocking gap? → **必须立即继续 Step 4, 不要暂停, 不要总结, 不要等用户**
- 有 blocking gap? → **暂停**: "以下字段缺失: [列表]. 请提供或跳过"
- 无供应商 (全部未匹配)? → **暂停**: "没有可生成询价的供应商"

⚠️ 关键: Step 3 的 check 工具返回 ready 状态时, **不是任务终点**。
你必须立即在下一个 tool call 调用 manage_inquiry(action="generate"), 不允许在这里暂停总结。
看到 ready 就继续, 看到 blocking gap 才暂停。

## Step 4: 生成询价 (这是 process-order 的真正终点)

调用 manage_inquiry(action="generate", order_id)

⚠️ 这一步是 process-order skill 的**最后一步**。只有这一步执行完, process-order 才算完成。
不要在调用 Step 3 之后就停下来 — 那叫做 "检查就绪", 不叫 "完成询价"。

生成后:
- 成功 → 报告: "已生成 N 份询价单, 涉及 M 个供应商. 文件已保存到工作目录."
- 失败 → 报告具体错误

## 完成

报告整体结果:
- 提取: N 个产品
- 匹配: 匹配率 X%
- 询价: 生成 Y 份, 涉及 Z 个供应商

$ARGUMENTS
