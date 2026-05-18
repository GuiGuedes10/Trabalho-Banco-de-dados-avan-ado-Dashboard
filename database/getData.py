import os
import time
from dotenv import load_dotenv
import requests
import pandas as pd
from datetime import datetime

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY")
MAX_RESULTS = 20000

# Intervalo mínimo entre requisições bem-sucedidas (segundos).
REQUEST_DELAY = float(os.getenv("STEAM_REQUEST_DELAY", "2.5"))
# Tentativas por appid quando receber 429 ou erro transitório.
MAX_RETRIES = int(os.getenv("STEAM_MAX_RETRIES", "8"))
# Espera padrão se o servidor não enviar Retry-After (segundos).
DEFAULT_RATE_LIMIT_WAIT = int(os.getenv("STEAM_RATE_LIMIT_WAIT", "60"))

SESSION_HEADERS = {
    "User-Agent": "SteamDashboard/1.0 (educational project)",
    "Accept": "application/json",
}

url_getID = f"https://api.steampowered.com/IStoreService/GetAppList/v1/?key={STEAM_API_KEY}&include_games=true&max_results={MAX_RESULTS}"

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
    "estimated_downloads_dlc",
    "estimated_players_dont_have_dlc",
    "estimated_income",
    "release_date.date",
]

def _retry_after_seconds(response):
    raw = response.headers.get("Retry-After", "")
    if str(raw).isdigit():
        return max(int(raw), 1)
    return DEFAULT_RATE_LIMIT_WAIT

_RELEASE_DATE_FORMATS = ("%d %b, %Y", "%d %B, %Y", "%b %d, %Y", "%B %d, %Y")
_DEFAULT_RELEASE_DATE = datetime(2020, 1, 1)


def _parse_release_date(game):
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


def _price_final(game):
    overview = game.get("price_overview") or {}
    final_cents = overview.get("final")
    if final_cents is None:
        return 0.0
    return float(final_cents) / 100.0


def multiplier_base(review_count, release_date):
    if release_date.year < 2018:
        if review_count <= 1000:
            return 70
        if review_count <= 5000:
            return 50
        return 40
    if review_count <= 1000:
        return 40
    if review_count <= 5000:
        return 35
    return 30

def multiplier_dlc(dlc_reviews, release_date):
    if release_date.year < 2018:
        if dlc_reviews <= 1000:
            return 120
        if dlc_reviews <= 5000:
            return 100
        return 80
    if dlc_reviews <= 1000:
        return 80
    if dlc_reviews <= 5000:
        return 60
    return 40

def _tiered_downloads(review_count, release_date, mult_fn):
    if review_count <= 0:
        return 0
    if review_count <= 1000:
        return review_count * mult_fn(review_count, release_date)
    if review_count <= 5000:
        return (
            1000 * mult_fn(1000, release_date)
            + (review_count - 1000) * mult_fn(review_count, release_date)
        )
    return (
        1000 * mult_fn(1000, release_date)
        + 4000 * mult_fn(5000, release_date)
        + (review_count - 5000) * mult_fn(review_count, release_date)
    )


def estimate_downloads(total_reviews, dlc_reviews, release_date):
    download_base = _tiered_downloads(total_reviews, release_date, multiplier_base)
    download_dlc = _tiered_downloads(dlc_reviews, release_date, multiplier_dlc)
    return download_base, download_dlc


def get_dlc_reviews(session, dlc_app_id):
    key = str(int(dlc_app_id))
    url = f"https://store.steampowered.com/appreviews/{key}?json=1&language=all"

    try:
        response = session.get(url, timeout=30)
        if response.status_code != 200:
            return 0
        payload = response.json()
        if payload.get("success"):
            return payload.get("query_summary", {}).get("total_reviews") or 0
        return 0
    except (requests.RequestException, ValueError):
        return 0


def _sum_dlc_reviews(session, dlc_ids):
    if not dlc_ids:
        return 0
    total = 0
    for dlc_id in dlc_ids:
        total += get_dlc_reviews(session, dlc_id)
        time.sleep(0.3)
    return total


def fetch_appdetails(session, app_id):
    key = str(int(app_id))
    url = f"https://store.steampowered.com/api/appdetails?appids={key}&l=english"
    url_reviews = f"https://store.steampowered.com/appreviews/{key}?json=1&language=all"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=30)
            response_reviews = session.get(url_reviews, timeout=30)
        except requests.RequestException as e:
            wait = min(5 * attempt, 30)
            print(f"app_id={key}: falha de rede ({e}). Nova tentativa em {wait}s...")
            time.sleep(wait)
            continue

        if response.status_code == 429 or response_reviews.status_code == 429:
            rate_limited = (
                response_reviews
                if response_reviews.status_code == 429
                else response
            )
            wait = _retry_after_seconds(rate_limited)
            print(
                f"app_id={key}: 429 Too Many Requests. "
                f"Aguardando {wait}s ({attempt}/{MAX_RETRIES})..."
            )
            time.sleep(wait)
            continue

        if response.status_code >= 500 or response_reviews.status_code >= 500:
            wait = min(10 * attempt, 120)
            print(
                f"app_id={key}: HTTP {response.status_code} ou {response_reviews.status_code}. "
                f"Nova tentativa em {wait}s..."
            )
            time.sleep(wait)
            continue

        if response.status_code != 200:
            print(f"app_id={key}: HTTP {response.status_code}, ignorando.")
            return None

        try:
            payload = response.json()
        except ValueError:
            print(f"app_id={key}: appdetails não é JSON válido.")
            return None

        entry = payload.get(key)
        if not entry or not entry.get("success"):
            return None

        game_data = entry["data"]
        dlc_ids = game_data.get("dlc") or []
        dlc_reviews = _sum_dlc_reviews(session, dlc_ids)

        total_reviews = 0
        if response_reviews.status_code == 200:
            try:
                payload_reviews = response_reviews.json()
                if payload_reviews.get("success"):
                    total_reviews = (
                        payload_reviews.get("query_summary", {}).get("total_reviews") or 0
                    )
            except ValueError:
                print(f"app_id={key}: appreviews não é JSON válido, total_reviews=0.")
        else:
            print(
                f"app_id={key}: appreviews HTTP {response_reviews.status_code}, "
                f"total_reviews=0."
            )

        return game_data, total_reviews, dlc_reviews

    print(f"app_id={key}: desistindo após {MAX_RETRIES} tentativas.")
    return None


def _load_existing_details(out_path):
    if not os.path.exists(out_path):
        return None, set()
    try:
        existing_df = pd.read_csv(out_path)
        if existing_df.empty:
            return None, set()
        done = set(existing_df["steam_appid"].astype(int).tolist())
        return existing_df, done
    except (ValueError, KeyError, pd.errors.EmptyDataError):
        return None, set()


def _append_game_to_csv(game, out_path, existing_df):
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


def getIDs():
    try:
        response = requests.get(url_getID, timeout=60)
        data = response.json()
        df = pd.DataFrame(data["response"]["apps"])
        df.to_csv("database/data/steam_app_list.csv", index=False)
        print("Data saved to steam_app_list.csv")
        return df
    except Exception as e:
        print(f"Error: {e}")
        return None

def getAppDetails(limit=None, skip_existing=True):
    csv_path = "database/data/steam_app_list.csv"
    out_path = "database/data/steam_app_details.csv"

    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}.")
        return

    df_list = pd.read_csv(csv_path)
    ids = df_list["appid"].tolist()
    if limit is not None:
        ids = ids[: int(limit)]

    os.makedirs("database/data", exist_ok=True)

    existing_df, done_ids = (None, set())
    if skip_existing:
        existing_df, done_ids = _load_existing_details(out_path)
        if done_ids:
            print(f"Retomando: {len(done_ids)} jogos já salvos em {out_path}")

    pending = [i for i in ids if int(i) not in done_ids] if skip_existing else ids
    if not pending:
        print("Nada a buscar: todos os appids já estão no CSV.")
        return

    print(
        f"Buscando {len(pending)} appids "
        f"(intervalo {REQUEST_DELAY}s, até {MAX_RETRIES} tentativas em 429)..."
    )

    session = requests.Session()
    session.headers.update(SESSION_HEADERS)

    fetched = 0
    for idx, app_id in enumerate(pending, start=1):
        key = str(int(app_id))
        result = fetch_appdetails(session, app_id)
        if result is None:
            print(f"app_id={key}: sem dados na loja ou falha definitiva")
            time.sleep(REQUEST_DELAY)
            continue

        game, total_reviews, dlc_reviews = result
        game["total_reviews"] = total_reviews
        game["dlc_reviews"] = dlc_reviews

        release_date = _parse_release_date(game)
        download_base, download_dlc = estimate_downloads(
            total_reviews, dlc_reviews, release_date
        )
        game["estimated_downloads_base"] = download_base
        game["estimated_downloads_dlc"] = download_dlc
        game["estimated_players_dont_have_dlc"] = download_base - download_dlc

        game["estimated_income"] = download_base * _price_final(game)

        existing_df = _append_game_to_csv(game, out_path, existing_df)
        fetched += 1

        if idx % 10 == 0 or idx == len(pending):
            print(f"Progresso: {idx}/{len(pending)} — total no CSV: {len(existing_df)}")

        time.sleep(REQUEST_DELAY)

    if fetched == 0 and (existing_df is None or existing_df.empty):
        print("Nenhum detalhe obtido; CSV não gerado.")
        return

    print(f"Salvo {out_path} ({len(existing_df)} apps no total)")
        

if __name__ == "__main__":
    getAppDetails(500)