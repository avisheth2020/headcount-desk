"""Synthetic data for Meridian Labs, a fictional AI research lab.

    uv run python -m scripts.seed            # dev database from .env
    uv run python -m scripts.seed --prod     # production database from .env

The random seed is fixed, so the people, positions and planted errors are the
same on every run. Dates are relative to "as of" (today, US Eastern), so the
demo always looks like it was loaded this morning.

Noise is planted on purpose, so the Exceptions page and the data checks have
something to find. Every plant is recorded in seed_manifest.json, and the
tests assert that each one is caught.
"""

import argparse
import json
import os
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from faker import Faker

from app import db

SEED = 42
ET = ZoneInfo("America/New_York")
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "seed_manifest.json"
HISTORY_DAYS = 60

# SVP org -> (primary family, [(VP org, primary, secondary, [director orgs])])
ORG_TREE = [
    ("Research", "research", [
        ("Applied Research", "research", "eng", ["Language Models", "Multimodal", "Agents", "Evaluation"]),
        ("Foundations Research", "research", "eng", ["Learning Theory", "Optimization", "Interpretability", "Reasoning"]),
        ("Safety & Alignment", "research", "eng", ["Alignment", "Red Teaming", "Policy Research", "Assurance"]),
        ("Research Platforms", "eng", "research", ["Training Systems", "Data Platform", "Experiment Tools", "Research Compute"]),
    ]),
    ("Engineering", "eng", [
        ("Product Engineering", "eng", "ops", ["Assistant", "API", "Enterprise", "Growth"]),
        ("Compute Infrastructure", "eng", "ops", ["Clusters", "Networking", "Storage", "Capacity"]),
        ("Developer Platform", "eng", "ops", ["Build & Release", "Developer Tools", "Observability", "Internal Apps"]),
        ("Security & Reliability", "eng", "ops", ["Security Engineering", "Site Reliability", "Privacy Engineering", "Incident Response"]),
    ]),
    ("Operations", "ops", [
        ("People & Recruiting", "ops", "g&a", ["Recruiting", "People Partners", "Learning & Development", "Total Rewards"]),
        ("Finance & Strategy", "g&a", "ops", ["Financial Planning", "Accounting", "Strategy", "Procurement"]),
        ("Legal & Policy", "g&a", "ops", ["Commercial Legal", "Public Policy", "Compliance", "Intellectual Property"]),
        ("Workplace & IT", "ops", "g&a", ["Workplace", "IT Services", "Business Systems", "Travel & Events"]),
    ]),
]
TEAM_SUFFIXES = ["Core", "Platform", "Tools", "Data", "Systems", "Quality"]
RECRUITING_TEAMS = [("Research", "research", 8), ("Engineering", "eng", 8), ("Operations", "ops", 5), ("G&A", "g&a", 5)]
FAMILIES = ["research", "eng", "ops", "g&a"]
COST_PER_HEAD = {"research": 420_000, "eng": 380_000, "ops": 190_000, "g&a": 210_000}
LOCATIONS = ["New York", "San Francisco", "London", "Seattle", "Toronto", "Remote"]
JUSTIFICATIONS = [
    "Owns the on-call rotation; the team cannot cover it without a replacement",
    "Only person who knows the data pipeline end to end",
    "Leads a project due next quarter",
    "Team is already two people under plan",
    "Customer-facing work will stall without this role",
    "Needed to keep the release schedule",
    "Covers a compliance requirement we cannot leave unstaffed",
    "Key reviewer for the team's research output",
]
REJECT_REASONS = [
    "Role is being consolidated into the Evaluation team",
    "Hold until the Q1 refresh confirms the team's scope",
]

# How many of each error to plant.
PLANT_COUNTS = {"stale_open": 150, "duplicate": 20, "ghost_fill": 15, "miscoded": 30, "reserve_misplaced": 25}
NEGATIVE_TEAMS, NEGATIVE_PER_TEAM = 6, 2
ANOMALY_VP, ANOMALY_POINTS = "Applied Research", 5.2
PRE_RESOLVED = 38


class Builder:
    """Builds every table as a list of dicts, in memory. No database access."""

    def __init__(self, as_of: date, now: datetime):
        self.as_of, self.now = as_of, now
        self.rng = random.Random(SEED)
        self.fake = Faker("en_US")
        self.fake.seed_instance(SEED)
        self.orgs, self.people, self.positions = [], [], []
        self.staffing, self.backfills, self.events = [], [], []
        self.coverage, self.snapshots, self.resolutions = [], [], []
        self.plan = defaultdict(int)          # (org_id, family) -> approved headcount
        self.emails = set()
        self.used = set()                     # people already used for a plant or a persona
        self.teams = []                       # team org dicts, with extra keys
        self.pending_reqs = []                # (position, opened_at, backfill or None)
        self.vacated_by = {}                  # position id -> departed person
        self.plants = {k: [] for k in PLANT_COUNTS}
        self.negatives = []
        self.manifest = {}

    # ── small helpers ────────────────────────────────────────────────────────

    def days_ago(self, n: int) -> date:
        return self.as_of - timedelta(days=n)

    def add_org(self, name, parent, level, family, secondary=None):
        org = {"id": len(self.orgs) + 1, "name": name, "parent_id": parent["id"] if parent else None,
               "level": level, "leader_person_id": None, "cost_center": f"CC-{1000 + len(self.orgs) + 1}",
               "family": family, "secondary": secondary or family, "parent": parent, "members": []}
        self.orgs.append(org)
        return org

    def add_person(self, org, family, level, start, end=None, manager=None, name=None):
        first, last = (name.split(" ", 1) if name else (self.fake.first_name(), self.fake.last_name()))
        person = {"id": len(self.people) + 1, "full_name": f"{first} {last}", "email": None, "org_id": org["id"],
                  "job_family": family, "level": level, "location": self.rng.choices(LOCATIONS, [25, 30, 15, 10, 8, 12])[0],
                  "start_date": start, "end_date": end, "manager_id": manager["id"] if manager else None,
                  "org": org, "ghost": False}
        self.set_email(person)
        self.people.append(person)
        return person

    def set_email(self, person):
        base = "".join(ch for ch in person["full_name"].lower().replace(" ", ".") if ch.isalpha() or ch == ".")
        email, n = f"{base}@meridianlabs.example", 1
        while email in self.emails:
            n += 1
            email = f"{base}{n}@meridianlabs.example"
        self.emails.add(email)
        person["email"] = email

    def rename(self, person, name):
        person["full_name"] = name
        self.set_email(person)
        self.used.add(person["id"])
        return person

    def add_position(self, org, family, level, opened, person=None, ptype="standard", source="plan", planned=True):
        pos = {"id": len(self.positions) + 1, "position_code": f"P-{len(self.positions) + 1:05d}", "org_id": org["id"],
               "job_family": family, "level": level, "position_type": ptype,
               "person_id": person["id"] if person else None, "opened_at": opened, "source": source, "org": org}
        self.positions.append(pos)
        if planned:
            self.plan[(org["id"], family)] += 1
        if person:
            person.setdefault("position", pos)
        return pos

    def seat(self, person, org=None):
        """Give a person a standard, plan-backed seat that opened shortly before they started."""
        opened = person["start_date"] - timedelta(days=self.rng.randint(15, 200))
        source = self.rng.choices(["plan", "backfill"], [80, 20])[0]
        return self.add_position(org or person["org"], person["job_family"], person["level"], opened, person, source=source)

    def clean_members(self, team=None, family=None):
        """Active people who are not a leader, a persona, or already used for a plant."""
        pool = team["members"] if team else [p for t in self.teams for p in t["members"]]
        return [p for p in pool if p["id"] not in self.used and p["end_date"] is None
                and (family is None or p["job_family"] == family)
                and p["start_date"] < self.days_ago(HISTORY_DAYS + 5)]

    def pick(self, pool, k):
        chosen = self.rng.sample(pool, k)
        self.used.update(p["id"] for p in chosen)
        return chosen

    # ── org chart, people and their seats ────────────────────────────────────

    def build_orgs_and_people(self):
        rng = self.rng
        old = lambda: self.days_ago(rng.randint(400, 2200))
        company = self.add_org("Meridian Labs", None, "company", "g&a")
        ceo = self.add_person(company, "g&a", "L9", old())
        company["leader"] = ceo
        self.seat(ceo)
        for svp_name, svp_family, vps in ORG_TREE:
            svp = self.add_org(svp_name, company, "svp", svp_family)
            svp["leader"] = self.add_person(svp, svp_family, "L9", old(), manager=ceo)
            self.seat(svp["leader"])
            for vp_name, primary, secondary, directors in vps:
                vp = self.add_org(vp_name, svp, "vp", primary, secondary)
                vp["leader"] = self.add_person(vp, primary, "L8", old(), manager=svp["leader"])
                self.seat(vp["leader"])
                keep = directors if vp_name in ("Applied Research", "People & Recruiting", "Finance & Strategy") \
                    else directors[:rng.choice([3, 4])]
                for dir_name in keep:
                    director = self.add_org(dir_name, vp, "director", primary, secondary)
                    director["leader"] = self.add_person(director, primary, "L7", old(), manager=vp["leader"])
                    self.seat(director["leader"])
                    if dir_name == "Recruiting":
                        specs = [(f"Recruiting · {label}", fam, n) for label, fam, n in RECRUITING_TEAMS]
                    else:
                        specs = [(f"{dir_name} · {s}", None, 0) for s in rng.sample(TEAM_SUFFIXES, rng.randint(3, 5))]
                    for team_name, covers, n_recruiters in specs:
                        self.build_team(team_name, director, primary, secondary, covers, n_recruiters)

    def build_team(self, name, director, primary, secondary, covers, n_recruiters):
        rng = self.rng
        team = self.add_org(name, director, "team", primary, secondary)
        self.teams.append(team)
        lead = self.add_person(team, primary, "L6", self.days_ago(rng.randint(300, 2200)), manager=director["leader"])
        team["leader"] = lead
        self.seat(lead)
        self.used.add(lead["id"])
        size = rng.randint(27, 45)
        recent = rng.choice([0, 0, 1, 1, 1, 2])          # hires in the last 60 days
        for i in range(size - 1):
            family = secondary if (i == 0 or rng.random() < 0.2) else primary
            level = rng.choices(["L3", "L4", "L5", "L6", "L7"], [15, 30, 30, 18, 7])[0]
            start = self.days_ago(rng.randint(0, HISTORY_DAYS - 1)) if i < recent + 1 and i > 0 \
                else self.days_ago(rng.randint(HISTORY_DAYS + 1, 2200))
            person = self.add_person(team, family, level, start, manager=lead)
            self.seat(person)
            team["members"].append(person)
        for person in team["members"][1:1 + n_recruiters]:
            self.coverage.append({"person_id": person["id"], "job_family": covers})
            self.used.add(person["id"])
        # Open seats the plan pays for. About 60% were vacated by someone who left.
        for kind, n in (("committed", rng.choice([0, 0, 1, 1, 1, 2, 2, 3])), ("open", rng.choice([0, 0, 1, 1, 1, 2, 2]))):
            for _ in range(n):
                family = secondary if rng.random() < 0.2 else primary
                level = rng.choices(["L3", "L4", "L5", "L6"], [20, 35, 30, 15])[0]
                opened = self.days_ago(rng.randint(8, 150) if kind == "committed" else rng.randint(1, 60))
                pos = self.add_position(team, family, level, opened, source="backfill" if rng.random() < 0.6 else "plan")
                if pos["source"] == "backfill":
                    start = opened - timedelta(days=rng.randint(200, 1800))
                    self.vacated_by[pos["id"]] = self.add_person(team, family, level, start, end=opened - timedelta(days=1), manager=lead)
                if kind == "committed":
                    req_opened = min(opened + timedelta(days=rng.randint(1, 7)), self.as_of)
                    self.pending_reqs.append({"position": pos, "opened_at": req_opened, "backfill": None})

    def pin_personas(self):
        org = {o["name"]: o for o in self.orgs}
        sam_org = org["Language Models"]
        sam_teams = [t for t in self.teams if t["parent"] is sam_org]
        fin_team = next(t for t in self.teams if t["parent"] is org["Financial Planning"])
        recruiters = {c["person_id"] for c in self.coverage if c["job_family"] == "research"}
        self.personas = {
            "svp": self.rename(org["Research"]["leader"], "Elena Marchetti"),
            "vp": self.rename(org["Applied Research"]["leader"], "Priya Shah"),
            "requester": self.rename(sam_org["leader"], "Sam Ortiz"),
            "recruiter": self.rename(next(p for p in self.people if p["id"] in recruiters), "Marcus Bell"),
            "rm": self.rename(next(p for p in fin_team["members"] if p["level"] in ("L5", "L6")), "Jordan Reyes"),
        }
        self.sam_org, self.sam_teams, self.priya_org = sam_org, sam_teams, org["Applied Research"]

    # ── planted noise ────────────────────────────────────────────────────────

    def plant_noise(self):
        rng = self.rng
        # Negative seats: a team hired over plan, so the seat has no approved headcount behind it.
        for team in rng.sample(self.teams, NEGATIVE_TEAMS):
            for person in self.pick(self.clean_members(team), NEGATIVE_PER_TEAM):
                pos = person["position"]
                pos["position_type"] = "negative"
                self.plan[(pos["org_id"], pos["job_family"])] -= 1
                self.negatives.append(pos)
        # Ghost fills: the person left, but the seat still points to them.
        for person in self.pick(self.clean_members(), PLANT_COUNTS["ghost_fill"]):
            person["end_date"], person["ghost"] = self.days_ago(rng.randint(10, 80)), True
            self.plants["ghost_fill"].append(person["position"])
        # Duplicates: the same person on a second seat, usually left behind by a transfer.
        for i, person in enumerate(self.pick(self.clean_members(), PLANT_COUNTS["duplicate"])):
            team = person["org"]
            siblings = [t for t in self.teams if t["parent"] is team["parent"] and t is not team]
            org = team if i < 8 else rng.choice(siblings)
            dup = self.add_position(org, person["job_family"], person["level"], self.days_ago(rng.randint(100, 700)),
                                    person, source="transfer", planned=False)
            self.plants["duplicate"].append(dup)
        # Mis-coded: the seat is coded to a job family this team has no plan line for.
        for person in self.pick(self.clean_members(), PLANT_COUNTS["miscoded"]):
            team, pos = person["org"], person["position"]
            pos["job_family"] = rng.choice([f for f in FAMILIES if f not in (team["family"], team["secondary"])])
            self.plants["miscoded"].append(pos)
        # Stale opens: open for more than 90 days, nobody recruiting, and not in the plan.
        for _ in range(PLANT_COUNTS["stale_open"]):
            team = rng.choice(self.teams)
            level = rng.choices(["L3", "L4", "L5", "L6"], [20, 35, 30, 15])[0]
            pos = self.add_position(team, team["family"], level, self.days_ago(rng.randint(95, 420)), planned=False)
            self.plants["stale_open"].append(pos)
        # Reserve: the plan holds it at the SVP. Some of it has been parked on teams instead.
        svps = [o for o in self.orgs if o["level"] == "svp"]
        for svp, n in zip(svps, (16, 17, 17)):
            for _ in range(n):
                self.add_position(svp, svp["family"], "L5", self.days_ago(rng.randint(15, 100)), ptype="reserve")
        for _ in range(PLANT_COUNTS["reserve_misplaced"]):
            team = rng.choice(self.teams)
            svp = team["parent"]["parent"]["parent"]
            pos = self.add_position(team, team["family"], "L5", self.days_ago(rng.randint(15, 100)), ptype="reserve", planned=False)
            self.plan[(svp["id"], svp["family"])] += 1
            self.plants["reserve_misplaced"].append(pos)

    def give_notice(self):
        """People who have resigned but have not left yet. These are who a backfill is for."""
        rng = self.rng
        dana = next(p for p in self.clean_members(self.sam_teams[0], "research") if p["level"] == "L5")
        self.rename(dana, "Dana Lee")
        dana["end_date"] = self.as_of + timedelta(days=12)
        self.dana = dana
        chosen = [dana]
        for team in self.sam_teams:                       # enough choice for the demo requester
            chosen += self.pick(self.clean_members(team, "research"), 2)
        others = [t for t in self.teams if t["parent"]["parent"] is self.priya_org and t not in self.sam_teams]
        for team in rng.sample(others, 4):
            chosen += self.pick(self.clean_members(team), 1)
        chosen += self.pick(self.clean_members(), 34)
        for person in chosen[1:]:
            person["end_date"] = self.as_of + timedelta(days=rng.randint(3, 30))
        self.notice = chosen

    # ── recruiting and the backfill workflow ─────────────────────────────────

    def recruiters_for(self, family):
        return [c["person_id"] for c in self.coverage if c["job_family"] == family]

    def build_backfills(self):
        """About forty requests spread across every status, each with a consistent audit trail."""
        rng, now = self.rng, self.now
        marcus, priya = self.personas["recruiter"], self.personas["vp"]
        person_by_id = {p["id"]: p for p in self.people}
        rr = defaultdict(int)                              # round-robin counter per family

        def next_recruiter(family, force_marcus=False):
            pool = [r for r in self.recruiters_for(family) if r != marcus["id"]]
            rr[family] += 1
            return marcus if force_marcus else person_by_id[pool[rr[family] % len(pool)]]

        def add(person, pos, status, submitted, *, justification=None, urgency=None, requester=None, recruiter=None,
                approve_h=None, open_at=None, fill_at=None, hire=None, reason=None):
            director, vp = pos["org"]["parent"], pos["org"]["parent"]["parent"]
            requester = requester or director["leader"]
            bf = {"id": 1001 + len(self.backfills), "departing_person_id": person["id"], "position_id": pos["id"],
                  "requested_by": requester["id"], "justification": justification or rng.choice(JUSTIFICATIONS),
                  "urgency": urgency or rng.choices(["low", "normal", "urgent"], [20, 55, 25])[0], "status": status,
                  "vp_approver_id": vp["leader"]["id"], "recruiter_id": None, "created_at": submitted, "updated_at": submitted}
            self.backfills.append(bf)

            def event(frm, to, actor, note, at):
                self.events.append({"backfill_request_id": bf["id"], "from_status": frm, "to_status": to,
                                    "actor_id": actor["id"] if actor else None, "note": note, "at": at})
                bf["updated_at"] = at

            event(None, "submitted", requester, bf["justification"], submitted)
            if status == "submitted":
                return bf
            decided = submitted + timedelta(hours=approve_h or rng.randint(4, 72))
            if status == "rejected":
                event("submitted", "rejected", vp["leader"], reason, decided)
                return bf
            event("submitted", "vp_approved", vp["leader"], "Approved", decided)
            bf["recruiter_id"] = recruiter["id"]
            event("vp_approved", "recruiter_assigned", None,
                  f"Auto-assigned to {recruiter['full_name']} (least-loaded {pos['job_family']} recruiter)",
                  decided + timedelta(seconds=1))
            if status == "recruiter_assigned":
                return bf
            event("recruiter_assigned", "req_open", recruiter, "Staffing request opened automatically", open_at)
            if status == "filled":
                event("req_open", "filled", recruiter, f"Offer accepted by {hire['full_name']}", fill_at)
            return bf

        noticed = [p for p in self.notice if p is not self.dana]
        in_sam = [p for p in noticed if p["org"] in self.sam_teams]
        in_priya = [p for p in noticed if p["org"]["parent"]["parent"] is self.priya_org and p not in in_sam]
        elsewhere = [p for p in noticed if p not in in_sam and p not in in_priya]

        # Waiting on the demo VP: exactly three.
        add(self.dana, self.dana["position"], "submitted", now - timedelta(days=2, hours=3),
            justification="Critical for the Q1 evaluation roadmap", urgency="urgent")
        add(in_priya[0], in_priya[0]["position"], "submitted", now - timedelta(days=4, hours=1), urgency="normal")
        add(in_priya[1], in_priya[1]["position"], "submitted", now - timedelta(hours=7), urgency="low")
        # Waiting on other VPs.
        for person in elsewhere[:5]:
            add(person, person["position"], "submitted", now - timedelta(hours=rng.randint(3, 130)))
        # Rejected: one of them is the demo requester's.
        add(in_sam[0], in_sam[0]["position"], "rejected", now - timedelta(days=9), reason=REJECT_REASONS[0], approve_h=30)
        add(elsewhere[5], elsewhere[5]["position"], "rejected", now - timedelta(days=6), reason=REJECT_REASONS[1], approve_h=20)
        # Approved and assigned, waiting for the recruiter to open the request.
        for i, person in enumerate([in_sam[1], in_priya[2]] + elsewhere[6:9]):
            family = person["position"]["job_family"]
            recruiter = next_recruiter(family, force_marcus=(i < 2 and family == "research"))
            add(person, person["position"], "recruiter_assigned", now - timedelta(hours=rng.randint(30, 100)),
                recruiter=recruiter, approve_h=rng.randint(4, 24))

        # Request open: seats already vacated, with a live staffing request created by the workflow.
        vacated = [r for r in self.pending_reqs if r["position"]["id"] in self.vacated_by
                   and r["opened_at"] >= self.days_ago(40)]
        sam_first = sorted(vacated, key=lambda r: r["position"]["org"] not in self.sam_teams)
        for i, req in enumerate(sam_first[:12]):
            pos = req["position"]
            open_at = datetime.combine(req["opened_at"], time(rng.randint(9, 16), rng.randint(0, 59)), ET)
            open_at = min(open_at, now - timedelta(hours=2))
            approve_gap, submit_gap = rng.randint(6, 60), rng.randint(4, 72)
            recruiter = next_recruiter(pos["job_family"], force_marcus=(i in (0, 5) and pos["job_family"] == "research"))
            req["backfill"] = add(self.vacated_by[pos["id"]], pos, "req_open",
                                  open_at - timedelta(hours=approve_gap + submit_gap), recruiter=recruiter,
                                  approve_h=submit_gap, open_at=open_at)
            req["recruiter"] = recruiter

        # Filled: a recent hire now sits in a seat someone left.
        hires = [p for t in self.teams for p in t["members"]
                 if self.days_ago(40) <= p["start_date"] <= self.days_ago(2) and p["id"] not in self.used]
        hires.sort(key=lambda p: p["org"] not in self.sam_teams)
        for hire in hires[:14]:
            pos, team = hire["position"], hire["org"]
            fill_at = datetime.combine(hire["start_date"] - timedelta(days=rng.randint(6, 14)), time(rng.randint(9, 16), 30), ET)
            open_at = fill_at - timedelta(days=rng.randint(18, 35))
            approve_gap, submit_gap = rng.randint(6, 60), rng.randint(4, 72)
            left = open_at.date() - timedelta(days=rng.randint(0, 10))
            departed = self.add_person(team, pos["job_family"], pos["level"], left - timedelta(days=rng.randint(300, 1500)),
                                       end=left, manager=team["leader"])
            pos["source"] = "backfill"
            pos["opened_at"] = left + timedelta(days=1)
            recruiter = next_recruiter(pos["job_family"])
            bf = add(departed, pos, "filled", open_at - timedelta(hours=approve_gap + submit_gap), recruiter=recruiter,
                     approve_h=submit_gap, open_at=open_at, fill_at=fill_at, hire=hire)
            self.staffing.append({"position_id": pos["id"], "recruiter_id": recruiter["id"], "status": "filled",
                                  "backfill_request_id": bf["id"], "opened_at": open_at.date(), "closed_at": fill_at.date()})

        # Every other committed seat gets an ordinary staffing request.
        marcus_quota = 3
        for req in self.pending_reqs:
            pos = req["position"]
            recruiter = req.get("recruiter")
            if recruiter is None:
                take = marcus_quota > 0 and pos["job_family"] == "research"
                marcus_quota -= take
                recruiter = next_recruiter(pos["job_family"], force_marcus=take)
            self.staffing.append({"position_id": pos["id"], "recruiter_id": recruiter["id"],
                                  "status": rng.choices(["open", "offer_out"], [75, 25])[0],
                                  "backfill_request_id": req["backfill"]["id"] if req["backfill"] else None,
                                  "opened_at": req["opened_at"], "closed_at": None})

    # ── the plan ─────────────────────────────────────────────────────────────

    def build_plan(self):
        rng = self.rng
        refresh = {k: v for k, v in sorted(self.plan.items()) if v > 0}
        original = dict(refresh)
        for key in rng.sample([k for k, v in refresh.items() if v > 8], 40):   # the refresh added a few seats
            original[key] -= rng.randint(1, 2)
        rm = self.personas["rm"]["id"]
        lock = lambda days: datetime.combine(self.days_ago(days), time(17, 0), ET)
        self.plan_versions = [
            {"id": 1, "name": "FY27 Plan", "locked_at": lock(96), "locked_by": rm},
            {"id": 2, "name": "FY27 Q1 Refresh", "locked_at": lock(12), "locked_by": rm},
        ]
        self.plan_lines = [
            {"plan_version_id": vid, "org_id": org_id, "job_family": family, "approved_headcount": n,
             "approved_cost_usd": n * COST_PER_HEAD[family]}
            for vid, lines in ((1, original), (2, refresh)) for (org_id, family), n in lines.items()
        ]

    # ── sixty days of snapshots ──────────────────────────────────────────────

    def bucket(self, pos, active_reqs):
        if pos["position_type"] != "standard":
            return pos["position_type"]
        if pos["person_id"]:
            return "filled"
        return "open_with_req" if pos["id"] in active_reqs else "open_no_req"

    def build_snapshots(self):
        """Start from today's real counts and walk backwards, undoing each day's hires and exits.
        That makes every day tie out to the next by construction."""
        rng, as_of = self.rng, self.as_of
        cols = ["filled", "open_with_req", "open_no_req", "reserve", "negative", "total_people"]
        ancestors = {}
        for org in self.orgs:
            chain, node = [], org
            while node:
                chain.append(node["id"])
                node = node["parent"]
            ancestors[org["id"]] = chain

        active_reqs = {s["position_id"] for s in self.staffing if s["status"] in ("open", "offer_out")}
        direct = {o["id"]: dict.fromkeys(cols, 0) for o in self.orgs}
        for pos in self.positions:
            direct[pos["org_id"]][self.bucket(pos, active_reqs)] += 1
        hires, exits, left = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
        for p in self.people:
            if p["end_date"] is None or p["end_date"] >= as_of:
                direct[p["org_id"]]["total_people"] += 1
            if p["start_date"] > self.days_ago(HISTORY_DAYS):
                hires[p["start_date"]][p["org_id"]] += 1
            if p["end_date"] and p["end_date"] < as_of:
                left[p["end_date"]][p["org_id"]] += 1            # everyone who left, for the people count
                if not p["ghost"]:
                    exits[p["end_date"]][p["org_id"]] += 1       # seats actually vacated

        def record(day):
            rolled = {o["id"]: dict.fromkeys(cols, 0) for o in self.orgs}
            for org_id, counts in direct.items():
                for anc in ancestors[org_id]:
                    for c in cols:
                        rolled[anc][c] += counts[c]
            for org_id, counts in rolled.items():
                self.snapshots.append({"snapshot_date": day, "org_id": org_id, **counts})

        record(as_of)
        for back in range(HISTORY_DAYS - 1):
            day, prev = self.days_ago(back), self.days_ago(back + 1)
            for org_id, n in hires[day].items():                 # undo today's hires
                d = direct[org_id]
                d["filled"] -= n; d["open_with_req"] += n; d["total_people"] -= n
            for org_id, n in exits[prev].items():                # undo yesterday's exits
                d = direct[org_id]
                d["filled"] += n
                from_no_req = min(n, d["open_no_req"])
                d["open_no_req"] -= from_no_req; d["open_with_req"] -= n - from_no_req
            for org_id, n in left[prev].items():
                direct[org_id]["total_people"] += n
            for d in direct.values():                            # a few requests were opened along the way
                if d["open_with_req"] > 0 and rng.random() < 0.03:
                    d["open_with_req"] -= 1; d["open_no_req"] += 1
                d["open_with_req"] = max(d["open_with_req"], 0)
            record(prev)

        # The planted anomaly: last night's load over-counted one VP org's people.
        vp = next(o for o in self.orgs if o["name"] == ANOMALY_VP)
        row = lambda org_id, day: next(s for s in self.snapshots if s["org_id"] == org_id and s["snapshot_date"] == day)
        company_today, vp_today, vp_before = row(1, as_of), row(vp["id"], as_of), row(vp["id"], self.days_ago(1))
        company_before = row(1, self.days_ago(1))
        vp_today["total_people"] += round(ANOMALY_POINTS / 100 * company_today["total_people"])
        self.anomaly = {"org_id": vp["id"], "org": vp["name"],
                        "share_before_pct": round(100 * vp_before["total_people"] / company_before["total_people"], 1),
                        "share_after_pct": round(100 * vp_today["total_people"] / company_today["total_people"], 1)}

    def build_resolutions(self):
        rm = self.personas["rm"]["id"]
        flat = [(kind, pos) for kind, items in self.plants.items() for pos in items]
        for kind, pos in self.rng.sample(flat, PRE_RESOLVED):
            self.resolutions.append({"exception_type": kind, "position_id": pos["id"], "resolved_by": rm,
                                     "resolved_at": self.now - timedelta(hours=self.rng.randint(5, 240))})

    def build(self):
        self.build_orgs_and_people()
        self.pin_personas()
        self.plant_noise()
        self.give_notice()
        self.build_backfills()
        self.build_plan()
        self.build_snapshots()
        self.build_resolutions()
        for org in self.orgs:
            org["leader_person_id"] = org["leader"]["id"]
        active = [p for p in self.people if p["end_date"] is None or p["end_date"] >= self.as_of]
        self.manifest = {
            "seed": SEED,
            "counts": {"orgs": len(self.orgs), "people": len(self.people), "active_people": len(active),
                       "positions": len(self.positions), "staffing_requests": len(self.staffing),
                       "backfill_requests": len(self.backfills), "plan_lines": len(self.plan_lines),
                       "snapshot_days": HISTORY_DAYS},
            "plants": {kind: sorted(p["position_code"] for p in items) for kind, items in self.plants.items()},
            "negative_positions": sorted(p["position_code"] for p in self.negatives),
            "anomaly": self.anomaly,
            "personas": {role: p["full_name"] for role, p in self.personas.items()},
        }
        return self


# ── loading ──────────────────────────────────────────────────────────────────

TABLES = {  # table -> columns, in load order
    "orgs": ["id", "name", "parent_id", "level", "leader_person_id", "cost_center"],
    "people": ["id", "full_name", "email", "org_id", "job_family", "level", "location", "start_date", "end_date", "manager_id"],
    "positions": ["id", "position_code", "org_id", "job_family", "level", "position_type", "person_id", "opened_at", "source"],
    "recruiter_coverage": ["person_id", "job_family"],
    "plan_versions": ["id", "name"],
    "plan_lines": ["plan_version_id", "org_id", "job_family", "approved_headcount", "approved_cost_usd"],
    "backfill_requests": ["id", "departing_person_id", "position_id", "requested_by", "justification", "urgency", "status",
                          "vp_approver_id", "recruiter_id", "created_at", "updated_at"],
    "staffing_requests": ["position_id", "recruiter_id", "status", "backfill_request_id", "opened_at", "closed_at"],
    "request_events": ["backfill_request_id", "from_status", "to_status", "actor_id", "note", "at"],
    "daily_snapshots": ["snapshot_date", "org_id", "filled", "open_with_req", "open_no_req", "reserve", "negative", "total_people"],
    "exception_resolutions": ["exception_type", "position_id", "resolved_by", "resolved_at"],
}
ALL_TABLES = list(TABLES) + ["check_runs", "check_results", "app_meta"]


def load(conn, b: Builder) -> None:
    """Replace everything in the database with the built data. The caller commits."""
    data = {"orgs": b.orgs, "people": b.people, "positions": b.positions, "recruiter_coverage": b.coverage,
            "plan_versions": b.plan_versions, "plan_lines": b.plan_lines, "backfill_requests": b.backfills,
            "staffing_requests": b.staffing, "request_events": b.events, "daily_snapshots": b.snapshots,
            "exception_resolutions": b.resolutions}
    cur = conn.cursor()
    cur.execute(f"TRUNCATE {', '.join(ALL_TABLES)} RESTART IDENTITY CASCADE")
    for table, cols in TABLES.items():
        with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as copy:
            for row in data[table]:
                copy.write_row([row[c] for c in cols])
    # Lock both plans and store their fingerprints.
    for v in b.plan_versions:
        cur.execute("UPDATE plan_versions SET locked_at = %s, locked_by = %s, content_hash = plan_hash(id) WHERE id = %s",
                    (v["locked_at"], v["locked_by"], v["id"]))
    # Hand-assigned ids: move each sequence past them.
    for table in ("orgs", "people", "positions", "plan_versions", "backfill_requests"):
        cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT max(id) FROM {table}))")
    meta = {"seed_as_of": b.as_of.isoformat(), "seeded_at": b.now.isoformat(),
            **{f"persona_{role}": str(p["id"]) for role, p in b.personas.items()}}
    cur.executemany("INSERT INTO app_meta (key, value) VALUES (%s, %s)", list(meta.items()))


def seed(conn) -> dict:
    """Build and load. Returns the manifest of what was planted."""
    as_of = db.one(conn, "SELECT today() AS d")["d"]
    builder = Builder(as_of, datetime.now(ET)).build()
    load(conn, builder)
    return builder.manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true", help="use PROD_DATABASE_URL")
    args = parser.parse_args()
    url = os.environ["PROD_DATABASE_URL"] if args.prod else db.database_url()
    with db.connect(url) as conn:
        manifest = seed(conn)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Seeded {'production' if args.prod else 'dev'}: " + ", ".join(f"{v:,} {k}" for k, v in manifest["counts"].items()))
    print("Planted: " + ", ".join(f"{len(v)} {k}" for k, v in manifest["plants"].items()))


if __name__ == "__main__":
    main()
