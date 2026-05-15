import os
from dotenv import load_dotenv
import requests
import time
import pandas as pd

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY")
MAX_RESULTS = 20000

url_getID = f"https://api.steampowered.com/IStoreService/GetAppList/v1/?key={STEAM_API_KEY}&include_games=true&max_results={MAX_RESULTS}"

def getIDs():
    try:
        response = requests.get(url_getID)
        data = response.json()
        df = pd.DataFrame(data["response"]["apps"])
        df.to_csv("database/data/steam_app_list.csv", index=False)
        print("Data saved to steam_app_list.csv")
        return df
    except Exception as e:
        print(f"Error: {e}")
        return None

def getAppDetails(limit=None):
    csv_path = "database/data/steam_app_list.csv"
    rows = []
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}.")
        return

    df_list = pd.read_csv(csv_path)
    ids = df_list["appid"].tolist()
    if limit is not None:
        ids = ids[: int(limit)]

    os.makedirs("database/data", exist_ok=True)

    for app_id in ids:
        key = str(int(app_id))
        url = f"https://store.steampowered.com/api/appdetails?appids={key}&l=english"

        try:
            response = requests.get(url)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as e:
            print(f"app_id={key}: erro na requisição: {e}")
            time.sleep(1)
            continue

        entry = payload.get(key)
        if not entry or not entry.get("success"):
            print(f"app_id={key}: sem dados na loja")
            time.sleep(1)
            continue
    
        game = entry["data"]
        total = game.get("recommendations", {}).get("total", 0)
        game["estimated_sales"] = total * 40

        rows.append(entry["data"])
        time.sleep(1)

    if not rows:
        print("Nenhum detalhe obtido; CSV não gerado.")
        return

    detail_df = pd.json_normalize(rows)
    out_path = "database/data/steam_app_details.csv"
    detail_df.to_csv(out_path, index=False)
    print(f"Salvo {out_path} ({len(rows)} apps)")
        

if __name__ == "__main__":
    getAppDetails(5)