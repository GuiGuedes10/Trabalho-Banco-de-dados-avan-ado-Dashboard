import math
import os
from datetime import datetime

import pandas as pd

DATA_DIR = "database/data"
DETAILS_CSV = f"{DATA_DIR}/steam_app_details.csv"

COLUMNS = [
    "steam_appid",
    "name",
    "type",
    "is_free",
    "about_the_game",
    "header_image",
    "dlc",
    "developers",
    "publishers",
    "genres",
    "categories",
    "price_overview.final",
    "price_overview.currency",
    "platforms.windows",
    "platforms.mac",
    "platforms.linux",
    "metacritic.score",
    "total_reviews",
    "dlc_reviews",
    "estimated_downloads_base",
    "estimated_downloads_base_optimistic",
    "estimated_downloads_base_pessimistic",
    "estimated_downloads_dlc",
    "estimated_players_dont_have_dlc",
    "estimated_income",
    "community_review_factor",
    "release_date.date",
]

_RELEASE_DATE_FORMATS = ("%d %b, %Y", "%d %B, %Y", "%b %d, %Y", "%B %d, %Y")
_DEFAULT_RELEASE_DATE = datetime(2020, 1, 1)

_MAJOR_SALES_PER_YEAR = 4
_SEASONAL_PROFILE = {
    "new": {"discount": 0.15, "sale_share": 0.22},
    "medium": {"discount": 0.62, "sale_share": 0.50},
    "mature": {"discount": 0.72, "sale_share": 0.60},
    "classic": {"discount": 0.90, "sale_share": 0.78},
}


def parse_release_date(game):
    release = game.get("release_date") or {}
    date_str = (release.get("date") or "").strip()
    if not date_str or date_str.lower() in ("coming soon", "tbd", "to be announced"):
        return _DEFAULT_RELEASE_DATE
    for fmt in _RELEASE_DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return _DEFAULT_RELEASE_DATE


def _review_tier(review_count):
    if review_count <= 1000:
        return "indie"
    if review_count <= 5000:
        return "AA"
    if review_count >= 1_000_000:
        return "public_success"
    return "AAA"


def _years_on_store(release_date):
    today = datetime.now()
    years = today.year - release_date.year
    if (today.month, today.day) < (release_date.month, release_date.day):
        years -= 1
    return max(0, years)


def _market_tier(release_date):
    years = _years_on_store(release_date)
    if years < 3:
        return "new"
    if years < 7:
        return "medium"
    if years < 10:
        return "mature"
    return "classic"


def _community_review_factor(review_count):
    if review_count <= 0:
        return 1.0
    if review_count < 300_000:
        return 1.0
    return max(0.55, 1.0 - math.log10(review_count / 300_000) * 0.35)


_MULTIPLIER_PROFILE = {
    ("new", "indie"): {"center": 15, "spread": 0.20},
    ("new", "AA"): {"center": 22, "spread": 0.24},
    ("new", "AAA"): {"center": 28, "spread": 0.30},
    ("new", "public_success"): {"center": 20, "spread_low": 0.40, "spread_high": 0.30},
    ("medium", "indie"): {"center": 30, "spread": 0.18},
    ("medium", "AA"): {"center": 38, "spread": 0.18},
    ("medium", "AAA"): {"center": 45, "spread": 0.18},
    ("medium", "public_success"): {"center": 24, "spread_low": 0.35, "spread_high": 0.28},
    ("mature", "indie"): {"center": 38, "spread": 0.15},
    ("mature", "AA"): {"center": 46, "spread": 0.15},
    ("mature", "AAA"): {"center": 52, "spread": 0.12},
    ("mature", "public_success"): {"center": 26, "spread_low": 0.32, "spread_high": 0.26},
    ("classic", "indie"): {"center": 45, "spread": 0.12},
    ("classic", "AA"): {"center": 55, "spread": 0.12},
    ("classic", "AAA"): {"center": 62, "spread": 0.10},
    ("classic", "public_success"): {"center": 42, "spread": 0.12},
}

_DEFAULT_MULTIPLIER_PROFILE = {"center": 28, "spread": 0.20}


def _multiplier_bounds(profile):
    center = profile["center"]
    if "spread_low" in profile:
        low = max(1, round(center * (1 - profile["spread_low"])))
        high = round(center * (1 + profile["spread_high"]))
    else:
        spread = profile["spread"]
        low = max(1, round(center * (1 - spread)))
        high = round(center * (1 + spread))
    if low >= high:
        high = low + 1
    return low, high


def multiplier_base(review_count, release_date):
    tier = _review_tier(review_count)
    market = _market_tier(release_date)
    profile = _MULTIPLIER_PROFILE.get((market, tier), _DEFAULT_MULTIPLIER_PROFILE)
    return _multiplier_bounds(profile)


def _tiered_downloads(review_count, mult):
    if review_count <= 0:
        return 0
    if review_count <= 1000:
        return review_count * mult
    if review_count <= 5000:
        return 1000 * mult + (review_count - 1000) * mult
    return review_count * mult


def _base_scenario_downloads(total_reviews, release_date, community_factor):
    low, high = multiplier_base(total_reviews, release_date)
    pessimistic = int(_tiered_downloads(total_reviews, low) * community_factor)
    optimistic = int(_tiered_downloads(total_reviews, high) * community_factor)
    if pessimistic > optimistic:
        pessimistic, optimistic = optimistic, pessimistic
    median = (pessimistic + optimistic) // 2
    return pessimistic, optimistic, median


def estimate_downloads(total_reviews, dlc_reviews, release_date):
    community_factor = _community_review_factor(total_reviews)
    download_base_pessimistic, download_base_optimistic, download_base = (
        _base_scenario_downloads(total_reviews, release_date, community_factor)
    )
    if dlc_reviews > 0:
        dlc_factor = _community_review_factor(dlc_reviews)
        dlc_low, dlc_high = multiplier_base(dlc_reviews, release_date)
        dlc_pessimistic = int(_tiered_downloads(dlc_reviews, int(dlc_low * 1.5)) * dlc_factor)
        dlc_optimistic = int(_tiered_downloads(dlc_reviews, int(dlc_high * 1.5)) * dlc_factor)
        if dlc_pessimistic > dlc_optimistic:
            dlc_pessimistic, dlc_optimistic = dlc_optimistic, dlc_pessimistic
        download_dlc = (dlc_pessimistic + dlc_optimistic) // 2
    else:
        download_dlc = 0
    return (
        download_base_optimistic,
        download_base_pessimistic,
        download_base,
        download_dlc,
        community_factor,
    )


def effective_price_brl(game):
    overview = game.get("price_overview") or {}
    initial_cents = overview.get("initial")
    final_cents = overview.get("final")
    if initial_cents is None and final_cents is None:
        return 0.0

    initial = float(initial_cents or final_cents) / 100.0
    current = float(final_cents or initial_cents) / 100.0

    release_date = parse_release_date(game)
    market = _market_tier(release_date)
    years = _years_on_store(release_date)
    profile = _SEASONAL_PROFILE[market]

    sale_cycles = years * _MAJOR_SALES_PER_YEAR
    sale_share = min(0.88, profile["sale_share"] + sale_cycles * 0.008)
    sale_price = initial * (1.0 - profile["discount"])
    effective = (1.0 - sale_share) * initial + sale_share * sale_price

    discount_pct = overview.get("discount_percent") or 0
    if discount_pct > 0 and initial > 0:
        recent_weight = min(0.25, 0.08 + sale_share * 0.15)
        effective = (1.0 - recent_weight) * effective + recent_weight * current

    return round(effective, 2)


def enrich_game_with_insights(game, total_reviews, dlc_reviews):
    game = dict(game)
    game["total_reviews"] = total_reviews
    game["dlc_reviews"] = dlc_reviews

    release_date = parse_release_date(game)
    download_base_optimistic, download_base_pessimistic, download_base, download_dlc, community_factor = estimate_downloads(
        total_reviews, dlc_reviews, release_date
    )
    game["estimated_downloads_base"] = download_base
    game["estimated_downloads_base_optimistic"] = download_base_optimistic
    game["estimated_downloads_base_pessimistic"] = download_base_pessimistic
    game["estimated_downloads_dlc"] = download_dlc
    game["estimated_players_dont_have_dlc"] = download_base - download_dlc
    game["community_review_factor"] = round(community_factor, 4)
    game["estimated_income"] = download_base * effective_price_brl(game)
    return game


def purge_f2p_from_df(df):
    if df is None or df.empty or "is_free" not in df.columns:
        return df, 0
    is_f2p = df["is_free"].apply(
        lambda v: v is True or str(v).strip().lower() in ("true", "1", "yes")
    )
    removed = int(is_f2p.sum())
    if removed:
        df = df[~is_f2p].copy()
    return df, removed


def load_existing_details(out_path=DETAILS_CSV):
    if not os.path.exists(out_path):
        return None, set()
    try:
        existing_df = pd.read_csv(out_path)
        if existing_df.empty:
            return None, set()
        existing_df, removed = purge_f2p_from_df(existing_df)
        if removed:
            existing_df.to_csv(out_path, index=False)
            print(f"Removidos {removed} jogos F2P do CSV existente.")
        done = set(existing_df["steam_appid"].astype(int).tolist())
        return existing_df, done
    except (ValueError, KeyError, pd.errors.EmptyDataError):
        return None, set()


def append_game_to_csv(game, out_path, existing_df):
    new_row = pd.json_normalize([game])
    if existing_df is not None and not existing_df.empty:
        detail_df = pd.concat([existing_df, new_row], ignore_index=True)
    else:
        detail_df = new_row

    detail_df = detail_df.drop_duplicates(subset=["steam_appid"], keep="last")
    cols = [c for c in COLUMNS if c in detail_df.columns]
    detail_df = detail_df.reindex(columns=cols)
    detail_df.to_csv(out_path, index=False)
    return detail_df


def prepare_dashboard_dataframe(df):
    if df.empty:
        return df
    df = df.copy()
    if "is_free" in df.columns:
        df, _ = purge_f2p_from_df(df)
    dlc = df["estimated_downloads_dlc"].fillna(0)
    base = df["estimated_downloads_base"].fillna(0)
    df["estimated_downloads"] = base + dlc
    if "estimated_downloads_base_pessimistic" in df.columns:
        df["estimated_downloads_pessimistic"] = (
            df["estimated_downloads_base_pessimistic"].fillna(0) + dlc
        )
    if "estimated_downloads_base_optimistic" in df.columns:
        df["estimated_downloads_optimistic"] = (
            df["estimated_downloads_base_optimistic"].fillna(0) + dlc
        )
    df["estimated_income"] = df["estimated_income"].fillna(0)
    df["price_brl"] = df["price_overview.final"].fillna(0) / 100
    df["name_short"] = df["name"].astype(str).str.slice(0, 28)
    df["has_dlc"] = df["estimated_downloads_dlc"].fillna(0) > 0
    return df
