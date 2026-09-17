"""Cards and loyalty programs travelers can pick from for perk research (PRD 11a).

Hand-maintained and intentionally small: the research agent looks up current
benefits live (they change too often to hardcode), this list just gives the
picker a starting set of recognizable names. A traveler can always add a name
that isn't listed here.
"""

CARD_CATALOG: list[str] = [
    # Credit cards
    "Chase Sapphire Reserve",
    "Chase Sapphire Preferred",
    "American Express Platinum",
    "American Express Gold",
    "Capital One Venture X",
    "Capital One Venture",
    "Citi Premier",
    "Citi Prestige",
    "The Business Platinum Card from American Express",
    # Hotel loyalty
    "Marriott Bonvoy",
    "Hilton Honors",
    "World of Hyatt",
    "IHG One Rewards",
    # Airline loyalty
    "United MileagePlus",
    "Delta SkyMiles",
    "American Airlines AAdvantage",
    "Southwest Rapid Rewards",
]
