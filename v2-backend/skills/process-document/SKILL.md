---
name: process-document
description: 处理新上传文档 — 先验证文档投影结果，再决定是否建单，并在可继续时衔接后续订单流程。
---

# 文档处理 Skill

## 目标

这个 Skill 只负责一件事:

- 把**已经提取完成的 Document**做成一个**可判断、可暂停、可继续**的订单入口

这个 Skill 不负责:

- 直接控制底层 PDF 提取
- 编造缺失字段
- 跳过验证直接建单

## 当前可用工具

- `manage_document_order(action="preview"|"create"|"products"|"compute_total"|"update_fields"|"clear_fields", document_id=...)`
- `manage_order(action="overview", order_id=...)`
- `use_skill(skill_name="process-order", arguments="order_id=...")`

重要边界:
- **Document 不是 Order**
- 在 `manage_document_order(action="create", ...)` 成功返回真实 `order_id` 之前，**不要**调用 `manage_order`
- 如果用户问的是“这份文档的总金额/产品/字段值/是否缺信息”，优先使用 `manage_document_order`
- 不要为了文档页问题改用 `query_db` 猜表结构或手写 SQL

## Context Package 优先

系统会在第一轮给你注入一份 `Document Context Package`。

这是当前文档处理的**首要信息源**，里面已经整理好了：
- 文档类型与分类置信度
- 关键字段状态
- 缺失字段
- 产品摘要
- 总金额计算
- 人工修正
- 推荐下一步

规则：
- **先读 package，再决定要不要调用工具**
- 如果 package 已经足够回答用户，就直接回答，不要为了保险再多调一轮 `preview`
- 只有这些情况才调工具：
  - 用户要求修改/清除字段
  - 用户要求重算总金额或看更详细产品
  - package 明确显示信息不足
  - 你准备正式建单或进入下一阶段

## 运行模式: 先修正, 再验证, 再建单, 有问题就暂停

正常情况下自动推进。
遇到关键问题时暂停，不要模糊，不要猜。

## 如果用户在文档页补充/修正字段

当用户明确提供新的字段值时，例如：
- “currency 改成 AUD”
- “location 是 Sydney”
- “交货日期改成 2026-04-15”

你的第一动作不是建单，而是：

1. 调用 `manage_document_order(action="update_fields", document_id=..., fields='{"字段": "值"}')`
2. 再调用 `manage_document_order(action="preview", document_id=...)`
3. 告诉用户更新后的结果和仍然缺失的字段

字段映射规则：
- `location` / `港口` / `目的港` → `destination_port`
- `currency` / `货币` / `币种` → `currency`
- `delivery date` / `交货日期` → `delivery_date`
- `order date` / `下单日期` → `order_date`
- `vendor` / `supplier` / `供应商` → `vendor_name`
- `ship` / `船名` → `ship_name`

重要：
- 用户是在修正文档，不是在要求你立即建单
- 只在用户明确要求“继续处理 / 建单 / 处理订单”时，才进入后面的建单流程
- 如果用户是在撤销某个值，用 `clear_fields`

## 如果用户是在文档页查询信息

常见意图:
- “总金额是多少”
- “帮我算一下 total”
- “看看有哪些产品”
- “现在缺哪些字段”

正确做法:
- 查总金额: `manage_document_order(action="compute_total", document_id=...)`
- 看产品: `manage_document_order(action="products", document_id=...)`
- 看建单前状态: `manage_document_order(action="preview", document_id=...)`

错误做法:
- 在还没建单时调用 `manage_order(order_id=document_id)`
- 直接写 SQL 去查 `v2_orders`
- 因为一次工具失败就跳到 `query_db`

## 总体原则

每一步都要回答 4 个问题:

1. 当前结果是否可信
2. 问题在哪里
3. 这个问题是否阻断下一步
4. 下一步应该继续还是暂停

如果 Tool 没有返回足够信息:
- 不要脑补
- 明确说信息不足
- 暂停并解释原因

如果字段不确定:
- 不要编造 `delivery_date`
- 不要编造 `currency`
- 不要编造 `destination_port`
- 不要编造产品明细

遇到以下情况必须暂停:
- 文档不存在
- 文档还在处理中
- 文档不是 `purchase_order`
- 产品数 = 0
- 缺少关键字段: `po_number` / `ship_name` / `delivery_date`
- 建单失败
- 建单后订单状态异常

## 当前最小字段契约

### 订单关键字段

- `po_number`
- `ship_name`
- `delivery_date`

### 订单重要但非阻断字段

- `vendor_name`
- `currency`
- `destination_port`
- `order_date`
- `total_amount`

### 产品最小要求

- `products` 必须非空
- 每个产品至少应有 `product_code` 或 `product_name` 之一

说明:
- 当前 `preview` 工具只暴露关键摘要，不暴露完整逐字段 JSON
- 因此本 Skill 先基于**当前可见信号**做验证，不假装拥有当前没有的检查能力

## Step 1: 先读 Context Package，再决定是否预览

默认先读取 `Document Context Package` 中已经给出的：
- 文档类型
- PO号
- 船名
- 交货日期
- 供应商
- 产品数
- 是否可直接建单
- 缺失字段

如果 package 已经完整，不需要再先调 `preview`。

只有在以下情况下才调用 `manage_document_order(action="preview", document_id=...)`：
- 用户刚修改过字段，需要刷新判断
- package 没有覆盖用户当前问题
- 你怀疑 package 与当前状态不一致

如果返回 `Error:`:
- 直接暂停
- 明确说明错误内容

## Step 2: 验证文档是否允许建单

按以下顺序检查:

### 2.1 文档类型检查

- 如果文档类型不是 `purchase_order` → 暂停
- 告知: 当前文档先保留在 documents 审核态，不进入订单流程

### 2.2 产品数检查

- 如果产品数 = 0 → 暂停
- 告知: 当前未识别到任何产品，不能建单

### 2.3 关键字段检查

关键字段:
- `po_number`
- `ship_name`
- `delivery_date`

如果任一缺失:
- 暂停
- 必须逐项列出缺失字段
- 不要强制建单，除非用户明确要求

### 2.4 可继续判断

只有在以下条件同时满足时，才允许自动进入建单:
- 文档类型 = `purchase_order`
- 产品数 > 0
- 缺失字段为空
- 工具结果明确显示 `可直接建单: 是`

如果条件不足:
- 暂停
- 输出当前阻断点

如果用户当前意图只是“修正字段 / 补充信息 / 确认某个值”：
- 到这里就停止
- 汇报最新预览结果
- 不要自动进入 Step 3

## Step 3: 创建订单

调用 `manage_document_order(action="create", document_id=...)`

创建后检查:
- 成功返回订单 ID → 继续
- 如果提示已有订单 → 使用已有订单 ID
- 如果返回 `Error:` → 暂停

必须明确区分:
- 是新建订单
- 还是复用已有订单

## Step 4: 立即验证新订单状态

拿到订单 ID 后，调用:

`manage_order(action="overview", order_id=...)`

检查:
- 订单是否真实存在
- 订单状态是否可继续
- `delivery_date` 是否存在
- `currency` 是否为空
- 是否已有明显 `processing_error`

处理规则:
- 如果订单不存在或工具报错 → 暂停
- 如果订单状态是 `error` → 暂停
- 如果出现“待补充关键字段”或类似 warning → 暂停
- 如果订单概览正常 → 继续

说明:
- `currency`、`destination_port`、`total_amount` 在当前阶段属于重要字段
- 如果它们为空，不一定阻断建单
- 但要在结果汇报里明确写出“已知缺口”

## Step 5: 进入订单处理

**这一步只允许这一种调用方式**:

```
use_skill(skill_name="process-order", arguments="order_id=<上一步得到的订单ID>")
```

**严格禁止的错误做法**:
- 不要用 `tool_search` 去搜 `process-order`
- 不要假设 `process-order` 是一个独立的 tool
- 不要去查时间、查别的工具、或做任何不相关的探索

`process-order` 是一个 **skill**，不是 tool。Skill 只能通过 `use_skill` 调用。
如果 `use_skill` 调用本身报错，**直接暂停并报告错误**，不要尝试用别的工具替代。

进入前说明:
- 当前文档验证已通过
- 已生成订单
- 后续由 `process-order` 负责提取复核、匹配与询价链路

## 暂停时的输出格式

如果暂停，必须按这个格式报告:

- 当前步骤
- 问题类型
- 具体问题
- 是否阻断
- 建议下一步

示例:
- 当前步骤: Step 2
- 问题类型: 缺关键字段
- 具体问题: 缺少 `delivery_date`
- 是否阻断: 是
- 建议下一步: 先补充交货日期，再重新处理文档

## 完成时的输出格式

完成时必须总结:

- 文档 ID
- 文档类型
- 产品数
- 缺失字段
- 是否建单
- 订单 ID
- 是新建还是复用
- 订单当前状态
- 是否已交给 `process-order`
- 仍然存在的风险或缺口

## Examples

### Example A: 正常可继续

1. 调用 `manage_document_order(action="preview", document_id=12)`
2. 结果显示:
   - 文档类型: `purchase_order`
   - 产品数: 24
   - 可直接建单: 是
   - 缺失字段: 无
3. 调用 `manage_document_order(action="create", document_id=12)`
4. 拿到订单 ID 后调用 `manage_order(action="overview", order_id=...)`
5. 概览正常 → 调用 `use_skill(skill_name="process-order", arguments="order_id=...")`

### Example B: 缺关键字段

1. 调用 `manage_document_order(action="preview", document_id=15)`
2. 结果显示:
   - 文档类型: `purchase_order`
   - 产品数: 22
   - 缺失字段: `delivery_date`
3. 不建单
4. 暂停并明确说明: 缺少交货日期，当前阻断后续处理

### Example C: 非订单文档

1. 调用 `manage_document_order(action="preview", document_id=18)`
2. 结果显示文档类型不是 `purchase_order`
3. 不建单
4. 告知: 当前文档先停留在 documents 审核态，等待后续扩展流程

## 不要做的事

- 不要因为用户想快一点就跳过验证
- 不要在缺关键字段时默认强制建单
- 不要把不确定字段写成确定值
- 不要假装已经验证了当前 Tool 没暴露出来的信息

$ARGUMENTS
