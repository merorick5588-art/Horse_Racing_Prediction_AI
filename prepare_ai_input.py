import pandas as pd
import os
import glob
import sys
import re
import ast


# =========================
# % → float
# =========================
def percent_to_float(x):
    if not isinstance(x, str):
        return None
    m = re.search(r"([\d\.]+)", x)
    return float(m.group(1)) if m else None


# =========================
# 距離成績（dist_stats）
# =========================
def extract_dist_stats(dist_raw):
    try:
        d = ast.literal_eval(dist_raw)
    except Exception:
        return [None] * 4

    at_key = None
    for k in d.keys():
        if "当" in k:
            at_key = k
            break

    if at_key is None:
        return [None] * 4

    vals = d[at_key]
    if not isinstance(vals, list) or len(vals) != 4:
        return [None] * 4

    return [int(v) if v.isdigit() else None for v in vals]


# =========================
# コース成績（course_stats）
# =========================
def extract_course_stats(course_raw, surface):
    try:
        d = ast.literal_eval(course_raw)
    except Exception:
        return [None] * 4

    key_candidates = []

    for k in d.keys():
        if "右" in k:
            key_candidates.append(k)

    if not key_candidates:
        for k in d.keys():
            if "左" in k:
                key_candidates.append(k)

    if not key_candidates:
        key_candidates = list(d.keys())

    key = key_candidates[0]
    vals = d[key]

    if not isinstance(vals, list) or len(vals) != 4:
        return [None] * 4

    return [int(v) if v.isdigit() else None for v in vals]


# =========================
# 馬場成績（surface_stats）
# =========================
def extract_surface_stats(surface_raw, track_condition, surface):
    try:
        d = ast.literal_eval(surface_raw)
    except Exception:
        return [None] * 4

    key = f"{surface}{track_condition}"
    if key not in d:
        return [None] * 4

    vals = d[key]
    if not isinstance(vals, list) or len(vals) != 4:
        return [None] * 4

    return [int(v) if v.isdigit() else None for v in vals]


# =========================
# 前走データ抽出
# =========================
def extract_prev_cols(df, num_prev=3):
    need_cols = []
    base_items = [
        "rank", "margin", "agari", "distance",
        "condition", "weather", "pace", "field_size",
    ]

    for i in range(1, num_prev + 1):
        for item in base_items:
            col = f"prev{i}_{item}"
            if col in df.columns:
                need_cols.append(col)

    return need_cols


# =========================
# ★ 追加：レースグレード数値化
# =========================
def grade_to_score(g, title=None):
    # ===== データなし判定（唯一の条件） =====
    if title is None:
        return None
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

    # ===== ★ 新規追加：race_title 条件補正 =====
    if isinstance(title, str):
        if "3勝" in title:
             return  0.35
        elif "2勝" in title:
            return  0.3
        elif "1勝" in title:
             return  0.12
        elif "新馬" in title:
            return  0.08
        elif "未勝利" in title:
            return  0.05
        else:
            return  0.4
    return None



# =========================
# メイン加工関数
# =========================
def make_ai_ready_csv(detail_csv, common_csv, output_csv):
    df = pd.read_csv(detail_csv)
    df_common = pd.read_csv(common_csv)

    drop_cols = ["race_id", "race_number", "headcount"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")

    base_cols = [
        "horse_number",
        "horse_name",
        "sex_age",
        "running_style_score_0to1",
        "horse_weight",
        "weight_diff",
        "kankaku",
    ]

    jockey_cols = [
        "jockey_course_win_rate",
        "horse_num_course_win_rate",
        "father_course_win_rate",
        "trainer_jockey_win_rate"
    ]
    for col in jockey_cols:
        if col in df.columns:
            df[col] = df[col].apply(percent_to_float)

    prev_cols = extract_prev_cols(df, num_prev=3)

    final_cols = base_cols + jockey_cols + prev_cols
    final_cols = [c for c in final_cols if c in df.columns]

    out_df = df[final_cols].copy()

    # ===== ★ 修正点：prevX_grade を out_df に追加 =====
    for i in range(1, 4):
        raw_col = f"prev{i}_race_grade"
        title_col = f"prev{i}_race_name"
        new_col = f"prev{i}_grade"
        if raw_col in df.columns:
            if title_col in df.columns:
                out_df[new_col] = df.apply(
                    lambda r: grade_to_score(r[raw_col], r[title_col]),
                    axis=1
                )
            else:
                out_df[new_col] = df[raw_col].apply(grade_to_score)

    track_condition = str(df_common["track_condition"].iloc[0])
    surface = str(df_common["surface"].iloc[0])

    dist_list, course_list, surface_list = [], [], []

    for _, row in df.iterrows():
        dist_list.append(extract_dist_stats(row.get("dist_stats")))
        course_list.append(extract_course_stats(row.get("course_stats"), surface))
        surface_list.append(extract_surface_stats(row.get("surface_stats"), track_condition, surface))

    dist_cols = ["dist_win", "dist_place2", "dist_place3", "dist_other"]
    course_cols = ["course_win", "course_place2", "course_place3", "course_other"]
    surface_cols = ["surface_win", "surface_place2", "surface_place3", "surface_other"]

    for i, col in enumerate(dist_cols):
        out_df[col] = [x[i] for x in dist_list]

    for i, col in enumerate(course_cols):
        out_df[col] = [x[i] for x in course_list]

    for i, col in enumerate(surface_cols):
        out_df[col] = [x[i] for x in surface_list]

    drop_common = {"race_id", "race_number", "headcount"}
    for col in df_common.columns:
        if col not in drop_common:
            out_df[col] = df_common[col].iloc[0]

    # ===== 全欠損カラム削除 =====
    out_df = out_df.dropna(axis=1, how="all")

    def is_all_empty(col):
        return all((v == "" or pd.isna(v)) for v in col)

    empty_cols = [c for c in out_df.columns if is_all_empty(out_df[c])]
    out_df = out_df.drop(columns=empty_cols)

    # ===== 新馬戦対応 =====
    race_title = str(df_common["race_title"].iloc[0])
    if "新馬" in race_title:
        remove_cols_shinma = [
            "running_style_score_0to1", "weight_diff", "kankaku",
            "dist_win", "dist_place2", "dist_place3", "dist_other",
            "course_win", "course_place2", "course_place3", "course_other",
            "surface_win", "surface_place2", "surface_place3", "surface_other"
        ]
        out_df = out_df.drop(columns=[c for c in remove_cols_shinma if c in out_df.columns], errors="ignore")

    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    out_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"[OK] AI用CSV → {output_csv}")


# =========================
# CLI
# =========================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python prepare_ai_input.py YYYYMMDD")
        exit()

    target_date = sys.argv[1]
    input_dir = f"race_data_{target_date}"

    detail_files = glob.glob(os.path.join(input_dir, "*_data.csv"))

    for detail_path in detail_files:
        common_path = detail_path.replace("_data.csv", "_common.csv")

        if not os.path.exists(common_path):
            print(f"[WARN] Common file not found: {common_path}")
            continue

        output_path = detail_path.replace("_data.csv", "_aiready.csv")
        make_ai_ready_csv(detail_path, common_path, output_path)
