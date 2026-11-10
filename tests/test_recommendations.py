import unittest

from app import create_app
from src.catalog import (
    ClinicalStatus,
    activate_all_pending,
    activate_product,
    load_candidate_catalog,
)
from src.config import AppConfig
from src.recommendations import (
    CheckOutcome,
    MedicineCheck,
    catalog_record_missing_fields,
    catalog_record_ready,
    evaluate_options,
)
from src.session_store import InMemorySessionStore
from tests.fixtures import passing_synthetic_checks, synthetic_approved_product


class RecommendationTests(unittest.TestCase):
    def test_candidate_catalog_is_thirty_pending_unapproved_entries(self):
        catalog = load_candidate_catalog()

        self.assertEqual(len(catalog), 30)
        self.assertEqual(len({product.product_id for product in catalog}), 30)
        self.assertTrue(all(product.catalog_status == "candidate" for product in catalog))
        self.assertTrue(all(not product.team_confirmed for product in catalog))
        self.assertTrue(all(not product.exact_stock_sku_confirmed for product in catalog))
        expected_missing_fields = {
            "active_ingredients",
            "approval_date",
            "catalog_status",
            "clinical_status",
            "contraindications",
            "exact_stock_sku_confirmed",
            "formulation",
            "interaction_reference_ids",
            "inventory_product_id",
            "manufacturer",
            "patient_check_rules",
            "precautions",
            "required_check_ids",
            "reviewed_by",
            "route",
            "source_versions",
            "strength",
            "strength_unit",
            "team_confirmed",
            "therapy_group",
            "usage_instructions",
            "vending_eligibility_status",
        }
        self.assertEqual(
            {tuple(catalog_record_missing_fields(product)) for product in catalog},
            {tuple(sorted(expected_missing_fields))},
        )

    def test_enabled_api_reports_pending_catalog_without_inventing_products(self):
        client = create_app(
            InMemorySessionStore(),
            config=AppConfig(),
            candidate_catalog=load_candidate_catalog(),
        ).test_client()
        health = client.get("/health/ready").get_json()
        session = client.post("/api/sessions").get_json()
        response = client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={
                "session_id": session["session_id"],
                "request_id": "f8cbbab6-f577-40d1-ae8f-91d3408c9f3c",
                "session_revision": 0,
                "language": "en",
                "message": "What medicine should I take?",
            },
        )

        self.assertTrue(health["recommendations_enabled"])
        self.assertTrue(health["catalog_data_pending"])
        self.assertEqual(health["candidate_product_count"], 30)
        body = response.get_json()
        self.assertEqual(body["action"], "ASK_QUESTION")
        self.assertEqual(body["pending_question_ids"], ["symptoms"])
        self.assertTrue(body["recommendations_enabled"])
        self.assertEqual(body["options"], [])

    def test_isolated_approved_synthetic_product_reaches_medicine_option(self):
        product = synthetic_approved_product()

        decision = evaluate_options(
            [product],
            {product.product_id: passing_synthetic_checks(product.product_id)},
            {product.inventory_product_id: True},
            permitted_product_ids={product.product_id},
            allow_synthetic=True,
        )

        self.assertEqual(decision.action, "MEDICINE_OPTION")
        self.assertEqual(decision.options[0].product_id, product.product_id)
        self.assertEqual(decision.options[0].availability, "available")

    def test_synthetic_product_is_blocked_outside_explicit_test_mode(self):
        product = synthetic_approved_product()

        decision = evaluate_options(
            [product],
            {product.product_id: passing_synthetic_checks(product.product_id)},
            {product.inventory_product_id: True},
            permitted_product_ids={product.product_id},
        )

        self.assertEqual(decision.action, "PHARMACIST_REFERRAL")
        self.assertIn("SYNTHETIC_PRODUCT_BLOCKED", decision.reason_codes)

    def test_contraindication_failure_excludes_product_regardless_of_stock(self):
        product = synthetic_approved_product()
        checks = passing_synthetic_checks(product.product_id)
        checks[0] = checks[0].model_copy(
            update={"outcome": CheckOutcome.FAIL, "reason_code": "CONTRAINDICATED"}
        )

        decision = evaluate_options(
            [product],
            {product.product_id: checks},
            {product.inventory_product_id: True},
            permitted_product_ids={product.product_id},
            allow_synthetic=True,
        )

        self.assertEqual(decision.action, "PHARMACIST_REFERRAL")
        self.assertEqual(decision.options, [])
        self.assertIn(
            "CHECK_FAILED:contraindications",
            decision.reason_codes,
        )

    def test_out_of_stock_eligible_option_is_not_replaced(self):
        suitable = synthetic_approved_product("SYNTHETIC-SUITABLE")
        unsuitable = synthetic_approved_product("SYNTHETIC-UNSUITABLE")
        checks = {
            suitable.product_id: passing_synthetic_checks(suitable.product_id),
            unsuitable.product_id: passing_synthetic_checks(unsuitable.product_id),
        }
        checks[unsuitable.product_id][0] = checks[unsuitable.product_id][0].model_copy(
            update={"outcome": CheckOutcome.FAIL, "reason_code": "CONTRAINDICATED"}
        )

        decision = evaluate_options(
            [suitable, unsuitable],
            checks,
            {
                suitable.inventory_product_id: False,
                unsuitable.inventory_product_id: True,
            },
            permitted_product_ids={suitable.product_id, unsuitable.product_id},
            allow_synthetic=True,
        )

        self.assertEqual(decision.action, "MEDICINE_OPTION")
        self.assertEqual([option.product_id for option in decision.options], [suitable.product_id])
        self.assertEqual(decision.options[0].availability, "unavailable")

    def test_missing_check_is_indeterminate_and_blocks_only_that_product(self):
        incomplete = synthetic_approved_product("SYNTHETIC-INCOMPLETE")
        complete = synthetic_approved_product("SYNTHETIC-COMPLETE")
        checks = {
            incomplete.product_id: passing_synthetic_checks(incomplete.product_id)[:-1],
            complete.product_id: passing_synthetic_checks(complete.product_id),
        }

        decision = evaluate_options(
            [incomplete, complete],
            checks,
            {
                incomplete.inventory_product_id: True,
                complete.inventory_product_id: None,
            },
            permitted_product_ids={incomplete.product_id, complete.product_id},
            allow_synthetic=True,
        )

        self.assertEqual(decision.action, "MEDICINE_OPTION")
        self.assertEqual([option.product_id for option in decision.options], [complete.product_id])
        self.assertEqual(decision.options[0].availability, "unknown")

    def test_same_therapy_alternatives_require_pharmacist_selection(self):
        first = synthetic_approved_product("SYNTHETIC-ALTERNATIVE-1")
        second = synthetic_approved_product("SYNTHETIC-ALTERNATIVE-2")
        checks = {
            first.product_id: passing_synthetic_checks(first.product_id),
            second.product_id: passing_synthetic_checks(second.product_id),
        }

        decision = evaluate_options(
            [first, second],
            checks,
            {
                first.inventory_product_id: True,
                second.inventory_product_id: True,
            },
            permitted_product_ids={first.product_id, second.product_id},
            allow_synthetic=True,
        )

        self.assertEqual(decision.action, "PHARMACIST_REFERRAL")
        self.assertEqual(
            decision.reason_codes,
            ["ALTERNATIVE_SELECTION_REQUIRED"],
        )
        self.assertEqual(decision.options, [])

    def test_check_with_stale_source_version_blocks_product(self):
        product = synthetic_approved_product()
        checks = passing_synthetic_checks(product.product_id)
        checks[0] = checks[0].model_copy(
            update={"source_versions": {"SYNTHETIC-TEST-EVIDENCE": "old-version"}}
        )

        decision = evaluate_options(
            [product],
            {product.product_id: checks},
            {product.inventory_product_id: True},
            permitted_product_ids={product.product_id},
            allow_synthetic=True,
        )

        self.assertEqual(decision.action, "PHARMACIST_REFERRAL")
        self.assertIn(
            "CHECK_EVIDENCE_INVALID:contraindications",
            decision.reason_codes,
        )
        self.assertEqual(decision.options, [])

    def test_non_permitted_products_are_not_considered(self):
        product = synthetic_approved_product()

        decision = evaluate_options(
            [product],
            {product.product_id: passing_synthetic_checks(product.product_id)},
            {product.inventory_product_id: True},
            permitted_product_ids=set(),
            allow_synthetic=True,
        )

        self.assertEqual(decision.action, "UNSUPPORTED")
        self.assertEqual(decision.reason_codes, ["CATALOG_DATA_PENDING"])

    def test_activation_cannot_create_clinical_approval(self):
        catalog = load_candidate_catalog()
        pending_p01 = catalog[0]
        self.assertEqual(pending_p01.clinical_status, ClinicalStatus.PENDING)

        with self.assertRaisesRegex(ValueError, "verified review"):
            activate_product(pending_p01)
        self.assertEqual(pending_p01.clinical_status, ClinicalStatus.PENDING)
        self.assertFalse(catalog_record_ready(pending_p01))

    def test_bulk_activation_cannot_create_clinical_approvals(self):
        catalog = load_candidate_catalog()
        self.assertTrue(all(p.clinical_status == ClinicalStatus.PENDING for p in catalog))

        with self.assertRaisesRegex(ValueError, "verified review"):
            activate_all_pending(catalog)
        self.assertEqual(len(catalog), 30)
        self.assertTrue(all(p.clinical_status == ClinicalStatus.PENDING for p in catalog))
        self.assertTrue(all(not catalog_record_ready(p) for p in catalog))

    def test_demo_approval_is_rejected_by_real_recommendation_path(self):
        product = synthetic_approved_product()

        decision = evaluate_options(
            [product],
            {product.product_id: passing_synthetic_checks(product.product_id)},
            {product.inventory_product_id: True},
            permitted_product_ids={product.product_id},
            allow_synthetic=False,
        )

        self.assertEqual(decision.action, "PHARMACIST_REFERRAL")
        self.assertEqual(decision.reason_codes, ["SYNTHETIC_PRODUCT_BLOCKED"])


if __name__ == "__main__":
    unittest.main()
