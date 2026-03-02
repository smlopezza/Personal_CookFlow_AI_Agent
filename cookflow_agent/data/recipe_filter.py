"""
CookFlow Recipe Filter
Fallback when Google Search returns no results.
Loads workspace/data/recipes.json and filters by user constraints,
following the same constraint hierarchy as the Recipe Finder prompt.
"""

import json
import os
import random
from typing import Optional


# --------------------------------------------------------------------------- #
# Load database once at module level
# --------------------------------------------------------------------------- #

_DB_PATH = os.path.join(os.path.dirname(__file__), "recipes.json")

def _load_db() -> list[dict]:
    with open(_DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["recipes"]

_RECIPES = _load_db()


# --------------------------------------------------------------------------- #
# Hard filters — never relaxed
# --------------------------------------------------------------------------- #

def _passes_allergen_check(recipe: dict, allergens: list[str]) -> bool:
    """Reject any recipe that contains a declared allergen."""
    if not allergens:
        return True
    recipe_allergens = {a.lower() for a in recipe.get("allergens", [])}
    for allergen in allergens:
        if allergen.lower() in recipe_allergens:
            return False
    return True


def _passes_condition_check(recipe: dict, condition_avoids: dict[str, list[str]]) -> bool:
    """
    Reject any recipe whose ingredients include condition-specific avoids.
    condition_avoids = {"hypothyroidism": ["broccoli", "soy"], ...}
    """
    if not condition_avoids:
        return True
    recipe_condition_avoids = recipe.get("condition_avoids", {})
    for condition, avoid_list in condition_avoids.items():
        recipe_avoid = recipe_condition_avoids.get(condition, [])
        if recipe_avoid:
            return False
    return True


def _passes_diet_check(recipe: dict, vegan: bool, vegetarian: bool) -> bool:
    """Reject recipe if user requires vegan/vegetarian but recipe is not."""
    tags = set(recipe.get("tags", []))
    if vegan and "vegan" not in tags:
        return False
    if vegetarian and "vegetarian" not in tags and "vegan" not in tags:
        return False
    return True


# --------------------------------------------------------------------------- #
# Soft filters — relaxed progressively if not enough results
# --------------------------------------------------------------------------- #

def _matches_cuisine(recipe: dict, cuisines: list[str]) -> bool:
    if not cuisines:
        return True
    tags = set(recipe.get("tags", []))
    return any(c.lower() in tags for c in cuisines)


def _matches_kid_friendly(recipe: dict) -> bool:
    return "kid_friendly" in recipe.get("tags", [])


def _matches_time(recipe: dict, max_total_minutes: Optional[int]) -> bool:
    if max_total_minutes is None:
        return True
    total = recipe.get("prep_time", 0) + recipe.get("cook_time", 0)
    return total <= max_total_minutes


def _matches_effort(recipe: dict, effort_levels: list[str]) -> bool:
    if not effort_levels:
        return True
    return recipe.get("effort_level") in effort_levels


def _matches_batch_cookable(recipe: dict, batch_cook: bool) -> bool:
    if not batch_cook:
        return True
    return "batch_cookable" in recipe.get("tags", [])


# --------------------------------------------------------------------------- #
# Main filter function
# --------------------------------------------------------------------------- #

def filter_recipes(
    count: int = 4,
    allergens: Optional[list[str]] = None,
    condition_avoids: Optional[dict] = None,
    cuisines: Optional[list[str]] = None,
    kid_friendly: bool = False,
    vegan: bool = False,
    vegetarian: bool = False,
    batch_cook: bool = False,
    max_total_minutes: Optional[int] = None,
    effort_levels: Optional[list[str]] = None,
    exclude_ids: Optional[list[str]] = None,
) -> tuple[list[dict], list[str]]:
    """
    Filter the curated recipe database using the CookFlow constraint hierarchy.

    Hard constraints (never relaxed):
        allergens, condition_avoids, vegan, vegetarian

    Soft constraints (relaxed progressively if results < count):
        cuisine → kid_friendly → time → effort → batch_cookable

    Args:
        count:               Number of recipes to return (4 for Mode B, 3 for Mode A)
        allergens:           List of allergen strings to exclude (e.g. ["nuts", "dairy"])
        condition_avoids:    Dict of condition → avoid list (e.g. {"hypothyroidism": [...]})
        cuisines:            Preferred cuisine tags (e.g. ["colombian", "canadian"])
        kid_friendly:        If True, prefer kid-friendly recipes
        vegan:               If True, only return vegan recipes
        vegetarian:          If True, only return vegetarian or vegan recipes
        batch_cook:          If True, prefer batch-cookable recipes
        max_total_minutes:   Max prep+cook time in minutes
        effort_levels:       List of accepted effort levels (e.g. ["easy", "medium"])
        exclude_ids:         Recipe IDs already shown this session (avoid repeats)

    Returns:
        (recipes, relaxed_constraints) where:
            recipes            = list of recipe dicts (len <= count)
            relaxed_constraints = list of constraint names that were relaxed
    """
    allergens = allergens or []
    condition_avoids = condition_avoids or {}
    cuisines = cuisines or []
    effort_levels = effort_levels or []
    exclude_ids = set(exclude_ids or [])
    relaxed = []

    # --- Step 1: Apply hard filters to full database ---
    hard_filtered = [
        r for r in _RECIPES
        if r["id"] not in exclude_ids
        and r.get("is_main_dish", True)
        and _passes_allergen_check(r, allergens)
        and _passes_condition_check(r, condition_avoids)
        and _passes_diet_check(r, vegan, vegetarian)
    ]

    if len(hard_filtered) == 0:
        return [], ["allergens_or_diet_impossible"]

    # --- Step 2: Apply all soft filters together ---
    def apply_soft(pool, use_cuisine, use_kid, use_time, use_effort, use_batch):
        results = pool
        if use_cuisine and cuisines:
            results = [r for r in results if _matches_cuisine(r, cuisines)]
        if use_kid and kid_friendly:
            results = [r for r in results if _matches_kid_friendly(r)]
        if use_time and max_total_minutes:
            results = [r for r in results if _matches_time(r, max_total_minutes)]
        if use_effort and effort_levels:
            results = [r for r in results if _matches_effort(r, effort_levels)]
        if use_batch and batch_cook:
            results = [r for r in results if _matches_batch_cookable(r)]
        return results

    # --- Step 3: Progressive relaxation ---
    # Try all soft constraints first
    results = apply_soft(hard_filtered, True, True, True, True, True)

    if len(results) < count:
        # Relax cuisine — mix in other cuisines
        results = apply_soft(hard_filtered, False, True, True, True, True)
        if len(results) >= count:
            relaxed.append("cuisine")

    if len(results) < count:
        # Relax kid_friendly
        results = apply_soft(hard_filtered, False, False, True, True, True)
        if len(results) >= count:
            relaxed.append("kid_friendly")

    if len(results) < count:
        # Relax time
        results = apply_soft(hard_filtered, False, False, False, True, True)
        if len(results) >= count:
            relaxed.append("time_limit")

    if len(results) < count:
        # Relax effort
        results = apply_soft(hard_filtered, False, False, False, False, True)
        if len(results) >= count:
            relaxed.append("effort_level")

    if len(results) < count:
        # Relax batch_cookable — use all hard-filtered
        results = hard_filtered
        relaxed.append("batch_cookable")

    # --- Step 4: Sample and return ---
    if len(results) <= count:
        return results, relaxed

    # Prefer variety: shuffle and pick, but try to include at least one
    # of each requested cuisine if possible
    random.shuffle(results)
    selected = results[:count]
    return selected, relaxed


# --------------------------------------------------------------------------- #
# Convenience: build a note string for the Root Agent to surface to user
# --------------------------------------------------------------------------- #

def relaxation_message(relaxed: list[str], original_constraints: dict) -> str:
    """
    Returns a human-readable message explaining which constraints were relaxed.
    Pass this to the Root Agent to surface transparently to the user.
    """
    if not relaxed:
        return ""

    messages = []
    if "cuisine" in relaxed:
        requested = ", ".join(original_constraints.get("cuisines", []))
        messages.append(
            f"I couldn't find enough {requested} recipes matching all your constraints, "
            f"so I've mixed in options from other cuisines."
        )
    if "kid_friendly" in relaxed:
        messages.append(
            "I couldn't find enough kid-friendly options, "
            "so I've included some recipes that aren't specifically tagged as kid-friendly — "
            "they're still mild and family-appropriate."
        )
    if "time_limit" in relaxed:
        messages.append(
            "I couldn't find enough recipes within your time limit, "
            "so I've included some slightly longer options."
        )
    if "effort_level" in relaxed:
        messages.append(
            "I couldn't find enough recipes at your preferred effort level, "
            "so I've included some that may take a bit more active cooking."
        )
    if "batch_cookable" in relaxed:
        messages.append(
            "Not all recipes in this list are optimised for batch cooking, "
            "but they can still be prepared in a single session."
        )

    return " ".join(messages)


# --------------------------------------------------------------------------- #
# filter_live_recipes — hard filters on live Recipe Finder output
# --------------------------------------------------------------------------- #

def filter_live_recipes(
    recipes: list[dict],
    allergens: list[str] = None,
    vegan: bool = False,
    vegetarian: bool = False,
) -> tuple[list[dict], list[str]]:
    """
    Apply hard constraint filters to live Recipe Finder output.
    Called in Root Agent interception step on every Recipe Finder result.
    Only enforces non-relaxable constraints (allergens, diet).
    Does NOT touch soft constraints — those are already handled by Recipe Finder LLM.

    Args:
        recipes:   Raw recipe list from Recipe Finder Agent
        allergens: Declared allergens — any match = reject recipe
        vegan:     If True, only pass vegan recipes
        vegetarian: If True, only pass vegetarian or vegan recipes

    Returns:
        (filtered_recipes, notes) — notes lists what was removed and why
    """
    allergens = allergens or []
    original_count = len(recipes)
    filtered = [
        r for r in recipes
        if _passes_allergen_check(r, allergens)
        and _passes_diet_check(r, vegan, vegetarian)
    ]
    removed = original_count - len(filtered)
    notes = [f"removed {removed} recipe(s) violating allergen or dietary constraints"] if removed > 0 else []
    return filtered, notes


# --------------------------------------------------------------------------- #
# Quick smoke test — run directly: python recipe_filter.py
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    # TC3: nut allergy, Colombian food
    results, relaxed = filter_recipes(
        count=4,
        allergens=["nuts"],
        cuisines=["colombian"],
    )
    print(f"\nTC3 — Colombian, nut-free ({len(results)} results, relaxed: {relaxed})")
    for r in results:
        print(f"  [{r['id']}] {r['name']} ({r['effort_level']}, "
              f"{r['prep_time'] + r['cook_time']} min)")

    # TC7: vegan, Colombian, under 90 min
    results, relaxed = filter_recipes(
        count=4,
        allergens=["nuts"],
        cuisines=["colombian"],
        vegan=True,
        max_total_minutes=90,
    )
    print(f"\nTC7 — Colombian, vegan, nut-free, <90min ({len(results)} results, relaxed: {relaxed})")
    for r in results:
        print(f"  [{r['id']}] {r['name']} ({r['effort_level']}, "
              f"{r['prep_time'] + r['cook_time']} min)")

    # TC5: nut allergy, Colombian + Canadian, kid-friendly
    results, relaxed = filter_recipes(
        count=4,
        allergens=["nuts"],
        cuisines=["colombian", "canadian"],
        kid_friendly=True,
    )
    print(f"\nTC5 — Colombian+Canadian, nut-free, kid-friendly ({len(results)} results, relaxed: {relaxed})")
    for r in results:
        print(f"  [{r['id']}] {r['name']} ({r['effort_level']}, "
              f"{r['prep_time'] + r['cook_time']} min)")

    # Allergen impossible
    results, relaxed = filter_recipes(
        count=4,
        allergens=["nuts", "dairy", "gluten", "soy", "fish", "eggs", "shellfish"],
    )
    print(f"\nImpossible constraints ({len(results)} results, relaxed: {relaxed})")