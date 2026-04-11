# Process Document Skill 研究记录

> 日期: 2026-04-10
> 目标: 先沉淀“如何写一个好的 Skill”，再据此改写 `process-document`

---

## 1. 这份文档回答什么问题

这份文档只回答 4 个问题:

1. 一个好的 Skill 核心是什么
2. `curise_agent` 当前文档处理 Skill 缺什么
3. 如果要把文档变成订单，当前最小字段集是什么
4. 新 Skill 应该先写什么、后写什么

这份文档不讨论代码实现细节，只讨论 Skill 设计、字段契约和验证规则。

---

## 2. 外部研究结论

### 2.1 好的 Skill / Playbook / Instruction 有哪些共同点

综合 Claude、Dialogflow、OpenAI、Anthropic 工程文档，结论高度一致:

1. **目标必须单一**
   - 一个 Skill 应聚焦一个明确意图
   - 不要把多个含糊职责塞进一个 Skill

2. **步骤必须顺序化**
   - 不是“做这些事”
   - 而是“先 A，再 B，再验证 C，不满足则暂停”

3. **必须明确 Tool 何时调用**
   - 只写 Tool 名不够
   - 要写“什么条件下调用、调用后看什么结果、结果为空怎么办”

4. **必须定义输出格式**
   - 没有格式约束，模型就会看起来合理但不一致
   - 结构、字段、枚举、空值规则都要写清楚

5. **必须有异常分支**
   - Skill 不能只写 happy path
   - 要明确哪些情况暂停、哪些情况继续、哪些情况要求补充信息

6. **必须有 examples**
   - 只给 schema 不够
   - 复杂 Skill 必须有 happy path / 缺字段 / 异常 path 示例

7. **必须处理空结果**
   - Tool 没有返回数据时，Skill 不能默认“脑补”
   - 必须明确: 不知道就是不知道，暂停并说明原因

8. **必须有验证环**
   - Skill 不是“调 Tool 的列表”
   - Skill 应该在每一步后验证结果是否可信

### 2.2 外部资料来源

- Claude Prompting Best Practices  
  https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Anthropic Advanced Tool Use  
  https://www.anthropic.com/engineering/advanced-tool-use
- Dialogflow CX Playbook Best Practices  
  https://cloud.google.com/dialogflow/cx/docs/concept/playbook/best-practices?authuser=1
- OpenAI Custom GPT Instruction Guidelines  
  https://help.openai.com/es-es/articles/9358033-key-guidelines-for-writing-instructions-for-custom-gpts

---

## 3. 我的结论与心得

### 3.1 一个好的 Skill 核心不在“聪明”，而在“边界清楚”

最重要的不是让模型“自由发挥”，而是让它在关键地方没有歧义:

- 这个 Skill 到底负责什么
- 它依赖哪些 Tool
- 哪些字段是必须的
- 哪些字段可以为空
- 什么情况下不能继续
- 输出必须长什么样

### 3.2 Tool schema 只能保证结构合法，不能保证业务合法

这点非常关键。

就算 Tool 调用参数是合法 JSON，也不代表:

- `delivery_date` 写对了格式
- `currency` 符合业务规范
- `destination_port` 是可用写法
- 产品列表足够可信可以建单

所以 Skill 必须补上三层约束:

1. 字段契约
2. 验证规则
3. 暂停规则

### 3.3 对当前项目最重要的是“不要猜”

当前项目里最容易出问题的不是 Tool 不够，而是模型在缺信息时会倾向于补全。

这个项目不能接受“看起来合理”的订单。

所以 Skill 必须明确:

- 不确定就标记不确定
- 缺字段就暂停
- 不要编造日期、币种、港口、数量、单价

---

## 4. 当前 `curise_agent` 的现实边界

### 4.1 当前文档上传后的主流程

当前系统并不是从一开始就走 Agent + Skill + Tool。

现实主链路是:

1. 文档上传
2. `run_document_pipeline()`
3. `process_document()`
4. `smart_extract()`
5. 保存 `metadata + products`
6. 再进入文档投影 / 建单 / 后续订单处理

也就是说:

- **抽取阶段** 主要还是 pipeline
- **建单后续阶段** 才更像 agent 工作流

### 4.2 当前 `process-document` Skill 的真实职责

当前这个 Skill 最适合做的是:

- 消费已经提取好的 `Document`
- 验证是否足够可信
- 决定是否建单
- 建单后衔接 `process-order`

它**不适合假装自己直接控制底层 PDF 抽取过程**。

---

## 5. 当前系统里“订单信息”的最小字段集

基于当前代码，`Document -> order_payload` 的订单信息字段是:

- `po_number`
- `ship_name`
- `vendor_name`
- `delivery_date`
- `order_date`
- `currency`
- `destination_port`
- `total_amount`
- `source_document_id`
- `source_doc_type`

来源:
- `services/document_order_projection.py`

### 5.1 当前最小关键字段

当前系统明确把以下字段视为关键字段:

- `po_number`
- `ship_name`
- `delivery_date`

如果缺失，当前应进入 review / pause，而不是静默当成完整订单。

### 5.2 建议的字段分层

#### A. 建单阻断字段

- `po_number`
- `ship_name`
- `delivery_date`
- `products` 非空
- `doc_type = purchase_order`

#### B. 建单可选但重要字段

- `vendor_name`
- `currency`
- `destination_port`
- `order_date`
- `total_amount`

#### C. 追踪字段

- `source_document_id`
- `source_doc_type`

---

## 6. 当前系统里“产品列表”的最小字段集

基于当前代码，产品表头是:

- `line_number`
- `product_code`
- `product_name`
- `quantity`
- `unit`
- `unit_price`
- `total_price`

来源:
- `services/document_processor.py`

### 6.1 建议的产品级最小要求

每个产品至少应满足以下之一:

- 有 `product_code`
- 或有 `product_name`

并且:

- `quantity` 应尽量是正数
- `unit` 如果不确定，可以为空，但不能编造
- `unit_price` / `total_price` 如果不确定，可以为空，但不能编造

### 6.2 当前适合用来判断“能否继续”的产品规则

- `products` 数组为空 → 阻断
- 产品行很多但名称/数量大量为空 → 需要复核
- 只有零星产品且明显不完整 → 需要复核

---

## 7. 字段格式策略草案

这里先给出第一版草案，后续可以再细化成正式 canonical schema。

### 7.1 `delivery_date`

- 目标格式: `YYYY-MM-DD`
- 如果源文档是其他日期格式，但含义明确，可在说明里写“应规范为 YYYY-MM-DD”
- 如果日期歧义明显，不要猜，标记为缺失并暂停

### 7.2 `order_date`

- 目标格式: `YYYY-MM-DD`
- 不确定时允许为空

### 7.3 `currency`

- 目标格式: 3 位大写代码
- 例如: `USD`, `EUR`, `JPY`, `CNY`
- 如果源文档是符号或模糊写法，不能自行臆断时，应标记为不确定

### 7.4 `destination_port`

- 当前阶段不要求 Skill 强行把它规范到数据库主键
- 先保留为文档中可辨认的港口文本
- 真正的数据库级解析应由后续匹配阶段处理

### 7.5 `po_number`

- 保留原文主要标识
- 不要随意去掉中划线、前缀、后缀

### 7.6 `ship_name`

- 保留文档中的主船名文本
- 不做主观缩写

### 7.7 `total_amount`

- 如果能可靠转成数字则保留数值含义
- 不能可靠解析时允许为空

---

## 8. 不确定时应该怎么办

这是这次 Skill 设计里最重要的规则:

### 8.1 不确定 ≠ 可以猜

出现以下情况时，不要继续编造:

- 日期不确定
- 币种不明确
- 目的港写法不清楚
- 产品数量明显异常
- 文档类型不确定

### 8.2 标准处理方式

如果不确定:

1. 明确指出不确定字段
2. 说明为什么不确定
3. 判断是否阻断下一步
4. 如果阻断，则暂停

### 8.3 Skill 输出里必须出现的信息

暂停时至少要输出:

- 当前步骤
- 问题类型
- 问题字段
- 是否阻断
- 建议下一步

---

## 9. 新 Skill 应该按什么顺序写

我认为正确顺序是:

1. 读取文档状态
2. 预览订单投影
3. 验证文档类型
4. 验证产品数
5. 验证关键字段
6. 判断是否允许建单
7. 建单
8. 建单后进入订单处理
9. 继续让后续 Skill 处理匹配 / 询价

也就是:

**先验证，再建单；先找问题，再推进。**

---

## 10. 当前版本的能力与限制

### 当前可做

- 判断文档是否存在
- 判断是否为 `purchase_order`
- 判断产品数是否为 0
- 判断是否缺 `po_number / ship_name / delivery_date`
- 决定是否建单
- 建单后进入 `process-order`

### 当前还做不到特别细

在不新增 Tool 的前提下，当前 `process-document` Skill 还**无法**细到这些层面:

- 逐字段读取完整原始 payload JSON
- 在建单前逐字段验证 `currency / destination_port / total_amount`
- 在建单前检查每一行产品的明细格式

这不是 Skill 写不好，而是**当前 Tool 暴露的信息还不够细**。

所以本轮 Skill 应该务实:

- 先把已有信号用好
- 不假装拥有当前没有的验证能力

---

## 11. 最终设计判断

这一轮最合理的 Skill 目标不是“万能文档 Agent”，而是:

**一个带 validation gate 的 document-to-order 决策 Skill。**

它的职责是:

- 接住已经提取好的文档
- 先验证
- 有问题就暂停并解释
- 没问题再建单
- 建单后把后续工作交给订单 Skill

---

## 12. 下一步

基于这份研究，下一步直接改写:

- `v2-backend/skills/process-document/SKILL.md`

改写目标:

- 加入 validation loop
- 加入字段与暂停规则
- 明确只使用当前真实存在的 Tool
- 让它能在当前系统里实际运行，而不是纸面设计
