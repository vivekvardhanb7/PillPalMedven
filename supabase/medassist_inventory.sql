-- ============================================================================
-- MedAssist Inventory Setup for Supabase
-- SAFE: Touches ONLY public.medassist_inventory. Does NOT modify other tables.
-- ============================================================================

-- 1. CREATE TABLE
create table if not exists public.medassist_inventory (
    inventory_product_id text primary key check (length(trim(inventory_product_id)) > 0),
    catalog_product_id text unique,
    product_name text not null check (length(trim(product_name)) > 0),
    quantity integer check (quantity is null or quantity >= 0),
    active_ingredients text,
    strength text,
    formulation text,
    route text,
    manufacturer text,
    contraindications text,
    precautions text,
    usage_instructions text,
    therapy_group text,
    updated_at timestamptz not null default now()
);

-- 2. ROW LEVEL SECURITY & SERVICE ROLE PERMISSIONS
alter table public.medassist_inventory enable row level security;
revoke all on table public.medassist_inventory from anon, authenticated;
grant select, insert, update, delete on table public.medassist_inventory to service_role;

-- 3. SEED 30 CANDIDATE PRODUCTS
insert into public.medassist_inventory (
    inventory_product_id,
    catalog_product_id,
    product_name,
    quantity,
    active_ingredients,
    strength,
    formulation,
    route,
    manufacturer,
    contraindications,
    precautions,
    usage_instructions,
    therapy_group,
    updated_at
) values
('INV-P01', 'P01', 'Paracetamol tablets; example Paracetamol-ratiopharm 500 mg', 50, 'Paracetamol', '500 mg', 'tablet', 'oral', 'ratiopharm GmbH', 'severe hepatic impairment; paracetamol hypersensitivity', 'do not exceed 4000 mg in 24 hours; avoid concurrent alcohol', 'Adults and adolescents from 12 years (>=43 kg): 1-2 tablets (500-1000 mg) every 4-8 hours as needed, max 4000 mg per 24 hours. Swallow whole with liquid.', 'analgesics-antipyretics', now()),
('INV-P02', 'P02', 'Ibuprofen tablets; example Ibu 400 akut-1 A Pharma', 45, 'Ibuprofen', '400 mg', 'film-coated tablet', 'oral', '1 A Pharma GmbH', 'active peptic ulcer; severe renal failure; NSAID hypersensitivity; third trimester pregnancy', 'take with meals; short-term use only', 'Adults and adolescents from 12 years (>=40 kg): 1 tablet (400 mg) every 6 hours as needed, max 3 tablets (1200 mg) per 24 hours. Take with meals and abundant liquid.', 'nsaid-analgesics', now()),
('INV-P03', 'P03', 'Diclofenac topical gel; example Diclofenac HEUMANN Gel', 30, 'Diclofenac sodium', '10 mg/g', 'gel', 'topical', 'HEUMANN Pharma GmbH & Co. Generica KG', 'damaged skin or open wounds; NSAID hypersensitivity', 'do not apply to mucosal membranes; wash hands after application', 'Apply a cherry-to-walnut-sized amount (2-4 g) to the affected area 3 to 4 times daily and massage gently into the skin. Wash hands immediately after application.', 'topical-nsaid', now()),
('INV-P04', 'P04', 'Cetirizine tablets; example Cetirizin-ratiopharm bei Allergien', 60, 'Cetirizine dihydrochloride', '10 mg', 'film-coated tablet', 'oral', 'ratiopharm GmbH', 'end-stage renal disease (CrCl < 10 ml/min); cetirizine hypersensitivity', 'may cause mild somnolence in sensitive individuals', 'Adults and adolescents from 12 years: 10 mg (1 tablet) once daily with water, preferably in the evening. Children 6-12 years: 5 mg (half tablet) twice daily.', 'antihistamines', now()),
('INV-P05', 'P05', 'Xylometazoline nasal spray; example Otriven 0.1% preservative-free metered spray', 35, 'Xylometazoline hydrochloride', '1 mg/ml', 'metered nasal spray', 'nasal', 'Haleon Germany GmbH', 'rhinitis sicca; narrow-angle glaucoma; post-hypophysectomy', 'do not use for more than 7 consecutive days to avoid rhinitis medicamentosa', 'Adults and school-age children (from 12 years): 1 spray into each nostril up to 3 times daily as needed. Blow nose thoroughly before administration.', 'nasal-decongestants', now()),
('INV-P06', 'P06', 'ORS sachets; example Elotrans', 80, 'Sodium chloride, Potassium chloride, Sodium citrate, Glucose', 'standard WHO formula sachet', 'sachet powder for solution', 'oral', 'STADA Consumer Health Deutschland GmbH', 'intractable vomiting; ileus; severe dehydration requiring IV', 'dissolve in exact amount of water specified', 'Dissolve contents of 1 sachet in exactly 200 ml of freshly boiled, cooled drinking water. Drink after each unformed stool or as recommended for dehydration.', 'oral-rehydration', now()),
('INV-P07', 'P07', 'Simeticone; example Espumisan Kautabletten', 40, 'Simeticone', '40 mg', 'chewable tablet', 'oral', 'Berlin-Chemie AG', 'simeticone hypersensitivity; intestinal obstruction', 'chew thoroughly before swallowing', 'Adults and adolescents from 12 years: 2 chewable tablets (80 mg) 3-4 times daily with or after meals, and before retiring if needed. Chew thoroughly before swallowing.', 'antiflatulents', now()),
('INV-P08', 'P08', 'Antacid chewable tablets; example Rennie', 55, 'Calcium carbonate, Magnesium carbonate', '680/80 mg', 'chewable tablet', 'oral', 'Bayer Vital GmbH', 'severe renal insufficiency; hypercalcaemia; nephrolithiasis', 'separate from other oral medications by 2 hours', 'Adults and adolescents from 12 years: 1 to 2 chewable tablets sucked or chewed as symptoms appear, preferably 1 hour after meals and before sleep. Max 11 tablets per 24 hours.', 'antacids', now()),
('INV-P09', 'P09', 'Clotrimazole skin cream; example Canesten Creme', 25, 'Clotrimazole', '10 mg/g', 'cream', 'topical', 'Bayer Vital GmbH', 'clotrimazole hypersensitivity', 'for external cutaneous use only; avoid contact with eyes', 'Apply thinly to cleansed, dry affected skin areas 2 to 3 times daily and rub in gently. Continue application for 2 weeks after clinical signs disappear to prevent recurrence.', 'topical-antifungals', now()),
('INV-P10', 'P10', 'Dexpanthenol ointment; example Bepanthen Wund- und Heilsalbe', 50, 'Dexpanthenol', '50 mg/g', 'ointment', 'topical', 'Bayer Vital GmbH', 'dexpanthenol hypersensitivity', 'for superficial wound and skin care', 'Apply thinly to cleaned superficial skin abrasions, minor wounds, or chapped skin once or several times daily as required until healed.', 'wound-healing', now()),
('INV-P11', 'P11', 'Saline nasal spray; exact product pending', 70, 'Sodium chloride 0.9%', '9 mg/ml', 'nasal spray', 'nasal', 'Hysan / Ursapharm', '', 'sterile solution; discard 6 months after opening', 'Adults and children: 1 to 2 sprays into each nostril several times daily as needed for nasal moisturising, clearing dry crusts, and hygiene.', 'saline-cleansing', now()),
('INV-P12', 'P12', 'Non-medicated throat comfort lozenges; exact product pending', 65, 'Iceland moss extract', '80 mg', 'pastille / lozenge', 'oral', 'Engelhard Arzneimittel GmbH & Co. KG', 'hypersensitivity to Iceland moss', 'suck slowly; comfort product', 'Adults and children from 4 years: suck 1 to 2 lozenges slowly several times daily as needed to soothe irritated throat and dry cough.', 'throat-comfort', now()),
('INV-P13', 'P13', 'Plain fragrance-free moisturiser; exact product pending', 30, 'Urea 5%, Ceramides', '5 %', 'lotion', 'topical', 'Beiersdorf AG', 'acute inflamed or oozing skin', 'external use only', 'Apply gently to clean, dry skin once or twice daily (especially after bathing) and massage lightly until absorbed.', 'dermatological-emollients', now()),
('INV-P14', 'P14', 'Sterile saline wound-rinse product; exact small pack pending', 40, 'Sodium chloride 0.9%', '9 mg/ml', 'rinse solution', 'topical', 'B. Braun Melsungen AG', 'not for intravenous infusion', 'single-use container', 'Open single-use ampoule and irrigate superficial wounds generously to flush out dirt and debris prior to dressing application.', 'wound-cleansing', now()),
('INV-P15', 'P15', 'Assorted adhesive plasters; exact pack pending', 100, 'Non-medicated adhesive dressing', 'standard unit', 'strip plaster', 'topical', 'Beiersdorf AG', '', 'clean and dry wound before application', 'Clean and dry wound and surrounding skin thoroughly. Apply plaster centered over the wound without stretching. Change dressing at least once daily.', 'dressings-plasters', now()),
('INV-P16', 'P16', 'Blister plasters; exact pack pending', 50, 'Hydrocolloid dressing', 'standard unit', 'hydrocolloid plaster', 'topical', 'Beiersdorf AG', 'infected blisters', 'apply to intact or unroofed clean blister without bursting', 'Clean and dry blister area. Warm plaster between hands, peel protective foil, and press firmly over blister without wrinkles. Leave on until it detaches naturally.', 'blister-care', now()),
('INV-P17', 'P17', 'Sterile non-adherent dressings; exact specification pending', 60, 'Non-adherent wound pad', '10x10 cm', 'sterile compress', 'topical', 'Beiersdorf AG', '', 'sterile until packet opened', 'Place sterile compress directly onto cleaned wound surface. Fix in place with medical fixation tape or conforming bandage. Change dressing daily or if saturated.', 'dressings-compresses', now()),
('INV-P18', 'P18', 'Fixation tape; exact pack pending', 50, 'Adhesive fixation tape', '2.5cm x 5m roll', 'tape', 'topical', 'Beiersdorf AG', '', 'do not apply directly to open wounds', 'Tear or cut desired length of tape and apply to secure wound compress or bandage edges to healthy, dry skin. Do not apply directly to open wounds.', 'fixation-materials', now()),
('INV-P19', 'P19', 'Conforming fixation bandage; exact size pending', 45, 'Elastic conforming bandage', '8cm x 4m roll', 'bandage', 'topical', 'Paul Hartmann AG', '', 'do not apply with excessive tension causing tourniquet effect', 'Wrap bandage around dressing with roughly 50% overlap per turn to hold compress securely on rounded or moving joints. Avoid applying excessive tension.', 'bandages', now()),
('INV-P20', 'P20', 'Instant cold pack; example Sport-Tec instant cold compress', 30, 'Urea and water cold pack', '13.5x22 cm', 'cold compress pack', 'topical', 'Sport-Tec Physio & Fitness', 'Raynaud''s syndrome; cold allergy / urticaria; circulatory disorders', 'wrap in cloth; do not apply directly to bare skin', 'Squeeze inner liquid bubble firmly to trigger endothermic cooling reaction. Shake briefly, wrap in a protective dry cloth, and place onto injured area for 15-20 minutes.', 'cryotherapy', now()),
('INV-P21', 'P21', 'Loratadin-ratiopharm 10 mg', 40, 'Loratadine', '10 mg', 'tablet', 'oral', 'ratiopharm GmbH', 'loratadine hypersensitivity', 'severe hepatic impairment requires lower initial dose', 'Adults and adolescents from 12 years (>=30 kg): 1 tablet (10 mg) once daily with water, independent of meals.', 'antihistamines', now()),
('INV-P22', 'P22', 'Levocetirizin STADA 5 mg', 40, 'Levocetirizine dihydrochloride', '5 mg', 'film-coated tablet', 'oral', 'STADA Consumer Health Deutschland GmbH', 'end-stage renal disease (CrCl < 10 ml/min)', 'avoid concurrent alcohol consumption', 'Adults and adolescents from 6 years: 1 tablet (5 mg) once daily with a glass of water.', 'antihistamines', now()),
('INV-P23', 'P23', 'Desloratadin HEUMANN 5 mg', 45, 'Desloratadine', '5 mg', 'film-coated tablet', 'oral', 'HEUMANN Pharma GmbH & Co. Generica KG', 'desloratadine hypersensitivity', 'severe renal impairment requires caution', 'Adults and adolescents from 12 years: 1 tablet (5 mg) once daily with water, with or without meals.', 'antihistamines', now()),
('INV-P24', 'P24', 'Naproxen-1 A Pharma 250 mg bei Regelschmerzen', 35, 'Naproxen', '250 mg', 'tablet', 'oral', '1 A Pharma GmbH', 'active peptic ulcer; severe heart failure; NSAID hypersensitivity; third trimester pregnancy', 'take with plenty of liquid; max 4 days without medical advice', 'Women and adolescents from 12 years: initial dose 2 tablets (500 mg), then if needed 1 tablet (250 mg) after 6-8 hours. Maximum 3 tablets (750 mg) per 24 hours. Take with food.', 'nsaid-analgesics', now()),
('INV-P25', 'P25', 'Aspirin 500 mg', 50, 'Acetylsalicylic acid', '500 mg', 'coated tablet', 'oral', 'Bayer Vital GmbH', 'peptic ulcers; bleeding diathesis; Reye syndrome risk in children/adolescents; third trimester pregnancy', 'take with food or copious water', 'Adults and adolescents from 16 years: 1 to 2 tablets (500-1000 mg) every 4 to 8 hours as needed, max 6 tablets (3000 mg) per 24 hours. Take with plentiful water after meals.', 'salicylate-analgesics', now()),
('INV-P26', 'P26', 'Loperamid akut HEUMANN', 60, 'Loperamide hydrochloride', '2 mg', 'tablet', 'oral', 'HEUMANN Pharma GmbH & Co. Generica KG', 'bloody diarrhea or high fever (invasive pathogens); acute ulcerative colitis; pseudomembranous colitis', 'does not replace fluid replacement; do not exceed 48 hours without doctor consultation', 'Adults: initial dose 2 tablets (4 mg), followed by 1 tablet (2 mg) after each subsequent liquid stool. Maximum 6 tablets (12 mg) per 24 hours. Adolescents >=12 yrs: max 4 tablets (8 mg) per 24 hours.', 'antidiarrheals', now()),
('INV-P27', 'P27', 'Dulcolax Dragees', 40, 'Bisacodyl', '5 mg', 'gastro-resistant tablet', 'oral', 'A. Nattermann & Cie. GmbH', 'ileus; acute appendicitis; severe abdominal pain with fever/vomiting', 'take in evening with liquid; do not consume with milk or antacids', 'Adults and children over 10 years: 1 to 2 gastro-resistant dragees (5-10 mg) once daily in the evening. Swallow whole with liquid. Do not take with milk or antacids.', 'stimulant-laxatives', now()),
('INV-P28', 'P28', 'Laxoberal Abfuehr-Tabletten 5 mg', 35, 'Sodium picosulfate', '5 mg', 'tablet', 'oral', 'A. Nattermann & Cie. GmbH', 'ileus; intestinal obstruction; severe dehydration', 'take in evening; effect after 6 to 12 hours', 'Adults: 1 to 2 tablets (5-10 mg) once daily in the evening with sufficient water. Onset of action usually occurs 6 to 12 hours after ingestion.', 'stimulant-laxatives', now()),
('INV-P29', 'P29', 'Pantoprazol TAD 20 mg bei Sodbrennen', 50, 'Pantoprazole sodium sesquihydrate', '20 mg', 'gastro-resistant tablet', 'oral', 'TAD Pharma GmbH', 'pantoprazole hypersensitivity', 'short term treatment up to 2 weeks; swallow whole with water before a meal', 'Adults from 18 years: 1 gastro-resistant tablet (20 mg) once daily 1 hour before a meal. Swallow whole with water; do not chew or crush.', 'proton-pump-inhibitors', now()),
('INV-P30', 'P30', 'Vomex A Dragees', 45, 'Dimenhydrinate', '50 mg', 'coated tablet', 'oral', 'Klinge Pharma GmbH', 'acute asthma; narrow-angle glaucoma; pheochromocytoma; porphyria', 'causes marked drowsiness; impairs ability to drive', 'Adults and adolescents from 14 years: 1 to 2 dragees (50-100 mg) 1 to 4 times daily (every 6 hours as needed), max 8 dragees (400 mg) per 24 hours. For motion sickness: take initial dose 30 min before departure.', 'antiemetics', now())
on conflict (inventory_product_id) do update set
    catalog_product_id = excluded.catalog_product_id,
    product_name = excluded.product_name,
    quantity = excluded.quantity,
    active_ingredients = excluded.active_ingredients,
    strength = excluded.strength,
    formulation = excluded.formulation,
    route = excluded.route,
    manufacturer = excluded.manufacturer,
    contraindications = excluded.contraindications,
    precautions = excluded.precautions,
    usage_instructions = excluded.usage_instructions,
    therapy_group = excluded.therapy_group,
    updated_at = now();
