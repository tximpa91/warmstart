"""Original agent-authored fictional policy fixtures. Human approval is pending."""

from dataclasses import asdict

from warmstart.config import Config, fingerprint
from warmstart.inference import offline_vector
from warmstart.models import Policy, SeedAnswer

PROFILES = tuple(
    f"store_{shop}_{country}_{tier}"
    for shop in ("a", "b")
    for country in ("ch", "de")
    for tier in ("standard", "premium")
)
VERSIONS = ("v1", "v2")
PROVENANCE = {
    "author": "AI implementation agent",
    "origin": "original fictional electronics support fixtures",
    "human_reviewed": False,
    "admission": "local_fixture_only",
    "real_customer_data": False,
}
QUESTIONS = {
    "returns:unopened": "How long can I return unopened products?",
    "returns:opened_headphones": "Can I return opened headphones?",
    "shipping:standard": "What is the standard shipping cost?",
    "refund:standard": "How long does refund processing take?",
    "warranty:standard": "How many months is the warranty period?",
}


def policies() -> list[Policy]:
    result = []
    for version in VERSIONS:
        for profile in PROFILES:
            shop = profile.split("_")[1]
            country = profile.split("_")[2]
            tier = profile.split("_")[3]
            days = (30 if shop == "a" else 14) if version == "v1" else (21 if shop == "a" else 10)
            fee = 0 if tier == "premium" else (5 if country == "ch" else 7)
            currency = "CHF" if country == "ch" else "EUR"
            months = 24 if shop == "a" else 12
            facts = {
                "returns:unopened": (
                    f"Unopened products may be returned within {days} days of delivery."
                ),
                "returns:opened_headphones": (
                    "Opened headphones are excluded from the ordinary return policy."
                ),
                "shipping:standard": f"Standard shipping costs {currency} {fee} per order.",
                "refund:standard": (
                    f"Refund processing takes {5 if shop == 'a' else 8} business days "
                    "after the returned product is accepted."
                ),
                "warranty:standard": (
                    f"The fictional store warranty lasts {months} months from delivery."
                ),
            }
            sources = {key: f"{profile}:{version}:{key.replace(':', '_')}" for key in facts}
            result.append(Policy(profile, version, facts, sources))
    return result


def seeds() -> list[SeedAnswer]:
    return [
        SeedAnswer(
            id=f"{policy.profile}:{policy.version}:{guard}",
            profile=policy.profile,
            version=policy.version,
            question=question,
            guard=guard,
            answer=policy.facts[guard],
            fact_ids=(policy.source_ids[guard],),
            vector=offline_vector(question),
            embedding_fingerprint=Config().embedding_fingerprint(),
        )
        for policy in policies()
        for guard, question in QUESTIONS.items()
    ]


def corpus_fingerprint() -> str:
    return fingerprint(
        {
            "provenance": PROVENANCE,
            "policies": [asdict(policy) for policy in policies()],
            "seeds": [asdict(seed) for seed in seeds()],
        }
    )
