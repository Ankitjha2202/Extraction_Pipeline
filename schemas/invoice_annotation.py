"""Pydantic schema sent to Mistral as document_annotation_format."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AnnotatedLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = Field(
        None, description="Line item description / product or service name."
    )
    quantity: Optional[str] = Field(
        None, description="Quantity as written on the invoice (string)."
    )
    unitPrice: Optional[str] = Field(
        None, description="Unit price as written on the invoice."
    )
    taxRate: Optional[str] = Field(
        None, description="Tax rate for the line (e.g. 10% or 0.1)."
    )
    taxAmount: Optional[str] = Field(
        None, description="Tax amount for the line."
    )
    lineAmount: Optional[str] = Field(
        None, description="Line total / amount (often excl. or incl. tax as shown)."
    )


class InvoiceAnnotation(BaseModel):
    """Structured invoice fields extracted from the full document."""

    model_config = ConfigDict(extra="forbid")

    invoiceNumber: Optional[str] = Field(
        None, description="Invoice / bill / receipt number."
    )
    invoiceDate: Optional[str] = Field(
        None, description="Invoice issue date as written on the document."
    )
    dueDate: Optional[str] = Field(
        None, description="Payment due date if present."
    )
    supplierName: Optional[str] = Field(
        None, description="Seller / vendor / supplier / merchant name."
    )
    supplierTaxId: Optional[str] = Field(
        None,
        description="Supplier tax ID / VAT / GST / TIN / BRN if present.",
    )
    buyerName: Optional[str] = Field(
        None, description="Buyer / bill-to / customer / client name."
    )
    buyerTaxId: Optional[str] = Field(
        None, description="Buyer tax ID / VAT / GST if present."
    )
    currency: Optional[str] = Field(
        None,
        description="ISO currency code if clear (USD, EUR, SGD, VND, HKD, PHP, etc.), "
        "else the currency symbol or name as written.",
    )
    subtotal: Optional[str] = Field(
        None, description="Subtotal / net amount before tax if present."
    )
    taxAmount: Optional[str] = Field(
        None, description="Total tax / VAT / GST amount if present."
    )
    totalAmount: Optional[str] = Field(
        None, description="Grand total / invoice total amount."
    )
    amountDue: Optional[str] = Field(
        None, description="Amount due / balance due if different from total."
    )
    paymentTerms: Optional[str] = Field(
        None, description="Payment terms text if present (e.g. Net 30)."
    )
    purchaseOrderNumber: Optional[str] = Field(
        None, description="PO / purchase order number if present."
    )
    lineItems: list[AnnotatedLineItem] = Field(
        default_factory=list,
        description="All line items / products / services listed on the invoice.",
    )


DOCUMENT_ANNOTATION_PROMPT = """\
Extract invoice fields from this document into the provided JSON schema.

Rules:
- Use null for fields that are not present or not legible.
- Preserve values as they appear on the document (do not invent values).
- For multilingual invoices, keep original script for names when that is what is printed;
  still fill currency and amounts.
- Handwritten and scanned invoices: extract best-effort; prefer null over guessing.
- currency: prefer a 3-letter ISO code when unambiguous from symbols/context.
- Include every distinct line item you can identify.
"""
