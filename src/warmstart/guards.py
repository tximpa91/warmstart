"""Conservative, inspectable cache admission rules for the fictional corpus."""

import math
import re

from warmstart.models import Classification


def normalize(question: str) -> str:
    """Whitespace/case normalization only: numbers and negation remain intact."""
    return " ".join(question.casefold().split())


def classify(question: str) -> Classification:
    text = normalize(question)
    if not text.isascii():
        return Classification("ambiguous", "", False, "english_ascii_pilot_only")
    if any(
        marker in text
        for marker in (
            "ignore previous",
            "ignore all",
            "system prompt",
            "api key",
            "secret",
            "<script",
            "execute",
            "override",
            "another tenant",
        )
    ):
        return Classification("unsupported", "", False, "unsupported_instruction")
    if any(
        marker in text
        for marker in ("my order", "order status", "tracking", "my account", "payment", "claim")
    ):
        return Classification("personal", "", False, "requires_private_integration")
    # Numbers, negation and exception words are not collapsed into generic FAQ matches.
    if re.search(
        r"\d|\b(no|not|never|except|unless|without|cannot|can't|don't|isn't|"
        r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
        r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b",
        text,
    ):
        return Classification("ambiguous", "", False, "conditions_require_clarification")
    intent_groups = (
        ("refund",),
        ("shipping", "delivery", "postage", "dispatch"),
        ("warranty", "guarantee"),
        ("return", "send back", "sending back"),
    )
    if sum(any(word in text for word in group) for group in intent_groups) > 1:
        return Classification("ambiguous", "", False, "multiple_policy_questions")
    if re.search(r"\b(unopened|sealed)\b", text) and re.search(r"\bopened\b", text):
        return Classification("ambiguous", "", False, "multiple_product_conditions")
    words = set(re.findall(r"[a-z']+", text))
    price_words = {"cost", "fee", "price", "charge", "charged"}
    return_question = any(word in text for word in ("return", "send back", "sending back"))
    shipping_question = any(
        word in text for word in ("shipping", "delivery", "postage", "dispatch")
    )
    if not shipping_question and words & price_words:
        return Classification("ambiguous", "", False, "unsupported_fee_question")
    if shipping_question and words & {"long", "days", "time", "duration", "period", "deadline"}:
        return Classification("ambiguous", "", False, "unsupported_shipping_timing")
    if return_question and words & {"processing", "process"}:
        return Classification("ambiguous", "", False, "unsupported_return_processing")
    if not return_question and words & {
        "opened",
        "unopened",
        "sealed",
        "headphones",
        "product",
        "products",
        "goods",
        "item",
        "items",
    }:
        return Classification("ambiguous", "", False, "unsupported_product_qualification")
    if "premium" in words and not re.search(r"\bpremium (customers?|profile|tier)\b", text):
        return Classification("ambiguous", "", False, "ambiguous_premium_service")
    # A bounded FAQ pilot cannot infer arbitrary destinations, product categories or
    # service levels from similarity. Unknown qualifiers are deliberately safe misses.
    supported_words = set(
        (
            "a an the this that is are be were what which when how many much long can may would "
            "should does do i you me for to of in as by if here now with please tell explain state "
            "applies apply active current new updated update edition policy store shop profile "
            "ordinary standard premium customers country allow allowed accepted accept eligible "
            "permitted covered covers cover coverage available expect need want happens within "
            "after under shipping delivery postage dispatch cost fee price charge charged carry "
            "refund processing process time days business speed duration take takes until finishes "
            "usual warranty guarantee months length period lasts return returns returning returned "
            "send sending back unopened sealed opened headphones product products item items goods "
            "window deadline"
        ).split()
    )
    if set(re.findall(r"[a-z']+", text)) - supported_words:
        return Classification("ambiguous", "", False, "unsupported_question_qualifier")
    if "refund" in text:
        if any(word in text for word in ("days", "long", "time", "processing", "speed")):
            return Classification("refund", "standard", True)
    if any(word in text for word in ("shipping", "delivery", "postage", "dispatch")):
        if any(word in text for word in ("cost", "fee", "price", "charge")):
            return Classification("shipping", "standard", True)
    if "warranty" in text or "guarantee" in text:
        if any(word in text for word in ("months", "long", "length", "duration", "period")):
            return Classification("warranty", "standard", True)
    if any(word in text for word in ("return", "send back", "sending back")):
        if re.search(r"\b(unopened|sealed)\b", text):
            return Classification("returns", "unopened", True)
        if "opened" in text and "headphone" in text:
            return Classification("returns", "opened_headphones", True)
    return Classification("ambiguous", "", False, "insufficient_supported_context")


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != 384 or len(right) != 384:
        raise ValueError("Expected 384-dimensional vectors")
    if not all(math.isfinite(value) for value in (*left, *right)):
        raise ValueError("Vectors must contain finite values")
    a = math.sqrt(sum(value * value for value in left))
    b = math.sqrt(sum(value * value for value in right))
    if a == 0 or b == 0:
        return 0.0
    return sum(x * y for x, y in zip(left, right, strict=True)) / (a * b)
