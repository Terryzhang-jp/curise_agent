from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Any


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    is_default_password: bool = False

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    is_default_password: bool = False
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str = ""
    token_type: str = "bearer"
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserCreateRequest(BaseModel):
    email: str
    full_name: str
    role: str = "employee"
    password: str = Field(min_length=8)


class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


# ─── Field Definition ───────────────────────────────────────────

class FieldDefinitionCreate(BaseModel):
    field_key: str
    field_label: str
    field_type: str = "string"
    is_core: bool = False
    is_required: bool = False
    extraction_hint: Optional[str] = None
    sort_order: int = 0


class FieldDefinitionUpdate(BaseModel):
    field_label: Optional[str] = None
    field_type: Optional[str] = None
    is_required: Optional[bool] = None
    extraction_hint: Optional[str] = None
    sort_order: Optional[int] = None


class FieldDefinitionResponse(BaseModel):
    id: int
    schema_id: int
    field_key: str
    field_label: str
    field_type: str
    is_core: bool
    is_required: bool
    extraction_hint: Optional[str] = None
    sort_order: int

    model_config = {"from_attributes": True}


# ─── Field Schema ───────────────────────────────────────────────

class FieldSchemaCreate(BaseModel):
    name: str
    description: Optional[str] = None


class FieldSchemaResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_default: bool
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    definitions: list[FieldDefinitionResponse] = []

    model_config = {"from_attributes": True}


# ─── Order Format Template ──────────────────────────────────────

class OrderFormatTemplateCreate(BaseModel):
    name: str
    file_type: str = "excel"
    header_row: int = 1
    data_start_row: int = 2
    column_mapping: Optional[dict[str, str]] = None
    field_schema_id: Optional[int] = None
    format_fingerprint: Optional[str] = None
    sample_file_url: Optional[str] = None
    layout_prompt: Optional[str] = None
    extracted_fields: Optional[list[dict[str, Any]]] = None
    source_company: Optional[str] = None
    match_keywords: Optional[list[str]] = None
    is_active: bool = True


class OrderFormatTemplateUpdate(BaseModel):
    name: Optional[str] = None
    file_type: Optional[str] = None
    header_row: Optional[int] = None
    data_start_row: Optional[int] = None
    column_mapping: Optional[dict[str, str]] = None
    field_schema_id: Optional[int] = None
    layout_prompt: Optional[str] = None
    extracted_fields: Optional[list[dict[str, Any]]] = None
    source_company: Optional[str] = None
    match_keywords: Optional[list[str]] = None
    is_active: Optional[bool] = None


class OrderFormatTemplateResponse(BaseModel):
    id: int
    name: str
    file_type: str = "excel"
    format_fingerprint: Optional[str] = None
    header_row: int
    data_start_row: int
    column_mapping: Optional[dict[str, str]] = None
    field_schema_id: Optional[int] = None
    sample_file_url: Optional[str] = None
    layout_prompt: Optional[str] = None
    extracted_fields: Optional[list[dict[str, Any]]] = None
    source_company: Optional[str] = None
    match_keywords: Optional[list[str]] = None
    is_active: bool = True
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Supplier Template ──────────────────────────────────────────

class SupplierTemplateCreate(BaseModel):
    supplier_id: Optional[int] = None
    country_id: Optional[int] = None
    template_name: str
    template_file_url: Optional[str] = None
    field_positions: Optional[dict[str, Any]] = None  # {key: {position, data_type, description}} or legacy {key: "A4"}
    has_product_table: bool = True
    product_table_config: Optional[dict[str, Any]] = None


class SupplierTemplateUpdate(BaseModel):
    template_name: Optional[str] = None
    country_id: Optional[int] = None
    template_file_url: Optional[str] = None
    field_positions: Optional[dict[str, Any]] = None
    has_product_table: Optional[bool] = None
    product_table_config: Optional[dict[str, Any]] = None


class SupplierTemplateResponse(BaseModel):
    id: int
    supplier_id: Optional[int] = None
    country_id: Optional[int] = None
    template_name: str
    template_file_url: Optional[str] = None
    field_positions: Optional[dict[str, Any]] = None
    has_product_table: bool
    product_table_config: Optional[dict[str, Any]] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Order ───────────────────────────────────────────────────

class OrderListItem(BaseModel):
    """订单列表项 — 不含 products/match_results 等大字段"""
    id: int
    filename: str
    file_url: Optional[str] = None
    file_type: str
    status: str
    processing_error: Optional[str] = None
    order_metadata: Optional[dict[str, Any]] = None
    product_count: int = 0
    total_amount: Optional[float] = None
    match_statistics: Optional[dict[str, Any]] = None
    has_inquiry: bool = False
    is_reviewed: bool = False
    fulfillment_status: str = "pending"
    template_id: Optional[int] = None
    template_match_method: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OrderDetail(BaseModel):
    """订单详情 — 含全部字段"""
    id: int
    user_id: int
    filename: str
    file_url: Optional[str] = None
    file_type: str
    status: str
    processing_error: Optional[str] = None
    country_id: Optional[int] = None
    port_id: Optional[int] = None
    delivery_date: Optional[str] = None
    extraction_data: Optional[dict[str, Any]] = None
    order_metadata: Optional[dict[str, Any]] = None
    products: Optional[list[dict[str, Any]]] = None
    product_count: int = 0
    total_amount: Optional[float] = None
    match_results: Optional[list[dict[str, Any]]] = None
    match_statistics: Optional[dict[str, Any]] = None
    anomaly_data: Optional[dict[str, Any]] = None
    financial_data: Optional[dict[str, Any]] = None
    inquiry_data: Optional[dict[str, Any]] = None
    is_reviewed: bool = False
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[int] = None
    review_notes: Optional[str] = None
    fulfillment_status: str = "pending"
    delivery_data: Optional[dict[str, Any]] = None
    invoice_number: Optional[str] = None
    invoice_amount: Optional[float] = None
    invoice_date: Optional[str] = None
    payment_amount: Optional[float] = None
    payment_date: Optional[str] = None
    payment_reference: Optional[str] = None
    attachments: list[dict[str, Any]] = []
    fulfillment_notes: Optional[str] = None
    delivery_environment: Optional[dict[str, Any]] = None
    template_id: Optional[int] = None
    template_match_method: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OrderReviewRequest(BaseModel):
    notes: Optional[str] = None


class OrderUpdateRequest(BaseModel):
    order_metadata: Optional[dict[str, Any]] = None
    products: Optional[list[dict[str, Any]]] = None


class OrderRematchRequest(BaseModel):
    pass  # Future: country_id/port_id overrides


# ─── Tool Config ─────────────────────────────────────────────

class ToolConfigResponse(BaseModel):
    id: int
    tool_name: str
    group_name: str
    display_name: str
    description: Optional[str] = None
    is_enabled: bool
    is_builtin: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ToolConfigUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    display_name: Optional[str] = None
    description: Optional[str] = None


# ─── Skill Config ────────────────────────────────────────────

class SkillConfigCreate(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    content: Optional[str] = None


class SkillConfigUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    is_enabled: Optional[bool] = None


class SkillConfigResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    content: Optional[str] = None
    is_builtin: bool
    is_enabled: bool
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════
# Data Management CRUD Schemas
# ═══════════════════════════════════════════════════════════════════


# ─── Country ─────────────────────────────────────────────────────

class CountryCreate(BaseModel):
    name: str
    code: Optional[str] = None
    status: bool = True


class CountryUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    status: Optional[bool] = None


class CountryResponse(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    status: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── Category ────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    status: bool = True


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    status: Optional[bool] = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    status: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── Port ────────────────────────────────────────────────────────

class PortCreate(BaseModel):
    name: str
    code: Optional[str] = None
    country_id: Optional[int] = None
    location: Optional[str] = None
    status: bool = True


class PortUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    country_id: Optional[int] = None
    location: Optional[str] = None
    status: Optional[bool] = None


class PortResponse(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    country_id: Optional[int] = None
    country_name: Optional[str] = None
    location: Optional[str] = None
    status: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── Supplier ────────────────────────────────────────────────────

class SupplierCreate(BaseModel):
    name: str
    country_id: Optional[int] = None
    contact: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    category_ids: list[int] = []
    status: bool = True


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    country_id: Optional[int] = None
    contact: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    category_ids: Optional[list[int]] = None
    status: Optional[bool] = None


class SupplierResponse(BaseModel):
    id: int
    name: str
    country_id: Optional[int] = None
    country_name: Optional[str] = None
    contact: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    categories: list[str] = []
    category_ids: list[int] = []
    status: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── Product ─────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    product_name_en: str
    product_name_jp: Optional[str] = None
    code: Optional[str] = None
    country_id: Optional[int] = None
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None
    port_id: Optional[int] = None
    unit: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    unit_size: Optional[str] = None
    pack_size: Optional[str] = None
    country_of_origin: Optional[str] = None
    brand: Optional[str] = None
    currency: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    status: bool = True


class ProductUpdate(BaseModel):
    product_name_en: Optional[str] = None
    product_name_jp: Optional[str] = None
    code: Optional[str] = None
    country_id: Optional[int] = None
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None
    port_id: Optional[int] = None
    unit: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    unit_size: Optional[str] = None
    pack_size: Optional[str] = None
    country_of_origin: Optional[str] = None
    brand: Optional[str] = None
    currency: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    status: Optional[bool] = None


class ProductResponse(BaseModel):
    id: int
    product_name_en: str
    product_name_jp: Optional[str] = None
    code: Optional[str] = None
    country_id: Optional[int] = None
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None
    port_id: Optional[int] = None
    country_name: Optional[str] = None
    category_name: Optional[str] = None
    supplier_name: Optional[str] = None
    port_name: Optional[str] = None
    unit: Optional[str] = None
    price: Optional[float] = None
    unit_size: Optional[str] = None
    pack_size: Optional[str] = None
    country_of_origin: Optional[str] = None
    brand: Optional[str] = None
    currency: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    status: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
