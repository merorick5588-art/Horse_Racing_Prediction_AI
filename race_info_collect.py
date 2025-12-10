import time
import pandas as pd
import random
import os
from datetime import date
from bs4 import BeautifulSoup
import re

# --- Selenium/WebDriver 関連のインポート ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service 
from webdriver_manager.chrome import ChromeDriverManager
# ----------------------------------------

# --- 設定 ---
REQUEST_DELAY_SECONDS = 5 
# 実行日の日付文字列。テストのため2025/12/07を使用します。
TODAY_STR = "20251207" 
# CSV保存先ディレクトリ
OUTPUT_DIR = f'race_data_{TODAY_STR}'

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
]

# race list
RACE_LIST_URL_TEMPLATE = "https://keibalab.jp/db/race/{date_str}/"
NEWSPAPER_URL_TEMPLATE = "https://keibalab.jp/db/race/{race_id}/umabashira.html?kind=yoko"

RACE_LIST_ITEM_SELECTOR = "table.table-bordered a[href*='/db/race/']"
HORSE_CONTAINER_SELECTOR = "table.yokobashiraTable tbody tr:has(td.umabanBox)"

# ----------------------------------------
# ■ STEP1: レースID取得
# ----------------------------------------

def get_race_ids_from_list_page(date_str: str, driver, wait) -> list[str]:
    list_url = RACE_LIST_URL_TEMPLATE.format(date_str=date_str)
    print(f"\n[STEP 1/2] レース一覧取得中: {list_url}")

    try:
        driver.get(list_url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.table-bordered")))
        soup = BeautifulSoup(driver.page_source, "lxml")

        race_ids = []
        for a_tag in soup.select(RACE_LIST_ITEM_SELECTOR):
            href = a_tag.get("href")
            m = re.search(r"/db/race/(\d{12})/", href)
            if m:
                race_ids.append(m.group(1))

        return sorted(list(set(race_ids)))

    except Exception as e:
        print("レースID抽出エラー:", e)
        return []


def get_all_race_card_urls(driver, wait):
    all_race_ids = get_race_ids_from_list_page(TODAY_STR, driver, wait)
    if not all_race_ids:
        print("レースID無し")
        return [], []

    race_urls = [NEWSPAPER_URL_TEMPLATE.format(race_id=_id) for _id in all_race_ids]
    print(f"取得レース数: {len(race_urls)}")
    return all_race_ids, race_urls


# ----------------------------------------
# ■ STEP2: 新聞HTML取得
# ----------------------------------------

def get_html_content_with_selenium(url, driver, wait):
    time.sleep(REQUEST_DELAY_SECONDS)
    try:
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.yokobashiraTable")))
        return driver.page_source
    except:
        return None


# ----------------------------------------
# ■ Utility
# ----------------------------------------

def get_text(parent, selector):
    tag = parent.select_one(selector)
    return tag.get_text(strip=True) if tag else ""


def parse_corner_order(raw_text: str):
    """
    コーナー通過順（例: －－⑮⑭）から数値だけ抽出 → [15,14]
    """
    nums = re.findall(r"(\d+)", raw_text)
    return nums[:4] if nums else []


# ----------------------------------------
# ■ 前走詳細データ抽出（完全版）
# ----------------------------------------
def blank_prev():
    return {
        "rank": "", "date": "", "distance": "",
        "weather": "", "condition": "", "race_name": "",
        "corner_order": [], "field_size": "", "horse_num": "",
        "popularity": "", "time": "", "agari": "", "pace": "",
        "weight": "", "weight_diff": "", "jockey": "",
        "margin": "", "opponent": ""
    }

def parse_prev_race(z):
    """
    keibalab 前走欄(td.zensouBox) を確実に解析する
    """
    dl = z.select_one(".zensouDl")
    if not dl:
        return blank_prev()

    dd = dl.select("dd")
    if len(dd) < 5:
        return blank_prev()

    # 0: 着順
    rank = dd[0].get_text(strip=True)

    # 1: 開催 + 日付 + 距離 + レース名
    info1 = dd[1].get_text(" ", strip=True)

    m_date = re.search(r"(\d+\/\d+\/\d+)", info1)
    date = m_date.group(1) if m_date else ""

    m_dist = re.search(r"(芝|ダ)(\d+)", info1)
    distance = m_dist.group(2) if m_dist else ""

    race_name = get_text(dd[1], ".tL.bold")

    # 2: 通過順位 + 頭数 + 馬番 + 人気 + 天気 + 馬場
    info2 = dd[2]
    spans = info2.select("span")

    corner_raw = spans[0].get_text(strip=True) if len(spans) >= 1 else ""
    corner_order = parse_corner_order(corner_raw)

    detail = spans[1].get_text(strip=True) if len(spans) >= 2 else ""
    m_head = re.search(r"(\d+)頭", detail)
    m_num = re.search(r"(\d+)番", detail)
    m_pop = re.search(r"(\d+)人", detail)

    field_size = m_head.group(1) if m_head else ""
    horse_num = m_num.group(1) if m_num else ""
    popularity = m_pop.group(1) if m_pop else ""

    # 天気・馬場
    text2 = info2.get_text(" ", strip=True)
    w = re.findall(r"(晴|曇|雨)", text2)
    c = re.findall(r"(良|稍|重|不)", text2)

    weather = w[-1] if w else ""
    condition = c[-1] if c else ""

    # 3: タイム + 上がり + ペース + 体重
    info3 = dd[3].get_text(" ", strip=True).split()

    time = info3[0] if len(info3) >= 1 else ""
    agari = info3[1] if len(info3) >= 2 else ""
    pace = info3[2] if len(info3) >= 3 else ""

    weight = ""
    weight_diff = ""
    if len(info3) >= 4:
        m_w = re.match(r"(\d+)kg\(([-＋+\-]?\d+|---)\)", info3[3])
        if m_w:
            weight = m_w.group(1)
            # --- の場合は空欄にする
            wd = m_w.group(2)
            weight_diff = "" if wd == "---" else wd

    # 4: 騎手・斤量・相手馬・着差
    info4 = dd[4].get_text(" ", strip=True)

    m_j = re.match(r"([ァ-ンヴー一-龥A-Za-z]+)", info4)
    jockey = m_j.group(1) if m_j else ""

    m_margin = re.search(r"\(([-\d\.]+)\)", info4)
    margin = m_margin.group(1) if m_margin else ""

    m_op = re.search(r"\)\s*([^\s]+)", info4)
    opponent = m_op.group(1) if m_op else ""

    return {
        "rank": rank,
        "date": date,
        "distance": distance,
        "weather": weather,
        "condition": condition,
        "race_name": race_name,
        "corner_order": corner_order,
        "field_size": field_size,
        "horse_num": horse_num,
        "popularity": popularity,
        "time": time,
        "agari": agari,
        "pace": pace,
        "weight": weight,
        "weight_diff": weight_diff,
        "jockey": jockey,
        "margin": margin,
        "opponent": opponent
    }






# ----------------------------------------
# ■ 新聞データ抽出（メイン）
# ----------------------------------------

def collect_and_format_race_data(race_urls, driver, wait):
    print("\n[STEP 2/2] 新聞データ抽出開始")

    for url in race_urls:
        print("\n▶", url)

        content = get_html_content_with_selenium(url, driver, wait)
        if not content:
            continue

        soup = BeautifulSoup(content, "html.parser")

        # race name / id
        race_table_tag = soup.select_one("table.yokobashiraTable")
        summary_text = race_table_tag["summary"] if race_table_tag else ""
        race_name = summary_text.replace("の横型馬柱", "").strip()

        race_id = re.search(r"/db/race/(\d{12})/", url).group(1)

        # 全馬ブロック
        horse_rows = soup.select(HORSE_CONTAINER_SELECTOR)
        if not horse_rows:
            print("馬データなし")
            continue

        race_data = []

        for container in horse_rows:

            # ----------------------
            # 基本情報
            # ----------------------
            wakuban = get_text(container, "td.wakubanBox")
            horse_number = get_text(container, "td.umabanBox")
            horse_name = get_text(container, "td.bameiBox .bamei3 a")

            # 性齢・間隔
            kisyu_list = container.select("td.bameiBox .kisyu3")
            basic_info = kisyu_list[1].get_text(" ", strip=True) if len(kisyu_list) >= 2 else ""
            sex_age = re.findall(r"(牡|牝|セ)\d", basic_info)
            sex_age = sex_age[0] if sex_age else ""
            kankaku = re.findall(r"(中\d+週|新馬)", basic_info)
            kankaku = kankaku[0] if kankaku else ""

            jockey_name = get_text(container, "td.bameiBox .kisyu3 a")
            kinryou = get_text(container, "td.bameiBox .dbkinryou").replace("(", "").replace(")", "")

            # 脚質（◁◁◀◀）
            legs_style = "".join([s.get_text("") for s in container.select("td.bameiBox .dbrunstyle2yoko span")])

            # ----------------------
            # 人気・オッズ・体重
            # ----------------------
            odd_dd = container.select("td.umaboddsBox .umaboddsDl dd")
            popularity = odd_dd[0].get_text(strip=True).replace("人気", "") if len(odd_dd) > 0 else ""
            odds = odd_dd[1].get_text(strip=True) if len(odd_dd) > 1 else ""
            horse_weight = odd_dd[2].get_text(strip=True).replace("kg", "") if len(odd_dd) > 2 else ""
            weight_diff = re.sub(r"[()＋－kg]", "", odd_dd[3].get_text(strip=True)) if len(odd_dd) > 3 else ""

            # ----------------------
            # 血統
            # ----------------------
            father_name = get_text(container, ".chichi3 a")
            mother_name = get_text(container, ".haha4")

            # ---------------------------
            # 騎手データの抽出（完全版 / 改良版）
            # ---------------------------

            jockey_course_win_rate = ""
            horse_num_course_win_rate = ""
            father_course_win_rate = ""
            trainer_jockey_win_rate = ""

            all_jd = container.select("td.jockeydata")

            # 「成績テーブルではないほう」を取得
            target_jd = None
            for jd in all_jd:
                classes = jd.get("class", [])
                if not any("dbSeisekiData" in c for c in classes):
                    target_jd = jd
                    break

            if target_jd:
                html = target_jd.decode_contents()

                # ★ すべての <br> タグで分割（<br>, <br/>, <br />）
                lines = re.split(r"<br\s*/?>", html)

                for line in lines:
                    # タグを解析しつつテキスト抽出
                    s = BeautifulSoup(line, "html.parser")
                    text = s.get_text(" ", strip=True)

                    if "：" not in text:
                        continue

                    label, value = text.split("：", 1)
                    label = label.strip()
                    value = value.strip()

                    if label == "騎手":
                        jockey_course_win_rate = value
                    elif label == "馬番":
                        horse_num_course_win_rate = value
                    elif label == "父馬":
                        father_course_win_rate = value
                    elif label == "コンビ":
                        trainer_jockey_win_rate = value
   


            # ----------------------
            # 成績表（距離 / コース / 馬場）
            # ----------------------
            seiseki = container.select("td.dbSeisekiData table")
            def parse_block(tbl):
                out = {}
                for tr in tbl.select("tr"):
                    th = tr.select_one("th").get_text(strip=True)
                    tds = [td.get_text(strip=True) for td in tr.select("td")]
                    out[th] = tds
                return out

            dist_stats = parse_block(seiseki[0]) if len(seiseki) >= 1 else {}
            course_stats = parse_block(seiseki[1]) if len(seiseki) >= 2 else {}
            surface_stats = parse_block(seiseki[2]) if len(seiseki) >= 3 else {}

            # ----------------------
            # 前走1〜5 詳細データ
            # ----------------------
            prev_boxes = container.select("td.zensouBox")
            prev_detail = {}

            for i in range(5):
                key = f"prev{i+1}_"
                if i < len(prev_boxes):
                    p = parse_prev_race(prev_boxes[i])
                else:
                    p = parse_prev_race(None)

                # 詳細カラム展開
                for k, v in p.items():
                    prev_detail[key + k] = v

            # ----------------------
            # DataFrame用レコード
            # ----------------------
            data = {
                "race_id": race_id,
                "race_name": race_name,
                "wakuban": wakuban,
                "horse_number": horse_number,
                "horse_name": horse_name,
                "jockey_name": jockey_name,
                "sex_age": sex_age,
                "kankaku": kankaku,
                "kinryou": kinryou,
                "legs_style": legs_style,
                "popularity": popularity,
                "odds": odds,
                "horse_weight": horse_weight,
                "weight_diff": weight_diff,
                "father_name": father_name,
                "mother_name": mother_name,
                "jockey_course_win_rate": jockey_course_win_rate,
                "horse_num_course_win_rate": horse_num_course_win_rate,
                "father_course_win_rate": father_course_win_rate,
                "trainer_jockey_win_rate": trainer_jockey_win_rate,
                "dist_stats": dist_stats,
                "course_stats": course_stats,
                "surface_stats": surface_stats
            }

            data.update(prev_detail)
            race_data.append(data)

        # 保存
        if race_data:
            df = pd.DataFrame(race_data)
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            safe_race_name = re.sub(r'[\\/:*?"<>|]', "", race_name)
            out_path = os.path.join(OUTPUT_DIR, f"{race_id}_{safe_race_name}.csv")
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            print("保存:", out_path)


# ----------------------------------------
# ■ MAIN
# ----------------------------------------

if __name__ == "__main__":
    user_agent = random.choice(USER_AGENTS)
    options = Options()
    options.add_argument("--headless")
    options.add_argument(f"user-agent={user_agent}")

    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 45)

        all_ids, urls = get_all_race_card_urls(driver, wait)
        if urls:
            collect_and_format_race_data(urls, driver, wait)

            print("\n=== 完了 ===")
            print(f"保存先: {OUTPUT_DIR}")

    finally:
        if driver:
            driver.quit()
