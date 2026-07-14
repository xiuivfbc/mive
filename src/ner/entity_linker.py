"""NER entity linker: dedup extracted elements by name similarity."""

from src.models.world import Element


def levenshtein_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return levenshtein_distance(b, a)

    if len(b) == 0:
        return len(a)

    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (ca != cb)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def _is_same_entity(name_a: str, name_b: str) -> bool:
    """Check if two names refer to the same entity.

    Merge when:
    - Edit distance < 2 (Levenshtein <= 1)
    - One name is a substring of the other (abbreviation/variant)
    """
    if name_a == name_b:
        return True
    if name_a in name_b or name_b in name_a:
        return True
    if levenshtein_distance(name_a, name_b) < 2:
        return True
    return False


def _merge_elements(a: Element, b: Element) -> Element:
    """Merge two elements, keeping longer content fields."""
    return Element(
        id=a.id,
        category=a.category,
        name=a.name if len(a.name) >= len(b.name) else b.name,
        brief=a.brief if len(a.brief) >= len(b.brief) else b.brief,
        detail=a.detail if len(a.detail) >= len(b.detail) else b.detail,
    )


def link_entities(elements: list[Element]) -> list[Element]:
    """Deduplicate and standardize extracted elements.

    Groups elements by category, then merges entities with similar names
    within each group.
    """
    if not elements:
        return []

    # Group by category
    groups: dict[str, list[Element]] = {}
    for elem in elements:
        groups.setdefault(elem.category, []).append(elem)

    result: list[Element] = []
    for _category, group in groups.items():
        merged: list[Element] = []
        for elem in group:
            found = False
            for i, existing in enumerate(merged):
                if _is_same_entity(elem.name, existing.name):
                    merged[i] = _merge_elements(existing, elem)
                    found = True
                    break
            if not found:
                merged.append(elem)
        result.extend(merged)

    return result
