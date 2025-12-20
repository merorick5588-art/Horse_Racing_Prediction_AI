import sys
import os
import json
import pandas as pd
import requests

# ==============================
# 設定
# ==============================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not DISCORD_WEBHOOK_URL:
    raise RuntimeError("DISCORD_WEBHOOK_URL が環境変数に設定されていません")

# ==============================
# ユーティリティ
# ==============================
def extract_race_number_from_filename(filename: str) -> str:
    """
    例: 202512200601_サラ系2歳未勝利.json
    → 下2桁 = 01 → 01R
    """
    base = os.path.basename(filename)
    race_id = base.split("_")[0]
    race_no = race_id[-2:]
    return f"{race_no}R"


def load_common_info(csv_path: str) -> dict:
    df = pd.read_csv(csv_path)
    return {
        "date_info": str(df["date_info"].iloc[0]),
        "race_title": str(df["race_title"].iloc[0]),
    }


def load_predictions(json_path: str) -> list:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ==============================
# 表フォーマット
# ==============================
def format_prediction_table(predictions: list) -> str:
    lines = []

    for i, p in enumerate(predictions, start=1):
        prefix = f"{i:02d}位"

        lines.append(
            f"{prefix}  {p['horse_number']} {p['horse_name']}\n"
            f"勝率: {p['win_rate']:.1f}% / 連対率: {p['place_rate']:.1f}%"
        )
        lines.append("")

    return "\n".join(lines).strip()


# ==============================
# Discord通知
# ==============================
def send_to_discord(message: str):
    payload = {"content": message}
    r = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    r.raise_for_status()


def build_discord_message(common: dict, race_number: str, predictions: list) -> str:
    table = format_prediction_table(predictions)

    lines = [
        "🏇 **レース予想結果**",
        "",
        f"📅 **日付**：{common['date_info']}",
        f"🏁 **レース**：{race_number} {common['race_title']}",
        "",
        "```",
        table,
        "```",
    ]

    return "\n".join(lines)


# ==============================
# main
# ==============================
def main():
    if len(sys.argv) != 3:
        print("Usage: python notify_discord.py <result.json> <race_info.csv>")
        sys.exit(1)

    json_path = sys.argv[1]
    csv_path = sys.argv[2]

    race_number = extract_race_number_from_filename(json_path)
    common_info = load_common_info(csv_path)
    predictions = load_predictions(json_path)

    # 勝率順にソート
    predictions = sorted(predictions, key=lambda x: x["win_rate"], reverse=True)

    message = build_discord_message(common_info, race_number, predictions)
    send_to_discord(message)

    print("Discord通知完了")


if __name__ == "__main__":
    main()
