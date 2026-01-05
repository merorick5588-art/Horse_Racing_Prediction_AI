import argparse
import pandas as pd
import json
import os
import re
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
    # ===== 既存ロジック（完全保持） =====
    if isinstance(g, str):
        if "GⅠ" in g or "G1" in g or "ＧⅠ" in g:
            return  1.00
        elif "GⅡ" in g or "G2" in g or "ＧⅡ" in g:
            return  0.8
        elif "GⅢ" in g or "G3" in g or "ＧⅢ" in g:
            return  0.6
        elif "L" in g or "OP" in g :
            return  0.4
        elif "3勝" in g:
            return  0.35
        elif "2勝" in g:
            return  0.3
        elif "1勝" in g:
             return  0.12
        elif "新馬" in g:
             return  0.08
        elif "未勝利" in g:
            return  0.05
        else:
            return  0.4

    return 0


# =========================
# CSV読込
# =========================
def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


# =========================
# 距離単位正規化
# =========================
def normalize_distance(v):
    if pd.isna(v):
        return v
    try:
        v = int(float(v))
        if v < 100:
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
# プロンプト生成（100点完全・全ロジック統合版）
# =========================
def build_prompt(common_info: dict, horses: list) -> str:
    # --- 1. 競馬場名の抽出と場別ロジック ---
    date_info = common_info.get('date_info', '')
    venue = ""
    venues = ["中山", "東京", "京都", "阪神", "中京", "新潟", "福島", "小倉", "札幌", "函館"]
    for v in venues:
        if v in date_info:
            venue = v
            break

    venue_logic = ""
    if venue == "東京":
        venue_logic = "- 【東京競馬場特化】: 直線が非常に長く末脚持続力が問われる。先行力よりも「prevX_agari」の順位と実績を最重視せよ。"
    elif venue == "中山":
        venue_logic = "- 【中山競馬場特化】: 直線が短く急坂がある。先行押し切りが基本。「running_style_score_0to1」が高い馬を優先評価せよ。"
    elif venue == "京都":
        venue_logic = "- 【京都競馬場特化】: 3コーナーの坂の下りを利用した加速が重要。平坦な直線でのスピード実績を重視せよ。"
    elif venue == "阪神":
        venue_logic = "- 【阪神競馬場特化】: 強力な急坂がある。パワーとスタミナを重視し、馬体重が重い馬や坂実績のある馬を評価せよ。"
    elif venue == "中京":
        venue_logic = "- 【中京競馬場特化】: 直線が長く急坂もあるタフなコース。差し・追い込みの「prevX_agari」実績を評価せよ。"
    elif venue == "新潟":
        venue_logic = "- 【新潟競馬場特化】: 日本一長い直線での極限のスピード勝負。「prevX_agari」の純粋なタイムの速さを最優先せよ。"
    elif venue == "福島":
        venue_logic = "- 【福島競馬場特化】: 小回りでコーナーが非常にきつい。「running_style_score_0to1」が高い馬を強力に加点せよ。"
    elif venue == "小倉":
        venue_logic = "- 【小倉競馬場特化】: 下り坂から始まるため超ハイペースになりやすい。ハイペースでの margin 実績を重視せよ。"
    elif venue == "札幌":
        venue_logic = "- 【札幌競馬場特化】: 直線が極めて短い洋芝コース。パワーを要するため、同表面（surface_win）の実績を重視せよ。"
    elif venue == "函館":
        venue_logic = "- 【函館競馬場特化】: 洋芝の平坦コース。先行馬の勝率が極めて高く、逃げ・先行実績を最優先せよ。"
    else:
        venue_logic = "- 【標準ロジック】: 距離適性と直近の着差（margin）を等価に評価せよ。"

    # --- 2. 表面・距離・馬場状態の動的ロジック ---
    surface = common_info.get('surface', '')
    distance = common_info.get('distance', 1600)
    condition = common_info.get('track_condition', '良')

    condition_logic = ""
    if surface == "ダ":
        if distance <= 1400:
            condition_logic = "- 【短距離ダート特化】: running_style_score_0to1 が 0.6 以上の先行力を最優先。砂被りのリスクが低い外枠（馬番12番以降）を微加点。"
        else:
            condition_logic = "- 【中長距離ダート特化】: 消耗戦になりやすいため、prevX_distance が今回と同等以上のスタミナ実績を重視。"
    else: # 芝
        if distance <= 1400:
            condition_logic = "- 【芝短距離特化】: prevX_agari（上がりの速さ）の順位を重視。一瞬の加速力がある馬を高く評価。"
        else:
            condition_logic = "- 【芝中長距離特化】: jockey_course_win_rate の重みを最大化。道中の折り合いと仕掛けのタイミングが重要なため、名手を優先。"

    if condition in ["重", "不", "不良", "稍"]:
        condition_logic += "\n- 【道悪補正】: prevX_condition が「重・不」での好走歴（margin <= 0.6）がある馬の評価を大幅に引き上げ。"

    # --- 3. プロンプト構築 ---
    prompt = f"""
あなたは統計的特徴量のみを用いて競馬予測を行う専門AIである。
主観・物語・人気・印象・オッズ推測は禁止する。
CSVに存在する数値・カテゴリ情報のみを使用せよ。

【使用可能カラム定義（厳守）】

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

【評価の絶対原則】
- 最優先評価: 直近3走（prev1-3）のうち、「今回の距離 ±200m かつ 今回の表面タイプ」で行われたレースでの最小 margin をその馬の「基準能力」とせよ。
- 補完評価: 上記の合致レースが存在しない場合、または NaN の場合は、prev1 を中心に評価しつつ、統計的期待値（jockey_course_win_rate 等）の重みを高めよ。
- トレンド補正: 3走の margin が改善傾向にある場合は加点、悪化傾向にある場合は減点せよ。
- 単純平均・機械合算は禁止する。

【コース・条件別動的ロジック（最優先適用）】
{venue_logic}
{condition_logic}

【レースグレード補正（反転禁止）】
- prev1_grade が高いレースで
  prev1_margin <= 1.0 の善戦をしている場合、
  同程度の prev1_margin を持つ下位グレード馬より
  相対評価を下げてはならない
- グレード差のみを理由に
  prev1_margin が明確に優秀な馬を下げてはならない

【着差評価基準】
- prevX_margin <= 0.3 : 非常に優秀
- 0.3 < prevX_margin <= 0.6 : 良好
- 0.6 < prevX_margin <= 1.0 : 標準
- prevX_margin > 1.5 : 大敗


【一時的不調判定（柔軟化・データ欠損対応）】
以下のいずれかに該当する場合、prev1 の大敗を能力低下と断定せず、過去の良好な数値を優先して評価せよ。

1. prev1 が「今回と異なる表面（芝/ダ）」または「距離差 400m 以上」での敗戦。
2. prev1 が「重・不良馬場」で今回が「良・稍重」かつ、過去に良馬場で好走実績がある。
3. prev2 または prev3 のいずれかで margin <= 0.6 を記録している。
4. キャリアが浅く prev2 や prev3 が NaN であるが、jockey/father の統計値が極めて高い。


【安定性評価】
- 3走中2走以上 margin <= 0.6 → 安定型
- 3走中1走のみ margin >= 1.5 → 一時的不調候補
- 3走中2走以上 margin >= 1.5 → 明確な下降型

【距離適性】
- prevX_distance が今回距離 ±200m → 適性あり
- 距離延長 × 先行型 → 加点
- 距離短縮 × 差し型 → 加点
- running_style_score_0to1 は先行性の強さを表す連続値であり、
  距離延長・短縮判断の補助としてのみ使用せよ

【補助補正ルール（反転禁止）】
- jockey_course_win_rate 高 → 安定性補正
- father_course_win_rate 高 → 距離適性補助
- dist/course/surface_win 高 → 条件一致補正
- kankaku 極端（短すぎ/長すぎ）→ 軽微減点
- prevX_grade が高く善戦 → 能力下方修正禁止
- 善戦とは prevX_margin <= 1.0 を指す
- kankaku は「中◯週」の数値部分のみを解釈対象とせよ
- kankakuで「連闘」とあった場合は0として解釈せよ

【数値制約】
- win_rate <= top2_rate <= top3_rate
- 相対評価のみ
- 数値の絶対値そのものに意味を持たせてはならない
- 上位と下位の差を明確に
- 全馬同値は禁止

【共通情報】
date_info: "{common_info.get('date_info')}"
race_grade: {common_info.get('race_grade')}
weather: "{common_info.get('weather')}"
track_condition: "{common_info.get('track_condition')}"
surface: "{common_info.get('surface')}"
distance: {common_info.get('distance')}

【出走馬データ】
{json.dumps(horses, ensure_ascii=False)}

【出力条件】
- JSON配列のみ
- horse_number 昇順
- 全馬必須
- JSON以外の文字列は禁止

【出力形式】
[
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
