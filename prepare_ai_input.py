import pandas as pd
import os
import glob
import argparse


def make_ai_ready_csv(detail_df: pd.DataFrame, common_df: pd.DataFrame) -> pd.DataFrame:
    # -----------------------------
    # 共通情報
    # -----------------------------
    common_info = {}

    for col in ["race_name", "track_condition", "weather", "distance"]:
        if col in common_df.columns:
            common_info[col] = common_df[col].iloc[0]

    # -----------------------------
    # detail CSV から必要カラム抜き取り
    # -----------------------------
    base_cols = [
        "horse_number",
        "horse_name",
        "sex_age",
        "kinryou",
        "running_style_score_0to1",
        "horse_weight",
        "weight_diff",
        "father_name",
        "mother_name",
    ]

    prev_items = [
        "rank",
        "margin",
        "agari",
        "distance",
        "condition",
        "weather",
        "corner_order",
        "field_size",
        "popularity",
    ]

    prev_cols = []
    for i in [1, 2, 3]:
        for item in prev_items:
            col = f"prev{i}_{item}"
            if col in detail_df.columns:
                prev_cols.append(col)

    final_cols = [c for c in (base_cols + prev_cols) if c in detail_df.columns]

    df_out = detail_df[final_cols].copy()

    # 共通情報を全行に追加
    for k, v in common_info.items():
        df_out[k] = v

    return df_out


def process_all_races(base_dir: str):

    print(f"[INFO] 対象フォルダ: {base_dir}")

    detail_files = glob.glob(os.path.join(base_dir, "*_data.csv"))
    if not detail_files:
        print("レースデータが見つかりません")
        return

    for detail_path in detail_files:

        file = os.path.basename(detail_path)

        race_id = file.split("_")[0]
        race_title = "_".join(file.split("_")[1:-1])

        common_path = os.path.join(base_dir, f"{race_id}_{race_title}_common.csv")
        if not os.path.exists(common_path):
            print(f"[WARN] 共通情報なし: {common_path}")
            continue

        output_path = os.path.join(base_dir, f"{race_id}_{race_title}_ai_ready.csv")

        detail_df = pd.read_csv(detail_path)
        common_df = pd.read_csv(common_path)

        ai_df = make_ai_ready_csv(detail_df, common_df)
        ai_df.to_csv(output_path, index=False, encoding="utf-8-sig")

        print(f"[OK] {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("date_str", help="YYYYMMDD")
    args = parser.parse_args()

    base = f"race_data_{args.date_str}"
    process_all_races(base)
