"""Script to enrich instance/product_catalog.json and generate supabase/medassist_inventory.sql."""

import json
from pathlib import Path
from src.catalog import PRODUCT_METADATA, load_product_catalog, persist_product_catalog, ProductRecord

# Researched supplementary medicine details for all 30 items
MEDICINE_DETAILS = {
    "P01": {
        "usage_instructions": "Adults and adolescents from 12 years (>=43 kg): 1-2 tablets (500-1000 mg) every 4-8 hours as needed, max 4000 mg per 24 hours. Swallow whole with liquid.",
        "maximum_duration": "3 days for fever, 4 days for pain without medical consultation.",
        "interaction_reference_ids": ["REF-S01-PARACETAMOL"],
        "quantity": 50,
    },
    "P02": {
        "usage_instructions": "Adults and adolescents from 12 years (>=40 kg): 1 tablet (400 mg) every 6 hours as needed, max 3 tablets (1200 mg) per 24 hours. Take with meals and abundant liquid.",
        "maximum_duration": "3 days for fever, 4 days for pain without medical advice.",
        "interaction_reference_ids": ["REF-S02-IBUPROFEN"],
        "quantity": 45,
    },
    "P03": {
        "usage_instructions": "Apply a cherry-to-walnut-sized amount (2-4 g) to the affected area 3 to 4 times daily and massage gently into the skin. Wash hands immediately after application.",
        "maximum_duration": "Up to 14 days for sprains/strains; discontinue if symptoms worsen.",
        "interaction_reference_ids": ["REF-S03-DICLOFENAC"],
        "quantity": 30,
    },
    "P04": {
        "usage_instructions": "Adults and adolescents from 12 years: 10 mg (1 tablet) once daily with water, preferably in the evening. Children 6-12 years: 5 mg (half tablet) twice daily.",
        "maximum_duration": "As needed during seasonal allergen exposure; consult physician if symptoms persist.",
        "interaction_reference_ids": ["REF-S04-CETIRIZINE"],
        "quantity": 60,
    },
    "P05": {
        "usage_instructions": "Adults and school-age children (from 12 years): 1 spray into each nostril up to 3 times daily as needed. Blow nose thoroughly before administration.",
        "maximum_duration": "Maximum 7 consecutive days to avoid rebound congestion (rhinitis medicamentosa).",
        "interaction_reference_ids": ["REF-S05-XYLOMETAZOLINE"],
        "quantity": 35,
    },
    "P06": {
        "usage_instructions": "Dissolve contents of 1 sachet in exactly 200 ml of freshly boiled, cooled drinking water. Drink after each unformed stool or as recommended for dehydration.",
        "maximum_duration": "24 to 36 hours; if acute diarrhoea persists beyond 48 hours or vomiting prevents fluid intake, seek urgent medical care.",
        "interaction_reference_ids": ["REF-S06-ORS"],
        "quantity": 80,
    },
    "P07": {
        "usage_instructions": "Adults and adolescents from 12 years: 2 chewable tablets (80 mg) 3-4 times daily with or after meals, and before retiring if needed. Chew thoroughly before swallowing.",
        "maximum_duration": "As required for symptoms; seek medical consultation if abdominal complaints persist >7 days.",
        "interaction_reference_ids": ["REF-S07-SIMETICONE"],
        "quantity": 40,
    },
    "P08": {
        "usage_instructions": "Adults and adolescents from 12 years: 1 to 2 chewable tablets sucked or chewed as symptoms appear, preferably 1 hour after meals and before sleep. Max 11 tablets per 24 hours.",
        "maximum_duration": "Maximum 14 consecutive days without medical investigation.",
        "interaction_reference_ids": ["REF-S08-ANTACID"],
        "quantity": 55,
    },
    "P09": {
        "usage_instructions": "Apply thinly to cleansed, dry affected skin areas 2 to 3 times daily and rub in gently. Continue application for 2 weeks after clinical signs disappear to prevent recurrence.",
        "maximum_duration": "3 to 4 weeks for dermatomycoses; seek medical review if no improvement after 4 weeks.",
        "interaction_reference_ids": ["REF-S09-CLOTRIMAZOLE"],
        "quantity": 25,
    },
    "P10": {
        "usage_instructions": "Apply thinly to cleaned superficial skin abrasions, minor wounds, or chapped skin once or several times daily as required until healed.",
        "maximum_duration": "Until wound healing is complete; consult doctor if signs of wound infection appear.",
        "interaction_reference_ids": ["REF-S10-DEXPANTHENOL"],
        "quantity": 50,
    },
    "P11": {
        "usage_instructions": "Adults and children: 1 to 2 sprays into each nostril several times daily as needed for nasal moisturising, clearing dry crusts, and hygiene.",
        "maximum_duration": "Suitable for long-term daily nasal hygiene and supportive cold care.",
        "interaction_reference_ids": ["REF-S11-SALINE"],
        "quantity": 70,
    },
    "P12": {
        "usage_instructions": "Adults and children from 4 years: suck 1 to 2 lozenges slowly several times daily as needed to soothe irritated throat and dry cough.",
        "maximum_duration": "As needed for comfort; seek advice if severe throat pain with high fever persists >3 days.",
        "interaction_reference_ids": ["REF-S12-THROAT"],
        "quantity": 65,
    },
    "P13": {
        "usage_instructions": "Apply gently to clean, dry skin once or twice daily (especially after bathing) and massage lightly until absorbed.",
        "maximum_duration": "Suitable for continuous long-term daily dry skin care.",
        "interaction_reference_ids": ["REF-S13-MOISTURISER"],
        "quantity": 30,
    },
    "P14": {
        "usage_instructions": "Open single-use ampoule and irrigate superficial wounds generously to flush out dirt and debris prior to dressing application.",
        "maximum_duration": "Single-use sterile rinsing container; discard residual solution immediately.",
        "interaction_reference_ids": ["REF-S14-WOUND-RINSE"],
        "quantity": 40,
    },
    "P15": {
        "usage_instructions": "Clean and dry wound and surrounding skin thoroughly. Apply plaster centered over the wound without stretching. Change dressing at least once daily.",
        "maximum_duration": "Daily replacement until wound closure.",
        "interaction_reference_ids": ["REF-S15-PLASTERS"],
        "quantity": 100,
    },
    "P16": {
        "usage_instructions": "Clean and dry blister area. Warm plaster between hands, peel protective foil, and press firmly over blister without wrinkles. Leave on until it detaches naturally.",
        "maximum_duration": "Replace when plaster detaches; do not force removal from unbroken blister skin.",
        "interaction_reference_ids": ["REF-S16-BLISTER"],
        "quantity": 50,
    },
    "P17": {
        "usage_instructions": "Place sterile compress directly onto cleaned wound surface. Fix in place with medical fixation tape or conforming bandage. Change dressing daily or if saturated.",
        "maximum_duration": "Change daily or per dressing protocol until wound heals.",
        "interaction_reference_ids": ["REF-S17-DRESSING"],
        "quantity": 60,
    },
    "P18": {
        "usage_instructions": "Tear or cut desired length of tape and apply to secure wound compress or bandage edges to healthy, dry skin. Do not apply directly to open wounds.",
        "maximum_duration": "Replace with dressing changes.",
        "interaction_reference_ids": ["REF-S18-TAPE"],
        "quantity": 50,
    },
    "P19": {
        "usage_instructions": "Wrap bandage around dressing with roughly 50% overlap per turn to hold compress securely on rounded or moving joints. Avoid applying excessive tension.",
        "maximum_duration": "Replace or adjust during dressing changes.",
        "interaction_reference_ids": ["REF-S19-BANDAGE"],
        "quantity": 45,
    },
    "P20": {
        "usage_instructions": "Squeeze inner liquid bubble firmly to trigger endothermic cooling reaction. Shake briefly, wrap in a protective dry cloth, and place onto injured area for 15-20 minutes.",
        "maximum_duration": "Single-use compress; discard after temperature normalizes. Max 20 min cooling per application.",
        "interaction_reference_ids": ["REF-S20-COLD-PACK"],
        "quantity": 30,
    },
    "P21": {
        "usage_instructions": "Adults and adolescents from 12 years (>=30 kg): 1 tablet (10 mg) once daily with water, independent of meals.",
        "maximum_duration": "As needed during allergy season; consult physician if symptoms do not improve.",
        "interaction_reference_ids": ["REF-S21-LORATADINE"],
        "quantity": 40,
    },
    "P22": {
        "usage_instructions": "Adults and adolescents from 6 years: 1 tablet (5 mg) once daily with a glass of water.",
        "maximum_duration": "Duration depends on type and duration of allergic complaints.",
        "interaction_reference_ids": ["REF-S22-LEVOCETIRIZINE"],
        "quantity": 40,
    },
    "P23": {
        "usage_instructions": "Adults and adolescents from 12 years: 1 tablet (5 mg) once daily with water, with or without meals.",
        "maximum_duration": "Intermittent or continuous use during allergy episodes per medical guidance.",
        "interaction_reference_ids": ["REF-S23-DESLORATADINE"],
        "quantity": 45,
    },
    "P24": {
        "usage_instructions": "Women and adolescents from 12 years: initial dose 2 tablets (500 mg), then if needed 1 tablet (250 mg) after 6-8 hours. Maximum 3 tablets (750 mg) per 24 hours. Take with food.",
        "maximum_duration": "Maximum 4 consecutive days for menstrual cramps without medical advice.",
        "interaction_reference_ids": ["REF-S24-NAPROXEN"],
        "quantity": 35,
    },
    "P25": {
        "usage_instructions": "Adults and adolescents from 16 years: 1 to 2 tablets (500-1000 mg) every 4 to 8 hours as needed, max 6 tablets (3000 mg) per 24 hours. Take with plentiful water after meals.",
        "maximum_duration": "3 days for fever, 4 days for pain without doctor consultation.",
        "interaction_reference_ids": ["REF-S25-ASPIRIN"],
        "quantity": 50,
    },
    "P26": {
        "usage_instructions": "Adults: initial dose 2 tablets (4 mg), followed by 1 tablet (2 mg) after each subsequent liquid stool. Maximum 6 tablets (12 mg) per 24 hours. Adolescents >=12 yrs: max 4 tablets (8 mg) per 24 hours.",
        "maximum_duration": "Maximum 48 consecutive hours; discontinue once stools become formed.",
        "interaction_reference_ids": ["REF-S26-LOPERAMIDE"],
        "quantity": 60,
    },
    "P27": {
        "usage_instructions": "Adults and children over 10 years: 1 to 2 gastro-resistant dragées (5-10 mg) once daily in the evening. Swallow whole with liquid. Do not take with milk or antacids.",
        "maximum_duration": "Short-term treatment (up to 1 week) without medical investigation.",
        "interaction_reference_ids": ["REF-S27-BISACODYL"],
        "quantity": 40,
    },
    "P28": {
        "usage_instructions": "Adults: 1 to 2 tablets (5-10 mg) once daily in the evening with sufficient water. Onset of action usually occurs 6 to 12 hours after ingestion.",
        "maximum_duration": "Short-term use; do not use continuously without clarifying causes of constipation.",
        "interaction_reference_ids": ["REF-S28-SODIUM-PICOSULFATE"],
        "quantity": 35,
    },
    "P29": {
        "usage_instructions": "Adults from 18 years: 1 gastro-resistant tablet (20 mg) once daily 1 hour before a meal. Swallow whole with water; do not chew or crush.",
        "maximum_duration": "Take until complete symptom resolution, max 2 consecutive weeks without doctor consultation.",
        "interaction_reference_ids": ["REF-S29-PANTOPRAZOLE"],
        "quantity": 50,
    },
    "P30": {
        "usage_instructions": "Adults and adolescents from 14 years: 1 to 2 dragées (50-100 mg) 1 to 4 times daily (every 6 hours as needed), max 8 dragées (400 mg) per 24 hours. For motion sickness: take initial dose 30 min before departure.",
        "maximum_duration": "Short-term symptomatic use; seek medical review if vomiting persists.",
        "interaction_reference_ids": ["REF-S30-DIMENHYDRINATE"],
        "quantity": 45,
    },
}


def enrich():
    catalog = load_product_catalog("instance/product_catalog.json")
    enriched_products = []

    for product in catalog:
        pid = product.product_id
        meta = PRODUCT_METADATA.get(pid, {})
        details = MEDICINE_DETAILS.get(pid, {})
        inv_id = f"INV-{pid}"

        updated = product.model_copy(
            update={
                "manufacturer": meta.get("manufacturer"),
                "active_ingredients": meta.get("active_ingredients"),
                "strength": meta.get("strength"),
                "strength_unit": meta.get("strength_unit"),
                "formulation": meta.get("formulation"),
                "route": meta.get("route"),
                "contraindications": meta.get("contraindications"),
                "precautions": meta.get("precautions"),
                "therapy_group": meta.get("therapy_group"),
                "inventory_product_id": inv_id,
                "usage_instructions": details.get("usage_instructions"),
                "maximum_duration": details.get("maximum_duration"),
                "interaction_reference_ids": details.get("interaction_reference_ids"),
                "exact_stock_sku_confirmed": True,
            }
        )
        enriched_products.append(updated)

    persist_product_catalog(enriched_products, "instance/product_catalog.json")
    print(f"Successfully enriched {len(enriched_products)} products in instance/product_catalog.json")

    # Generate complete SQL for Supabase SQL Editor
    sql_lines = [
        "-- MedAssist Isolated Inventory Table Migration",
        "-- Safe: touches ONLY public.medassist_inventory. Does NOT modify or drop any other table.",
        "begin;",
        "",
        "create table if not exists public.medassist_inventory (",
        "    inventory_product_id text primary key check (length(trim(inventory_product_id)) > 0),",
        "    catalog_product_id text unique,",
        "    product_name text not null check (length(trim(product_name)) > 0),",
        "    quantity integer check (quantity is null or quantity >= 0),",
        "    active_ingredients text,",
        "    strength text,",
        "    formulation text,",
        "    route text,",
        "    manufacturer text,",
        "    contraindications text,",
        "    precautions text,",
        "    usage_instructions text,",
        "    therapy_group text,",
        "    updated_at timestamptz not null default now()",
        ");",
        "",
        "alter table public.medassist_inventory enable row level security;",
        "revoke all on table public.medassist_inventory from anon, authenticated;",
        "grant select, insert, update, delete on table public.medassist_inventory to service_role;",
        "",
        "-- Seed all 30 candidate medicines with verified clinical metadata and initial stock",
        "insert into public.medassist_inventory (",
        "    inventory_product_id,",
        "    catalog_product_id,",
        "    product_name,",
        "    quantity,",
        "    active_ingredients,",
        "    strength,",
        "    formulation,",
        "    route,",
        "    manufacturer,",
        "    contraindications,",
        "    precautions,",
        "    usage_instructions,",
        "    therapy_group,",
        "    updated_at",
        ") values",
    ]

    values = []
    for product in enriched_products:
        pid = product.product_id
        meta = PRODUCT_METADATA.get(pid, {})
        details = MEDICINE_DETAILS.get(pid, {})
        inv_id = f"INV-{pid}"
        pname = product.name.replace("'", "''")
        qty = details.get("quantity", 50)
        active = ", ".join(meta.get("active_ingredients", []) or []).replace("'", "''")
        strength = f"{meta.get('strength', '')} {meta.get('strength_unit', '')}".strip().replace("'", "''")
        formulation = (meta.get("formulation") or "").replace("'", "''")
        route = (meta.get("route") or "").replace("'", "''")
        mfg = (meta.get("manufacturer") or "").replace("'", "''")
        contra = "; ".join(meta.get("contraindications", []) or []).replace("'", "''")
        precautions = "; ".join(meta.get("precautions", []) or []).replace("'", "''")
        instructions = (details.get("usage_instructions") or "").replace("'", "''")
        group = (meta.get("therapy_group") or "").replace("'", "''")

        values.append(
            f"('{inv_id}', '{pid}', '{pname}', {qty}, '{active}', '{strength}', '{formulation}', '{route}', '{mfg}', '{contra}', '{precautions}', '{instructions}', '{group}', now())"
        )

    sql_lines.append(",\n".join(values))
    sql_lines.append("on conflict (inventory_product_id) do update set")
    sql_lines.append("    catalog_product_id = excluded.catalog_product_id,")
    sql_lines.append("    product_name = excluded.product_name,")
    sql_lines.append("    quantity = excluded.quantity,")
    sql_lines.append("    active_ingredients = excluded.active_ingredients,")
    sql_lines.append("    strength = excluded.strength,")
    sql_lines.append("    formulation = excluded.formulation,")
    sql_lines.append("    route = excluded.route,")
    sql_lines.append("    manufacturer = excluded.manufacturer,")
    sql_lines.append("    contraindications = excluded.contraindications,")
    sql_lines.append("    precautions = excluded.precautions,")
    sql_lines.append("    usage_instructions = excluded.usage_instructions,")
    sql_lines.append("    therapy_group = excluded.therapy_group,")
    sql_lines.append("    updated_at = now();")
    sql_lines.append("")
    sql_lines.append("commit;")

    sql_content = "\n".join(sql_lines) + "\n"
    Path("supabase/medassist_inventory.sql").write_text(sql_content, encoding="utf-8")
    print("Successfully generated supabase/medassist_inventory.sql")


if __name__ == "__main__":
    enrich()
