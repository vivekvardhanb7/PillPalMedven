"""Seed or update medassist_inventory table in Supabase via PostgREST."""

import json
import os
import sys
import urllib.request
from urllib.error import HTTPError
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SERVICE_ROLE_KEY:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured in .env")
    sys.exit(1)

CATALOG_PATH = os.getenv("PRODUCT_CATALOG_PATH", "instance/product_catalog.json")


def load_products_for_inventory():
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        products = json.load(f)

    rows = []
    for p in products:
        inv_id = p.get("inventory_product_id") or f"INV-{p['product_id']}"
        rows.append(
            {
                "inventory_product_id": inv_id,
                "catalog_product_id": p.get("product_id"),
                "product_name": p.get("name"),
                "quantity": 50,
                "active_ingredients": ", ".join(p.get("active_ingredients") or []) if p.get("active_ingredients") else None,
                "strength": f"{p.get('strength') or ''} {p.get('strength_unit') or ''}".strip() or None,
                "formulation": p.get("formulation"),
                "route": p.get("route"),
                "manufacturer": p.get("manufacturer"),
                "contraindications": "; ".join(p.get("contraindications") or []) if p.get("contraindications") else None,
                "precautions": "; ".join(p.get("precautions") or []) if p.get("precautions") else None,
                "usage_instructions": p.get("usage_instructions"),
                "therapy_group": p.get("therapy_group"),
            }
        )
    return rows


def seed_supabase_inventory():
    rows = load_products_for_inventory()
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/medassist_inventory"

    headers = {
        "apikey": SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    if not SERVICE_ROLE_KEY.startswith("sb_"):
        headers["Authorization"] = f"Bearer {SERVICE_ROLE_KEY}"

    data = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            print(f"Successfully seeded {len(rows)} products into medassist_inventory (HTTP {resp.status}).")
            return True
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 404:
            print("Table 'public.medassist_inventory' does not exist in Supabase yet.")
            print("Please run the SQL script in 'supabase/medassist_inventory.sql' in the Supabase SQL Editor first.")
        else:
            print(f"HTTPError {e.code}: {body}")
        return False
    except Exception as e:
        print(f"Connection error: {e}")
        return False


if __name__ == "__main__":
    seed_supabase_inventory()
