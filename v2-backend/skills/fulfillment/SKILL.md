---
name: fulfillment
description: 管理订单履约周期（状态更新、交货验收、发票、付款）
---

## 履约管理

### 状态流转
```
pending → inquiry_sent → quoted → confirmed → delivering → delivered → invoiced → paid
```

### 可用操作
- **查看/更新履约状态**: 使用 `get_order_fulfillment` 查看、`update_order_fulfillment` 更新
- **记录交货验收**: 逐产品记录接收数量、拒收数量和原因（`record_delivery_receipt`）
- **附加文件**: 上传交货照片、发票扫描件等（`attach_order_file`）
- **记录发票和付款信息**: 通过状态更新记录

### 自然语言理解
用户可能用自然语言描述状态更新，你需要理解意图：
- "订单已交货" → update 状态为 delivered
- "土豆只收了500kg" → record_delivery_receipt 部分接收
- "发票已到" → update 状态为 invoiced
- "已付款" → update 状态为 paid

### 安全规则
- 执行重要操作前调用 `request_confirmation`
- 确认后才执行状态变更

$ARGUMENTS
