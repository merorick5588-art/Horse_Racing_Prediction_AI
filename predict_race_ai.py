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
# 距離単位正規化（★最重要）
# =========================
def normalize_distance(v):
    if pd.isna(v):
        return v
    try:
        v = int(v)
        if v < 100:      # 16 → 1600
            return v * 100
        return v
    except Exception:
        return v


# =========================
# 共通情報 / 馬データ分離
# =========================
def split_common_and_horses(df: pd.DataFrame):
    common_info = {}

    for col in ["date_info", "weather", "track_condition", "surface", "distance"]:
        if col in df.columns:
            common_info[col] = df[col].iloc[0]

    if "race_title" in df.columns:
        common_info["race_grade"] = grade_to_score(df["race_title"].iloc[0])
    else:
        common_info["race_grade"] = 0

    horse_df = df.drop(columns=[c for c in COMMON_COLS if c in df.columns])

    # ★ 距離系正規化
    for x in [1, 2, 3]:
        col = f"prev{x}_distance"
        if col in horse_df.columns:
            horse_df[col] = horse_df[col].apply(normalize_distance)

    horses = horse_df.to_dict(orient="records")
    return common_info, horses


# =========================
# プロンプト生成（100点完全版）
# =========================
def build_prompt(common_info: dict, horses: list) -> str:
    prompt = f"""
あなたは統計的特徴量のみを用いて競馬予測を行う専門AIである。
主観・物語・人気・印象・オッズ推測は禁止する。
CSVに存在する数値・カテゴリ情報のみを使用せよ。

────────────────────
【使用可能カラム定義（厳守）】
────────────────────

■ 基本
- horse_number
- horse_name
- running_style_score_0to1
- kankaku

■ 騎手・血統
- jockey_course_win_rate
- father_course_win_rate

■ 条件別実績
- dist_win
- course_win
- surface_win

■ 直近3走（prev1 最重要）
- prevX_rank
- prevX_margin
- prevX_distance
- prevX_agari
- prevX_pace
- prevX_weather
- prevX_condition
- prevX_grade

X は 1,2,3 のいずれか。
NaN は「評価不能」とし、推測・補完は禁止。
NaN が多いこと自体を理由に減点してはならない。
上記以外のカラムが存在する場合、それらも数値・カテゴリ情報として使用してよい。

────────────────────
【評価の絶対原則】
────────────────────
- 評価の中心は必ず prev1
- prev2 / prev3 は一時的不調・例外検出専用
- prev2 / prev3 を理由に評価を反転させてはならない
- 単純平均・機械合算は禁止
- どの補助情報も prev1 の評価を上書きしてはならない


────────────────────
【着差評価基準】
────────────────────
- prevX_margin <= 0.3 : 非常に優秀
- 0.3 < prevX_margin <= 0.6 : 良好
- 0.6 < prevX_margin <= 1.0 : 標準
- prevX_margin > 1.5 : 大敗


────────────────────
【一時的不調判定（厳格）】
────────────────────
以下すべてを満たす場合のみ、
prev1 の大敗を能力低下と断定してはならない。

1. prev1_margin >= 1.5
2. prev2_margin <= 0.6
3. prev3_margin <= 0.6
4. prev2 または prev3 の距離が今回距離 ±200m

満たさない場合、prev1 を最優先で評価する。
────────────────────
【安定性評価】
────────────────────
- 3走中2走以上 margin <= 0.6 → 安定型
- 3走中1走のみ margin >= 1.5 → 一時的不調候補
- 3走中2走以上 margin >= 1.5 → 明確な下降型

────────────────────
【距離適性】
────────────────────
- prevX_distance が今回距離 ±200m → 適性あり
- 距離延長 × 先行型 → 加点
- 距離短縮 × 差し型 → 加点
- running_style_score_0to1 は先行性の強さを表す連続値であり、
  距離延長・短縮判断の補助としてのみ使用せよ

────────────────────
【補助補正ルール（反転禁止）】
────────────────────
- jockey_course_win_rate 高 → 安定性補正
- father_course_win_rate 高 → 距離適性補助
- dist/course/surface_win 高 → 条件一致補正
- kankaku 極端（短すぎ/長すぎ）→ 軽微減点
- prevX_grade が高く善戦 → 能力下方修正禁止
- 善戦とは prevX_margin <= 1.0 を指す
- kankaku は「中◯週」の数値部分のみを解釈対象とせよ
- kankakuで「連闘」とあった場合は0として解釈せよ

────────────────────
【数値制約】
────────────────────
- win_rate <= top2_rate <= top3_rate
- 相対評価のみ
- 数値の絶対値そのものに意味を持たせてはならない
- 上位と下位の差を明確に
- 全馬同値は禁止

────────────────────
【共通情報】
────────────────────
date_info: "{common_info.get('date_info')}"
race_grade: {common_info.get('race_grade')}
weather: "{common_info.get('weather')}"
track_condition: "{common_info.get('track_condition')}"
surface: "{common_info.get('surface')}"
distance: {common_info.get('distance')}

────────────────────
【出走馬データ】
────────────────────
{json.dumps(horses, ensure_ascii=False)}

────────────────────
【出力条件】
────────────────────
- JSON配列のみ
- horse_number 昇順
- 全馬必須
- JSON以外の文字列は禁止

────────────────────
【出力形式】
────────────────────[
  {{
    "horse_number": number,
    "horse_name": "string",
    "win_rate": number,
    "top2_rate": number,
    "top3_rate": number
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
    prompt_path = os.path.join(out_dir, f"{base_name}_prompt.txt")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    print(f"[OK] プロンプト出力: {prompt_path}")

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
