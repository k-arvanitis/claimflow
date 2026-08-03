import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from html import unescape
from pathlib import Path

from pydantic import Field, create_model

from claimflow.config import settings  # noqa: E402 (must precede doc-intel import)

os.environ["DOC_INTEL_PROVIDER"] = settings.doc_intel_provider
os.environ["DOC_INTEL_MODEL"] = settings.doc_intel_model
os.environ["DOC_INTEL_MAX_TOKENS"] = str(settings.doc_intel_max_tokens)
if settings.doc_intel_llm_base_url:
    os.environ["DOC_INTEL_LLM_BASE_URL"] = settings.doc_intel_llm_base_url
if settings.openai_api_key.get_secret_value():
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key.get_secret_value()
if settings.anthropic_api_key.get_secret_value():
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key.get_secret_value()

from doc_intel import config as _doc_intel_config  # noqa: E402
from doc_intel.chunker import find_conflicted_fields, merge_extractions  # noqa: E402
from doc_intel.confidence import score  # noqa: E402
from doc_intel.extract import _extract_layout, extract  # noqa: E402
from doc_intel.inputs import DocumentBlock, DocumentLayout, load_source  # noqa: E402
from doc_intel.llm import get_client  # noqa: E402
from doc_intel.ocr_backends import get_backend  # noqa: E402
from doc_intel.schemas.base import (  # noqa: E402
    BaseExtraction,
    Evidence,
    ExtractionResult,
    SchemaSpec,
)

_doc_intel_config.PROVIDER = settings.doc_intel_provider
_doc_intel_config.MODEL = settings.doc_intel_model
_doc_intel_config.MAX_TOKENS = settings.doc_intel_max_tokens
if settings.doc_intel_llm_base_url:
    _doc_intel_config.LLM_BASE_URL = settings.doc_intel_llm_base_url
if settings.openai_api_key.get_secret_value():
    _doc_intel_config.OPENAI_API_KEY = settings.openai_api_key.get_secret_value()
if settings.anthropic_api_key.get_secret_value():
    _doc_intel_config.ANTHROPIC_API_KEY = settings.anthropic_api_key.get_secret_value()

# lighton (a common fallback when the default paddleocr_vl isn't installed) gives one
# page-level markdown block with no bbox at all, by design — every field extracted from
# a lighton-OCR'd page loses source-evidence highlighting entirely, which defeats this
# product's core value. tesseract gives real word/element-level bboxes at a real but
# smaller accuracy cost; for this product, evidence traceability outweighs that.
if (
    _doc_intel_config.OCR_FALLBACK_PROVIDERS
    and "lighton" in _doc_intel_config.OCR_FALLBACK_PROVIDERS
):
    _doc_intel_config.OCR_FALLBACK_PROVIDERS = [
        p for p in _doc_intel_config.OCR_FALLBACK_PROVIDERS if p != "lighton"
    ] + ["lighton"]
    if "tesseract" not in _doc_intel_config.OCR_FALLBACK_PROVIDERS:
        _doc_intel_config.OCR_FALLBACK_PROVIDERS.insert(0, "tesseract")

from claimflow.state import ClaimState  # noqa: E402

logger = logging.getLogger(__name__)

_CMS1500_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"}
_CMS1500_LLM_SPECS: tuple[SchemaSpec, SchemaSpec] | None = None
_CMS1500_SERVICE_LINES_LLM_SPEC: SchemaSpec | None = None
_XACTIMATE_LLM_SPECS: tuple[SchemaSpec, SchemaSpec] | None = None
_CMS1500_REGIONS = (
    ("patient and insured", 0.000, 1.000, 0.068, 0.508),
    ("claim details", 0.000, 1.000, 0.420, 0.664),
    ("diagnoses and service lines", 0.000, 1.000, 0.586, 0.879),
    ("provider and totals", 0.000, 1.000, 0.820, 0.996),
    ("diagnosis indicator", 0.455, 0.657, 0.557, 0.664),
    ("tax id type", 0.152, 0.329, 0.815, 0.898),
)


def _cms1500_llm_specs(spec: SchemaSpec) -> tuple[SchemaSpec, SchemaSpec]:
    """Split the wide CMS schema so local completion limits cannot truncate Box 24.

    Service lines are intentionally absent from both response models because the
    standardized table is parsed deterministically below. The two smaller responses
    are merged and rescored against the canonical public schema afterward.
    """
    global _CMS1500_LLM_SPECS
    if _CMS1500_LLM_SPECS is not None:
        return _CMS1500_LLM_SPECS

    names = list(spec.model.model_fields)
    split_at = names.index("service_lines")
    groups = (names[:split_at], names[split_at + 1 :])
    llm_specs = []
    for index, group in enumerate(groups, start=1):
        model = create_model(
            f"CMS1500ExtractionPart{index}",
            __base__=BaseExtraction,
            **{
                name: (
                    spec.model.model_fields[name].annotation,
                    deepcopy(spec.model.model_fields[name]),
                )
                for name in group
            },
        )
        llm_specs.append(
            SchemaSpec(
                name=spec.name,
                model=model,
                system_prompt=(
                    f"{spec.system_prompt} Extract only the fields present in this response schema; "
                    "Box 24 service lines are parsed separately and must not be returned in this pass."
                ),
                validators={
                    name: validator
                    for name, validator in spec.validators.items()
                    if name in group
                },
                hints=spec.hints,
                zero_is_blank_fields=spec.zero_is_blank_fields.intersection(group),
            )
        )
    _CMS1500_LLM_SPECS = (llm_specs[0], llm_specs[1])
    return _CMS1500_LLM_SPECS


def _cms1500_service_lines_llm_spec(spec: SchemaSpec) -> SchemaSpec:
    """Box 24 service lines, extracted by the LLM directly.

    Only used for native/born-digital PDFs, which skip OCR entirely and so never
    produce the region markers _cms1500_service_lines() depends on to parse Box 24
    deterministically. Kept as its own call (rather than folded into one of the two
    split scalar schemas) so it doesn't reintroduce the truncation risk the split
    was built to avoid.
    """
    global _CMS1500_SERVICE_LINES_LLM_SPEC
    if _CMS1500_SERVICE_LINES_LLM_SPEC is not None:
        return _CMS1500_SERVICE_LINES_LLM_SPEC

    field = spec.model.model_fields["service_lines"]
    model = create_model(
        "CMS1500ServiceLines",
        __base__=BaseExtraction,
        service_lines=(field.annotation, deepcopy(field)),
    )
    _CMS1500_SERVICE_LINES_LLM_SPEC = SchemaSpec(
        name=spec.name,
        model=model,
        system_prompt=(
            f"{spec.system_prompt} Extract only Box 24's service line rows; no other fields."
        ),
        validators={
            name: validator
            for name, validator in spec.validators.items()
            if name == "service_lines"
        },
        hints=spec.hints,
        zero_is_blank_fields=spec.zero_is_blank_fields.intersection({"service_lines"}),
    )
    return _CMS1500_SERVICE_LINES_LLM_SPEC


def _xactimate_llm_specs(spec: SchemaSpec) -> tuple[SchemaSpec, SchemaSpec]:
    global _XACTIMATE_LLM_SPECS
    if _XACTIMATE_LLM_SPECS is not None:
        return _XACTIMATE_LLM_SPECS

    scalar_definitions = {
        name: (
            model_field.annotation | None,
            Field(default=None, description=model_field.description),
        )
        for name, model_field in spec.model.model_fields.items()
        if name != "line_items"
    }
    line_field = spec.model.model_fields["line_items"]
    scalar_model = create_model(
        "XactimateSummaryExtraction",
        __base__=BaseExtraction,
        **scalar_definitions,
    )
    line_model = create_model(
        "XactimatePageLineExtraction",
        __base__=BaseExtraction,
        line_items=(
            line_field.annotation,
            Field(default_factory=list, description=line_field.description),
        ),
    )
    scalar_spec = SchemaSpec(
        name=spec.name,
        model=scalar_model,
        system_prompt=(
            f"{spec.system_prompt} Extract document-level summary fields only; line items are "
            "parsed separately and must not be returned in this pass."
        ),
        validators={
            name: validator
            for name, validator in spec.validators.items()
            if name != "line_items"
        },
        hints=spec.hints,
        zero_is_blank_fields=spec.zero_is_blank_fields - {"line_items"},
    )
    line_spec = SchemaSpec(
        name=spec.name,
        model=line_model,
        system_prompt=(
            f"{spec.system_prompt} This is one page of a multi-page estimate. Extract only this "
            "page's line items; do not return document-level summary fields."
        ),
        validators=(
            {"line_items": spec.validators["line_items"]}
            if "line_items" in spec.validators
            else {}
        ),
        hints=spec.hints,
    )
    _XACTIMATE_LLM_SPECS = (scalar_spec, line_spec)
    return _XACTIMATE_LLM_SPECS


def _render_cms1500_regions(source: Path, out_dir: Path) -> list[tuple[str, Path]]:
    """Render overlapping bands from the standardized CMS-1500 page layout.

    Whole-page OCR can lose the dense six-row Box 24 table even when every value is
    legible. The form geometry is standardized, so overlapping proportional bands
    give the OCR model enough resolution and context without tying the crop to one
    particular image size.
    """
    import fitz

    doc = fitz.open(str(source))
    try:
        page = doc[0]
        source_pixmap = fitz.Pixmap(str(source))
        zoom = source_pixmap.width / page.rect.width
        source_pixmap = None

        rendered: list[tuple[str, Path]] = []
        for index, (label, x_start, x_end, y_start, y_end) in enumerate(
            _CMS1500_REGIONS
        ):
            clip = fitz.Rect(
                page.rect.width * x_start,
                page.rect.height * y_start,
                page.rect.width * x_end,
                page.rect.height * y_end,
            )
            region_zoom = zoom * (4 if x_end - x_start < 0.5 else 1)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(region_zoom, region_zoom), clip=clip, alpha=False
            )
            path = out_dir / f"cms1500-region-{index}.png"
            pixmap.save(str(path))
            rendered.append((label, path))
        return rendered
    finally:
        doc.close()


def _cms1500_tax_id_type_from_image(source: Path) -> str | None:
    """Read the standardized Box 25 SSN/EIN checkboxes from image pixels.

    OCR frequently transcribes both the empty outline and the marked box as an X.
    Comparing dark-pixel counts inside the two checkbox interiors distinguishes the
    actual mark without relying on the OCR text.
    """
    import fitz

    pixmap = fitz.Pixmap(str(source))

    def dark_pixels(bounds: tuple[float, float, float, float]) -> int:
        x0, y0, x1, y1 = bounds
        count = 0
        for y in range(int(pixmap.height * y0), int(pixmap.height * y1)):
            for x in range(int(pixmap.width * x0), int(pixmap.width * x1)):
                if min(pixmap.pixel(x, y)[:3]) < 160:
                    count += 1
        return count

    ssn = dark_pixels((0.209, 0.860, 0.234, 0.880))
    ein = dark_pixels((0.240, 0.860, 0.266, 0.880))
    if max(ssn, ein) < 5 or max(ssn, ein) < min(ssn, ein) * 1.5:
        return None
    return "SSN" if ssn > ein else "EIN"


def _cms1500_region_text(source: Path) -> str | None:
    """Return layout-preserving OCR text for a CMS-1500 image when available.

    LightOn produces useful HTML/Markdown tables for focused form regions, while a
    whole-page call on the same dense form can omit Box 24. If the configured OCR
    stack does not include LightOn, or any region fails, extraction falls back to
    doc-intel's normal source path instead of turning an optional enhancement into a
    processing failure.
    """
    from doc_intel.config import OCR_FALLBACK_PROVIDERS, OCR_PROVIDER

    if "lighton" not in {OCR_PROVIDER, *OCR_FALLBACK_PROVIDERS}:
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="claimflow-cms1500-") as tmp:
            regions = _render_cms1500_regions(source, Path(tmp))
            backend = get_backend("lighton")

            def ocr_region(item: tuple[str, Path]) -> tuple[str, str]:
                label, path = item
                return label, backend.process_page(str(path), 0).text.strip()

            with ThreadPoolExecutor(max_workers=len(regions)) as pool:
                results = list(pool.map(ocr_region, regions))
    except Exception as exc:
        logger.warning("CMS-1500 regional OCR unavailable: %s", exc)
        return None

    if any(not text for _, text in results):
        return None

    sections: list[str] = []
    for label, text in results:
        # LightOn occasionally continues after a complete top-region HTML table
        # with repeated synthetic headings. The first table contains every field in
        # that crop; discarding the repetition keeps the extraction context focused.
        if label == "patient and insured" and "</table>" in text:
            text = text.split("</table>", 1)[0] + "</table>"
        sections.append(f"===== CMS-1500 {label.upper()} REGION =====\n{text}")
    tax_id_type = _cms1500_tax_id_type_from_image(source)
    if tax_id_type:
        sections.append("===== CMS-1500 DETECTED TAX ID TYPE =====\n" + tax_id_type)
    return "\n\n".join(sections)


def _normalize_cms1500_date(value: str | None) -> str | None:
    """Expand the CMS form's printed two-digit year into MMDDYYYY."""
    if not value:
        return value
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 6:
        return digits if len(digits) == 8 else value
    year = int(digits[-2:])
    century = "19" if year >= 50 else "20"
    return f"{digits[:4]}{century}{digits[4:]}"


def _cms1500_service_lines(text: str) -> list[dict]:
    """Parse well-formed Box 24 Markdown rows emitted by regional OCR.

    LightOn preserves the standardized table columns reliably in a focused crop,
    but a general LLM can still shift C (EMG), D (modifiers), and E (diagnosis
    pointer) by one cell. Reading the pipe-delimited row deterministically keeps the
    values aligned with the printed column headers.
    """
    marker = "===== CMS-1500 DIAGNOSES AND SERVICE LINES REGION ====="
    if marker not in text:
        return []
    region = text.split(marker, 1)[1].split(
        "===== CMS-1500 PROVIDER AND TOTALS REGION =====", 1
    )[0]

    rows: list[dict] = []
    for line in region.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [re.sub(r"<[^>]+>", "", cell).strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 20 or not cells[0].isdigit():
            continue
        try:
            date_of_service = _normalize_cms1500_date("".join(cells[1:4]))
            charges = float(cells[15].replace(",", ""))
            units = int(float(cells[16]))
        except (TypeError, ValueError):
            continue
        if not date_of_service or not cells[9] or not cells[14]:
            continue
        rows.append(
            {
                "cpt_code": cells[9],
                "date_of_service": date_of_service,
                "service_to_date": _normalize_cms1500_date("".join(cells[4:7])),
                "place_of_service": cells[7],
                "emergency_indicator": cells[8] or None,
                "diagnosis_pointer": cells[14],
                "charges": charges,
                "units": units,
                "epsdt_family_plan": cells[17] or None,
                "rendering_provider_id_qualifier": cells[18] or None,
                "rendering_provider_npi": cells[19] or None,
            }
        )
    return rows


def _cms1500_box_33a(text: str) -> str | None:
    marker = "===== CMS-1500 PROVIDER AND TOTALS REGION ====="
    if marker not in text:
        return None
    provider_region = text.split(marker, 1)[1]
    values = re.findall(r"\ba[.]?\s+(\d[A-Za-z0-9-]{2,})", provider_region)
    return values[-1] if values else None


def _cms1500_html_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in re.findall(
        r"<tr[^>]*>(.*?)</tr>", text, flags=re.IGNORECASE | re.DOTALL
    ):
        cells = [
            unescape(re.sub(r"<[^>]+>", " ", cell)).strip()
            for cell in re.findall(
                r"<t[dh][^>]*>(.*?)</t[dh]>",
                row,
                flags=re.IGNORECASE | re.DOTALL,
            )
        ]
        rows.append([re.sub(r"\s+", " ", cell) for cell in cells])
    return rows


def _complete_provider_addresses(data: dict, text: str) -> None:
    marker = "===== CMS-1500 PROVIDER AND TOTALS REGION ====="
    if marker not in text:
        return
    provider_region = text.split(marker, 1)[1]
    rows = _cms1500_html_rows(provider_region)
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if any(
                cell.upper().startswith("31. SIGNATURE OF PHYSICIAN") for cell in row
            )
        ),
        None,
    )
    if header_index is not None and len(rows) > header_index + 3:
        header = rows[header_index]
        names = rows[header_index + 1]
        streets = rows[header_index + 2]
        dates_and_cities = rows[header_index + 3]
        if len(names) >= 3 and len(streets) >= 3 and len(dates_and_cities) >= 3:
            signature_name = names[0] or None
            data.update(
                {
                    "physician_signature_name": signature_name,
                    "physician_signature_date": _normalize_cms1500_date(
                        dates_and_cities[0]
                    ),
                    "service_facility_name": names[1] or None,
                    "service_facility_address": "\n".join(
                        part for part in (streets[1], dates_and_cities[1]) if part
                    )
                    or None,
                    "billing_provider_name": names[2] or None,
                    "billing_provider_address": "\n".join(
                        part for part in (streets[2], dates_and_cities[2]) if part
                    )
                    or None,
                }
            )
            if signature_name:
                data["signature_on_file"] = True
            data["service_date"] = data["physician_signature_date"]
        phone = re.search(
            r"[(]\d{3}[)]\s*\d{3}-\d{4}", " ".join(header), flags=re.IGNORECASE
        )
        if phone:
            data["billing_provider_phone"] = phone.group(0)

    city_lines = [
        cell
        for row in rows
        for cell in row
        if re.fullmatch(
            r"[A-Za-z][A-Za-z ,.']*(?:,\s*|\s+)[A-Z]{2}\s+\d{5}(?:-\d{4})?",
            cell,
        )
    ]
    service_city = next((line for line in city_lines if "," in line), None)
    billing_city = next((line for line in city_lines if line != service_city), None)
    for field, city in (
        ("service_facility_address", service_city),
        ("billing_provider_address", billing_city),
    ):
        address = data.get(field)
        if address and city and city not in address:
            data[field] = f"{address}\n{city}"


def _cms1500_focused_fields(text: str) -> dict:
    fields: dict = {}
    diagnosis_marker = "===== CMS-1500 DIAGNOSIS INDICATOR REGION ====="
    tax_marker = "===== CMS-1500 TAX ID TYPE REGION ====="
    if diagnosis_marker in text:
        diagnosis_region = text.split(diagnosis_marker, 1)[1].split(tax_marker, 1)[0]
        indicator = re.search(
            r"<th>\s*(?:ICD|ICO|1CO)\s+Ind[.]?\s*</th>\s*<th>\s*([A-Za-z0-9]+)\s*</th>",
            diagnosis_region,
            flags=re.IGNORECASE,
        )
        if indicator:
            fields["diagnosis_code_indicator"] = indicator.group(1)

    if tax_marker in text:
        rows = _cms1500_html_rows(text.split(tax_marker, 1)[1])
        for row_index, row in enumerate(rows[:-1]):
            ssn_column = next(
                (column for column, value in enumerate(row) if value.upper() == "SSN"),
                None,
            )
            if ssn_column is None:
                continue
            checked_row = rows[row_index + 1]
            checked_column = next(
                (
                    column
                    for column, value in enumerate(checked_row)
                    if "X" in value.upper()
                ),
                None,
            )
            if checked_column is not None:
                fields["federal_tax_id_type"] = (
                    "SSN" if checked_column == ssn_column else "EIN"
                )
    detected_tax_marker = "===== CMS-1500 DETECTED TAX ID TYPE ====="
    if detected_tax_marker in text:
        detected = text.split(detected_tax_marker, 1)[1].strip().splitlines()[0]
        if detected in {"SSN", "EIN"}:
            fields["federal_tax_id_type"] = detected
    return fields


def _cms1500_box_1a_is_blank(top_region: str) -> bool:
    """Box 1a (INSURED'S I.D. NUMBER) has no line drawn under the label on some
    forms, so a blank box renders as just the label with nothing after it. The
    LLM sometimes fills it anyway by copying a nearby name or ID, so check the
    actual cell content deterministically rather than trust the model's guess.
    """
    match = re.search(
        r"<td[^>]*>((?:(?!</td>).)*1a[.](?:(?!</td>).)*)</td>",
        top_region,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return False
    cell = unescape(re.sub(r"<[^>]+>", "\n", match.group(1)))
    remaining = re.sub(
        r"1a[.]\s*INSURED'S\s*I\.?D\.?\s*NUMBER|\(For Program in Item 1\)",
        "",
        cell,
        flags=re.IGNORECASE,
    )
    return not remaining.strip()


def _correct_cms1500_result(result, regional_text: str) -> None:
    """Apply deterministic CMS layout facts and keep field rows in sync."""
    data = dict(result.data)
    for field in (
        "patient_dob",
        "insured_dob",
        "patient_signature_date",
        "date_of_current_illness",
        "other_date",
        "unable_to_work_from",
        "unable_to_work_to",
        "hospitalization_from",
        "hospitalization_to",
        "physician_signature_date",
        "service_date",
    ):
        data[field] = _normalize_cms1500_date(data.get(field))

    if data.get("physician_signature_date") is None:
        data["physician_signature_date"] = data.get("service_date")
    if data.get("service_date") is None:
        data["service_date"] = data.get("physician_signature_date")

    referring_name = data.get("referring_provider_name")
    if referring_name and " " in referring_name:
        qualifier, name = referring_name.split(" ", 1)
        if (
            re.fullmatch(r"[A-Za-z0-9]{2}", qualifier)
            and (qualifier.isupper() or qualifier.islower())
            and "," in name
        ):
            data["referring_provider_qualifier"] = qualifier
            data["referring_provider_name"] = name

    top_marker = "===== CMS-1500 PATIENT AND INSURED REGION ====="
    claim_marker = "===== CMS-1500 CLAIM DETAILS REGION ====="
    top_region = ""
    if top_marker in regional_text:
        top_region = regional_text.split(top_marker, 1)[1].split(claim_marker, 1)[0]
    if data.get("insurance_id") == data.get("insured_id") and "1a." not in top_region:
        data["insurance_id"] = None
    if data.get("insurance_id") and data.get("insurance_id") in (
        data.get("patient_name"),
        data.get("insured_name"),
    ):
        data["insurance_id"] = None
    if _cms1500_box_1a_is_blank(top_region):
        data["insurance_id"] = None
    claim_region = ""
    if claim_marker in regional_text:
        claim_region = regional_text.split(claim_marker, 1)[1].split(
            "===== CMS-1500 DIAGNOSES AND SERVICE LINES REGION =====", 1
        )[0]
    insured_signature = re.search(
        r"13[.]\s+INSURED'S.*?SIGNED\s+([A-Za-z0-9][^<\n]*)",
        f"{top_region}\n{claim_region}",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if insured_signature:
        data["insured_signature_on_file"] = True
    accident_state = re.search(
        r"PLACE\s*[(]State[)].*?(?:□|☐)\s*([A-Z]{2})(?:<|\s)",
        top_region,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if accident_state:
        data["auto_accident_state"] = accident_state.group(1).upper()
    qualifier = re.search(
        r"14[.]\s+DATE OF CURRENT.*?QUAL\s+([A-Za-z0-9-]+)",
        claim_region,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if qualifier:
        data["date_of_current_illness_qualifier"] = qualifier.group(1)
    other_date_qualifier = re.search(
        r"15[.]\s+OTHER DATE.*?QUAL\s+([A-Za-z0-9-]+)",
        claim_region,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if other_date_qualifier:
        data["other_date_qualifier"] = other_date_qualifier.group(1)
    referring_provider = re.search(
        r"17[.]\s+NAME OF REFERRING PROVIDER OR OTHER SOURCE\s+"
        r"([A-Za-z0-9]{2})\s+([^\n<]+)",
        claim_region,
        flags=re.IGNORECASE,
    )
    if referring_provider:
        data["referring_provider_qualifier"] = referring_provider.group(1)
        data["referring_provider_name"] = referring_provider.group(2).strip()
    referring_other_id = re.search(
        r"17a\s+([A-Za-z0-9-]+)\s+([A-Za-z0-9-]+)", claim_region, flags=re.IGNORECASE
    )
    if referring_other_id:
        if referring_other_id.group(1).lower() != "17a":
            data["referring_provider_other_id_qualifier"] = referring_other_id.group(1)
        elif data.get("referring_provider_other_id_qualifier", "").lower() == "17a":
            data["referring_provider_other_id_qualifier"] = None
        data["referring_provider_other_id"] = referring_other_id.group(2)
    referring_npi = re.search(
        r"17b\s+NPI\s+([A-Za-z0-9-]+)", claim_region, flags=re.IGNORECASE
    )
    if referring_npi:
        data["referring_provider_npi"] = referring_npi.group(1)
    diagnosis_indicator = re.search(
        r"ICD\s+Ind[.:]?\s+([A-Za-z0-9]+)", claim_region, flags=re.IGNORECASE
    )
    if diagnosis_indicator:
        data["diagnosis_code_indicator"] = diagnosis_indicator.group(1)

    service_lines = _cms1500_service_lines(regional_text)
    if service_lines:
        data["service_lines"] = service_lines
    billing_provider_npi = _cms1500_box_33a(regional_text)
    if billing_provider_npi:
        data["billing_provider_npi"] = billing_provider_npi
    _complete_provider_addresses(data, regional_text)
    data.update(_cms1500_focused_fields(regional_text))

    result.data = data
    for field in result.fields:
        if field.name in data:
            field.value = data[field.name]
            continue
        match = re.fullmatch(r"service_lines\[(\d+)]", field.name)
        if match and int(match.group(1)) < len(data.get("service_lines", [])):
            field.value = data["service_lines"][int(match.group(1))]


def _extract_cms1500_text(
    regional_text: str, spec: SchemaSpec, *, include_service_lines_via_llm: bool = False
):
    llm_specs: tuple[SchemaSpec, ...] = _cms1500_llm_specs(spec)
    if include_service_lines_via_llm:
        llm_specs = (*llm_specs, _cms1500_service_lines_llm_spec(spec))
    with ThreadPoolExecutor(max_workers=len(llm_specs)) as pool:
        results = list(
            pool.map(
                lambda llm_spec: extract(regional_text, llm_spec, classify_doc=False),
                llm_specs,
            )
        )

    successful = [result for result in results if result.status != "error"]
    if not successful:
        return results[0]

    data = {name: value for result in successful for name, value in result.data.items()}
    result = successful[0].model_copy(update={"data": data, "fields": []})
    _correct_cms1500_result(result, regional_text)

    layout = load_source(regional_text)
    fields, overall, status, flagged = score(
        result.data,
        spec=spec,
        source_text=layout.full_text,
        blocks=layout.blocks,
        weights=_doc_intel_config.SIGNAL_WEIGHTS,
        threshold=_doc_intel_config.CONFIDENCE_THRESHOLD,
        null_placeholders=_doc_intel_config.NULL_PLACEHOLDER_VALUES,
    )
    result.fields = fields
    result.overall_confidence = overall
    result.status = status
    result.flagged_fields = flagged
    return result


def _xactimate_line_layouts(
    layout: DocumentLayout, items_per_chunk: int = 3
) -> list[DocumentLayout]:
    line_layouts = []
    for page_number in layout.pages():
        page_text = DocumentLayout(
            blocks=layout.blocks_on_page(page_number), meta=layout.meta
        ).full_text
        item_starts = [
            match.start()
            for match in re.finditer(r"(?<!\d)(?=\d{1,3}[.]\s{2,})", page_text)
        ]
        if not item_starts:
            continue
        prefix = page_text[: item_starts[0]]
        for index in range(0, len(item_starts), items_per_chunk):
            end = (
                item_starts[index + items_per_chunk]
                if index + items_per_chunk < len(item_starts)
                else len(page_text)
            )
            chunk_text = f"{prefix}\n{page_text[item_starts[index] : end]}"
            line_layouts.append(
                DocumentLayout(
                    blocks=[
                        DocumentBlock(
                            text=chunk_text,
                            page=page_number,
                            block_type="table",
                            source="native_pdf",
                        )
                    ],
                    meta={**layout.meta, "pages": 1},
                )
            )
    return line_layouts


def _xactimate_native_line_items(source: str) -> list[dict]:
    """Read the numeric estimate table directly from a native Xactimate PDF.

    Xactimate keeps every item on a consistently aligned text row.  The LLM is
    useful for cleaning up wrapped descriptions, but the native row is the more
    reliable source for line numbers and amounts and avoids silently dropping a
    short section between page breaks.
    """
    path = Path(source)
    if path.suffix.lower() != ".pdf":
        return []

    import fitz

    items = []
    with fitz.open(str(path)) as document:
        for page in document:
            page_text = page.get_text("text", sort=True)
            has_tax_column = bool(
                re.search(r"UNIT (?:COST|PRICE)\s+TAX\s+RCV", page_text, re.IGNORECASE)
            )
            amount_columns = (
                r"\s+([\d,.]+)\s+([\d,.]+)\s+" if has_tax_column else r"\s+([\d,.]+)\s+"
            )
            row_pattern = re.compile(
                r"^\s*(\d{1,3})[.]\s+(.+?)\s{2,}([\d,.]+)\s+([A-Z]{1,5})"
                r"\s+([\d,.]+)" + amount_columns,
                flags=re.MULTILINE,
            )
            for match in row_pattern.finditer(page_text):
                description = " ".join(match.group(2).split())
                if has_tax_column:
                    tax = float(match.group(6).replace(",", ""))
                    replacement_cost = float(match.group(7).replace(",", ""))
                    total = round(replacement_cost - tax, 2)
                else:
                    total = float(match.group(6).replace(",", ""))
                items.append(
                    {
                        "line_number": int(match.group(1)),
                        "category": description,
                        "description": description,
                        "quantity": float(match.group(3).replace(",", "")),
                        "unit": match.group(4),
                        "unit_cost": float(match.group(5).replace(",", "")),
                        "total": total,
                    }
                )
    return items


def _extract_xactimate_pages(source: str, spec: SchemaSpec) -> ExtractionResult:
    layout = load_source(source)
    scalar_spec, line_spec = _xactimate_llm_specs(spec)
    page_layouts = [
        DocumentLayout(
            blocks=layout.blocks_on_page(page_number),
            meta={**layout.meta, "pages": 1},
        )
        for page_number in layout.pages()
    ]
    line_layouts = _xactimate_line_layouts(layout)
    if not line_layouts:
        # Some Xactimate templates print the line-item table without leading item
        # numbers, so the numbered-row chunker above finds nothing to split on. Ask
        # the LLM to read the whole page's table directly instead of skipping line
        # items entirely.
        line_layouts = page_layouts
    client = get_client()

    jobs = [
        *((page_layout, scalar_spec) for page_layout in page_layouts),
        *((line_layout, line_spec) for line_layout in line_layouts),
    ]

    def extract_job(job: tuple[DocumentLayout, SchemaSpec]) -> dict:
        job_layout, job_spec = job
        try:
            return _extract_layout(
                job_layout,
                job_spec,
                client,
                chunked=job_spec is line_spec,
            )
        except Exception as exc:
            logger.warning(
                "Xactimate %s extraction unavailable: %s",
                (
                    f"page {job_layout.pages()[0]}"
                    if job_spec is line_spec and job_layout.pages()
                    else "summary"
                ),
                exc,
            )
            return {}

    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
        page_results = list(pool.map(extract_job, jobs))

    line_results = page_results[len(page_layouts) :]
    retry_jobs = []
    for line_layout, line_result in zip(line_layouts, line_results, strict=True):
        expected_numbers = {
            int(number)
            for number in re.findall(
                r"(?<!\d)(\d{1,3})[.]\s{2,}", line_layout.full_text
            )
        }
        returned_numbers = {
            item.get("line_number")
            for item in line_result.get("line_items", [])
            if item.get("line_number") is not None
        }
        if expected_numbers - returned_numbers:
            retry_jobs.append((line_layout, line_spec))
    if retry_jobs:
        with ThreadPoolExecutor(max_workers=min(4, len(retry_jobs))) as pool:
            page_results.extend(pool.map(extract_job, retry_jobs))

    summary_labels = {
        "line_item_total": ("line item total",),
        "overhead": ("overhead",),
        "profit": ("profit",),
        "material_sales_tax": ("material sales tax",),
        "total_replacement_cost": ("replacement cost value",),
        "depreciation": (
            "less non-recoverable depreciation",
            "less depreciation",
        ),
        "actual_cash_value": ("actual cash value",),
    }
    for page_result, page_layout in zip(
        page_results[: len(page_layouts)], page_layouts, strict=True
    ):
        page_text = page_layout.full_text.lower()
        for field, labels in summary_labels.items():
            if not any(label in page_text for label in labels):
                page_result[field] = None

    data = merge_extractions(page_results, source_text=layout.full_text)
    numbered_items: dict[int, dict] = {
        item["line_number"]: item
        for item in data.get("line_items", [])
        if item.get("line_number") is not None
    }
    for native_item in _xactimate_native_line_items(source):
        line_number = native_item["line_number"]
        if line_number in numbered_items:
            numbered_items[line_number].update(
                {
                    name: native_item[name]
                    for name in ("quantity", "unit", "unit_cost", "total")
                }
            )
        else:
            numbered_items[line_number] = native_item
    if numbered_items:
        data["line_items"] = [
            numbered_items[number] for number in sorted(numbered_items)
        ]
    line_totals = re.search(
        r"line item totals:\s+\S+\s+([\d,.]+)\s+([\d,.]+)"
        r"\s+([\d,.]+)\s+([\d,.]+)",
        layout.full_text,
        flags=re.IGNORECASE,
    )
    if line_totals:
        data["depreciation"] = float(line_totals.group(3).replace(",", ""))
        data["actual_cash_value"] = float(line_totals.group(4).replace(",", ""))
    else:
        depreciation = re.search(
            r"less depreciation(?:\s*\([^)]*\))?[*\s|:]*\(?\$?([\d,.]+)",
            layout.full_text,
            flags=re.IGNORECASE,
        )
        if depreciation:
            data["depreciation"] = float(depreciation.group(1).replace(",", ""))
    if (
        data.get("actual_cash_value") is None
        and data.get("total_replacement_cost") is not None
        and data.get("depreciation") is not None
    ):
        # Fallback only — derive ACV when extraction found no printed value. When a
        # value WAS extracted, keep it as printed: acv_check exists to catch a
        # printed ACV that doesn't reconcile with RCV minus depreciation, which this
        # would otherwise silently paper over before validation ever saw it.
        data["actual_cash_value"] = round(
            data["total_replacement_cost"] - data["depreciation"], 2
        )
    claim_number = data.get("claim_number")
    labeled_claims = re.findall(
        r"(?:claim|reference)(?:\s+number|\s+no[.]?|\s*#)\s*[:#]?\s*([A-Za-z0-9-]+)",
        layout.full_text,
        flags=re.IGNORECASE,
    )
    if claim_number and not any(
        str(claim_number).lower() == value.lower() for value in labeled_claims
    ):
        data["claim_number"] = None
    property_address = data.get("property_address")
    labeled_addresses = re.findall(
        r"(?:property(?:\s+(?:location|address))?|(?:risk|loss|insured)"
        r"\s+(?:location|address))\s*[:#]?\s*([^\n|]+)",
        layout.full_text,
        flags=re.IGNORECASE,
    )
    if property_address and not any(
        str(property_address).lower() in value.lower()
        or value.lower() in str(property_address).lower()
        for value in labeled_addresses
    ):
        data["property_address"] = None
    has_loss_date_label = re.search(
        r"date of loss|loss date", layout.full_text, flags=re.IGNORECASE
    )
    has_xactimate_header_date = re.search(
        r"\b\d{1,2}/\d{1,2}/\d{4}\s+Page\s*:",
        layout.full_text,
        flags=re.IGNORECASE,
    )
    if data.get("date_of_loss") and not (
        has_loss_date_label or has_xactimate_header_date
    ):
        data["date_of_loss"] = None
    conflicted = frozenset(
        find_conflicted_fields(page_results, source_text=layout.full_text)
    )
    fields, overall, status, flagged = score(
        data,
        spec=spec,
        source_text=layout.full_text,
        blocks=layout.blocks,
        weights=_doc_intel_config.SIGNAL_WEIGHTS,
        threshold=_doc_intel_config.CONFIDENCE_THRESHOLD,
        null_placeholders=_doc_intel_config.NULL_PLACEHOLDER_VALUES,
        conflicted_fields=conflicted,
    )
    return ExtractionResult(
        schema_name=spec.name,
        data=data,
        fields=fields,
        overall_confidence=overall,
        status=status,
        flagged_fields=flagged,
        source_meta=layout.meta,
    )


def _null_placeholder_fields(result) -> None:
    """Keep the public data projection consistent with placeholder field status."""
    for field in result.fields:
        if (
            field.parent_field is None
            and field.field_status == "redacted_or_placeholder"
        ):
            result.data[field.name] = None
            field.value = None


def _correct_eob_payer(result, source_text: str) -> None:
    payer = result.data.get("payer_name")
    if not payer:
        return
    labeled_payers = re.findall(
        r"(?:payer|insurance company|health plan|plan name)(?:\s+name)?\s*[:#]\s*([^\n|]+)",
        source_text,
        flags=re.IGNORECASE,
    )
    if any(payer.lower() in value.lower() for value in labeled_payers):
        return

    result.data["payer_name"] = None
    for field in result.fields:
        if field.name == "payer_name" and field.parent_field is None:
            field.value = None
            field.confidence = 0.3
            field.grounded = False
            field.evidence = None
            field.field_status = "not_found"
            break
    top_fields = [field for field in result.fields if field.parent_field is None]
    if top_fields:
        result.overall_confidence = round(
            sum(field.confidence for field in top_fields) / len(top_fields), 3
        )


def _correct_sba_form_413_widgets(result, source: Path) -> None:
    if source.suffix.lower() != ".pdf":
        return
    import fitz

    field_names = {
        "TotalAssets": "total_assets",
        "TotalLiabilities": "total_liabilities",
        "Net Worth": "net_worth",
    }
    widget_values: dict[str, tuple[float, int, str]] = {}
    with fitz.open(str(source)) as document:
        for page_number, page in enumerate(document, start=1):
            for widget in page.widgets() or []:
                name = field_names.get(widget.field_name)
                if name is None or widget.field_value in (None, ""):
                    continue
                try:
                    value = float(str(widget.field_value).replace(",", ""))
                except ValueError:
                    continue
                widget_values[name] = (value, page_number, widget.field_name)

    for name, (value, page_number, widget_name) in widget_values.items():
        result.data[name] = value
        for field in result.fields:
            if field.name == name and field.parent_field is None:
                field.value = value
                field.confidence = 1.0
                field.grounded = True
                field.valid = True
                field.field_status = "found"
                field.evidence = Evidence(
                    page=page_number,
                    text=f"{widget_name}: {value:g}",
                    block_type="form_field",
                    source_type="native_pdf",
                    extraction_method="acroform_widget",
                )
                break
    top_fields = [field for field in result.fields if field.parent_field is None]
    if top_fields:
        result.overall_confidence = round(
            sum(field.confidence for field in top_fields) / len(top_fields), 3
        )
        result.flagged_fields = [
            field.name
            for field in top_fields
            if field.confidence < _doc_intel_config.CONFIDENCE_THRESHOLD
        ]


def _cms1500_extract_fn(source: str, spec: SchemaSpec) -> ExtractionResult:
    path = Path(source)
    if path.suffix.lower() in _CMS1500_IMAGE_SUFFIXES:
        regional_text = _cms1500_region_text(path)
        if regional_text:
            return _extract_cms1500_text(regional_text, spec)
    elif path.suffix.lower() == ".pdf":
        # Native/born-digital PDFs skip OCR but must still use the split schema —
        # the full 76-field CMS1500 model in one completion can hit the model's
        # length ceiling on dense documents, the same truncation risk the split
        # schema was built to avoid for the OCR path (_cms1500_llm_specs). Box 24
        # normally comes from the OCR-region-marker parser below, which has no
        # markers to work with here, so the LLM extracts service_lines directly
        # instead (include_service_lines_via_llm).
        return _extract_cms1500_text(source, spec, include_service_lines_via_llm=True)
    return extract(source, spec, classify_doc=True)


# Imported here (rather than at module top) so that claimflow.domains — which wires
# this module's extract_fn/extraction_hook callables onto domain registrations as a
# side effect of import — sees a fully-defined module instead of a partially
# initialized one when the two modules import each other.
import claimflow.domains  # noqa: F401, E402
from claimflow.domains.base import get as get_domain  # noqa: E402


def extract_node(state: ClaimState) -> dict:
    domain_key = state.get("domain")
    if not domain_key:
        return {
            "error": "No supported domain detected in package",
            "extraction_status": "error",
        }

    domain = get_domain(domain_key)
    if domain is None:
        return {"error": f"Unknown domain: {domain_key}", "extraction_status": "error"}

    claim_doc = next(
        (d for d in state["documents"] if d["doc_type"] == domain_key),
        None,
    )
    if claim_doc is None:
        detected = state.get("detected_domain")
        hint = (
            f" (documents appear to be {detected})"
            if detected and detected != domain_key
            else ""
        )
        return {
            "error": f"No {domain_key} document found in package{hint}",
            "extraction_status": "error",
        }

    try:
        source: str = claim_doc["path"]
        path = Path(source)
        if domain.extract_fn is not None:
            result = domain.extract_fn(source, domain.spec)
        else:
            result = extract(source, domain.spec, classify_doc=True)
        _null_placeholder_fields(result)
        if domain.extraction_hook is not None and result.status != "error":
            if domain.doc_type == "eob":
                # EOB's hook cross-checks the payer against the document body, so it
                # needs the loaded full text rather than the file path.
                domain.extraction_hook(result, load_source(source).full_text)
            else:
                domain.extraction_hook(result, path)
    except Exception as exc:
        return {"error": str(exc), "extraction_status": "error"}

    secondary_extractions = _extract_secondary_documents(state, domain_key)

    return {
        "extraction_data": result.data,
        "extraction_fields": [f.model_dump() for f in result.fields],
        "extraction_status": result.status,
        "extraction_overall_confidence": result.overall_confidence,
        "secondary_extractions": secondary_extractions,
    }


def _extract_secondary_documents(state: ClaimState, primary_domain_key: str) -> list[dict]:
    """
    Extract every other document in the package that has its own registered
    domain pack (e.g. an EOB alongside the primary CMS-1500 claim form).
    Sequential, not parallel — these are whole-document extractions, not the
    page-level work ThreadPoolExecutor is used for elsewhere in this module,
    and a demo-sized package (a handful of documents) doesn't need it.
    One failing document is caught and recorded per-entry; it does not fail
    the run.
    """
    results: list[dict] = []
    for doc in state["documents"]:
        doc_type = doc["doc_type"]
        if doc_type == primary_domain_key:
            continue
        sub_domain = get_domain(doc_type)
        if sub_domain is None:
            continue

        entry: dict = {
            "doc_type": doc_type,
            "filename": Path(doc["path"]).name,
        }
        try:
            source = doc["path"]
            if sub_domain.extract_fn is not None:
                sub_result = sub_domain.extract_fn(source, sub_domain.spec)
            else:
                sub_result = extract(source, sub_domain.spec, classify_doc=True)
            _null_placeholder_fields(sub_result)
            if sub_domain.extraction_hook is not None and sub_result.status != "error":
                if sub_domain.doc_type == "eob":
                    sub_domain.extraction_hook(
                        sub_result, load_source(source).full_text
                    )
                else:
                    sub_domain.extraction_hook(sub_result, Path(source))
            entry.update(
                {
                    "data": sub_result.data,
                    "fields": [f.model_dump() for f in sub_result.fields],
                    "status": sub_result.status,
                    "overall_confidence": sub_result.overall_confidence,
                    "error": None,
                }
            )
        except Exception as exc:
            entry.update(
                {
                    "data": None,
                    "fields": [],
                    "status": "error",
                    "overall_confidence": None,
                    "error": str(exc),
                }
            )
        results.append(entry)
    return results
