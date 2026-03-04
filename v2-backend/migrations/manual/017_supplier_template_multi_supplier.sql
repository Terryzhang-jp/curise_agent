-- 017: 供应商模板支持多供应商关联
-- supplier_ids JSON 列存储供应商 ID 数组, 如 [1, 2, 3]
-- 保留 supplier_id 列兼容旧数据

ALTER TABLE v2_supplier_templates
ADD COLUMN IF NOT EXISTS supplier_ids JSON;

-- 将旧 supplier_id 数据迁移到 supplier_ids
UPDATE v2_supplier_templates
SET supplier_ids = JSON_ARRAY(supplier_id)
WHERE supplier_id IS NOT NULL AND supplier_ids IS NULL;
