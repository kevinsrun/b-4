from __future__ import annotations

import re
from dataclasses import dataclass

from .models import (
    FOCUS_VARIABLES,
    BacteriocinIdentity,
    EvidenceProvenance,
    EvidenceRecord,
    ExperimentalConditions,
    LiteratureQuery,
    Measurement,
    SourceDocument,
    TargetIdentity,
)
from .normalization import normalize_concentration, normalize_time, observed_quantity

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
# Molar units are matched case-sensitively, inside an otherwise case-insensitive
# pattern. Case-folding them collides with the length units that abstracts are
# full of: nM/nm (particle diameter), mM/mm (zone width), µM/um. A diameter read
# as a dose is worse than a missed dose, so the molar units keep their capital M.
MOLAR_UNITS = r"(?-i:nM|[uµμ]M|mM)"
MASS_UNITS = r"ng\s*/\s*mL|[uµμ]g\s*/\s*(?:mL|L)|mg\s*/\s*(?:mL|L)|g\s*/\s*L"
ACTIVITY_UNITS = r"AU\s*/\s*mL|IU\s*/\s*mL"
CONCENTRATION_UNITS = rf"{MASS_UNITS}|{MOLAR_UNITS}|{ACTIVITY_UNITS}"
CONCENTRATION_RE = re.compile(
    rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{CONCENTRATION_UNITS})",
    re.I,
)
PH_RE = re.compile(r"\bpH\s*(?:of\s*)?(?P<value>\d+(?:\.\d+)?)", re.I)
TEMP_RE = re.compile(r"(?P<value>-?\d+(?:\.\d+)?)\s*(?:°\s*)?(?P<unit>C|K|F)\b", re.I)
TIME_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>hours?|hrs?|h|minutes?|mins?|days?|d)\b", re.I)
CFU_RE = re.compile(
    r"(?P<value>(?:\d+(?:\.\d+)?\s*[x×]\s*)?10\s*\^\s*\d+|\d+(?:\.\d+)?)\s*(?P<unit>CFU\s*/\s*(?:mL|ml|g))",
    re.I,
)
OD_RE = re.compile(r"\bOD(?:600|\s*600)?\s*(?:of|=|:)??\s*(?P<value>\d+(?:\.\d+)?)", re.I)
SEQUENCE_RE = re.compile(r"(?:amino[- ]acid\s+sequence|sequence)\s*(?:is|:|=)\s*([ACDEFGHIKLMNPQRSTVWY]{8,})", re.I)
ZONE_RE = re.compile(
    r"(?:inhibition\s+zone|zone\s+of\s+inhibition)\D{0,20}(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm|cm)", re.I
)
MIC_RE = re.compile(
    rf"\bMIC\D{{0,16}}(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{CONCENTRATION_UNITS})",
    re.I,
)
LOG_REDUCTION_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*[- ]?log(?:10)?\s+(?:CFU\s+)?reduction", re.I)
PERCENT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%\s*(?:growth\s+)?(?:inhibition|reduction|survival)", re.I)

ASSAYS = {
    "broth microdilution": "broth_microdilution",
    "agar well diffusion": "agar_well_diffusion",
    "disc diffusion": "disc_diffusion",
    "disk diffusion": "disc_diffusion",
    "time-kill": "time_kill",
    "time kill": "time_kill",
    "minimum inhibitory concentration": "mic",
    "mic assay": "mic",
}
MEDIA = {
    "de man rogosa sharpe": "MRS",
    "mrs broth": "MRS broth",
    "mrs agar": "MRS agar",
    "brain heart infusion": "BHI",
    "bhi broth": "BHI broth",
    "tryptic soy broth": "TSB",
    "mueller-hinton broth": "Mueller-Hinton broth",
    "mueller hinton broth": "Mueller-Hinton broth",
    "phosphate-buffered saline": "PBS",
}


# Family and trivial names used to decide whether a measurement describes a
# bacteriocin at all. Without this the extractor attributes any antimicrobial
# number in any abstract -- a silver-nanoparticle inhibition zone, say -- to an
# unnamed bacteriocin, which reads as evidence but names no agent.
BACTERIOCIN_TERMS = (
    "bacteriocin",
    "bacteriocins",
    "colicin",
    "divercin",
    "enterocin",
    "epidermin",
    "gallidermin",
    "gassericin",
    "lactococcin",
    "lacticin",
    "lactacin",
    "leucocin",
    "mersacidin",
    "microcin",
    "mutacin",
    "nisin",
    "nukacin",
    "pediocin",
    "pentocin",
    "plantaricin",
    "sakacin",
    "salivaricin",
    "subtilin",
    "subtilosin",
    "thuricin",
    "warnerin",
)
BACTERIOCIN_TERM_RE = re.compile(rf"(?<!\w)({'|'.join(BACTERIOCIN_TERMS)})(?!\w)", re.I)
# A trailing variant token: "A" in "nisin A", "PA-1" in "pediocin PA-1",
# "3147" in "lacticin 3147".
VARIANT_TOKEN_RE = re.compile(r"^(?:[A-Za-z]|[A-Za-z]{0,3}[- ]?\d+)$")


@dataclass(frozen=True)
class ExtractedMeasurement:
    measurement: Measurement
    sentence: str
    attributed_name: str | None = None


def _surface_forms(name: str) -> list[str]:
    """Acceptable spellings of a queried bacteriocin, most specific first.

    A query for ``nisin A`` should not discard every abstract that writes
    ``nisin``; the base name is accepted, and the caller records which spelling
    actually occurred rather than asserting the variant.
    """
    forms = [name]
    tokens = name.split()
    if len(tokens) > 1 and VARIANT_TOKEN_RE.match(tokens[-1]):
        base = " ".join(tokens[:-1])
        if base:
            forms.append(base)
    return forms


def _detect_bacteriocin(sentence: str) -> str | None:
    """Name the bacteriocin a sentence is about, or ``None`` if it names none."""
    match = BACTERIOCIN_TERM_RE.search(re.sub(r"<[^>]+>", " ", sentence))
    return match.group(1) if match else None


def _sentence_for(text: str, start: int) -> str:
    cursor = 0
    for sentence in SENTENCE_RE.split(text.strip()):
        end = cursor + len(sentence)
        if cursor <= start <= end:
            return sentence.strip()[:1200]
        cursor = end + 1
    return text.strip()[:1200]


def _first_match(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    return pattern.search(text)


def _conditions(text: str) -> ExperimentalConditions:
    concentration = _first_match(CONCENTRATION_RE, text)
    ph = _first_match(PH_RE, text)
    temperature = _first_match(TEMP_RE, text)
    duration = _first_match(TIME_RE, text)
    cfu = _first_match(CFU_RE, text)
    od = _first_match(OD_RE, text)
    lower = text.lower()
    assay = next((value for key, value in ASSAYS.items() if key in lower), None)
    medium = next((value for key, value in MEDIA.items() if key in lower), None)
    assay_domain = (
        "in_vivo"
        if re.search(r"\bin vivo\b|animal model|murine|mouse model", lower)
        else "in_vitro"
        if re.search(r"\bin vitro\b|broth|agar|culture", lower)
        else "unknown"
    )
    density = None
    if cfu:
        density = observed_quantity(cfu.group("value"), re.sub(r"\s+", "", cfu.group("unit")))
    elif od:
        density = observed_quantity(od.group("value"), "OD600")
    return ExperimentalConditions(
        bacteriocin_concentration=normalize_concentration(concentration.group("value"), concentration.group("unit"))
        if concentration
        else None,
        target_cell_density=density,
        ph=observed_quantity(ph.group("value"), "pH") if ph else None,
        temperature_c=_temperature(temperature) if temperature else None,
        medium=medium,
        incubation_time=normalize_time(duration.group("value"), duration.group("unit")) if duration else None,
        assay_type=assay,
        assay_domain=assay_domain,
    )


def _temperature(match: re.Match[str]):
    value = float(match.group("value"))
    unit = match.group("unit").upper()
    normalized = value if unit == "C" else value - 273.15 if unit == "K" else (value - 32) * 5 / 9
    quantity = observed_quantity(match.group("value"), f"°{unit}")
    return quantity.model_copy(
        update={
            "normalized_value": normalized,
            "normalized_unit": "°C",
            "normalization_note": "Converted to degrees Celsius.",
        }
    )


def _contains_term(text: str, term: str | None) -> bool:
    if not term:
        return False
    plain = re.sub(r"<[^>]+>", " ", text)
    normalized = re.sub(r"\s+", " ", plain)
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized, re.I) is not None


def _measurement_is_bound_to_candidate(sentence: str, matched_text: str, candidate_name: str | None) -> bool:
    if not candidate_name:
        return True
    lower_sentence = sentence.casefold()
    lower_candidate = candidate_name.casefold()
    lower_match = matched_text.casefold()
    measurement_start = lower_sentence.find(lower_match)
    if measurement_start < 0:
        return False

    match_end = measurement_start + len(lower_match)
    for candidate_match in re.finditer(rf"(?<!\w){re.escape(lower_candidate)}(?!\w)", lower_sentence):
        if measurement_start <= candidate_match.start() < match_end:
            return True
        if candidate_match.start() < measurement_start:
            intervening = lower_sentence[candidate_match.end() : measurement_start]
            if len(intervening) <= 100 and not re.search(
                r"\b(?:peptide|compound|variant|analogue|analog|derivative)\b[^.;:]{0,40}\b(?:exhibited|showed|had)\b",
                intervening,
            ):
                return True
    return False


def _measurements(
    text: str,
    candidate_name: str | None,
    target_organism: str | None,
    unattributed: list[str] | None = None,
) -> list[ExtractedMeasurement]:
    found: list[ExtractedMeasurement] = []
    patterns = (
        (MIC_RE, "minimum_inhibitory_concentration", lambda m: (float(m.group("value")), m.group("unit"))),
        (ZONE_RE, "inhibition_zone", lambda m: (float(m.group("value")), m.group("unit"))),
        (LOG_REDUCTION_RE, "log_reduction", lambda m: (float(m.group("value")), "log10 CFU")),
        (PERCENT_RE, "percent_response", lambda m: (float(m.group("value")), "%")),
    )
    occupied: list[tuple[int, int]] = []
    for pattern, measurement_type, converter in patterns:
        for match in pattern.finditer(text):
            if any(a <= match.start() < b for a, b in occupied):
                continue
            value, unit = converter(match)
            sentence = _sentence_for(text, match.start())
            if candidate_name:
                if not _measurement_is_bound_to_candidate(sentence, match.group(0), candidate_name):
                    continue
                attributed = candidate_name
            else:
                # No bacteriocin was requested, so the sentence has to name one
                # itself. Otherwise the measurement belongs to some other agent
                # and is not bacteriocin evidence.
                attributed = _detect_bacteriocin(sentence)
                if attributed is None:
                    if unattributed is not None:
                        unattributed.append(match.group(0))
                    continue
            found.append(
                ExtractedMeasurement(
                    Measurement(
                        type=measurement_type,
                        value=value,
                        unit=unit,
                        original_text=match.group(0),
                        data_role="measured",
                    ),
                    sentence,
                    attributed_name=attributed,
                )
            )
            occupied.append(match.span())
    if found:
        return found

    polarity_patterns = (
        (
            r"\b(?:no (?:detectable )?activity against|not active against|did not inhibit|"
            r"resistant to|insensitive to)\b",
            "inactive",
        ),
        (
            r"\b(?:inhibited|was active against|were active against|showed antimicrobial activity against|"
            r"susceptible to|sensitive to)\b",
            "active",
        ),
    )
    for sentence in SENTENCE_RE.split(text.strip()):
        for pattern, value in polarity_patterns:
            match = re.search(pattern, sentence, re.I)
            if not match or not _contains_term(sentence, target_organism):
                continue
            if candidate_name:
                if not _contains_term(sentence, candidate_name):
                    continue
                attributed = candidate_name
            else:
                attributed = _detect_bacteriocin(sentence)
                if attributed is None:
                    if unattributed is not None:
                        unattributed.append(match.group(0))
                    continue
            excerpt = sentence.strip()[:1200]
            return [
                ExtractedMeasurement(
                    Measurement(
                        type="antimicrobial_activity",
                        value=value,
                        original_text=match.group(0),
                        data_role="author-interpretation",
                    ),
                    excerpt,
                    attributed_name=attributed,
                )
            ]
    return []


def _missing(record: EvidenceRecord) -> list[str]:
    values = {
        "bacteriocin_identity": record.bacteriocin.name,
        "bacteriocin_sequence": record.bacteriocin.sequence,
        "target_organism": record.target.organism,
        "target_strain": record.target.strain,
        "antimicrobial_spectrum": None,
        "bacteriocin_concentration": record.conditions.bacteriocin_concentration,
        "target_cell_density": record.conditions.target_cell_density,
        "producer_cell_density": record.conditions.producer_cell_density,
        "growth_phase": record.conditions.growth_phase,
        "ph": record.conditions.ph,
        "temperature_c": record.conditions.temperature_c,
        "medium": record.conditions.medium,
        "ionic_conditions": record.conditions.ionic_conditions or None,
        "incubation_time": record.conditions.incubation_time,
        "assay_type": record.conditions.assay_type,
        "assay_domain": None if record.conditions.assay_domain == "unknown" else record.conditions.assay_domain,
        "resistance_or_susceptibility": record.measurement.value
        if record.measurement.type == "antimicrobial_activity"
        else None,
        "measured_antimicrobial_response": record.measurement if record.measurement.data_role == "measured" else None,
    }
    return [name for name in FOCUS_VARIABLES if values[name] is None]


MIC_MENTION_RE = re.compile(r"\bMICs?\b|\bminimum\s+inhibitory\s+concentrations?\b", re.I)


def extract_document(
    query: LiteratureQuery,
    document: SourceDocument,
    make_id,
    unattributed: list[str] | None = None,
    unparsed: list[str] | None = None,
) -> list[EvidenceRecord]:
    text = document.text
    identity_text = f"{document.source.title}. {text}"
    # A query for "nisin A" is satisfied by a source that says "nisin"; the
    # record then reports the spelling the source used, keeping the requested
    # term as an alias rather than asserting a variant the paper never named.
    matched_name = None
    if query.bacteriocin:
        matched_name = next(
            (form for form in _surface_forms(query.bacteriocin) if _contains_term(identity_text, form)),
            None,
        )
        if matched_name is None:
            return []
    target_present = _contains_term(identity_text, query.target_organism)
    if query.target_organism and not target_present:
        return []

    sequence_match = SEQUENCE_RE.search(text)
    aliases = (
        [query.bacteriocin]
        if query.bacteriocin and matched_name and query.bacteriocin.casefold() != matched_name.casefold()
        else []
    )
    target = TargetIdentity(
        organism=query.target_organism if target_present else None,
        strain=query.target_strain if _contains_term(identity_text, query.target_strain) else None,
    )
    conditions = _conditions(text)
    records: list[EvidenceRecord] = []
    for ordinal, item in enumerate(_measurements(text, matched_name, target.organism, unattributed)):
        bacteriocin = BacteriocinIdentity(
            name=item.attributed_name,
            aliases=aliases,
            sequence=sequence_match.group(1).upper() if sequence_match and item.attributed_name else None,
        )
        confidence = 0.45
        confidence += 0.1 if bacteriocin.name else 0
        confidence += 0.1 if target.organism else 0
        confidence += 0.1 if item.measurement.data_role == "measured" else 0
        confidence += min(0.15, 0.03 * sum(value is not None for value in conditions.model_dump().values()))
        record = EvidenceRecord(
            evidence_id=make_id(document.source.source_id, item.sentence, item.measurement.type, str(ordinal)),
            source=document.source,
            bacteriocin=bacteriocin,
            target=target,
            conditions=conditions,
            measurement=item.measurement,
            claim=item.sentence,
            confidence=min(confidence, 0.9),
            missing_variables=[],
            provenance=EvidenceProvenance(
                locator=document.locator, excerpt=item.sentence, extraction_method="deterministic-rule"
            ),
        )
        records.append(record.model_copy(update={"missing_variables": _missing(record)}))
    if unparsed is not None and not records and MIC_MENTION_RE.search(text):
        # The source reports an MIC the rules could not attribute -- typically a
        # range ("4-8 µg/mL"), or several agents in one "respectively" clause.
        # Guessing which number belongs to which peptide is how a wrong
        # measurement enters the state, so the source is flagged for
        # adjudication instead of parsed.
        unparsed.append(document.source.source_id)
    return records
