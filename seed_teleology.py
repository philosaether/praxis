"""
Seed script: Phil's teleological structure from Initial Teleological Import.pdf
"""

import sys
sys.path.insert(0, "src")

from praxis.generators import (
    GeneratorGraph,
    Goal,
    Obligation,
    Capacity,
    Accomplishment,
    Practice,
)
from praxis.db import get_connection


def seed_teleology():
    print("Loading generator graph...")
    graph = GeneratorGraph(get_connection)
    graph.load()

    print(f"Existing generators: {len(graph.nodes)}")
    if graph.nodes:
        print("Database not empty. Clear it first if you want a fresh seed.")
        return

    print("\nSeeding Phil's teleological structure...\n")

    # =========================================================================
    # GOALS
    # =========================================================================

    # Root goal
    graph.add(Goal(
        id="positive-change",
        name="Accomplish as much positive change as possible",
        agent_context="Top-level life goal. Before I die.",
    ))

    # Level 2: Implement philosophy
    graph.add(Goal(
        id="implement-philosophy",
        name="Implement a philosophy of change",
        agent_context="Theoretical foundation for action",
    ), parent_ids=["positive-change"])

    # Level 3: Acquire capacity vs power
    graph.add(Goal(
        id="acquire-capacity",
        name="Acquire the capacity to improve systems",
        agent_context="Internal capability development",
    ), parent_ids=["implement-philosophy"])

    graph.add(Goal(
        id="acquire-power",
        name="Acquire the power to improve systems",
        agent_context="External influence and resources",
    ), parent_ids=["implement-philosophy"])

    # Under acquire-capacity: capacities
    graph.add(Capacity(
        id="cap-systems-engineering",
        name="Systems engineering",
        agent_context="Ability to analyze, design, and improve complex systems",
        measurement_method="Portfolio of successful system improvements",
    ), parent_ids=["acquire-capacity"])

    graph.add(Capacity(
        id="cap-moral-reasoning",
        name="Moral reasoning",
        agent_context="Ability to reason about ethics and make principled decisions",
    ), parent_ids=["acquire-capacity"])

    # Under acquire-power: reputation -> influence -> outcomes -> reputation loop
    graph.add(Goal(
        id="gain-reputation",
        name="Gain reputation as an effective agent of systemic change",
        agent_context="Build credibility and brand",
    ), parent_ids=["acquire-power"])

    graph.add(Goal(
        id="gain-influence",
        name="Use reputation to gain influence over embodied systems",
        agent_context="Convert reputation to access and leverage",
    ), parent_ids=["acquire-power"])

    graph.add(Goal(
        id="improve-outcomes",
        name="Use influence to improve outcomes in measurable ways",
        agent_context="Actual systemic improvements",
    ), parent_ids=["acquire-power"])

    graph.add(Goal(
        id="outcomes-to-reputation",
        name="Use improved outcomes to gain reputation",
        agent_context="Virtuous cycle: results -> credibility",
    ), parent_ids=["acquire-power"])

    # Under gain-reputation
    # Link systems engineering capacity (already exists, add second parent)
    graph.link("cap-systems-engineering", "gain-reputation")

    graph.add(Capacity(
        id="cap-communication",
        name="Communication of complex ideas",
        agent_context="Ability to explain systems thinking to diverse audiences",
    ), parent_ids=["gain-reputation"])

    graph.add(Accomplishment(
        id="acc-brand-identity",
        name="Brand identity",
        agent_context="Defined personal/professional brand",
        success_criteria="Clear positioning, visual identity, messaging",
    ), parent_ids=["gain-reputation"])

    graph.add(Accomplishment(
        id="acc-brand-recognition",
        name="Brand recognition",
        agent_context="Market awareness of brand",
        success_criteria="Inbound inquiries, recognition in target circles",
    ), parent_ids=["gain-reputation"])

    graph.add(Practice(
        id="prac-publish",
        name="Publish",
        agent_context="Regular publishing of essays, code, and ideas",
        rhythm_frequency="weekly",
    ), parent_ids=["gain-reputation"])

    # Under gain-influence: day job, freelance
    graph.add(Accomplishment(
        id="acc-day-job",
        name="Day job",
        agent_context="Secure employment at target company",
        success_criteria="Signed offer letter",
    ), parent_ids=["gain-influence"])

    graph.add(Accomplishment(
        id="acc-passed-interview",
        name="Passed interview gate",
        agent_context="Successfully pass technical interviews",
        success_criteria="Offer extended",
    ), parent_ids=["acc-day-job"])

    graph.add(Capacity(
        id="cap-technical-interviews",
        name="Technical interviews",
        agent_context="Ability to perform in technical interview settings",
        measurement_method="Recorded practice sessions graded by AI",
        measurement_rubric="Comprehension, approach, correctness, syntax, time",
        target_level="Consistent medium solves in <25 min",
    ), parent_ids=["acc-passed-interview"])

    graph.add(Accomplishment(
        id="acc-freelance-established",
        name="Established freelance workstream",
        agent_context="Paying consulting clients",
        success_criteria="Recurring revenue from consulting",
    ), parent_ids=["gain-influence"])

    graph.add(Accomplishment(
        id="acc-freelance-overtakes",
        name="Freelance workstream overtakes day job",
        agent_context="Consulting income exceeds salary",
        success_criteria="Monthly consulting > monthly salary",
    ), parent_ids=["gain-influence"])

    # Under improve-outcomes and outcomes-to-reputation: case study practice
    graph.add(Practice(
        id="prac-case-studies",
        name="Write case study for each project",
        agent_context="Document systemic improvements for portfolio and credibility",
        rhythm_frequency="per-project",
    ), parent_ids=["improve-outcomes", "outcomes-to-reputation"])

    # =========================================================================
    # OBLIGATIONS
    # =========================================================================

    # Root obligation: remain able to express agency
    graph.add(Obligation(
        id="obl-express-agency",
        name="Remain able to express agency",
        agent_context="Preserve freedom and capability to act",
        consequence_of_neglect="Loss of autonomy",
    ))

    # Stay alive
    graph.add(Obligation(
        id="obl-stay-alive",
        name="Stay alive",
        consequence_of_neglect="Death",
    ), parent_ids=["obl-express-agency"])

    graph.add(Accomplishment(
        id="acc-income-this-year",
        name="Acquire income this year",
        agent_context="Financial survival",
        success_criteria="Sufficient income to cover expenses through 2026",
    ), parent_ids=["obl-stay-alive"])

    # Stay out of jail
    graph.add(Obligation(
        id="obl-stay-out-of-jail",
        name="Stay out of jail",
        consequence_of_neglect="Incarceration",
    ), parent_ids=["obl-express-agency"])

    graph.add(Obligation(
        id="obl-pay-taxes",
        name="Pay taxes",
        consequence_of_neglect="IRS penalties, potential prosecution",
    ), parent_ids=["obl-stay-out-of-jail"])

    graph.add(Practice(
        id="prac-file-taxes",
        name="File taxes yearly",
        rhythm_frequency="yearly",
        rhythm_constraints="Q1 for previous year",
    ), parent_ids=["obl-pay-taxes"])

    graph.add(Accomplishment(
        id="acc-onboard-finances-fms",
        name="Onboard all finances to optimized Financial Management System",
        success_criteria="All accounts tracked, automated where possible",
    ), parent_ids=["obl-pay-taxes"])

    graph.add(Accomplishment(
        id="acc-create-fms",
        name="Create Financial Management System",
        success_criteria="System exists and is functional",
    ), parent_ids=["acc-onboard-finances-fms"])

    graph.add(Accomplishment(
        id="acc-optimize-fms",
        name="Optimize Financial Management System",
        success_criteria="System is efficient and low-maintenance",
    ), parent_ids=["acc-onboard-finances-fms"])

    graph.add(Obligation(
        id="obl-obey-laws",
        name="Obey laws",
        consequence_of_neglect="Legal consequences",
    ), parent_ids=["obl-stay-out-of-jail"])

    # Maintain PE
    graph.add(Obligation(
        id="obl-maintain-pe",
        name="Maintain Proper Elevation's growth trajectory",
        agent_context="Ronique partnership, PE business",
        consequence_of_neglect="Partnership strain, business stagnation",
    ))

    graph.add(Obligation(
        id="obl-pe-legal-status",
        name="Maintain PE legal status",
        consequence_of_neglect="Business dissolution, legal issues",
    ), parent_ids=["obl-maintain-pe"])

    graph.add(Practice(
        id="prac-pe-filings",
        name="Complete PE filings yearly",
        rhythm_frequency="yearly",
    ), parent_ids=["obl-pe-legal-status"])

    graph.add(Accomplishment(
        id="acc-pe-onboard-filings",
        name="Onboard PE filings to Filing Management System",
        success_criteria="All PE filings tracked and scheduled",
    ), parent_ids=["obl-pe-legal-status"])

    graph.add(Accomplishment(
        id="acc-pe-create-filing-ms",
        name="Create PE Filing Management System",
    ), parent_ids=["acc-pe-onboard-filings"])

    graph.add(Accomplishment(
        id="acc-pe-optimize-filing-ms",
        name="Optimize PE Filing Management System",
    ), parent_ids=["acc-pe-onboard-filings"])

    # Maintain EE (Ethical Engineering)
    graph.add(Obligation(
        id="obl-maintain-ee",
        name="Maintain Ethical Engineering's growth trajectory",
        agent_context="Consulting business entity",
        consequence_of_neglect="Business dissolution, legal issues",
    ))

    graph.add(Obligation(
        id="obl-ee-legal-status",
        name="Maintain EE legal status",
        consequence_of_neglect="Business dissolution, legal issues",
    ), parent_ids=["obl-maintain-ee"])

    graph.add(Practice(
        id="prac-ee-filings",
        name="Complete EE filings yearly",
        rhythm_frequency="yearly",
    ), parent_ids=["obl-ee-legal-status"])

    graph.add(Accomplishment(
        id="acc-ee-onboard-filings",
        name="Onboard EE filings to Filing Management System",
        success_criteria="All EE filings tracked and scheduled",
    ), parent_ids=["obl-ee-legal-status"])

    graph.add(Accomplishment(
        id="acc-ee-create-filing-ms",
        name="Create EE Filing Management System",
    ), parent_ids=["acc-ee-onboard-filings"])

    graph.add(Accomplishment(
        id="acc-ee-optimize-filing-ms",
        name="Optimize EE Filing Management System",
    ), parent_ids=["acc-ee-onboard-filings"])

    # Maintain Prometheus partnership
    graph.add(Obligation(
        id="obl-maintain-prometheus",
        name="Maintain partnership with Prometheus",
        consequence_of_neglect="Lost partnership, reputation damage",
    ))

    graph.add(Obligation(
        id="obl-prometheus-commitments",
        name="Follow through on work commitments",
        consequence_of_neglect="Broken promises, trust erosion",
    ), parent_ids=["obl-maintain-prometheus"])

    graph.add(Practice(
        id="prac-pro-bono",
        name="Pro-bono engineering",
        agent_context="Volunteer technical work for Prometheus",
        rhythm_frequency="as-needed",
    ), parent_ids=["obl-prometheus-commitments"])

    # Maintain professional network
    graph.add(Obligation(
        id="obl-maintain-network",
        name="Maintain professional network",
        consequence_of_neglect="Relationship atrophy, lost opportunities",
    ))

    graph.add(Practice(
        id="prac-keep-in-touch",
        name="Keep in touch with network members",
        rhythm_frequency="varies by relationship",
    ), parent_ids=["obl-maintain-network"])

    graph.add(Accomplishment(
        id="acc-onboard-network-cms",
        name="Onboard existing network to CMS",
        agent_context="Contact management system",
        success_criteria="All contacts tracked with relationship metadata",
    ), parent_ids=["obl-maintain-network"])

    # =========================================================================
    # Summary
    # =========================================================================

    print(f"Created {len(graph.nodes)} generators")
    print(f"  Goals: {len(graph.goals())}")
    print(f"  Obligations: {len(graph.obligations())}")
    print(f"  Capacities: {len(graph.capacities())}")
    print(f"  Accomplishments: {len(graph.accomplishments())}")
    print(f"  Practices: {len(graph.practices())}")

    root_count = len(graph.roots())
    print(f"\nRoot generators: {root_count}")
    for root in sorted(graph.roots(), key=lambda g: g.id):
        print(f"  - {root.id}: {root.name}")

    print("\n✓ Teleology seeded successfully!")
    print("\nTry: praxis gen tree")


if __name__ == "__main__":
    seed_teleology()
