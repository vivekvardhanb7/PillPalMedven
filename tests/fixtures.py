from datetime import date

from src.catalog import ClinicalStatus, PatientCheckRule, ProductRecord, VendingStatus
from src.recommendations import CheckOutcome, MedicineCheck


def synthetic_approved_product(product_id: str = "SYNTHETIC-01") -> ProductRecord:
    return ProductRecord(
        product_id=product_id,
        name=f"{product_id} synthetic test product",
        category="synthetic test fixture",
        broad_scope="isolated evaluator tests only",
        evidence_level="synthetic",
        source_ids=["SYNTHETIC-TEST-EVIDENCE"],
        source_versions={"SYNTHETIC-TEST-EVIDENCE": "synthetic-v1"},
        source_check_status="identity_and_broad_scope_checked",
        manufacturer="Synthetic fixture only",
        active_ingredients=["synthetic"],
        strength="synthetic",
        strength_unit="synthetic",
        formulation="synthetic",
        route="synthetic",
        contraindications=["synthetic test contraindication data"],
        precautions=["synthetic test precaution data"],
        interaction_reference_ids=["SYNTHETIC-TEST-EVIDENCE"],
        usage_instructions="Synthetic instructions for isolated tests only.",
        inventory_product_id=f"TEST-{product_id}",
        therapy_group="synthetic-alternative-group",
        catalog_status="active",
        exact_stock_sku_confirmed=True,
        team_confirmed=True,
        clinical_status=ClinicalStatus.APPROVED,
        vending_eligibility_status=VendingStatus.ELIGIBLE,
        patient_eligibility_status="eligible",
        required_check_ids=[
            "contraindications",
            "interactions",
            "duplicate_ingredients",
        ],
        patient_check_rules=[
            PatientCheckRule(
                check_id=check_id,
                fact_id=fact_id,
                reviewed_complete=True,
                source_id="SYNTHETIC-TEST-EVIDENCE",
                source_version="synthetic-v1",
            )
            for check_id, fact_id in (
                ("contraindications", "allergies"),
                ("interactions", "current_medications"),
                ("duplicate_ingredients", "current_medications"),
            )
        ],
        reviewed_by="synthetic test reviewer",
        approval_date=date(2026, 1, 1),
        synthetic=True,
    )


def passing_synthetic_checks(
    product_id: str,
) -> list[MedicineCheck]:
    return [
        MedicineCheck(
            check_id=check_id,
            outcome=CheckOutcome.PASS,
            reason_code="SYNTHETIC_TEST_PASS",
            source_ids=["SYNTHETIC-TEST-EVIDENCE"],
            source_versions={"SYNTHETIC-TEST-EVIDENCE": "synthetic-v1"},
        )
        for check_id in (
            "contraindications",
            "interactions",
            "duplicate_ingredients",
        )
    ]
