---
name: fulfillment
description: 管理订单履约周期（状态更新、交货验收、发票、付款）
---

## 前置准备

先激活履约工具：
```
tool_search("fulfillment")
```
激活: get_order_fulfillment, update_order_fulfillment, record_delivery_receipt, attach_order_file

## 状态流转
```
pending → inquiry_sent → quoted → confirmed → delivering → delivered → invoiced → paid
```

## 可用操作

| 操作 | 工具 | 说明 |
|------|------|------|
| 查看履约状态 | get_order_fulfillment(order_id) | 当前状态、交货、发票、付款 |
| 更新状态 | update_order_fulfillment(order_id, status) | 按顺序推进 |
| 交货验收 | record_delivery_receipt(order_id, line_items) | 逐产品记录数量 |
| 附加文件 | attach_order_file(order_id, filename) | 上传照片/发票等 |

## 自然语言理解

用户会用日常语言描述，你需要翻译为工具调用：
- "订单已交货" → update_order_fulfillment(status="delivered")
- "土豆只收了500kg" → record_delivery_receipt(部分接收)
- "发票已到" → update_order_fulfillment(status="invoiced")
- "已付款" → update_order_fulfillment(status="paid", payment_amount=...)

## 安全规则
- 执行状态变更前调用 request_confirmation
- 确认后才执行

$ARGUMENTS
