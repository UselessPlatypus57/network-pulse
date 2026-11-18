"""Simulated cell-site catalogue: 40 sites across the Greater Houston area.

Coordinates are approximate neighbourhood/city centres; site IDs and names are
made up for the simulation and are not real tower locations.
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
    "Inner Houston": ("HOU", [
        ("Downtown", 29.7604, -95.3698),
        ("Midtown", 29.7399, -95.3780),
        ("Montrose", 29.7453, -95.3910),
        ("Texas Medical Center", 29.7069, -95.4010),
        ("Galleria / Uptown", 29.7390, -95.4610),
        ("The Heights", 29.7980, -95.3980),
        ("Rice Village", 29.7171, -95.4150),
        ("EaDo", 29.7520, -95.3500),
        ("Third Ward", 29.7290, -95.3600),
        ("Bellaire", 29.7058, -95.4588),
        ("Memorial", 29.7790, -95.5420),
        ("Westchase", 29.7280, -95.5680),
        ("Sharpstown", 29.6930, -95.5160),
        ("Hobby Airport", 29.6454, -95.2789),
        ("Greenspoint", 29.9450, -95.4160),
        ("IAH Airport", 29.9902, -95.3368),
    ]),
    "West": ("WST", [
        ("Energy Corridor", 29.7840, -95.6440),
        ("Katy", 29.7858, -95.8245),
        ("Cinco Ranch", 29.7400, -95.7600),
        ("Fulshear", 29.6930, -95.8980),
        ("Sugar Land", 29.6197, -95.6349),
        ("Missouri City", 29.6186, -95.5377),
        ("Richmond", 29.5822, -95.7608),
    ]),
    "North": ("NTH", [
        ("The Woodlands", 30.1658, -95.4613),
        ("Spring", 30.0799, -95.4172),
        ("Humble", 29.9988, -95.2622),
        ("Kingwood", 30.0500, -95.1850),
        ("Cypress", 29.9691, -95.6972),
        ("Tomball", 30.0972, -95.6161),
        ("Conroe", 30.3119, -95.4561),
        ("Atascocita", 29.9988, -95.1766),
    ]),
    "Bay Area": ("BAY", [
        ("Pasadena", 29.6911, -95.2091),
        ("Deer Park", 29.7052, -95.1238),
        ("Baytown", 29.7355, -94.9774),
        ("Pearland", 29.5636, -95.2860),
        ("Friendswood", 29.5294, -95.2010),
        ("Clear Lake", 29.5560, -95.0950),
        ("League City", 29.5075, -95.0950),
        ("Texas City", 29.3838, -94.9027),
        ("Galveston", 29.3013, -94.7977),
    ]),
}


def catalogue() -> list[SiteSpec]:
    sites: list[SiteSpec] = []
    for region, (prefix, places) in _RAW.items():
        for i, (name, lat, lon) in enumerate(places, start=1):
            # The dense urban core and west side run 5G; outer areas mix in LTE.
            tech = "5G" if region in ("Inner Houston", "West") or i % 3 else "LTE"
            sites.append(SiteSpec(f"{prefix}-{i:03d}", name, region, tech, lat, lon))
    return sites
