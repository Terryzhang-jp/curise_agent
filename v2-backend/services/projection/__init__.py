"""Domain projectors (Stage 3).

Each projector takes a universal `ExtractedDocument` and produces a typed
business object. The projection layer is where domain knowledge lives —
"this is what a purchase order looks like", "this is what an invoice looks
like", etc.

Adding a new document type means adding a new projector here, NOT modifying
the extractor.
"""

from services.projection.purchase_order import (
    PurchaseOrderProjection,
    project_purchase_order,
)

__all__ = ["PurchaseOrderProjection", "project_purchase_order"]
