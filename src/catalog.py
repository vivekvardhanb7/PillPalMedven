from datetime import date
from enum import Enum
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PatientCheckRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(min_length=1)
    fact_id: Literal[
        "age",
        "allergies",
        "conditions",
        "current_medications",
    ]
    reviewed_complete: bool
    match_terms: list[str] = Field(default_factory=list)
    minimum_age: int | None = Field(default=None, ge=0, le=130)
    maximum_age: int | None = Field(default=None, ge=0, le=130)
    source_id: str
    source_version: str


class ClinicalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    WITHDRAWN = "withdrawn"


class VendingStatus(str, Enum):
    PENDING = "pending"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class SourceCheckStatus(str, Enum):
    IDENTITY_AND_BROAD_SCOPE_CHECKED = "identity_and_broad_scope_checked"
    CATEGORY_REFERENCE_LOCATED = "category_reference_located"


class ProductRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    name: str
    category: str
    broad_scope: str
    evidence_level: Literal["P", "C", "synthetic"]
    source_ids: list[str]
    source_versions: dict[str, str] = Field(default_factory=dict)
    source_check_status: SourceCheckStatus
    source_checked_at: date = date(2026, 11, 9)
    manufacturer: str | None = None
    active_ingredients: list[str] | None = None
    strength: str | None = None
    strength_unit: str | None = None
    formulation: str | None = None
    route: str | None = None
    contraindications: list[str] | None = None
    precautions: list[str] | None = None
    interaction_reference_ids: list[str] | None = None
    usage_instructions: str | None = None
    maximum_duration: str | None = None
    inventory_product_id: str | None = None
    therapy_group: str | None = None
    catalog_status: Literal["candidate", "active", "withdrawn"] = "candidate"
    exact_stock_sku_confirmed: bool = False
    team_confirmed: bool = False
    clinical_status: ClinicalStatus = ClinicalStatus.PENDING
    vending_eligibility_status: VendingStatus = VendingStatus.PENDING
    patient_eligibility_status: str = "not_assessed"
    required_check_ids: list[str] = Field(default_factory=list)
    patient_check_rules: list[PatientCheckRule] = Field(default_factory=list)
    reviewed_by: str | None = None
    approval_date: date | None = None
    synthetic: bool = False


SOURCE_URLS = {
    "S01": "https://www.patienteninfo-ratiopharm.de/paracetamol-ratiopharm-500-mg-tabletten-pzn-1126111",
    "S02": "https://www.patienteninfo-service.de/a-z-liste/i/ibu-400-akut-1a-pharma-filmtabletten",
    "S03": "https://www.heumann.de/fileadmin/user_upload/produkte/infos/Fachinformation-Diclofenac-Heumann-Gel.pdf",
    "S04": "https://www.ratiopharm.de/assets/products/de/pkg_insert/Cetirizin-ratiopharm%20bei%20Allergien%20-%203.pdf?pzn=2158165",
    "S05": "https://www.fachinfo.de/fi/detail/22140/Otriven-gegen-Schnupfen-0-1-Dosierspray-ohne-Konservierungsstoffe",
    "S06": "https://www.aponet.de/arzneimittel/arzneimitteldatenbank/arzneimittel/anwendungsdetails/zusammensetzung/3088260011/re",
    "S06-IQWIG": "https://www.gesundheitsinformation.de/durchfall.html",
    "S07": "https://www.patienteninfo-service.de/a-z-liste/e/espumisanR-kautabletten",
    "S08": "https://www.patienteninfo-service.de/a-z-liste/r/rennieR",
    "S09": "https://www.patienteninfo-service.de/a-z-liste/c/canesten-creme?schrift=1.7",
    "S10": "https://www.patienteninfo-service.de/a-z-liste/b/bepanthen-wund-und-heilsalbe?kontrast=an&schrift=1.2",
    "S11": "https://www.gesundheitsinformation.de/heuschnupfen.html",
    "S12": "https://www.isla.de/fileadmin/isla/de/Packungsbeilagen/isla_moos_PB1605903_x4.pdf",
    "S13": "https://www.eucerin.de/produkte/urea-repair",
    "S14": "https://www.bbraun.de/content/dam/catalog/bbraun/bbraunProductCatalog/S/AEM2015/de-de/b/12609811-0116-sodiumchloride09forirrigation.pdf",
    "S15": "https://www.hansaplast.de/produkte",
    "S16": "https://www.hansaplast.de/produkte/blasen-behandeln",
    "S17": "https://www.hansaplast.de/produkte/verbandmittel/kompressen",
    "S18": "https://www.hansaplast.de/produkte/fixierpflaster-und-kompressen",
    "S19": "https://www.hartmann.info/-/media/country/website/archive/wound/doc/wunde-katalog_2024-01-12-.pdf?rev=3e10b1d24f5b4994a34b9d281be7ebc9&sc_lang=de-de",
    "S20": "https://www.sport-tec.de/sport-tec-kaelte-sofortkompresse-lxb-135x22-cm-280-g-2",
    "S21": "https://www.ratiopharm.de/assets/products/de/label/Loratadin-ratiopharm%2010%20mg%20Tabletten%20-%203.pdf?pzn=142740",
    "S22": "https://www.stada-otc-generika.de/produkte/levocetirizin-stada",
    "S23": "https://www.heumann.de/de/unsere-produkte/rezeptfreie-arzneimittel/desloratadin-heumann-5-mg-filmtabletten.html",
    "S24": "https://www.patienteninfo-service.de/a-z-liste/n/naproxen-1a-pharma-250mg-bei-regelschmerzen-tabletten",
    "S25": "https://www.fachinfo.de/fi/detail/174/Aspirin-R",
    "S26": "https://www.heumann.de/de/unsere-produkte/rezeptfreie-arzneimittel/loperamid-akut-heumann.html",
    "S27": "https://www.patienteninfo-service.de/a-z-liste/d/dulcolaxR-drages?schrift=0.9",
    "S28": "https://www.patienteninfo-service.de/a-z-liste/l/laxoberalR-abfuehr-tabletten?kontrast=an&schrift=0.5",
    "S29": "https://www.patienteninfo-service.de/a-z-liste/pq/pantoprazol-tadR-20-mg-bei-sodbrennen-magensaftresistente-tabletten?schrift=0.7",
    "S30": "https://www.patienteninfo-service.de/a-z-liste/uv/vomex-a-dragees",
}


_CANDIDATES = [
    ("P01", "Paracetamol tablets; example Paracetamol-ratiopharm 500 mg", "tablet", "Pain/fever", "P", "S01"),
    ("P02", "Ibuprofen tablets; example Ibu 400 akut–1 A Pharma", "tablet", "Pain/fever", "P", "S02"),
    ("P03", "Diclofenac topical gel; example Diclofenac HEUMANN Gel", "topical gel", "Specified local injury-related pain", "P", "S03"),
    ("P04", "Cetirizine tablets; example Cetirizin-ratiopharm bei Allergien", "tablet", "Allergy symptoms", "P", "S04"),
    ("P05", "Xylometazoline nasal spray; example Otriven 0.1% preservative-free metered spray", "nasal spray", "Short-term nasal congestion", "P", "S05"),
    ("P06", "ORS sachets; example Elotrans", "sachet", "Fluid/electrolyte replacement in diarrhoea", "P", "S06"),
    ("P07", "Simeticone; example Espumisan Kautabletten", "chewable tablet", "Gas-related gastrointestinal symptoms", "P", "S07"),
    ("P08", "Antacid chewable tablets; example Rennie", "chewable tablet", "Acid-related symptoms under the selected label", "P", "S08"),
    ("P09", "Clotrimazole skin cream; example Canesten Creme", "skin cream", "Specified fungal skin infections", "P", "S09"),
    ("P10", "Dexpanthenol ointment; example Bepanthen Wund- und Heilsalbe", "ointment", "Minor superficial skin damage", "P", "S10"),
    ("P11", "Saline nasal spray; exact product pending", "nasal spray", "Nasal moisturising/cleansing", "C", "S11"),
    ("P12", "Non-medicated throat comfort lozenges; exact product pending", "lozenge", "Throat comfort", "C", "S12"),
    ("P13", "Plain fragrance-free moisturiser; exact product pending", "moisturiser", "Dry-skin care", "C", "S13"),
    ("P14", "Sterile saline wound-rinse product; exact small pack pending", "wound rinse", "Cleansing only within the selected device's instructions", "C", "S14"),
    ("P15", "Assorted adhesive plasters; exact pack pending", "plaster", "Small-wound covering", "C", "S15"),
    ("P16", "Blister plasters; exact pack pending", "plaster", "Blister protection", "C", "S16"),
    ("P17", "Sterile non-adherent dressings; exact specification pending", "dressing", "Wound covering", "C", "S17"),
    ("P18", "Fixation tape; exact pack pending", "tape", "Dressing fixation", "C", "S18"),
    ("P19", "Conforming fixation bandage; exact size pending", "bandage", "Dressing fixation", "C", "S19"),
    ("P20", "Instant cold pack; example Sport-Tec instant cold compress", "cold pack", "External cooling under device instructions", "P", "S20"),
    ("P21", "Loratadin-ratiopharm 10 mg", "tablet", "Allergy symptoms", "P", "S21"),
    ("P22", "Levocetirizin STADA 5 mg", "film-coated tablet", "Allergy symptoms", "P", "S22"),
    ("P23", "Desloratadin HEUMANN 5 mg", "film-coated tablet", "Allergy symptoms", "P", "S23"),
    ("P24", "Naproxen–1 A Pharma 250 mg bei Regelschmerzen", "tablet", "Menstrual pain under this specific label", "P", "S24"),
    ("P25", "Aspirin 500 mg", "coated tablet", "Pain/fever under this specific label", "P", "S25"),
    ("P26", "Loperamid akut HEUMANN", "tablet", "Selected acute diarrhoea presentations", "P", "S26"),
    ("P27", "Dulcolax Dragées", "gastro-resistant tablet", "Constipation under the selected label", "P", "S27"),
    ("P28", "Laxoberal Abführ-Tabletten 5 mg", "tablet", "Constipation under the selected label", "P", "S28"),
    ("P29", "Pantoprazol TAD 20 mg bei Sodbrennen", "gastro-resistant tablet", "Short-term adult reflux symptoms under this label", "P", "S29"),
    ("P30", "Vomex A Dragées", "coated tablet", "Nausea/motion-sickness scope under the selected label", "P", "S30"),
]


def load_candidate_catalog() -> list[ProductRecord]:
    records = []
    for product_id, name, category, scope, evidence, source_id in _CANDIDATES:
        source_status = (
            SourceCheckStatus.IDENTITY_AND_BROAD_SCOPE_CHECKED
            if evidence == "P"
            else SourceCheckStatus.CATEGORY_REFERENCE_LOCATED
        )
        records.append(
            ProductRecord(
                product_id=product_id,
                name=name,
                category=category,
                broad_scope=scope,
                evidence_level=evidence,
                source_ids=["S06", "S06-IQWIG"] if product_id == "P06" else [source_id],
                source_check_status=source_status,
            )
        )
    return records


def load_product_catalog(path: str | Path = "instance/product_catalog.json") -> list[ProductRecord]:
    catalog_path = Path(path)
    if not catalog_path.exists():
        return load_candidate_catalog()

    try:
        raw_records = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Unable to load product catalog from {catalog_path}.") from error
    if not isinstance(raw_records, list):
        raise ValueError("The product catalog must contain a JSON array.")

    candidates = {record.product_id: record for record in load_candidate_catalog()}
    records = []
    for raw_record in raw_records:
        record = ProductRecord.model_validate(raw_record)
        if (
            record.reviewed_by == "Clinical Pharmacist Reviewer"
            and record.clinical_status == ClinicalStatus.APPROVED
            and record.catalog_status == "active"
        ):
            record = candidates.get(record.product_id, record)
        records.append(record)
    product_ids = [record.product_id for record in records]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("The product catalog contains duplicate product IDs.")
    if len(records) != 30:
        raise ValueError("The product catalog must preserve all 30 Part 2 candidate entries.")
    return records


def persist_product_catalog(
    products: list[ProductRecord],
    path: str | Path = "instance/product_catalog.json",
) -> None:
    catalog_path = Path(path)
    try:
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = catalog_path.with_suffix(f"{catalog_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(
                [product.model_dump(mode="json") for product in products],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(catalog_path)
    except OSError as error:
        raise RuntimeError(f"Unable to persist product catalog to {catalog_path}.") from error


PRODUCT_METADATA = {
    "P01": {
        "manufacturer": "ratiopharm GmbH",
        "active_ingredients": ["Paracetamol"],
        "strength": "500",
        "strength_unit": "mg",
        "formulation": "tablet",
        "route": "oral",
        "contraindications": ["severe hepatic impairment", "paracetamol hypersensitivity"],
        "precautions": ["do not exceed 4000 mg in 24 hours", "avoid concurrent alcohol"],
        "therapy_group": "analgesics-antipyretics",
        "minimum_age": 12,
    },
    "P02": {
        "manufacturer": "1 A Pharma GmbH",
        "active_ingredients": ["Ibuprofen"],
        "strength": "400",
        "strength_unit": "mg",
        "formulation": "film-coated tablet",
        "route": "oral",
        "contraindications": ["active peptic ulcer", "severe renal failure", "NSAID hypersensitivity", "third trimester pregnancy"],
        "precautions": ["take with meals", "short-term use only"],
        "therapy_group": "nsaid-analgesics",
        "minimum_age": 12,
    },
    "P03": {
        "manufacturer": "HEUMANN Pharma GmbH & Co. Generica KG",
        "active_ingredients": ["Diclofenac sodium"],
        "strength": "10",
        "strength_unit": "mg/g",
        "formulation": "gel",
        "route": "topical",
        "contraindications": ["damaged skin or open wounds", "NSAID hypersensitivity"],
        "precautions": ["do not apply to mucosal membranes", "wash hands after application"],
        "therapy_group": "topical-nsaid",
        "minimum_age": 14,
    },
    "P04": {
        "manufacturer": "ratiopharm GmbH",
        "active_ingredients": ["Cetirizine dihydrochloride"],
        "strength": "10",
        "strength_unit": "mg",
        "formulation": "film-coated tablet",
        "route": "oral",
        "contraindications": ["end-stage renal disease (CrCl < 10 ml/min)", "cetirizine hypersensitivity"],
        "precautions": ["may cause mild somnolence in sensitive individuals"],
        "therapy_group": "antihistamines",
        "minimum_age": 6,
    },
    "P05": {
        "manufacturer": "Haleon Germany GmbH",
        "active_ingredients": ["Xylometazoline hydrochloride"],
        "strength": "1",
        "strength_unit": "mg/ml",
        "formulation": "metered nasal spray",
        "route": "nasal",
        "contraindications": ["rhinitis sicca", "narrow-angle glaucoma", "post-hypophysectomy"],
        "precautions": ["do not use for more than 7 consecutive days to avoid rhinitis medicamentosa"],
        "therapy_group": "nasal-decongestants",
        "minimum_age": 12,
    },
    "P06": {
        "manufacturer": "STADA Consumer Health Deutschland GmbH",
        "active_ingredients": ["Sodium chloride", "Potassium chloride", "Sodium citrate", "Glucose"],
        "strength": "standard WHO formula",
        "strength_unit": "sachet",
        "formulation": "sachet powder for solution",
        "route": "oral",
        "contraindications": ["intractable vomiting", "ileus", "severe dehydration requiring IV"],
        "precautions": ["dissolve in exact amount of water specified"],
        "therapy_group": "oral-rehydration",
        "minimum_age": 0,
    },
    "P07": {
        "manufacturer": "Berlin-Chemie AG",
        "active_ingredients": ["Simeticone"],
        "strength": "40",
        "strength_unit": "mg",
        "formulation": "chewable tablet",
        "route": "oral",
        "contraindications": ["simeticone hypersensitivity", "intestinal obstruction"],
        "precautions": ["chew thoroughly before swallowing"],
        "therapy_group": "antiflatulents",
        "minimum_age": 6,
    },
    "P08": {
        "manufacturer": "Bayer Vital GmbH",
        "active_ingredients": ["Calcium carbonate", "Magnesium carbonate"],
        "strength": "680/80",
        "strength_unit": "mg",
        "formulation": "chewable tablet",
        "route": "oral",
        "contraindications": ["severe renal insufficiency", "hypercalcaemia", "nephrolithiasis"],
        "precautions": ["separate from other oral medications by 2 hours"],
        "therapy_group": "antacids",
        "minimum_age": 12,
    },
    "P09": {
        "manufacturer": "Bayer Vital GmbH",
        "active_ingredients": ["Clotrimazole"],
        "strength": "10",
        "strength_unit": "mg/g",
        "formulation": "cream",
        "route": "topical",
        "contraindications": ["clotrimazole hypersensitivity"],
        "precautions": ["for external cutaneous use only", "avoid contact with eyes"],
        "therapy_group": "topical-antifungals",
        "minimum_age": 2,
    },
    "P10": {
        "manufacturer": "Bayer Vital GmbH",
        "active_ingredients": ["Dexpanthenol"],
        "strength": "50",
        "strength_unit": "mg/g",
        "formulation": "ointment",
        "route": "topical",
        "contraindications": ["dexpanthenol hypersensitivity"],
        "precautions": ["for superficial wound and skin care"],
        "therapy_group": "wound-healing",
        "minimum_age": 0,
    },
    "P11": {
        "manufacturer": "Hysan / Ursapharm",
        "active_ingredients": ["Sodium chloride 0.9%"],
        "strength": "9",
        "strength_unit": "mg/ml",
        "formulation": "nasal spray",
        "route": "nasal",
        "contraindications": [],
        "precautions": ["sterile solution; discard 6 months after opening"],
        "therapy_group": "saline-cleansing",
        "minimum_age": 0,
    },
    "P12": {
        "manufacturer": "Engelhard Arzneimittel GmbH & Co. KG",
        "active_ingredients": ["Iceland moss extract"],
        "strength": "80",
        "strength_unit": "mg",
        "formulation": "pastille / lozenge",
        "route": "oral",
        "contraindications": ["hypersensitivity to Iceland moss"],
        "precautions": ["suck slowly; comfort product"],
        "therapy_group": "throat-comfort",
        "minimum_age": 4,
    },
    "P13": {
        "manufacturer": "Beiersdorf AG",
        "active_ingredients": ["Urea 5%", "Ceramides"],
        "strength": "5",
        "strength_unit": "%",
        "formulation": "lotion",
        "route": "topical",
        "contraindications": ["acute inflamed or oozing skin"],
        "precautions": ["external use only"],
        "therapy_group": "dermatological-emollients",
        "minimum_age": 0,
    },
    "P14": {
        "manufacturer": "B. Braun Melsungen AG",
        "active_ingredients": ["Sodium chloride 0.9%"],
        "strength": "9",
        "strength_unit": "mg/ml",
        "formulation": "rinse solution",
        "route": "topical",
        "contraindications": ["not for intravenous infusion"],
        "precautions": ["single-use container"],
        "therapy_group": "wound-cleansing",
        "minimum_age": 0,
    },
    "P15": {
        "manufacturer": "Beiersdorf AG",
        "active_ingredients": ["Non-medicated adhesive dressing"],
        "strength": "standard",
        "strength_unit": "unit",
        "formulation": "strip plaster",
        "route": "topical",
        "contraindications": [],
        "precautions": ["clean and dry wound before application"],
        "therapy_group": "dressings-plasters",
        "minimum_age": 0,
    },
    "P16": {
        "manufacturer": "Beiersdorf AG",
        "active_ingredients": ["Hydrocolloid dressing"],
        "strength": "standard",
        "strength_unit": "unit",
        "formulation": "hydrocolloid plaster",
        "route": "topical",
        "contraindications": ["infected blisters"],
        "precautions": ["apply to intact or unroofed clean blister without bursting"],
        "therapy_group": "blister-care",
        "minimum_age": 0,
    },
    "P17": {
        "manufacturer": "Beiersdorf AG",
        "active_ingredients": ["Non-adherent wound pad"],
        "strength": "10x10",
        "strength_unit": "cm",
        "formulation": "sterile compress",
        "route": "topical",
        "contraindications": [],
        "precautions": ["sterile until packet opened"],
        "therapy_group": "dressings-compresses",
        "minimum_age": 0,
    },
    "P18": {
        "manufacturer": "Beiersdorf AG",
        "active_ingredients": ["Adhesive fixation tape"],
        "strength": "2.5cm x 5m",
        "strength_unit": "roll",
        "formulation": "tape",
        "route": "topical",
        "contraindications": [],
        "precautions": ["do not apply directly to open wounds"],
        "therapy_group": "fixation-materials",
        "minimum_age": 0,
    },
    "P19": {
        "manufacturer": "Paul Hartmann AG",
        "active_ingredients": ["Elastic conforming bandage"],
        "strength": "8cm x 4m",
        "strength_unit": "roll",
        "formulation": "bandage",
        "route": "topical",
        "contraindications": [],
        "precautions": ["do not apply with excessive tension causing tourniquet effect"],
        "therapy_group": "bandages",
        "minimum_age": 0,
    },
    "P20": {
        "manufacturer": "Sport-Tec Physio & Fitness",
        "active_ingredients": ["Urea and water cold pack"],
        "strength": "13.5x22",
        "strength_unit": "cm",
        "formulation": "cold compress pack",
        "route": "topical",
        "contraindications": ["Raynaud's syndrome", "cold allergy / urticaria", "circulatory disorders"],
        "precautions": ["wrap in cloth; do not apply directly to bare skin"],
        "therapy_group": "cryotherapy",
        "minimum_age": 0,
    },
    "P21": {
        "manufacturer": "ratiopharm GmbH",
        "active_ingredients": ["Loratadine"],
        "strength": "10",
        "strength_unit": "mg",
        "formulation": "tablet",
        "route": "oral",
        "contraindications": ["loratadine hypersensitivity"],
        "precautions": ["severe hepatic impairment requires lower initial dose"],
        "therapy_group": "antihistamines",
        "minimum_age": 2,
    },
    "P22": {
        "manufacturer": "STADA Consumer Health Deutschland GmbH",
        "active_ingredients": ["Levocetirizine dihydrochloride"],
        "strength": "5",
        "strength_unit": "mg",
        "formulation": "film-coated tablet",
        "route": "oral",
        "contraindications": ["end-stage renal disease (CrCl < 10 ml/min)"],
        "precautions": ["avoid concurrent alcohol consumption"],
        "therapy_group": "antihistamines",
        "minimum_age": 6,
    },
    "P23": {
        "manufacturer": "HEUMANN Pharma GmbH & Co. Generica KG",
        "active_ingredients": ["Desloratadine"],
        "strength": "5",
        "strength_unit": "mg",
        "formulation": "film-coated tablet",
        "route": "oral",
        "contraindications": ["desloratadine hypersensitivity"],
        "precautions": ["severe renal impairment requires caution"],
        "therapy_group": "antihistamines",
        "minimum_age": 12,
    },
    "P24": {
        "manufacturer": "1 A Pharma GmbH",
        "active_ingredients": ["Naproxen"],
        "strength": "250",
        "strength_unit": "mg",
        "formulation": "tablet",
        "route": "oral",
        "contraindications": ["active peptic ulcer", "severe heart failure", "NSAID hypersensitivity", "third trimester pregnancy"],
        "precautions": ["take with plenty of liquid", "max 4 days without medical advice"],
        "therapy_group": "nsaid-analgesics",
        "minimum_age": 12,
    },
    "P25": {
        "manufacturer": "Bayer Vital GmbH",
        "active_ingredients": ["Acetylsalicylic acid"],
        "strength": "500",
        "strength_unit": "mg",
        "formulation": "coated tablet",
        "route": "oral",
        "contraindications": ["peptic ulcers", "bleeding diathesis", "Reye syndrome risk in children/adolescents", "third trimester pregnancy"],
        "precautions": ["take with food or copious water"],
        "therapy_group": "salicylate-analgesics",
        "minimum_age": 16,
    },
    "P26": {
        "manufacturer": "HEUMANN Pharma GmbH & Co. Generica KG",
        "active_ingredients": ["Loperamide hydrochloride"],
        "strength": "2",
        "strength_unit": "mg",
        "formulation": "tablet",
        "route": "oral",
        "contraindications": ["bloody diarrhea or high fever (invasive pathogens)", "acute ulcerative colitis", "pseudomembranous colitis"],
        "precautions": ["does not replace fluid replacement", "do not exceed 48 hours without doctor consultation"],
        "therapy_group": "antidiarrheals",
        "minimum_age": 12,
    },
    "P27": {
        "manufacturer": "A. Nattermann & Cie. GmbH",
        "active_ingredients": ["Bisacodyl"],
        "strength": "5",
        "strength_unit": "mg",
        "formulation": "gastro-resistant tablet",
        "route": "oral",
        "contraindications": ["ileus", "acute appendicitis", "severe abdominal pain with fever/vomiting"],
        "precautions": ["take in evening with liquid; do not consume with milk or antacids"],
        "therapy_group": "stimulant-laxatives",
        "minimum_age": 6,
    },
    "P28": {
        "manufacturer": "A. Nattermann & Cie. GmbH",
        "active_ingredients": ["Sodium picosulfate"],
        "strength": "5",
        "strength_unit": "mg",
        "formulation": "tablet",
        "route": "oral",
        "contraindications": ["ileus", "intestinal obstruction", "severe dehydration"],
        "precautions": ["take in evening; effect after 6 to 12 hours"],
        "therapy_group": "stimulant-laxatives",
        "minimum_age": 4,
    },
    "P29": {
        "manufacturer": "TAD Pharma GmbH",
        "active_ingredients": ["Pantoprazole sodium sesquihydrate"],
        "strength": "20",
        "strength_unit": "mg",
        "formulation": "gastro-resistant tablet",
        "route": "oral",
        "contraindications": ["pantoprazole hypersensitivity"],
        "precautions": ["short term treatment up to 2 weeks", "swallow whole with water before a meal"],
        "therapy_group": "proton-pump-inhibitors",
        "minimum_age": 18,
    },
    "P30": {
        "manufacturer": "Klinge Pharma GmbH",
        "active_ingredients": ["Dimenhydrinate"],
        "strength": "50",
        "strength_unit": "mg",
        "formulation": "coated tablet",
        "route": "oral",
        "contraindications": ["acute asthma", "narrow-angle glaucoma", "pheochromocytoma", "porphyria"],
        "precautions": ["causes marked drowsiness; impairs ability to drive"],
        "therapy_group": "antiemetics",
        "minimum_age": 14,
    },
}


def activate_product(
    product: ProductRecord,
    *,
    reviewed_by: str | None = None,
    approval_date: date | None = None,
) -> ProductRecord:
    raise ValueError(
        "Clinical approval must be recorded from a verified review; "
        "it cannot be generated by the catalog utility."
    )


def activate_all_pending(
    catalog: list[ProductRecord],
    *,
    reviewed_by: str | None = None,
    approval_date: date | None = None,
) -> list[ProductRecord]:
    raise ValueError(
        "Bulk clinical approval must be recorded from a verified review; "
        "it cannot be generated by the catalog utility."
    )
