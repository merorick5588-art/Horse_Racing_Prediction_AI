import sys
import os
import json
import pandas as pd
import requests

# ==============================
# 設定
# ==============================

COURSE_CODE_MAP = {
    "01": "SAPPORO",
    "02": "HAKODATE",
    "03": "FUKUSHIMA",
    "04": "NIIGATA",
    "05": "TOKYO",
    "06": "NAKAYAMA",
    "07": "CHUKYO",
    "08": "KYOTO",
    "09": "HANSHIN",
    "10": "KOKURA",
}
DISCORD_WEBHOOK_URL = None

# JRA枠番カラー対応（整数キーに変更）
WAKU_COLOR_MAP = {
    1: "⬜",
    2: "⬛",
    3: "🟥",
    4: "🟦",
    5: "🟨",
    6: "🟩",
    7: "🟧",
    8: "🟪",
}


# ==============================
# ユーティリティ
# ==============================

def get_waku_number(horse_number: int, total_horses: int) -> int:
    """
    JRAの枠番割当ルールに基づき、馬番から枠番を算出する
    """
    if total_horses <= 8:
        return horse_number

    # 各枠の最低頭数(base)と、多めに割り振る枠の数(extras)を計算
    base_count = total_horses // 8
    extras = total_horses % 8

    # 多頭数になる枠の境界線（この枠番号より大きい枠は base_count + 1 頭入る）
    # 例：10頭立てなら extras=2 なので、7枠と8枠が2頭になる。境界は 8-2 = 6。
    boundary_frame = 8 - extras

    # 境界線までの枠に入っている馬の総数
    boundary_horse_count = boundary_frame * base_count

    if horse_number <= boundary_horse_count:
        # 少ない方の頭数（base_count）で割る
        return (horse_number - 1) // base_count + 1
    else:
        # 境界以降の馬番。多い方の頭数（base_count + 1）で割る
        offset_horse_num = horse_number - boundary_horse_count
        return boundary_frame + (offset_horse_num - 1) // (base_count + 1) + 1

def extract_race_number_from_filename(filename: str) -> str:
    """
    例: 202512200601_サラ系2歳未勝利.json
    → 下2桁 = 01 → 01R
    """
    base = os.path.basename(filename)
    race_id = base.split("_")[0]
    race_no = race_id[-2:]
    return f"{race_no}R"

def extract_course_code_from_filename(filename: str) -> str:
    """
    例: 202512200601_サラ系2歳未勝利.json
    → 下3,4桁 = 06
    """
    base = os.path.basename(filename)
    race_id = base.split("_")[0]
    return race_id[8:10]

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
    total_horses = len(predictions)
    for i, p in enumerate(predictions, start=1):
        prefix = f"{i:02d}位"
        waku_num = get_waku_number(p["horse_number"], total_horses)
        waku_color = WAKU_COLOR_MAP.get(waku_num, "⬜")

        lines.append(
            f"{prefix} {waku_color} {p['horse_number']} {p['horse_name']}\n"
            f"勝率: {p['win_rate']:.1f}% / "
            f"連対率: {p['top2_rate']:.1f}% / "
            f"3着内: {p['top3_rate']:.1f}%"
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

    # --- 開催場判定 ---
    course_code = extract_course_code_from_filename(json_path)
    if course_code not in COURSE_CODE_MAP:
        raise RuntimeError(f"未対応の開催場コード: {course_code}")

    env_key = f"DISCORD_WEBHOOK_URL_{COURSE_CODE_MAP[course_code]}"
    global DISCORD_WEBHOOK_URL
    DISCORD_WEBHOOK_URL = os.environ.get(env_key)

    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError(f"{env_key} が環境変数に設定されていません")

    # --- データ読込 ---
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
