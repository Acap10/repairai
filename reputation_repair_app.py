from flask import Flask, request, jsonify
from anthropic import Anthropic

app = Flask(__name__)
client = Anthropic()  # Uses ANTHROPIC_API_KEY env variable

# ---------------------------------------------------------------------------
# PRICING TIERS
# ---------------------------------------------------------------------------
# Starter  £49/mo  — Google only, response drafts (owner approves), 30/mo cap
# Growth   £99/mo  — Google + Trustpilot, auto-post, review request emails
# Pro     £149/mo  — All platforms, dispute letters, monthly report, unlimited
# ---------------------------------------------------------------------------

TIERS = {
    "starter": {
        "price": 49,
        "label": "Starter",
        "platforms": ["google"],
        "auto_post": False,
        "review_requests": False,
        "dispute_letters": False,
        "monthly_report": False,
        "response_limit": 30,
    },
    "growth": {
        "price": 99,
        "label": "Growth",
        "platforms": ["google", "trustpilot"],
        "auto_post": True,
        "review_requests": True,
        "dispute_letters": False,
        "monthly_report": False,
        "response_limit": 100,
    },
    "pro": {
        "price": 149,
        "label": "Pro",
        "platforms": ["google", "trustpilot", "facebook"],
        "auto_post": True,
        "review_requests": True,
        "dispute_letters": True,
        "monthly_report": True,
        "response_limit": 999,  # effectively unlimited
    },
}

# ---------------------------------------------------------------------------
# CLIENT PROFILES
# Add a new entry for every business you onboard.
# ---------------------------------------------------------------------------

CLIENT_PROFILES = {
    "smile_dental": {
        "name": "Smile Dental London",
        "tone": "warm, professional, and reassuring",
        "services": "general dentistry, cosmetic dentistry, teeth whitening, Invisalign",
        "owner_name": "Dr. Patel",
        "never_mention": ["prices without consulting first", "competitors", "pain"],
        "tier": "growth",
        "response_count_this_month": 0,
    },
    "marios_kitchen": {
        "name": "Mario's Italian Kitchen",
        "tone": "friendly, passionate about food, family-oriented",
        "services": "authentic Italian dining, private events, takeaway",
        "owner_name": "Mario",
        "never_mention": ["wait times", "parking"],
        "tier": "starter",
        "response_count_this_month": 0,
    },
    "swift_plumbing": {
        "name": "Swift Plumbing & Heating",
        "tone": "reliable, straight-talking, and trustworthy",
        "services": "emergency plumbing, boiler installation, bathroom fitting, gas safety checks",
        "owner_name": "Dave",
        "never_mention": ["delays", "pricing complaints"],
        "tier": "pro",
        "response_count_this_month": 0,
    },
}

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def get_tier(client_id: str) -> dict:
    profile = CLIENT_PROFILES.get(client_id, {})
    tier_key = profile.get("tier", "starter")
    return TIERS[tier_key]


def tier_allows(client_id: str, feature: str) -> tuple:
    tier = get_tier(client_id)
    profile = CLIENT_PROFILES.get(client_id, {})
    tier_key = profile.get("tier", "starter")

    if not tier.get(feature, False):
        upgrades = {
            "starter": "Growth (£99/mo)",
            "growth": "Pro (£149/mo)",
            "pro": None,
        }
        next_tier = upgrades.get(tier_key)
        msg = (
            f"This feature is not included in your {tier['label']} plan. "
            f"Upgrade to {next_tier} to unlock it."
            if next_tier else "Feature unavailable on your current plan."
        )
        return False, msg
    return True, ""


def check_response_limit(client_id: str) -> tuple:
    profile = CLIENT_PROFILES.get(client_id, {})
    tier = get_tier(client_id)
    used = profile.get("response_count_this_month", 0)
    limit = tier["response_limit"]
    if used >= limit:
        return False, (
            f"Monthly response limit of {limit} reached on your {tier['label']} plan. "
            f"Upgrade for more responses."
        )
    return True, ""


def increment_response_count(client_id: str):
    if client_id in CLIENT_PROFILES:
        CLIENT_PROFILES[client_id]["response_count_this_month"] += 1


def build_system_prompt(client_id: str) -> str:
    profile = CLIENT_PROFILES.get(client_id)
    if not profile:
        return "You are a helpful business assistant."

    tier = get_tier(client_id)
    never = ", ".join(profile["never_mention"])
    auto_post_note = (
        "Responses will be posted automatically — make sure they are polished and publish-ready."
        if tier["auto_post"]
        else "Responses will be reviewed by the owner before posting — you may add a short note in [brackets] for them if helpful."
    )

    return f"""
You are an expert reputation manager responding to online reviews on behalf of {profile["name"]}.

Your goals:
1. Match this tone in every response: {profile["tone"]}.
2. POSITIVE reviews (4-5 stars): thank the reviewer warmly, reference a specific detail they mentioned, and subtly highlight a relevant service from: {profile["services"]}.
3. NEGATIVE reviews (1-2 stars): apologise sincerely, acknowledge their experience without being defensive, and invite them to contact {profile["owner_name"]} directly to resolve things offline.
4. NEUTRAL reviews (3 stars): acknowledge what went well, gently address concerns, invite them back.
5. Keep responses 3-5 sentences. Sound human — never corporate or robotic.
6. Never mention: {never}.
7. Always sign off with: — {profile["owner_name"]} & The Team at {profile["name"]}

{auto_post_note}

Respond ONLY with the review reply. No preamble, no explanation, no quotation marks.
""".strip()


def classify_review(star_rating: int) -> str:
    if star_rating >= 4:
        return "positive"
    elif star_rating == 3:
        return "neutral"
    else:
        return "negative"


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route("/respond", methods=["POST"])
def respond_to_review():
    """
    Generate an AI response to a review.

    Body: {
        "client_id": "smile_dental",
        "review_text": "Brilliant service, very gentle!",
        "star_rating": 5,
        "reviewer_name": "Sarah J.",   (optional)
        "platform": "google"           (optional, default: google)
    }
    """
    data = request.json or {}
    client_id = data.get("client_id")
    review_text = data.get("review_text")
    star_rating = int(data.get("star_rating", 3))
    reviewer_name = data.get("reviewer_name", "a customer")
    platform = data.get("platform", "google").lower()

    if not client_id or not review_text:
        return jsonify({"error": "client_id and review_text are required"}), 400

    if client_id not in CLIENT_PROFILES:
        return jsonify({"error": f"Unknown client_id '{client_id}'"}), 404

    # Check platform is included in tier
    tier = get_tier(client_id)
    if platform not in tier["platforms"]:
        return jsonify({
            "error": f"{platform.capitalize()} reviews are not included in your {tier['label']} plan.",
            "included_platforms": tier["platforms"],
            "tip": "Upgrade your plan to add more platforms.",
        }), 403

    # Check monthly cap
    within_limit, limit_msg = check_response_limit(client_id)
    if not within_limit:
        return jsonify({"error": limit_msg}), 403

    review_type = classify_review(star_rating)
    system_prompt = build_system_prompt(client_id)
    user_message = (
        f"Review from {reviewer_name} ({star_rating} stars — {review_type}) "
        f"on {platform.capitalize()}:\n\n{review_text}"
    )

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    increment_response_count(client_id)
    profile = CLIENT_PROFILES[client_id]

    return jsonify({
        "client_id": client_id,
        "plan": tier["label"],
        "price": f"£{tier['price']}/mo",
        "auto_post": tier["auto_post"],
        "platform": platform,
        "star_rating": star_rating,
        "review_type": review_type,
        "reviewer_name": reviewer_name,
        "original_review": review_text,
        "draft_response": message.content[0].text,
        "responses_used_this_month": profile["response_count_this_month"],
        "response_limit": tier["response_limit"] if tier["response_limit"] < 999 else "Unlimited",
    })


@app.route("/review-request-email", methods=["POST"])
def generate_review_request():
    """
    Growth + Pro only. Generate a personalised review request email.

    Body: {
        "client_id": "smile_dental",
        "customer_name": "John",
        "service_received": "teeth whitening",
        "google_review_link": "https://g.page/r/..."
    }
    """
    data = request.json or {}
    client_id = data.get("client_id")

    if not client_id:
        return jsonify({"error": "client_id is required"}), 400
    if client_id not in CLIENT_PROFILES:
        return jsonify({"error": f"Unknown client_id '{client_id}'"}), 404

    allowed, msg = tier_allows(client_id, "review_requests")
    if not allowed:
        return jsonify({"error": msg}), 403

    customer_name = data.get("customer_name", "there")
    service = data.get("service_received", "our service")
    review_link = data.get("google_review_link", "[INSERT GOOGLE REVIEW LINK]")
    profile = CLIENT_PROFILES[client_id]

    system_prompt = f"""
You write short, warm, non-pushy follow-up emails asking happy customers to leave a Google review.
Tone: {profile["tone"]}.
Business: {profile["name"]}.
Owner first name: {profile["owner_name"]}.
Rules:
- Under 100 words.
- Friendly and personal — not a template-sounding email.
- Never offer incentives or discounts in exchange for a review.
- Include the review link naturally near the end.
- No subject line — just the email body.
""".strip()

    user_message = (
        f"Write a review request email to {customer_name} who recently used our {service}. "
        f"Google review link: {review_link}"
    )

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    return jsonify({
        "client_id": client_id,
        "plan": get_tier(client_id)["label"],
        "customer_name": customer_name,
        "service": service,
        "email_draft": message.content[0].text,
    })


@app.route("/dispute-letter", methods=["POST"])
def generate_dispute_letter():
    """
    Pro only. Generate a formal dispute letter for a fake or unfair review.

    Body: {
        "client_id": "swift_plumbing",
        "review_text": "They broke my pipes!",
        "reason_for_dispute": "We have no record of this person as a customer"
    }
    """
    data = request.json or {}
    client_id = data.get("client_id")

    if not client_id:
        return jsonify({"error": "client_id is required"}), 400
    if client_id not in CLIENT_PROFILES:
        return jsonify({"error": f"Unknown client_id '{client_id}'"}), 404

    allowed, msg = tier_allows(client_id, "dispute_letters")
    if not allowed:
        return jsonify({"error": msg}), 403

    review_text = data.get("review_text", "")
    reason = data.get("reason_for_dispute", "This review appears to be fraudulent")
    profile = CLIENT_PROFILES[client_id]

    system_prompt = """
You write formal but concise dispute letters to Google requesting removal of fake or policy-violating reviews.
Structure: (1) identify the business and the review, (2) explain why it violates Google review policies, (3) request removal.
Under 150 words. Professional tone. No emotional language.
""".strip()

    user_message = (
        f"Business: {profile['name']}\n"
        f"Review to dispute: \"{review_text}\"\n"
        f"Reason: {reason}\n\n"
        f"Write the dispute letter."
    )

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    return jsonify({
        "client_id": client_id,
        "plan": get_tier(client_id)["label"],
        "disputed_review": review_text,
        "dispute_letter": message.content[0].text,
    })


@app.route("/monthly-report", methods=["POST"])
def generate_monthly_report():
    """
    Pro only. Generate a plain-English monthly summary for the client.

    Body: {
        "client_id": "swift_plumbing",
        "current_rating": 4.4,
        "previous_rating": 4.1,
        "reviews_this_month": 12,
        "responses_sent": 12,
        "new_reviews_breakdown": {"5_star": 8, "4_star": 2, "3_star": 1, "2_star": 1, "1_star": 0}
    }
    """
    data = request.json or {}
    client_id = data.get("client_id")

    if not client_id:
        return jsonify({"error": "client_id is required"}), 400
    if client_id not in CLIENT_PROFILES:
        return jsonify({"error": f"Unknown client_id '{client_id}'"}), 404

    allowed, msg = tier_allows(client_id, "monthly_report")
    if not allowed:
        return jsonify({"error": msg}), 403

    profile = CLIENT_PROFILES[client_id]
    current_rating = data.get("current_rating", 4.2)
    previous_rating = data.get("previous_rating", 4.0)
    reviews_this_month = data.get("reviews_this_month", 0)
    responses_sent = data.get("responses_sent", 0)
    breakdown = data.get("new_reviews_breakdown", {})

    system_prompt = f"""
You write friendly, encouraging monthly reputation summary reports for small business owners.
Tone: {profile["tone"]}.
Keep it under 120 words. One short paragraph — no bullet points, no headers.
Highlight wins, flag anything to watch, end on a positive note.
Write as if you're talking directly to {profile["owner_name"]}.
""".strip()

    user_message = (
        f"Business: {profile['name']}\n"
        f"This month: {reviews_this_month} new reviews received. "
        f"Rating moved from {previous_rating} to {current_rating} stars. "
        f"Responses sent: {responses_sent}.\n"
        f"Star breakdown: {breakdown}\n\n"
        f"Write their monthly summary."
    )

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    return jsonify({
        "client_id": client_id,
        "plan": get_tier(client_id)["label"],
        "period_summary": {
            "previous_rating": previous_rating,
            "current_rating": current_rating,
            "change": round(current_rating - previous_rating, 2),
            "reviews_this_month": reviews_this_month,
            "responses_sent": responses_sent,
        },
        "report_narrative": message.content[0].text,
    })


@app.route("/upgrade", methods=["POST"])
def upgrade_client():
    """
    Move a client to a higher tier.

    Body: { "client_id": "marios_kitchen", "new_tier": "growth" }
    """
    data = request.json or {}
    client_id = data.get("client_id")
    new_tier = data.get("new_tier", "").lower()

    if not client_id:
        return jsonify({"error": "client_id is required"}), 400
    if client_id not in CLIENT_PROFILES:
        return jsonify({"error": f"Unknown client_id '{client_id}'"}), 404
    if new_tier not in TIERS:
        return jsonify({"error": f"Invalid tier. Options: {list(TIERS.keys())}"}), 400

    old_tier_key = CLIENT_PROFILES[client_id]["tier"]
    CLIENT_PROFILES[client_id]["tier"] = new_tier

    newly_unlocked = [
        f for f in ["auto_post", "review_requests", "dispute_letters", "monthly_report"]
        if TIERS[new_tier].get(f) and not TIERS[old_tier_key].get(f)
    ]

    return jsonify({
        "client_id": client_id,
        "previous_plan": TIERS[old_tier_key]["label"],
        "new_plan": TIERS[new_tier]["label"],
        "new_price": f"£{TIERS[new_tier]['price']}/mo",
        "newly_unlocked_features": newly_unlocked,
        "message": f"Upgraded to {TIERS[new_tier]['label']}. New features are live immediately.",
    })


@app.route("/clients", methods=["GET"])
def list_clients():
    """List all active clients with their tier and usage stats."""
    return jsonify({
        "clients": [
            {
                "client_id": k,
                "name": v["name"],
                "plan": TIERS[v["tier"]]["label"],
                "price": f"£{TIERS[v['tier']]['price']}/mo",
                "platforms": TIERS[v["tier"]]["platforms"],
                "responses_used_this_month": v["response_count_this_month"],
                "response_limit": (
                    TIERS[v["tier"]]["response_limit"]
                    if TIERS[v["tier"]]["response_limit"] < 999
                    else "Unlimited"
                ),
            }
            for k, v in CLIENT_PROFILES.items()
        ]
    })


@app.route("/pricing", methods=["GET"])
def show_pricing():
    """Return the full pricing table — useful for your sales page."""
    return jsonify({
        "pricing": [
            {
                "tier": k,
                "label": v["label"],
                "price": f"£{v['price']}/mo",
                "platforms": v["platforms"],
                "auto_post": v["auto_post"],
                "review_request_emails": v["review_requests"],
                "dispute_letters": v["dispute_letters"],
                "monthly_report": v["monthly_report"],
                "response_limit": v["response_limit"] if v["response_limit"] < 999 else "Unlimited",
            }
            for k, v in TIERS.items()
        ]
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AI Reputation Repair",
        "tiers": [f"{v['label']} £{v['price']}/mo" for v in TIERS.values()],
    })


if __name__ == "__main__":
    import os
app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
