"""
UniCamplink AI action and intent detection.

This module contains only local intent detection.
It does not access the database and does not generate URLs.

Database access and Flask route handling remain in app.py.
"""

import re


NAVIGATION_ROUTES = {
    "dashboard": "/dashboard",
    "home": "/dashboard",
    "feed": "/feed",
    "profile": "/profile",
    "groups": "/groups",
    "marketplace": "/marketplace",
    "messages": "/messages",
    "notifications": "/notifications",
    "friends": "/friends",
    "announcements": "/announcements",
    "ai": "/ai",
}


MARKETPLACE_CATEGORY_ALIASES = {
    "electronics": "Electronics",
    "electronic": "Electronics",
    "fashion": "Fashion",
    "clothes": "Fashion",
    "clothing": "Fashion",
    "books": "Books",
    "book": "Books",
    "hostel": "Hostel",
    "food": "Food",
    "services": "Services",
    "service": "Services",
    "other": "Other",
}


NAVIGATION_PATTERNS = {
    "dashboard": [
        r"\bopen\s+(?:my\s+)?dashboard\b",
        r"\bgo\s+to\s+(?:my\s+)?dashboard\b",
        r"\btake\s+me\s+to\s+(?:my\s+)?dashboard\b",
        r"\bshow\s+(?:my\s+)?dashboard\b",
        r"\bopen\s+home\b",
        r"\bgo\s+home\b",
    ],
    "feed": [
        r"\bopen\s+(?:the\s+)?feed\b",
        r"\bgo\s+to\s+(?:the\s+)?feed\b",
        r"\btake\s+me\s+to\s+(?:the\s+)?feed\b",
        r"\bshow\s+(?:the\s+)?feed\b",
    ],
    "profile": [
        r"\bopen\s+(?:my\s+)?profile\b",
        r"\bgo\s+to\s+(?:my\s+)?profile\b",
        r"\btake\s+me\s+to\s+(?:my\s+)?profile\b",
        r"\bshow\s+(?:my\s+)?profile\b",
    ],
    "groups": [
        r"\bopen\s+(?:my\s+)?groups\b",
        r"\bgo\s+to\s+(?:my\s+)?groups\b",
        r"\btake\s+me\s+to\s+(?:my\s+)?groups\b",
        r"\bshow\s+(?:my\s+)?groups\b",
    ],
    "marketplace": [
        r"\bopen\s+(?:the\s+)?marketplace\b",
        r"\bgo\s+to\s+(?:the\s+)?marketplace\b",
        r"\btake\s+me\s+to\s+(?:the\s+)?marketplace\b",
        r"\bshow\s+(?:the\s+)?marketplace\b",
    ],
    "messages": [
        r"\bopen\s+(?:my\s+)?messages\b",
        r"\bgo\s+to\s+(?:my\s+)?messages\b",
        r"\btake\s+me\s+to\s+(?:my\s+)?messages\b",
        r"\bshow\s+(?:my\s+)?messages\b",
    ],
    "notifications": [
        r"\bopen\s+(?:my\s+)?notifications\b",
        r"\bgo\s+to\s+(?:my\s+)?notifications\b",
        r"\btake\s+me\s+to\s+(?:my\s+)?notifications\b",
        r"\bshow\s+(?:my\s+)?notifications\b",
    ],
    "friends": [
        r"\bopen\s+(?:my\s+)?friends\b",
        r"\bgo\s+to\s+(?:my\s+)?friends\b",
        r"\btake\s+me\s+to\s+(?:my\s+)?friends\b",
        r"\bshow\s+(?:my\s+)?friends\b",
    ],
    "announcements": [
        r"\bopen\s+(?:the\s+)?announcements\b",
        r"\bgo\s+to\s+(?:the\s+)?announcements\b",
        r"\btake\s+me\s+to\s+(?:the\s+)?announcements\b",
        r"\bshow\s+(?:the\s+)?announcements\b",
    ],
    "ai": [
        r"\bopen\s+(?:the\s+)?ai\b",
        r"\bgo\s+to\s+(?:the\s+)?ai\b",
        r"\btake\s+me\s+to\s+(?:the\s+)?ai\b",
    ],
}


OPPORTUNITY_TERMS = (
    "opportunity",
    "opportunities",
    "scholarship",
    "scholarships",
    "competition",
    "competitions",
    "internship",
    "internships",
    "fellowship",
    "fellowships",
    "grant",
    "grants",
    "hackathon",
    "hackathons",
    "contest",
    "contests",
    "funding",
    "job",
    "jobs",
)


MARKETPLACE_TERMS = (
    "marketplace",
    "product",
    "products",
    "buy",
    "buying",
    "sell",
    "selling",
    "for sale",
    "listing",
    "listings",
    "price",
    "prices",
)

def _normalize(message):
    if not isinstance(message, str):
        return ""

    return re.sub(
        r"\s+",
        " ",
        message.strip().lower()
    )


def _detect_navigation(message):
    for route_name, patterns in NAVIGATION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, message):
                return {
                    "type": "navigate",
                    "route": route_name,
                    "url": NAVIGATION_ROUTES[route_name],
                }

    return None


def _detect_marketplace(message):
    category = None

    for alias, canonical_category in MARKETPLACE_CATEGORY_ALIASES.items():
        if re.search(
            r"\b" + re.escape(alias) + r"\b",
            message
        ):
            category = canonical_category
            break

    has_marketplace_term = any(
        term in message
        for term in MARKETPLACE_TERMS
    )

    has_category = category is not None

    # Product/category language without an explicit
    # Marketplace word can still represent a search.
    product_language = any(
        word in message
        for word in (
            "laptop",
            "laptops",
            "phone",
            "phones",
            "iphone",
            "iphones",
            "android",
            "computer",
            "computers",
            "tablet",
            "tablets",
            "shoe",
            "shoes",
            "dress",
            "dresses",
            "textbook",
            "textbooks",
            "food",
            "hostel",
            "service",
            "services",
        )
    )

    if not (
        has_marketplace_term
        or has_category
        or product_language
    ):
        return None

    query = message

    removable_phrases = [
        r"\bwhat\s+is\s+available\b",
        r"\bwhat\s+products\s+are\s+available\b",
        r"\bwhat\s+items\s+are\s+available\b",
        r"\bshow\s+me\b",
        r"\bfind\s+me\b",
        r"\bfind\b",
        r"\bsearch\s+for\b",
        r"\bsearch\b",
        r"\blook\s+for\b",
        r"\blooking\s+for\b",
        r"\bi\s+want\b",
        r"\bi\s+need\b",
        r"\bavailable\b",
        r"\bfor\s+sale\b",
        r"\bon\s+the\s+marketplace\b",
        r"\bin\s+the\s+marketplace\b",
        r"\bmarketplace\b",
        r"\bproducts?\b",
        r"\blistings?\b",
        r"\bplease\b",
    ]

    for phrase in removable_phrases:
        query = re.sub(
            phrase,
            " ",
            query,
            flags=re.IGNORECASE
        )

    # If the whole remaining query is simply a category,
    # let the category filter do the work.
    query = re.sub(r"\s+", " ", query).strip()

    if category:
        query = re.sub(
            r"\b" + re.escape(category.lower()) + r"\b",
            " ",
            query,
            flags=re.IGNORECASE
        )
        query = re.sub(r"\s+", " ", query).strip()

    return {
        "type": "marketplace_search",
        "query": query,
        "category": category,
    }


def _detect_opportunity(message):
    if not any(
        term in message
        for term in OPPORTUNITY_TERMS
    ):
        return None

    query = message

    removable_phrases = [
        r"\bwhat\s+opportunities\s+are\s+available\b",
        r"\bwhat\s+opportunities\s+do\s+we\s+have\b",
        r"\bshow\s+me\b",
        r"\bfind\s+me\b",
        r"\bfind\b",
        r"\bsearch\s+for\b",
        r"\bsearch\b",
        r"\bavailable\b",
        r"\bon\s+unicamplink\b",
        r"\bin\s+unicamplink\b",
        r"\bopportunities\b",
        r"\bopportunity\b",
        r"\bplease\b",
    ]

    for phrase in removable_phrases:
        query = re.sub(
            phrase,
            " ",
            query,
            flags=re.IGNORECASE
        )

    query = re.sub(
        r"\s+",
        " ",
        query
    ).strip()

    return {
        "type": "opportunity_search",
        "query": query,
    }


def detect_action(message):
    """
    Return a local UniCamplink action or None.

    Priority:
    1. Explicit navigation
    2. Opportunity search
    3. Marketplace search
    4. None -> send to normal AI
    """

    normalized = _normalize(message)

    if not normalized:
        return None

    navigation = _detect_navigation(
        normalized
    )

    if navigation:
        return navigation

    opportunity = _detect_opportunity(
        normalized
    )

    if opportunity:
        return opportunity

    marketplace = _detect_marketplace(
        normalized
    )

    if marketplace:
        return marketplace

    return None
