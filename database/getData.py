import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv

from database.dataTratament import (
    DETAILS_CSV,
    append_game_to_csv,
    enrich_game_with_insights,
    is_free_to_play_game,
    load_existing_details,
)

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "20000"))

REQUEST_DELAY = float(os.getenv("STEAM_REQUEST_DELAY", "0.5"))
MAX_RETRIES = int(os.getenv("STEAM_MAX_RETRIES", "8"))
DEFAULT_RATE_LIMIT_WAIT = int(os.getenv("STEAM_RATE_LIMIT_WAIT", "60"))
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "100"))

SESSION_HEADERS = {
    "User-Agent": "SteamDashboard/1.0 (educational project)",
    "Accept": "application/json",
}

DATA_DIR = "database/data"
APP_LIST_CSV = f"{DATA_DIR}/steam_app_list.csv"

URL_GET_APP_LIST = (
    f"https://api.steampowered.com/IStoreService/GetAppList/v1/"
    f"?key={STEAM_API_KEY}&include_games=true&max_results={MAX_RESULTS}"
)


def _retry_after_seconds(response):
    raw = response.headers.get("Retry-After", "")
    if str(raw).isdigit():
        return max(int(raw), 1)
    return DEFAULT_RATE_LIMIT_WAIT


def _is_brl_catalog(game_data):
    currency = (game_data.get("price_overview") or {}).get("currency")
    return currency == "BRL"


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
    url = (
        f"https://store.steampowered.com/api/appdetails"
        f"?appids={key}&l=english&cc=br"
    )
    url_reviews = f"https://store.steampowered.com/appreviews/{key}?json=1&language=all"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=30)
        except requests.RequestException as e:
            wait = min(5 * attempt, 30)
            print(f"app_id={key}: falha de rede ({e}). Nova tentativa em {wait}s...")
            time.sleep(wait)
            continue

        if response.status_code == 429:
            wait = _retry_after_seconds(response)
            print(
                f"app_id={key}: 429 Too Many Requests. "
                f"Aguardando {wait}s ({attempt}/{MAX_RETRIES})..."
            )
            time.sleep(wait)
            continue

        if response.status_code >= 500:
            wait = min(10 * attempt, 120)
            print(
                f"app_id={key}: HTTP {response.status_code}. "
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
        if is_free_to_play_game(game_data):
            print(
                f"app_id={key} ({game_data.get('name', '?')}): F2P — ignorado "
                f"(is_free ou genero Free to Play)."
            )
            return None

        if not _is_brl_catalog(game_data):
            name = game_data.get("name", "?")
            currency = (game_data.get("price_overview") or {}).get("currency") or "(sem preço)"
            print(
                f"app_id={key} ({name}): moeda {currency} — ignorado "
                f"(somente catálogo BRL; use cc=br na loja)."
            )
            return None

        try:
            response_reviews = session.get(url_reviews, timeout=30)
        except requests.RequestException as e:
            print(f"app_id={key}: appreviews falhou ({e}), total_reviews=0.")
            response_reviews = None

        dlc_ids = game_data.get("dlc") or []
        dlc_reviews = _sum_dlc_reviews(session, dlc_ids)

        total_reviews = 0
        if response_reviews is not None and response_reviews.status_code == 200:
            try:
                payload_reviews = response_reviews.json()
                if payload_reviews.get("success"):
                    total_reviews = (
                        payload_reviews.get("query_summary", {}).get("total_reviews") or 0
                    )
            except ValueError:
                print(f"app_id={key}: appreviews não é JSON válido, total_reviews=0.")
        elif response_reviews is not None:
            print(
                f"app_id={key}: appreviews HTTP {response_reviews.status_code}, "
                f"total_reviews=0."
            )

        return game_data, total_reviews, dlc_reviews

    print(f"app_id={key}: desistindo após {MAX_RETRIES} tentativas.")
    return None


def getIDs():
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        response = requests.get(URL_GET_APP_LIST, timeout=60)
        data = response.json()
        df = pd.DataFrame(data["response"]["apps"])
        df.to_csv(APP_LIST_CSV, index=False)
        print("Data saved to steam_app_list.csv")
        return df
    except Exception as e:
        print(f"Error: {e}")
        return None


def getAppDetails(limit=None, skip_existing=True):
    out_path = DETAILS_CSV

    if not os.path.exists(APP_LIST_CSV):
        print(f"Arquivo não encontrado: {APP_LIST_CSV}. Baixando lista de apps...")
        os.makedirs(DATA_DIR, exist_ok=True)
        getIDs()

    if not os.path.exists(APP_LIST_CSV):
        print(f"Não foi possível obter {APP_LIST_CSV}.")
        return

    df_list = pd.read_csv(APP_LIST_CSV)
    ids = df_list["appid"].tolist()
    if limit is not None:
        ids = ids[: int(limit)]

    os.makedirs(DATA_DIR, exist_ok=True)

    existing_df, done_ids = (None, set())
    if skip_existing:
        existing_df, done_ids = load_existing_details(out_path)
        if done_ids:
            print(f"Retomando: {len(done_ids)} jogos já salvos em {out_path}")

    pending = [i for i in ids if int(i) not in done_ids] if skip_existing else ids
    if not pending:
        print("Nada a buscar: todos os appids já estão no CSV.")
        return

    print(
        f"Buscando {len(pending)} appids pagos (BRL) "
        f"(F2P ignorados; intervalo {REQUEST_DELAY}s)..."
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

        game_data, total_reviews, dlc_reviews = result
        game = enrich_game_with_insights(game_data, total_reviews, dlc_reviews)
        existing_df = append_game_to_csv(game, out_path, existing_df)
        fetched += 1

        if idx % 10 == 0 or idx == len(pending):
            print(f"Progresso: {idx}/{len(pending)} — total no CSV: {len(existing_df)}")

        time.sleep(REQUEST_DELAY)

    if fetched == 0 and (existing_df is None or existing_df.empty):
        print("Nenhum detalhe obtido; CSV não gerado.")
        return

    print(f"Salvo {out_path} ({len(existing_df)} apps no total)")


if __name__ == "__main__":
    getAppDetails(RATE_LIMIT)
