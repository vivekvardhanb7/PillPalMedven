from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.catalog import ClinicalStatus, PatientCheckRule, ProductRecord, VendingStatus
from src.state import ClinicalFact, FactStatus


def catalog_record_ready(
    product: ProductRecord,
    *,
    allow_synthetic: bool = False,
) -> bool:
    if product.synthetic and not allow_synthetic:
        return False
    return not catalog_record_missing_fields(product)


def catalog_record_missing_fields(product: ProductRecord) -> list[str]:
    missing: list[str] = []
    field_values = {
        "catalog_status": product.catalog_status == "active",
        "exact_stock_sku_confirmed": product.exact_stock_sku_confirmed,
        "team_confirmed": product.team_confirmed,
        "clinical_status": product.clinical_status == ClinicalStatus.APPROVED,
        "vending_eligibility_status": (
            product.vending_eligibility_status == VendingStatus.ELIGIBLE
        ),
        "reviewed_by": product.reviewed_by is not None,
        "approval_date": product.approval_date is not None,
        "source_ids": bool(product.source_ids),
        "manufacturer": product.manufacturer is not None,
        "active_ingredients": product.active_ingredients is not None,
        "strength": product.strength is not None,
        "strength_unit": product.strength_unit is not None,
        "formulation": product.formulation is not None,
        "route": product.route is not None,
        "contraindications": product.contraindications is not None,
        "precautions": product.precautions is not None,
        "interaction_reference_ids": product.interaction_reference_ids is not None,
        "usage_instructions": product.usage_instructions is not None,
        "inventory_product_id": product.inventory_product_id is not None,
        "therapy_group": product.therapy_group is not None,
        "required_check_ids": bool(product.required_check_ids),
        "patient_check_rules": bool(product.patient_check_rules),
    }
    missing.extend(name for name, present in field_values.items() if not present)
    if any(source_id not in product.source_versions for source_id in product.source_ids):
        missing.append("source_versions")
    for check_id in product.required_check_ids:
        rules = [rule for rule in product.patient_check_rules if rule.check_id == check_id]
        if not rules or any(not rule.reviewed_complete for rule in rules):
            missing.append(f"patient_check_rules.{check_id}")
        if any(
            rule.source_id not in product.source_versions
            or product.source_versions.get(rule.source_id) != rule.source_version
            for rule in rules
        ):
            missing.append(f"patient_check_rules.{check_id}.source_version")
    return sorted(set(missing))


def evaluate_patient_checks(
    product: ProductRecord,
    facts: dict[str, ClinicalFact],
) -> list[MedicineCheck]:
    checks: list[MedicineCheck] = []
    for check_id in product.required_check_ids:
        rules = [
            rule
            for rule in product.patient_check_rules
            if rule.check_id == check_id
        ]
        if not rules:
            continue
        source_ids = sorted({rule.source_id for rule in rules})
        source_versions = {rule.source_id: rule.source_version for rule in rules}
        evidence_valid = all(
            product.source_versions.get(rule.source_id) == rule.source_version
            for rule in rules
        )
        if not evidence_valid or any(not rule.reviewed_complete for rule in rules):
            outcome = CheckOutcome.INDETERMINATE
            reason_code = "CHECK_RULE_EVIDENCE_INCOMPLETE"
        else:
            rule_outcomes = [
                _evaluate_check_rule(rule, facts.get(rule.fact_id))
                for rule in rules
            ]
            if CheckOutcome.FAIL in rule_outcomes:
                outcome = CheckOutcome.FAIL
                reason_code = f"CHECK_FAILED:{check_id}"
            elif CheckOutcome.INDETERMINATE in rule_outcomes:
                outcome = CheckOutcome.INDETERMINATE
                reason_code = f"CHECK_INDETERMINATE:{check_id}"
            else:
                outcome = CheckOutcome.PASS
                reason_code = f"CHECK_PASSED:{check_id}"
        checks.append(
            MedicineCheck(
                check_id=check_id,
                outcome=outcome,
                reason_code=reason_code,
                source_ids=source_ids,
                source_versions=source_versions,
            )
        )
    return checks


def _evaluate_check_rule(
    rule: PatientCheckRule,
    fact: ClinicalFact | None,
) -> CheckOutcome:
    if fact is None or fact.status in {
        FactStatus.NOT_ASKED,
        FactStatus.UNKNOWN,
        FactStatus.CONFLICTING,
    }:
        return CheckOutcome.INDETERMINATE
    if rule.fact_id == "age":
        if not isinstance(fact.value, int) or isinstance(fact.value, bool):
            return CheckOutcome.INDETERMINATE
        if rule.minimum_age is not None and fact.value < rule.minimum_age:
            return CheckOutcome.FAIL
        if rule.maximum_age is not None and fact.value > rule.maximum_age:
            return CheckOutcome.FAIL
        return CheckOutcome.PASS
    if fact.status == FactStatus.DENIED and fact.value is False:
        return CheckOutcome.PASS
    values = fact.value if isinstance(fact.value, list) else [fact.value]
    normalized_values = [
        str(value).strip().casefold()
        for value in values
        if value is not None and value is not False
    ]
    if not normalized_values:
        return CheckOutcome.INDETERMINATE
    normalized_terms = [term.strip().casefold() for term in rule.match_terms]
    if any(
        term and term in value
        for term in normalized_terms
        for value in normalized_values
    ):
        return CheckOutcome.FAIL
    return CheckOutcome.PASS


class CheckOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


class MedicineCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    outcome: CheckOutcome
    reason_code: str
    source_ids: list[str] = Field(min_length=1)
    source_versions: dict[str, str] = Field(min_length=1)


class OptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    eligibility: Literal["eligible"] = "eligible"
    availability: Literal["available", "unavailable", "unknown"]
    reason_codes: list[str] = Field(default_factory=list)


class RecommendationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "ASK_QUESTION",
        "SELF_CARE",
        "MEDICINE_OPTION",
        "PHARMACIST_REFERRAL",
        "MEDICAL_REFERRAL",
        "EMERGENCY",
        "UNSUPPORTED",
    ]
    reason_codes: list[str] = Field(default_factory=list)
    options: list[OptionResult] = Field(default_factory=list)


def evaluate_options(
    products: list[ProductRecord],
    required_checks: dict[str, list[MedicineCheck]],
    availability: dict[str, bool | None],
    *,
    permitted_product_ids: set[str],
    allow_synthetic: bool = False,
) -> RecommendationDecision:
    """Evaluate only protocol-permitted products; inventory never affects eligibility."""
    eligible: list[OptionResult] = []
    blocked_reason_codes: list[str] = []

    for product in products:
        if product.product_id not in permitted_product_ids:
            continue
        if product.synthetic and not allow_synthetic:
            blocked_reason_codes.append("SYNTHETIC_PRODUCT_BLOCKED")
            continue

        product_reasons: list[str] = []
        if not catalog_record_ready(product, allow_synthetic=allow_synthetic):
            product_reasons.append("CATALOG_APPROVAL_INCOMPLETE")
        if product.patient_eligibility_status != "eligible":
            product_reasons.append("PATIENT_ELIGIBILITY_UNCONFIRMED")

        checks = {
            check.check_id: check
            for check in required_checks.get(product.product_id, [])
        }
        for check_id in product.required_check_ids:
            check = checks.get(check_id)
            if check is None or check.outcome == CheckOutcome.INDETERMINATE:
                product_reasons.append(f"CHECK_INDETERMINATE:{check_id}")
            elif check.outcome == CheckOutcome.FAIL:
                product_reasons.append(f"CHECK_FAILED:{check_id}")
            elif any(
                source_id not in product.source_versions
                or check.source_versions.get(source_id)
                != product.source_versions.get(source_id)
                for source_id in check.source_ids
            ):
                product_reasons.append(f"CHECK_EVIDENCE_INVALID:{check_id}")

        if product_reasons:
            blocked_reason_codes.extend(product_reasons)
            continue

        stock = availability.get(product.inventory_product_id)
        eligible.append(
            OptionResult(
                product_id=product.product_id,
                eligibility="eligible",
                availability=(
                    "available"
                    if stock is True
                    else "unavailable"
                    if stock is False
                    else "unknown"
                ),
                reason_codes=[] if stock is True else ["AVAILABILITY_NOT_CONFIRMED"],
            )
        )

    therapy_groups: dict[str, int] = {}
    for product in products:
        if any(option.product_id == product.product_id for option in eligible):
            therapy_groups[product.therapy_group] = therapy_groups.get(
                product.therapy_group, 0
            ) + 1
    if any(count > 1 for count in therapy_groups.values()):
        return RecommendationDecision(
            action="PHARMACIST_REFERRAL",
            reason_codes=["ALTERNATIVE_SELECTION_REQUIRED"],
        )

    if eligible:
        return RecommendationDecision(action="MEDICINE_OPTION", options=eligible)
    if not any(product.product_id in permitted_product_ids for product in products):
        return RecommendationDecision(
            action="UNSUPPORTED",
            reason_codes=["CATALOG_DATA_PENDING"],
        )
    return RecommendationDecision(
        action="PHARMACIST_REFERRAL",
        reason_codes=sorted(set(blocked_reason_codes)) or ["NO_ELIGIBLE_OPTION"],
    )
