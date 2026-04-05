import os
import json
import requests
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# Polygon / Quickswap / LGNS-DAI 대표 풀
CHAIN_ID = "polygon"
PAIR_ADDRESS = "0x882df4b0fb50a229c3b4124eb18c759911485bfb"

PAIR_URL = f"https://api.dexscreener.com/latest/dex/pairs/{CHAIN_ID}/{PAIR_ADDRESS}"
STATE_FILE = "state.json"

KST = timezone(timedelta(hours=9))


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def pct_change(current, previous):
    if previous in (None, 0):
        return None
    return ((current - previous) / previous) * 100.0


def load_previous_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_pair():
    resp = requests.get(PAIR_URL, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    pairs = data.get("pairs") or []
    if not pairs:
        raise RuntimeError("DexScreener에서 페어 데이터를 찾지 못했습니다.")

    return pairs[0]


def format_usd(value):
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:.2f}"


def format_pct(value):
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def score_liquidity(liquidity_usd):
    if liquidity_usd >= 300_000_000:
        return 0, "유동성 매우 큼"
    elif liquidity_usd >= 100_000_000:
        return 1, "유동성 양호"
    else:
        return 2, "유동성 낮음"


def score_liquidity_change(liq_change_pct):
    if liq_change_pct is None:
        return 0, "유동성 변화 비교 데이터 없음"
    if liq_change_pct <= -3:
        return 2, "유동성 감소 강함"
    elif liq_change_pct <= -1:
        return 1, "유동성 소폭 감소"
    else:
        return 0, "유동성 변화 안정"


def score_volume(volume_24h):
    if volume_24h >= 20_000_000:
        return 0, "24시간 거래량 높음"
    elif volume_24h >= 5_000_000:
        return 1, "24시간 거래량 보통"
    else:
        return 2, "24시간 거래량 약함"


def score_volume_change(vol_change_pct):
    if vol_change_pct is None:
        return 0, "거래량 변화 비교 데이터 없음"
    if vol_change_pct <= -30:
        return 2, "거래량 감소 강함"
    elif vol_change_pct <= -10:
        return 1, "거래량 소폭 감소"
    else:
        return 0, "거래량 변화 안정"


def score_price_change(price_change_24h):
    abs_change = abs(price_change_24h)
    if abs_change < 5:
        return 0, "가격 변동 안정"
    elif abs_change < 15:
        return 1, "가격 변동 주의"
    else:
        return 2, "가격 변동 큼"


def score_sell_ratio(buys_24h, sells_24h):
    total = buys_24h + sells_24h
    if total == 0:
        return 2, 0.0, "거래 건수 부족"

    sell_ratio = sells_24h / total
    if sell_ratio > 0.65:
        return 2, sell_ratio, "매도 비중 높음"
    elif sell_ratio > 0.55:
        return 1, sell_ratio, "매도 우세"
    else:
        return 0, sell_ratio, "매수/매도 균형 무난"


def classify(total_score):
    if total_score <= 2:
        return "🟢 유지", "기존 보유자는 추세 관찰"
    elif total_score <= 5:
        return "🟡 주의", "부분 출금 또는 원금 회수 검토"
    else:
        return "🔴 위험", "신규 진입 보수적 접근, 출금 우선 검토"


def build_report(pair, previous_state):
    base = pair.get("baseToken", {})
    quote = pair.get("quoteToken", {})
    chain_id = pair.get("chainId", "-")
    dex_id = pair.get("dexId", "-")
    price_usd = safe_float(pair.get("priceUsd"))
    liquidity_usd = safe_float((pair.get("liquidity") or {}).get("usd"))
    volume_24h = safe_float((pair.get("volume") or {}).get("h24"))
    price_change_24h = safe_float((pair.get("priceChange") or {}).get("h24"))

    txns_24h = (pair.get("txns") or {}).get("h24") or {}
    buys_24h = int(txns_24h.get("buys") or 0)
    sells_24h = int(txns_24h.get("sells") or 0)

    prev_liquidity = previous_state.get("liquidity_usd") if previous_state else None
    prev_volume = previous_state.get("volume_24h") if previous_state else None

    liquidity_change_pct = pct_change(liquidity_usd, prev_liquidity)
    volume_change_pct = pct_change(volume_24h, prev_volume)

    s1, r1 = score_liquidity(liquidity_usd)
    s2, r2 = score_liquidity_change(liquidity_change_pct)
    s3, r3 = score_volume(volume_24h)
    s4, r4 = score_volume_change(volume_change_pct)
    s5, r5 = score_price_change(price_change_24h)
    s6, sell_ratio, r6 = score_sell_ratio(buys_24h, sells_24h)

    total_score = s1 + s2 + s3 + s4 + s5 + s6
    status, action = classify(total_score)

    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "📊 LGNS 업그레이드 자동 분석 리포트",
        f"⏰ KST: {now_kst}",
        "",
        f"체인: {chain_id}",
        f"DEX: {dex_id}",
        f"페어: {base.get('symbol', '?')}/{quote.get('symbol', '?')}",
        f"가격: ${price_usd:.6f}",
        f"유동성: {format_usd(liquidity_usd)}",
        f"유동성 변화: {format_pct(liquidity_change_pct)}",
        f"24시간 거래량: {format_usd(volume_24h)}",
        f"거래량 변화: {format_pct(volume_change_pct)}",
        f"24시간 가격변동: {price_change_24h:.2f}%",
        f"24시간 매수/매도: {buys_24h}/{sells_24h}",
        f"매도 비율: {sell_ratio * 100:.2f}%",
        "",
        f"신호: {status}",
        f"점수: {total_score}",
        f"판단: {action}",
        "",
        "근거:",
        f"- {r1} ({s1}점)",
        f"- {r2} ({s2}점)",
        f"- {r3} ({s3}점)",
        f"- {r4} ({s4}점)",
        f"- {r5} ({s5}점)",
        f"- {r6} ({s6}점)",
    ]

    return "\n".join(lines), {
        "timestamp": now_kst,
        "liquidity_usd": liquidity_usd,
        "volume_24h": volume_24h
    }


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, data=payload, timeout=20)
    resp.raise_for_status()


def main():
    try:
        pair = fetch_pair()
        previous_state = load_previous_state()
        report, new_state = build_report(pair, previous_state)
        save_state(new_state)
    except Exception as e:
        report = f"❌ LGNS 분석 실패\n오류: {e}"

    send_telegram(report)


if __name__ == "__main__":
    main()
