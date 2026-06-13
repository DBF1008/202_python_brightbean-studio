"""Keyword-based sentiment analysis engine for inbox messages."""

POSITIVE_KEYWORDS = [
    "love",
    "great",
    "amazing",
    "thank",
    "thanks",
    "excellent",
    "awesome",
    "perfect",
    "best",
    "fantastic",
    "wonderful",
    "beautiful",
    "brilliant",
    "incredible",
    "outstanding",
    "impressive",
    "helpful",
    "appreciate",
    "happy",
    "glad",
    "excited",
    "recommend",
    "superb",
    "delighted",
    "thrilled",
]

NEGATIVE_KEYWORDS = [
    "hate",
    "terrible",
    "awful",
    "worst",
    "disappointed",
    "broken",
    "scam",
    "refund",
    "horrible",
    "disgusting",
    "pathetic",
    "useless",
    "angry",
    "furious",
    "unacceptable",
    "frustrating",
    "annoying",
    "poor",
    "waste",
    "trash",
    "spam",
    "fake",
    "misleading",
    "rude",
    "unprofessional",
]


def analyze_sentiment(text: str) -> str:
    """Analyze sentiment of text using keyword matching.

    Returns 'positive', 'negative', or 'neutral'.
    """
    if not text:
        return "neutral"

    import re

    text_lower = text.lower()
    # Strip punctuation from each word so "great!" matches "great"
    words = set(re.sub(r"[^\w\s]", "", text_lower).split())

    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in words)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in words)

    if neg_count > pos_count:
        return "negative"
    elif pos_count > neg_count:
        return "positive"
    return "neutral"
