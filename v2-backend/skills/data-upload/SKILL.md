---
name: data-upload
description: 上传产品报价单/价格表到数据库（解析→准备→确认→执行→回滚）
---

# 数据上传流程

## 主流程（推荐）

### Step 1: 解析文件
`parse_file` — 自动识别列映射、创建暂存数据。

### Step 2: 确认必填信息
在 prepare_upload 之前确认：
- 国家、港口、供应商、生效日期
- 如有缺失引用数据，用 `create_references` 创建

### Step 3: 一键准备 ⭐ 主入口
`prepare_upload(batch_id)` — 自动执行: 匹配验证 + 数据审计 + 预览。返回审查卡片。
- prepare_upload 返回卡片后**等待用户确认**，不要主动执行下一步

### Step 4: 执行
用户确认后 `execute_upload(batch_id)`。

### Step 5: 回滚（如需）
`rollback_batch(batch_id)` — 发现导入错误时回滚整批。

## 高级用法（仅在 prepare_upload 失败时手动使用）

以下工具是 prepare_upload 的内部步骤，正常情况不需要单独调用：
- `analyze_columns` — 检测未映射列是否包含 supplier/country/port
- `resolve_and_validate` — 手动触发置信度匹配
- `audit_data` — 手动触发数据质量审计
- `preview_changes` — 手动触发预览

## 规则
- 简短回复，不要重复卡片已展示的信息
- 优先用 `prepare_upload` 而非逐步调用

$ARGUMENTS
