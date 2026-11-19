"""Network Pulse traffic simulator.

Plays the role of the probes/collectors in a real network: registers a set of
cell sites with the API, then every few seconds reports latency, packet loss
and availability for each one.

Besides normal jitter it produces three kinds of trouble on its own:

- **blips**     — a single bad sample. The monitor should *ignore* these.
- **incidents** — a few minutes of genuine congestion. These *should* alert.
- **chaos**     — faults injected on demand via the API / dashboard.

Usage:
    python simulator.py                       # talks to http://localhost:8000
    API_URL=http://api:8000 python simulator.py
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx
from sites import SiteSpec, catalogue, synthetic_sites

log = logging.getLogger("simulator")

BATCH_SIZE = 2000  # samples per POST; the API caps a batch at 5,000


@dataclass
class SiteSim:
    spec: SiteSpec
    base_latency: float
    tick: int = 0
    incident_until: float = 0.0
    incident_kind: str = ""
    blip: bool = False
    rng: random.Random = field(default_factory=random.Random)

    def sample(self, now: float, fault: str | None) -> dict | None:
        """One reading for this site, or None if the site is silent (outage)."""
        self.tick += 1
        r = self.rng

        latency = max(5.0, r.gauss(self.base_latency, self.base_latency * 0.08))
        loss = min(100.0, abs(r.gauss(0.05, 0.08)))
        avail = 100.0 if r.random() > 0.05 else r.uniform(99.85, 99.99)

        # --- organically occurring trouble -----------------------------------
        if now < self.incident_until:
            if self.incident_kind == "congestion":
                latency = r.gauss(260, 40)
                loss = r.uniform(0.5, 3.0)
            else:  # interference
                loss = r.uniform(4, 12)
                avail = r.uniform(96.0, 98.5)
        if self.blip:
            latency = r.uniform(600, 2500)
            loss = r.uniform(5, 40)
            self.blip = False

        # --- injected chaos --------------------------------------------------
        if fault == "outage":
            return None
        if fault == "latency":
            latency = r.gauss(450, 60)
        elif fault == "packet_loss":
            loss = r.uniform(8, 25)
            avail = r.uniform(95.5, 98.0)
        elif fault == "flap" and self.tick % 3 == 0:
            # Spikes on every third sample only: never a majority of the
            # window, so the median holds steady and no alert should fire.
            latency = r.uniform(700, 1200)
            loss = r.uniform(10, 30)

        return {
            "site_id": self.spec.id,
            "latency_ms": round(max(1.0, latency), 2),
            "packet_loss_pct": round(min(100.0, max(0.0, loss)), 3),
            "availability_pct": round(min(100.0, max(0.0, avail)), 3),
        }


class Simulator:
    def __init__(
        self, api_url: str, interval_s: float, blip_rate: float, incident_rate: float, seed: int | None,
        extra_sites: int = 0,
    ):
        self.api = httpx.Client(base_url=api_url.rstrip("/"), timeout=5.0)
        self.interval_s = interval_s
        self.blip_rate = blip_rate
        self.incident_rate = incident_rate
        self.rng = random.Random(seed)
        self.sites = [
            SiteSim(spec, base_latency=self.rng.uniform(22, 55), rng=random.Random(self.rng.random()))
            for spec in catalogue() + synthetic_sites(extra_sites)
        ]
        self.running = True

    def wait_for_api(self) -> None:
        while self.running:
            try:
                if self.api.get("/readyz").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            log.info("waiting for API at %s ...", self.api.base_url)
            time.sleep(2)

    def _register(self, spec: SiteSpec) -> None:
        self.api.put(f"/api/v1/sites/{spec.id}", json={
            "name": spec.name, "region": spec.region, "technology": spec.technology,
            "latitude": spec.latitude, "longitude": spec.longitude,
        }).raise_for_status()

    def register_sites(self) -> None:
        started = time.monotonic()
        # Parallel PUTs so a 10,000-site scale test registers in seconds, not minutes.
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(self._register, (s.spec for s in self.sites)))
        log.info("registered %d sites in %.1fs", len(self.sites), time.monotonic() - started)

    def active_faults(self) -> dict[str, str]:
        try:
            return {f["site_id"]: f["fault"] for f in self.api.get("/api/v1/chaos").json()}
        except (httpx.HTTPError, ValueError):
            return {}

    def maybe_start_trouble(self, s: SiteSim, now: float) -> None:
        if self.rng.random() < self.blip_rate:
            s.blip = True
        if now >= s.incident_until and self.rng.random() < self.incident_rate:
            s.incident_kind = self.rng.choice(["congestion", "congestion", "interference"])
            duration = self.rng.uniform(60, 180)
            s.incident_until = now + duration
            log.info("organic %s incident on %s for %ds", s.incident_kind, s.spec.id, duration)

    def tick(self) -> None:
        now = time.time()
        faults = self.active_faults()
        batch = []
        for s in self.sites:
            self.maybe_start_trouble(s, now)
            sample = s.sample(now, faults.get(s.spec.id))
            if sample is not None:
                batch.append(sample)
        unknown = False
        for i in range(0, len(batch), BATCH_SIZE):
            resp = self.api.post("/api/v1/metrics", json={"samples": batch[i : i + BATCH_SIZE]})
            resp.raise_for_status()
            unknown = unknown or bool(resp.json().get("unknown_sites"))
        if unknown:  # API lost its DB? re-register.
            self.register_sites()

    def run(self) -> None:
        self.wait_for_api()
        self.register_sites()
        log.info("sending metrics every %.1fs", self.interval_s)
        while self.running:
            started = time.monotonic()
            try:
                self.tick()
            except httpx.HTTPError as exc:
                log.warning("tick failed: %s", exc)
            time.sleep(max(0.0, self.interval_s - (time.monotonic() - started)))

    def stop(self, *_: object) -> None:
        self.running = False


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default=os.getenv("API_URL", "http://localhost:8000"))
    p.add_argument("--interval", type=float, default=float(os.getenv("SIM_INTERVAL_S", "5")))
    p.add_argument("--blip-rate", type=float, default=float(os.getenv("SIM_BLIP_RATE", "0.004")),
                   help="per-site, per-tick probability of a single bad sample")
    p.add_argument("--incident-rate", type=float, default=float(os.getenv("SIM_INCIDENT_RATE", "0.0004")),
                   help="per-site, per-tick probability of a multi-minute incident (0 to disable)")
    p.add_argument("--seed", type=int, default=int(os.environ["SIM_SEED"]) if os.getenv("SIM_SEED") else None)
    p.add_argument("--extra-sites", type=int, default=int(os.getenv("SIM_EXTRA_SITES", "0")),
                   help="add N synthetic sites around Houston for scale testing")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one log line per request is noise at scale
    sim = Simulator(args.api, args.interval, args.blip_rate, args.incident_rate, args.seed, args.extra_sites)
    signal.signal(signal.SIGINT, sim.stop)
    signal.signal(signal.SIGTERM, sim.stop)
    sim.run()


if __name__ == "__main__":
    main()
