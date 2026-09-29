"""Output models matching the assignment JSON schema."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BBox(BaseModel):
    page: int = Field(..., description="1-indexed page number")
    x1: float
    y1: float
    x2: float
    y2: float


class FieldValue(BaseModel):
    value: Optional[str] = None
    bbox: Optional[BBox] = None
    isHumanReviewRequired: bool = False
    reviewReasons: list[str] = Field(default_factory=list)


class LineItem(BaseModel):
    description: FieldValue = Field(default_factory=FieldValue)
    quantity: FieldValue = Field(default_factory=FieldValue)
    unitPrice: FieldValue = Field(default_factory=FieldValue)
    taxRate: FieldValue = Field(default_factory=FieldValue)
    taxAmount: FieldValue = Field(default_factory=FieldValue)
    lineAmount: FieldValue = Field(default_factory=FieldValue)


class InvoiceFields(BaseModel):
    invoiceNumber: FieldValue = Field(default_factory=FieldValue)
    invoiceDate: FieldValue = Field(default_factory=FieldValue)
    dueDate: FieldValue = Field(default_factory=FieldValue)
    supplierName: FieldValue = Field(default_factory=FieldValue)
    supplierTaxId: FieldValue = Field(default_factory=FieldValue)
    buyerName: FieldValue = Field(default_factory=FieldValue)
    buyerTaxId: FieldValue = Field(default_factory=FieldValue)
    currency: FieldValue = Field(default_factory=FieldValue)
    subtotal: FieldValue = Field(default_factory=FieldValue)
    taxAmount: FieldValue = Field(default_factory=FieldValue)
    totalAmount: FieldValue = Field(default_factory=FieldValue)
    amountDue: FieldValue = Field(default_factory=FieldValue)
    paymentTerms: FieldValue = Field(default_factory=FieldValue)
    purchaseOrderNumber: FieldValue = Field(default_factory=FieldValue)


class DocumentResult(BaseModel):
    documentId: str
    invoice: InvoiceFields = Field(default_factory=InvoiceFields)
    lineItems: list[LineItem] = Field(default_factory=list)
    isHumanReviewRequired: bool = False
    reviewReasons: list[str] = Field(default_factory=list)

    def to_assignment_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


MANDATORY_FIELDS = (
    "invoiceNumber",
    "invoiceDate",
    "supplierName",
    "buyerName",
    "currency",
    "totalAmount",
)

HEADER_FIELDS = (
    "invoiceNumber",
    "invoiceDate",
    "dueDate",
    "supplierName",
    "supplierTaxId",
    "buyerName",
    "buyerTaxId",
    "currency",
    "subtotal",
    "taxAmount",
    "totalAmount",
    "amountDue",
    "paymentTerms",
    "purchaseOrderNumber",
)

LINE_ITEM_FIELDS = (
    "description",
    "quantity",
    "unitPrice",
    "taxRate",
    "taxAmount",
    "lineAmount",
)
