---
name: data-upload
description: 上传产品报价单/价格表到数据库（含列分析、验证、审计、回滚）
---

## 产品数据上传流程

### Step 1: 解析文件
调用 `parse_file` — 自动映射列、创建暂存数据。

### Step 2: 分析未映射列（关键！）
调用 `analyze_columns` — 交叉比对未映射列与数据库参考表。
- 检查是否有列包含 supplier_id、country_id、port_id
- 如果数据中包含多个供应商，需要告知用户
- 这一步可以防止把 country_id 误认为 supplier_id

### Step 3: 确认必填信息
在调用 prepare_upload 之前确认：
- **国家**（country_name）
- **港口**（port_name）
- **供应商**（supplier_name）— 结合 analyze_columns 发现
- **生效日期**（effective_from / effective_to）

### Step 4: 一键准备
调用 `prepare_upload` — 验证+审计+预览，返回审查卡片。
如有缺失引用数据，用 `create_references` 创建后重新调用。

### Step 5: 执行
用户确认后调用 `execute_upload`，支持排除指定行号。

### Step 6: 回滚（如需）
发现导入错误时，调用 `rollback_batch(batch_id=...)` 回滚。

$ARGUMENTS
