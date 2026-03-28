-- 022: 扩展供应商字段 + 新建仓库配送点表 + 公司配置表
-- 支持询价单模板引擎的完整数据组装

-- ─── 1. 扩展 suppliers 表 ───────────────────────────
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS zip_code VARCHAR(20);
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS fax VARCHAR(50);
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS default_payment_method VARCHAR(100);
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS default_payment_terms VARCHAR(100);

-- ─── 2. 仓库/配送点 ────────────────────────────────
CREATE TABLE IF NOT EXISTS v2_delivery_locations (
    id SERIAL PRIMARY KEY,
    port_id INTEGER REFERENCES ports(id),
    name VARCHAR(200) NOT NULL,
    address TEXT,
    contact_person VARCHAR(100),
    contact_phone VARCHAR(50),
    delivery_notes VARCHAR(200),
    ship_name_label VARCHAR(200),
    is_default BOOLEAN DEFAULT true,
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ─── 3. 公司配置 ────────────────────────────────────
CREATE TABLE IF NOT EXISTS v2_company_config (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    label VARCHAR(100),
    sort_order INTEGER DEFAULT 0,
    updated_by INTEGER,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 初始数据
INSERT INTO v2_company_config (key, value, label, sort_order) VALUES
    ('name', '株式会社メリットトレーディング', '公司名称', 1),
    ('zip_code', '〒900-0003', '邮编', 2),
    ('address', '沖縄県那覇市安謝1-2-21 アーバンウエスト秋桜201', '地址', 3),
    ('tel', '098-917-2295', '电话', 4),
    ('fax', '098-917-2296', '传真', 5),
    ('email', 'cruise.merit@gmail.com', '邮箱', 6),
    ('contact', '邢　080-4311-1145', '担当者', 7)
ON CONFLICT (key) DO NOTHING;

-- ─── 4. 供应商模板加 template_styles 字段 ──────────
ALTER TABLE v2_supplier_templates ADD COLUMN IF NOT EXISTS template_styles JSON;
