import argparse
import pandas as pd
import json
import os
from openai import OpenAI

DEFAULT_MODEL = "gpt-4.1-mini"

COMMON_COLS = [
    "date_info",
    "race_title",
    "weather",
    "track_condition",
    "surface",
    "distance",
]


# =========================
# レースグレード数値化
# =========================
def grade_to_score(g):
    if not isinstance(g, str):
        return 0
    if "GⅠ" in g or "G1" in g:
        return 4
    if "GⅡ" in g or "G2" in g:
        return 3
    if "GⅢ" in g or "G3" in g:
        return 2
    if "L" in g or "OP" in g:
        return 1
    return 0


# =========================
# CSV読込
# =========================
def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


# =========================
# 共通情報 / 馬データ分離
# =========================
def split_common_and_horses(df: pd.DataFrame):
    common_info = {}

    # そのまま使う共通情報
    for col in ["date_info", "weather", "track_condition", "surface", "distance"]:
        if col in df.columns:
            common_info[col] = df[col].iloc[0]

    # race_title → race_grade に変換
    if "race_title" in df.columns:
        race_title = df["race_title"].iloc[0]
        common_info["race_grade"] = grade_to_score(race_title)
    else:
        common_info["race_grade"] = 0

    # 出走馬データ（共通列を除外）
    drop_cols = COMMON_COLS
    horse_df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    horses = horse_df.to_dict(orient="records")

    return common_info, horses


# =========================
# プロンプト生成
# =========================
def build_prompt(common_info: dict, horses: list) -> str:
    prompt = f"""
あなたは世界トップレベルの日本のJRA競馬予想家です。
添付のCSVデータをもとに、各馬について以下3つの指標を予測してください。

- win_rate : 1着になる可能性の強さ
- top2_rate : 2着以内に入る可能性の強さ
- top3_rate : 3着以内に入る可能性の強さ

■ 制約
- オッズ・人気はデータに含まれていません。
- 数値の過剰推測は禁止。
- すべての馬に対して必ず3つの数値を返す。
- 出力はwin_rateが高い順に返す。
- win_rate / top2_rate / top3_rate は論理的に
  「1着 ⊂ 2着以内 ⊂ 3着以内」の関係を満たすこと。
- ただし、勝ち切れないが着内率が高い馬など、
  勝率が低く着内率が高いケースは積極的に表現してよい。
- 数値は相対評価でよく、合計値や正規化は考慮しなくてよい。

■ 共通情報
date_info: "{common_info.get('date_info')}"
race_grade: {common_info.get('race_grade')}
weather: "{common_info.get('weather')}"
track_condition: "{common_info.get('track_condition')}"
surface: "{common_info.get('surface')}"
distance: {common_info.get('distance')}

■ 出走馬データ
{json.dumps(horses, ensure_ascii=False)}

■ 出力形式（JSONのみ）
[
  {{
    "horse_number": 馬番,
    "horse_name": "馬名",
    "win_rate": 数値,
    "top2_rate": 数値,
    "top3_rate": 数値
  }}
]
"""
    return prompt.strip()


# =========================
# GPT問い合わせ
# =========================
def ask_gpt(prompt: str, model_name: str) -> list:
    client = OpenAI()

    # =========================
    # モデル別 generation 設定
    # =========================
    kwargs = {}

    if not model_name.startswith("gpt-5"):
        kwargs["temperature"] = 0.7
    else:
        kwargs["temperature"] = 0.2

    resp = client.responses.create(
        model=model_name,
        input=[
            {
                "role": "system",
                "content": "あなたはJRA競馬予想AIです。JSON以外は一切返さないでください。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        **kwargs
    )


    text = resp.output_text

    try:
        return json.loads(text)
    except Exception:
        print("[WARN] JSON抽出を試行")
        text = text[text.find("["): text.rfind("]") + 1]
        return json.loads(text)

# =========================
# 正規化処理 ★追加
# =========================
def normalize_rates(prediction: list) -> list:
    def norm(key, total_target):
        total = sum(p.get(key, 0) for p in prediction)
        if total == 0:
            return
        for p in prediction:
            p[key] = round(p[key] / total * total_target, 2)

    norm("win_rate", 100.0)
    norm("top2_rate", 200.0)
    norm("top3_rate", 300.0)

    return prediction
# =========================
# 出力パス生成
# =========================
def build_base_name(csv_path: str) -> str:
    base = os.path.basename(csv_path)

    return os.path.splitext(base)[0]


# =========================
# メイン処理
# =========================
def main(csv_path: str, model_name: str):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(csv_path)

    print(f"使用モデル: {model_name}")
    print(f"分析対象CSV: {csv_path}")

    df = load_csv(csv_path)
    common_info, horses = split_common_and_horses(df)

    prompt = build_prompt(common_info, horses)

    base_name = build_base_name(csv_path)
    out_dir = os.path.dirname(csv_path)

    # --- プロンプトTXT出力（テスト用） ---
    #prompt_path = os.path.join(out_dir, f"{base_name}_prompt.txt")
    #with open(prompt_path, "w", encoding="utf-8") as f:
    #    f.write(prompt)

    #print(f"[OK] プロンプト出力: {prompt_path}")

    # --- AI予測 ---
    prediction = ask_gpt(prompt, model_name)

    # ★ 正規化
    prediction = normalize_rates(prediction)

    # 勝率降順で整列
    prediction_sorted = sorted(prediction, key=lambda x: -x["win_rate"])

    out_json = os.path.join(out_dir, f"{base_name}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(prediction_sorted, f, ensure_ascii=False, indent=2)

    print(f"[OK] 予測結果出力: {out_json}")
    print("=== 完了 ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", help="*_aiready.csv を指定")
    parser.add_argument(
        "model",
        nargs="?",
        default=DEFAULT_MODEL,
        help="使用するOpenAIモデル（省略可）"
    )
    args = parser.parse_args()

    main(args.csv_path, args.model)
