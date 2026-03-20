import json
import os
import re
import time
import requests
from datetime import datetime
from pathlib import Path

# =============================
# 設定
# =============================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
PRICES_FILE = "prices.json"
PRODUCTS_FILE = "products.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
}

# =============================
# 価格履歴の読み込み・保存
# =============================
def load_prices():
    if Path(PRICES_FILE).exists():
        with open(PRICES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_prices(prices):
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(prices, f, ensure_ascii=False, indent=2)

# =============================
# 商品リストの読み込み
# =============================
def load_products():
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# =============================
# Amazon 価格取得
# =============================
def get_amazon_price(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()

        # 複数パターンで価格を探す
        patterns = [
            r'"priceAmount":([\d.]+)',
            r'id="priceblock_ourprice"[^>]*>([\d,]+)',
            r'class="a-price-whole"[^>]*>([\d,]+)',
            r'"price":\s*"¥\s*([\d,]+)"',
            r'<span[^>]*class="[^"]*a-price-whole[^"]*"[^>]*>([\d,]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, res.text)
            if match:
                price_str = match.group(1).replace(",", "").replace(".", "")
                price = int(float(price_str))
                if 100 <= price <= 1_000_000:  # 妥当な価格範囲チェック
                    return price

        print(f"  [警告] 価格を取得できませんでした: {url}")
        return None

    except Exception as e:
        print(f"  [エラー] Amazon取得失敗: {e}")
        return None

# =============================
# 楽天 価格取得（将来用）
# =============================
def get_rakuten_price(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()

        patterns = [
            r'"price":\s*([\d]+)',
            r'class="price2"[^>]*>\s*￥([\d,]+)',
            r'itemprop="price"[^>]*content="([\d.]+)"',
        ]

        for pattern in patterns:
            match = re.search(pattern, res.text)
            if match:
                price = int(match.group(1).replace(",", ""))
                if 100 <= price <= 1_000_000:
                    return price

        print(f"  [警告] 価格を取得できませんでした: {url}")
        return None

    except Exception as e:
        print(f"  [エラー] 楽天取得失敗: {e}")
        return None

# =============================
# Yahoo!ショッピング 価格取得（将来用）
# =============================
def get_yahoo_price(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()

        patterns = [
            r'"price":\s*([\d]+)',
            r'class="price[^"]*"[^>]*>\s*￥([\d,]+)',
            r'itemprop="price"[^>]*content="([\d.]+)"',
        ]

        for pattern in patterns:
            match = re.search(pattern, res.text)
            if match:
                price = int(match.group(1).replace(",", ""))
                if 100 <= price <= 1_000_000:
                    return price

        print(f"  [警告] 価格を取得できませんでした: {url}")
        return None

    except Exception as e:
        print(f"  [エラー] Yahoo!取得失敗: {e}")
        return None

# =============================
# サイトに応じて価格取得を振り分け
# =============================
def get_price(product):
    site = product.get("site", "amazon")
    url = product["url"]

    if site == "amazon":
        return get_amazon_price(url)
    elif site == "rakuten":
        return get_rakuten_price(url)
    elif site == "yahoo":
        return get_yahoo_price(url)
    else:
        print(f"  [警告] 未対応のサイト: {site}")
        return None

# =============================
# Discord通知
# =============================
def send_discord(message):
    if not DISCORD_WEBHOOK_URL:
        print("[警告] DISCORD_WEBHOOK_URL が設定されていません")
        return

    payload = {"content": message}
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        res.raise_for_status()
        print("  [通知] Discordに送信しました")
    except Exception as e:
        print(f"  [エラー] Discord送信失敗: {e}")

# =============================
# メイン処理
# =============================
def main():
    print(f"\n{'='*50}")
    print(f"価格チェック開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    products = load_products()
    prices = load_prices()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for product in products:
        name = product["name"]
        url = product["url"]
        target = product["target_price"]
        site = product.get("site", "amazon")

        print(f"\n📦 {name}")
        print(f"   サイト: {site} | 目標価格: ¥{target:,}")

        # 価格取得（リトライ付き）
        price = None
        for attempt in range(3):
            price = get_price(product)
            if price:
                break
            if attempt < 2:
                print(f"   リトライ {attempt + 1}/2...")
                time.sleep(5)

        if price is None:
            print(f"   → 価格取得失敗（スキップ）")
            continue

        print(f"   現在価格: ¥{price:,}")

        # 価格履歴を更新
        if url not in prices:
            prices[url] = []
        prices[url].append({"price": price, "checked_at": now})
        # 履歴は直近30件だけ保持
        prices[url] = prices[url][-30:]

        # 目標価格以下かチェック
        if price <= target:
            diff = target - price
            message = (
                f"🎉 **価格アラート！**\n"
                f"```\n"
                f"商品: {name}\n"
                f"現在価格: ¥{price:,}\n"
                f"目標価格: ¥{target:,}\n"
                f"目標より: ¥{diff:,} 安い！\n"
                f"```\n"
                f"🛒 {url}"
            )
            print(f"   🎉 目標価格以下！通知を送ります")
            send_discord(message)
        else:
            diff = price - target
            print(f"   → まだ目標まで ¥{diff:,} 高い")

        time.sleep(3)  # サーバー負荷対策

    save_prices(prices)
    print(f"\n✅ チェック完了 - 価格履歴を保存しました")

if __name__ == "__main__":
    main()
