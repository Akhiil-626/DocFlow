import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.config import settings

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


@dataclass
class Issue:
    code: str
    severity: Literal["error", "warning"]
    field: str | None
    message: str


@dataclass
class ValidationContext:
    today: date
    tolerance: Decimal
    max_invoice_age_days: int
    allowed_tax_rates: list[Decimal]
    allowed_gst_state_codes: list[str]
    warnings_route_to_review: bool = True

    @classmethod
    def from_settings(cls, today: date | None = None) -> "ValidationContext":
        return cls(
            today=today or date.today(),
            tolerance=settings.VALIDATION_TOLERANCE,
            max_invoice_age_days=settings.VALIDATION_MAX_INVOICE_AGE_DAYS,
            allowed_tax_rates=settings.VALIDATION_ALLOWED_TAX_RATES,
            allowed_gst_state_codes=settings.VALIDATION_ALLOWED_GST_STATE_CODES,
            warnings_route_to_review=settings.VALIDATION_WARNINGS_ROUTE_TO_REVIEW,
        )


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _parse_date(date_val: Any) -> date | None:
    if isinstance(date_val, date) and not isinstance(date_val, datetime):
        return date_val
    if isinstance(date_val, datetime):
        return date_val.date()
    if not date_val or not isinstance(date_val, str):
        return None

    date_str = date_val.strip()
    # Try ISO format YYYY-MM-DD
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        pass

    # Try common formats
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def validate_extraction(
    extraction: dict[str, Any],
    context: ValidationContext | None = None,
) -> list[Issue]:
    """Pure validation function for extracted invoice data.

    Returns a list of deterministic validation issues with stable codes.
    No database or network calls are performed.
    """
    ctx = context or ValidationContext.from_settings()
    issues: list[Issue] = []

    # 1. Missing Vendor Name
    vendor_name = extraction.get("vendor_name")
    if not vendor_name or not str(vendor_name).strip():
        issues.append(
            Issue(
                code="MISSING_VENDOR_NAME",
                severity="error",
                field="vendor_name",
                message="Vendor name is missing or empty",
            )
        )

    # 2. Missing Invoice Number
    invoice_number = extraction.get("invoice_number")
    if not invoice_number or not str(invoice_number).strip():
        issues.append(
            Issue(
                code="MISSING_INVOICE_NUMBER",
                severity="error",
                field="invoice_number",
                message="Invoice number is missing or empty",
            )
        )

    # 3. Line Items Check & Amount Mismatches
    line_items = extraction.get("line_items") or []
    if not line_items:
        issues.append(
            Issue(
                code="NO_LINE_ITEMS",
                severity="error",
                field="line_items",
                message="Invoice must contain at least one line item",
            )
        )

    calculated_line_items_sum = Decimal("0")
    for idx, item in enumerate(line_items):
        desc = item.get("description", "")
        qty = _to_decimal(item.get("quantity"))
        unit_price = _to_decimal(item.get("unit_price"))
        amount = _to_decimal(item.get("amount"))

        calculated_line_items_sum += amount

        # Negative check on line item
        if qty < 0:
            issues.append(
                Issue(
                    code="NEGATIVE_AMOUNT",
                    severity="error",
                    field=f"line_items[{idx}].quantity",
                    message=f"Line item {idx + 1} quantity cannot be negative ({qty})",
                )
            )
        if unit_price < 0:
            issues.append(
                Issue(
                    code="NEGATIVE_AMOUNT",
                    severity="error",
                    field=f"line_items[{idx}].unit_price",
                    message=f"Line item {idx + 1} unit price cannot be negative ({unit_price})",
                )
            )
        if amount < 0:
            issues.append(
                Issue(
                    code="NEGATIVE_AMOUNT",
                    severity="error",
                    field=f"line_items[{idx}].amount",
                    message=f"Line item {idx + 1} amount cannot be negative ({amount})",
                )
            )

        # Line item: quantity * unit_price must equal amount within tolerance
        expected_amount = qty * unit_price
        diff = abs(expected_amount - amount)
        if diff > ctx.tolerance:
            issues.append(
                Issue(
                    code="LINE_ITEM_AMOUNT_MISMATCH",
                    severity="error",
                    field=f"line_items[{idx}].amount",
                    message=(
                        f"Line item {idx + 1} ({desc or 'Item'}) amount mismatch: "
                        f"{qty} * {unit_price} = {expected_amount:.2f}, but stated amount is {amount:.2f} "
                        f"(difference: {diff:.2f} > tolerance {ctx.tolerance})"
                    ),
                )
            )

    # 4. Header Amounts & Negatives
    subtotal = _to_decimal(extraction.get("subtotal"))
    cgst = _to_decimal(extraction.get("cgst"))
    sgst = _to_decimal(extraction.get("sgst"))
    igst = _to_decimal(extraction.get("igst"))
    total = _to_decimal(extraction.get("total"))

    for f_name, f_val in [
        ("subtotal", subtotal),
        ("cgst", cgst),
        ("sgst", sgst),
        ("igst", igst),
        ("total", total),
    ]:
        if f_val < 0:
            issues.append(
                Issue(
                    code="NEGATIVE_AMOUNT",
                    severity="error",
                    field=f_name,
                    message=f"Invoice {f_name} cannot be negative ({f_val})",
                )
            )

    # 5. Sum of Line Items vs Subtotal
    if line_items:
        diff_subtotal = abs(calculated_line_items_sum - subtotal)
        if diff_subtotal > ctx.tolerance:
            issues.append(
                Issue(
                    code="LINE_ITEMS_SUM_MISMATCH",
                    severity="error",
                    field="subtotal",
                    message=(
                        f"Sum of line item amounts ({calculated_line_items_sum:.2f}) does not match "
                        f"subtotal ({subtotal:.2f}) within tolerance {ctx.tolerance}"
                    ),
                )
            )

    # 6. Subtotal + Taxes vs Total
    calculated_total = subtotal + cgst + sgst + igst
    diff_total = abs(calculated_total - total)
    if diff_total > ctx.tolerance:
        issues.append(
            Issue(
                code="TOTAL_MISMATCH",
                severity="error",
                field="total",
                message=(
                    f"Subtotal ({subtotal:.2f}) + CGST ({cgst:.2f}) + SGST ({sgst:.2f}) + "
                    f"IGST ({igst:.2f}) = {calculated_total:.2f}, but total is {total:.2f} "
                    f"(difference: {diff_total:.2f} > tolerance {ctx.tolerance})"
                ),
            )
        )

    # 7. Tax Type Conflict: IGST cannot be combined with CGST/SGST
    if igst > ctx.tolerance and (cgst > ctx.tolerance or sgst > ctx.tolerance):
        issues.append(
            Issue(
                code="TAX_TYPE_CONFLICT",
                severity="error",
                field="igst",
                message=(
                    f"Inter-state IGST ({igst:.2f}) cannot be combined with "
                    f"intra-state CGST ({cgst:.2f}) or SGST ({sgst:.2f})"
                ),
            )
        )

    # 8. Vendor GSTIN Validation
    vendor_gstin = extraction.get("vendor_gstin")
    if vendor_gstin is None or not str(vendor_gstin).strip():
        # Warning: vendor_gstin missing
        issues.append(
            Issue(
                code="MISSING_GSTIN",
                severity="warning",
                field="vendor_gstin",
                message="Vendor GSTIN is missing",
            )
        )
    else:
        gstin_str = str(vendor_gstin).strip()
        is_valid = True
        err_msg = ""
        if len(gstin_str) != 15:
            is_valid = False
            err_msg = f"GSTIN must be exactly 15 characters (got {len(gstin_str)})"
        elif not GSTIN_REGEX.match(gstin_str):
            is_valid = False
            err_msg = "GSTIN does not match official format ^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
        else:
            state_code = gstin_str[:2]
            if state_code not in ctx.allowed_gst_state_codes:
                is_valid = False
                err_msg = f"GSTIN state code '{state_code}' is not a valid Indian state code"

        if not is_valid:
            issues.append(
                Issue(
                    code="INVALID_GSTIN",
                    severity="error",
                    field="vendor_gstin",
                    message=f"Invalid vendor GSTIN '{gstin_str}': {err_msg}",
                )
            )

    # 9. Invoice Date Validation (Future date & Age)
    raw_date = extraction.get("invoice_date")
    parsed_date = _parse_date(raw_date)
    if parsed_date is not None:
        if parsed_date > ctx.today:
            issues.append(
                Issue(
                    code="FUTURE_INVOICE_DATE",
                    severity="error",
                    field="invoice_date",
                    message=f"Invoice date {parsed_date} is in the future (today is {ctx.today})",
                )
            )
        else:
            age_days = (ctx.today - parsed_date).days
            if age_days > ctx.max_invoice_age_days:
                issues.append(
                    Issue(
                        code="OLD_INVOICE_DATE",
                        severity="warning",
                        field="invoice_date",
                        message=(
                            f"Invoice date {parsed_date} is {age_days} days old, "
                            f"exceeding max age of {ctx.max_invoice_age_days} days"
                        ),
                    )
                )

    # 10. CGST and SGST Mismatch Warning
    # For intra-state supply, CGST and SGST should match
    if cgst > 0 or sgst > 0:
        if abs(cgst - sgst) > ctx.tolerance:
            issues.append(
                Issue(
                    code="CGST_SGST_MISMATCH",
                    severity="warning",
                    field="cgst",
                    message=f"CGST ({cgst:.2f}) and SGST ({sgst:.2f}) amounts differ by more than tolerance",
                )
            )

    # 11. Unexpected Tax Rate Warning
    total_tax = cgst + sgst + igst
    if subtotal > 0 and total_tax > 0:
        calculated_rate = total_tax / subtotal
        # Check if rate matches any allowed rate within a small tolerance (0.005)
        rate_matches = any(abs(calculated_rate - allowed) <= Decimal("0.005") for allowed in ctx.allowed_tax_rates)
        if not rate_matches:
            rate_pct = float(calculated_rate * 100)
            issues.append(
                Issue(
                    code="UNEXPECTED_TAX_RATE",
                    severity="warning",
                    field="tax_rate",
                    message=(
                        f"Calculated effective tax rate {rate_pct:.1f}% ({total_tax} / {subtotal}) "
                        f"is not among configured allowed tax rates"
                    ),
                )
            )

    return issues
