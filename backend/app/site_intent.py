from __future__ import annotations

import re
from typing import Any


_UNSAFE_TERMS = [
    "certified rams",
    "certify rams",
    "approve work",
    "approved for work",
    "work approval",
    "guarantee safe",
    "emergency guidance",
    "emergency route",
    "replace competent",
]

_SITE_TYPE_TERMS = {
    "solar": ["solar", "pv", "photovoltaic", "module", "inverter"],
    "quarry": ["quarry", "borrow pit", "aggregate"],
    "substation": ["substation", "transformer", "switchgear"],
    "bess": ["bess", "battery", "energy storage"],
    "roof": ["roof", "rooftop", "warehouse roof"],
    "rural_field": ["farm", "field", "rural", "pasture"],
    "data_centre": ["data centre", "data center"],
    "wind": ["wind farm", "turbine"],
}

_ACTIVITY_TERMS = {
    "survey": ["survey", "walkover"],
    "inspection": ["inspection", "inspect"],
    "maintenance": ["maintenance", "repair", "service"],
    "delivery": ["delivery", "deliver", "lorry", "cranage", "crane"],
    "drainage_slope": ["drainage", "slope", "earthwork", "ground", "geotechnical"],
    "access_track": ["access track", "track", "gate", "bridge", "culvert"],
    "electrical": ["electrical", "energised", "inverter", "transformer", "switchgear"],
}

_WEAK_SITE_LABELS = {
    "hello",
    "hi",
    "hey",
    "hiya",
    "good morning",
    "good afternoon",
    "good evening",
    "thanks",
    "thank you",
    "ok",
    "okay",
    "yes",
    "no",
    "nope",
    "nah",
    "not that",
    "not this",
    "wrong",
    "wrong site",
    "what do you mean",
    "what does that mean",
    "help",
    "today",
    "tomorrow",
    "next week",
    "next month",
    "survey",
    "inspection",
    "maintenance",
    "delivery",
    "this place",
    "this site",
    "the site",
}

_VAGUE_PLACE_TERMS = [
    "park",
    "field",
    "road",
    "river",
    "beach",
    "forest",
    "wood",
    "woods",
    "farm",
    "site",
]


def parse_site_intent(message: str) -> dict[str, Any]:
    cleaned = re.sub(r"\s+", " ", message).strip()
    lower = cleaned.lower()
    coordinate = extract_coordinate(cleaned)
    postcode = extract_postcode(cleaned)
    outcode = extract_outcode(cleaned, postcode)
    nearest_town = extract_nearest_town(cleaned)
    area_hint = extract_area_hint(cleaned)
    place_hint = extract_place_hint(cleaned)
    local_authority = extract_local_authority(cleaned)
    site_name = extract_site_label(cleaned, coordinate=coordinate, postcode=postcode)
    site_types = _matched_terms(lower, _SITE_TYPE_TERMS)
    activities = _matched_terms(lower, _ACTIVITY_TERMS)
    unsafe_terms = [term for term in _UNSAFE_TERMS if term in lower]
    visit_date = extract_visit_date(cleaned)
    known_lambeth = any(term in lower for term in ["lambeth", "albert embankment", "thames", "8 albert"])
    site_visit_intent = any(
        term in lower
        for term in [
            "site visit",
            "pre-visit",
            "visit",
            "survey",
            "inspection",
            "maintenance",
        ]
    )
    vague_location_hint = bool((place_hint or area_hint or nearest_town) and site_visit_intent and not coordinate and not postcode)
    named_site_hint = bool(site_types) or any(
        term in lower
        for term in [
            "farm",
            "quarry",
            "substation",
            "data centre",
            "data center",
            "road",
            "embankment",
        ]
    )
    has_location_evidence = bool(coordinate or postcode or known_lambeth)
    return {
        "rawMessage": cleaned,
        "messageSummary": cleaned[:160],
        "siteName": site_name,
        "coordinate": coordinate,
        "postcode": postcode,
        "outcode": outcode,
        "nearestTown": nearest_town,
        "areaHint": area_hint,
        "placeHint": place_hint,
        "localAuthority": local_authority,
        "siteTypes": site_types,
        "activities": activities,
        "visitDate": visit_date,
        "unsafeIntent": bool(unsafe_terms),
        "unsafeTerms": unsafe_terms,
        "knownPublicFixture": known_lambeth,
        "namedSiteHint": named_site_hint,
        "vagueLocationHint": vague_location_hint,
        "siteVisitIntent": site_visit_intent,
        "hasLocationEvidence": has_location_evidence,
    }


def extract_coordinate(message: str) -> tuple[float, float] | None:
    match = re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", message)
    if not match:
        return None
    latitude = float(match.group(1))
    longitude = float(match.group(2))
    if -90 <= latitude <= 90 and -180 <= longitude <= 180:
        return latitude, longitude
    return None


def extract_postcode(message: str) -> str | None:
    match = re.search(
        r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b",
        message.upper(),
    )
    if not match:
        return None
    compact = re.sub(r"\s+", "", match.group(1).upper())
    return f"{compact[:-3]} {compact[-3:]}"


def extract_outcode(message: str, postcode: str | None = None) -> str | None:
    if postcode:
        return postcode.split()[0]
    match = re.search(r"\b([A-Z]{1,2}\d[A-Z\d]?)\b", message.upper())
    return match.group(1) if match else None


def extract_nearest_town(message: str) -> str | None:
    patterns = [
        r"\bnear\s+([A-Z][A-Za-z' -]{2,40})(?:\s+tomorrow\b|\s+today\b|\s+for\b|[.,]|$)",
        r"\bnearest town\s+(?:is\s+)?([A-Z][A-Za-z' -]{2,40})(?:\s+tomorrow\b|\s+today\b|\s+for\b|[.,]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return _clean_label(match.group(1))
    return None


def extract_area_hint(message: str) -> str | None:
    patterns = [
        r"\bin\s+([A-Z][A-Za-z' -]{2,40})(?:\s+can\b|\s+could\b|\s+i\b|\s+we\b|\s+for\b|[,.?!]|$)",
        r"\bnear\s+([A-Z][A-Za-z' -]{2,40})(?:\s+can\b|\s+could\b|\s+i\b|\s+we\b|\s+for\b|[,.?!]|$)",
        r"\bclose to\s+([A-Z][A-Za-z' -]{2,40})(?:\s+can\b|\s+could\b|\s+i\b|\s+we\b|\s+for\b|[,.?!]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            label = _clean_label(match.group(1))
            if label and not _is_weak_site_label(label):
                return label
    return None


def extract_place_hint(message: str) -> str | None:
    lower = message.lower()
    for term in _VAGUE_PLACE_TERMS:
        if re.search(rf"\b(?:a|an|the)?\s*{re.escape(term)}\b", lower):
            return term
    return None


def extract_local_authority(message: str) -> str | None:
    match = re.search(r"\b(?:council|local authority)\s+(?:is\s+)?([A-Z][A-Za-z' -]{2,60})(?:[.,]|$)", message)
    return _clean_label(match.group(1)) if match else None


def extract_visit_date(message: str) -> str | None:
    lower = message.lower()
    if "tomorrow" in lower:
        return "tomorrow"
    if "today" in lower:
        return "today"
    match = re.search(r"\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b", message)
    return match.group(1) if match else None


def extract_site_label(
    message: str,
    *,
    coordinate: tuple[float, float] | None = None,
    postcode: str | None = None,
) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    working = cleaned
    if coordinate:
        working = re.sub(
            r"\s+(?:at\s+)?-?\d{1,2}\.\d+\s*,\s*-?\d{1,3}\.\d+",
            "",
            working,
            flags=re.IGNORECASE,
        )
    if postcode:
        working = re.sub(re.escape(postcode), "", working, flags=re.IGNORECASE)
        working = re.sub(re.escape(postcode.replace(" ", "")), "", working, flags=re.IGNORECASE)
    extraction_patterns = [
        r"\bsite visit at\s+(.+?)(?:\s+tomorrow\b|\s+today\b|\s+for\b|\s+please\b|[.;]|$)",
        r"\bvisit\s+(.+?)(?:\s+tomorrow\b|\s+today\b|\s+for\b|\s+please\b|[.;]|$)",
        r"\bat\s+(.+?)(?:\s+tomorrow\b|\s+today\b|\s+for\b|\s+please\b|[.;]|$)",
    ]
    for pattern in extraction_patterns:
        match = re.search(pattern, working, flags=re.IGNORECASE)
        if match:
            label = _clean_label(match.group(1))
            if label and not _is_weak_site_label(label) and not _is_vague_site_label(label):
                return label[:90] if len(label) <= 90 else label[:87].rstrip() + "..."
    if coordinate:
        return f"Coordinate {coordinate[0]:.6f}, {coordinate[1]:.6f}"
    if postcode:
        return f"Postcode {postcode}"
    label = _clean_label(working[:90])
    return "" if _is_weak_site_label(label) or _is_vague_site_label(label) else label


def _matched_terms(lower_message: str, groups: dict[str, list[str]]) -> list[str]:
    return [name for name, terms in groups.items() if any(term in lower_message for term in terms)]


def _clean_label(value: str) -> str:
    label = value.strip(" ,.;:")
    label = re.sub(r"\s+", " ", label)
    label = re.sub(r"\s+\bat\b\s*$", "", label, flags=re.IGNORECASE)
    return label.strip(" ,.;:")


def _is_weak_site_label(value: str) -> bool:
    label = value.strip().lower()
    if not label:
        return True
    return label in _WEAK_SITE_LABELS


def _is_vague_site_label(value: str) -> bool:
    label = value.strip().lower()
    if not label:
        return True
    vague_starts = ("near ", "close to ", "around ", "by ", "where i live", "where we live")
    vague_phrases = ("can you help", "help me find", "i need to visit there", "near a ", "near the ")
    return label.startswith(vague_starts) or any(phrase in label for phrase in vague_phrases)
