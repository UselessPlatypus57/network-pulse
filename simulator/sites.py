"""Simulated cell-site catalogue: ~40 sites across the Seattle metro area.

Coordinates are approximate neighbourhood centres; site IDs and names are
made up for the simulation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SiteSpec:
    id: str
    name: str
    region: str
    technology: str
    latitude: float
    longitude: float


_RAW: dict[str, tuple[str, list[tuple[str, float, float]]]] = {
    "Seattle": ("SEA", [
        ("Downtown", 47.6062, -122.3321),
        ("Capitol Hill", 47.6253, -122.3222),
        ("Ballard", 47.6687, -122.3847),
        ("Fremont", 47.6505, -122.3509),
        ("University District", 47.6615, -122.3138),
        ("Queen Anne", 47.6374, -122.3570),
        ("West Seattle", 47.5667, -122.3868),
        ("Beacon Hill", 47.5682, -122.3087),
        ("Columbia City", 47.5596, -122.2867),
        ("Georgetown", 47.5478, -122.3220),
        ("Northgate", 47.7062, -122.3255),
        ("Lake City", 47.7193, -122.2953),
        ("Greenwood", 47.6909, -122.3552),
        ("SoDo", 47.5806, -122.3343),
        ("South Lake Union", 47.6234, -122.3366),
        ("Magnolia", 47.6505, -122.4000),
        ("Rainier Beach", 47.5212, -122.2683),
    ]),
    "Eastside": ("EAS", [
        ("Bellevue Downtown", 47.6101, -122.2015),
        ("Factoria", 47.5776, -122.1700),
        ("Crossroads", 47.6178, -122.1290),
        ("Redmond", 47.6740, -122.1215),
        ("Kirkland", 47.6769, -122.2060),
        ("Issaquah", 47.5301, -122.0326),
        ("Bothell", 47.7601, -122.2054),
        ("Mercer Island", 47.5707, -122.2221),
        ("Sammamish", 47.6163, -122.0356),
        ("Woodinville", 47.7543, -122.1635),
    ]),
    "South King": ("SKC", [
        ("Renton", 47.4829, -122.2171),
        ("Tukwila", 47.4740, -122.2610),
        ("SeaTac", 47.4436, -122.3016),
        ("Burien", 47.4704, -122.3468),
        ("Kent", 47.3809, -122.2348),
        ("Federal Way", 47.3223, -122.3126),
        ("Auburn", 47.3073, -122.2285),
    ]),
    "Snohomish": ("SNO", [
        ("Shoreline", 47.7557, -122.3415),
        ("Lynnwood", 47.8209, -122.3151),
        ("Edmonds", 47.8107, -122.3774),
        ("Everett", 47.9790, -122.2021),
        ("Mill Creek", 47.8601, -122.2043),
        ("Lake Forest Park", 47.7568, -122.2804),
        ("Mukilteo", 47.9445, -122.3046),
        ("Marysville", 48.0518, -122.1771),
    ]),
}


def catalogue() -> list[SiteSpec]:
    sites: list[SiteSpec] = []
    for region, (prefix, places) in _RAW.items():
        for i, (name, lat, lon) in enumerate(places, start=1):
            # Denser urban cores run 5G; outer suburbs mix in LTE.
            tech = "5G" if region in ("Seattle", "Eastside") or i % 3 else "LTE"
            sites.append(SiteSpec(f"{prefix}-{i:03d}", name, region, tech, lat, lon))
    return sites
