---
name: data-upload
description: 上传产品报价单/价格表到数据库（解析→分析→验证→执行→回滚）
---

## 前置准备

上传工具在文件附带时自动激活（无需 tool_search）。

## 上传流程

### Step 1: 解析文件
`parse_file` — 自动识别列映射、创建暂存数据。

### Step 2: 分析未映射列（关键！）
`analyze_columns` — 检测是否有列包含 supplier_id、country_id、port_id。
- parse_file 后**必须**立即调用
- 防止误映射

### Step 3: 确认必填信息
在 prepare_upload 之前确认：
- 国家、港口、供应商、生效日期
- 如有缺失引用数据，用 `create_references` 创建

### Step 4: 一键准备
`prepare_upload(...)` — 验证 + 审计 + 预览，返回审查卡片。
- prepare_upload 返回卡片后**等待用户确认**，不要主动执行

### Step 5: 执行
用户确认后 `execute_upload(batch_id)`。

### Step 6: 回滚（如需）
`rollback_batch(batch_id)` — 发现导入错误时回滚。

## 规则
- 简短回复，不要重复卡片已展示的信息
- 不要跳步骤（每步都有依赖）

$ARGUMENTS
