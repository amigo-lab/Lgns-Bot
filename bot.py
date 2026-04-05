import os
import math
import requests
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# 기준 풀: Polygon / Quickswap / LGNS-DAI
TARGET_PAIR_ADDRESS = "0x882df4b0fb50a229c3b4124eb18c759911485bfb"
DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search?q=LGNS/DAI"

KST = timezone(timedelta(hours=9))


def fetch_pair():
    resp = requests.get(DEX_SEARCH_URL, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    pairs = data.get("pairs", [])
    if not pairs:
        raise RuntimeError("DexScreener에서 LGNS/DAI 페어를 찾지 못했습니다.")

    # 1순위: 지정한 pair address 정확히 일치
    for p in pairs:
        if str(p.get("pairAddress", "")).lower() == TARGET_PAIR_ADDRESS.lower():
            return p

    # 2순위: polygon + quickswap 조합 우선
    polygon_quickswap = []
    for p in pairs:
        chain_id = str(p.get("chainId", "")).lower()
        dex_id = str(p.get("dexId", "")).lower()
        if chain_id == "polygon" and "quick" in dex_id:
            polygon_quickswap.append(p)

    if polygon_quickswap:
        polygon_quickswap.sort(
            key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0),
            reverse=True,
        )
        return polygon_quickswap[0]

    # 3순위: 유동성 가장 큰 페어
    pairs.sort(
        key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0),
        reverse=True,
    )
    return pairs[0]


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def classify_signal(liquidity_usd, volume_24h, price_change_24h, buys_24h, sells_24h):
    score = 0
    reasons = []

    # 1) 유동성
    if liquidity_usd >= 300_000_000:
        reasons.append("유동성 매우 큼")
    elif liquidity_usd >= 100_000_000:
        score += 1
        reasons.append("유동성 양호")
    else:
        score += 2
        reasons.append("유동성 낮음")

    # 2) 거래량
    if volume_24h >= 20_000_000:
        reasons.append("24시간 거래량 높음")
    elif volume_24h >= 5_000_000:
        score += 1
        reasons.append("24시간 거래량 보통")
    else:
        score += 2
        reasons.append("24시간 거래량 약함")

    # 3) 가격 변동성
    abs_change = abs(price_change_24h)
    if abs_change < 5:
        reasons.append("가격 변동 안정")
    elif abs_change < 15:
        score += 1
        reasons.append("가격 변동 주의")
    else:
        score += 2
        reasons.append("가격 변동 큼")

    # 4) 매수/매도 균형
    total_trades = buys_24h + sells_24h
    if total_trades > 0:
        sell_ratio = sells_24h / total_trades
        if sell_ratio > 0.65:
            score += 2
            reasons.append("매도 비중 높음")
        elif sell_ratio > 0.55:
            score += 1
            reasons.append("매도 우세")
        else:
            reasons.append("매수/매도 균형 무난")
    else:
        score += 2
        reasons.append("거래 건수 부족")

    if score <= 1:
        status = "🟢 유지"
        action = "기존 보유자는 추세 관찰"
    elif score <= 4:
        status = "🟡 주의"
        action = "부분 출금 또는 원금 회수 검토"
    else:
        status = "🔴 위험"
        action = "신규 진입 보수적 접근, 출금 우선 검토"

    return status, action, reasons, score


def format_usd(value):
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:.2f}"


def build_report(pair):
    base = pair.get("baseToken", {})
    quote = pair.get("quoteToken", {})
    pair_addr = pair.get("pairAddress", "-")
    chain_id = pair.get("chainId", "-")
    dex_id = pair.get("dexId", "-")
    price_usd = safe_float(pair.get("priceUsd"))
    liquidity_usd = safe_float((pair.get("liquidity") or {}).get("usd"))
    volume_24h = safe_float((pair.get("volume") or {}).get("h24"))
    price_change_24h = safe_float((pair.get("priceChange") or {}).get("h24"))
    txns_24h = (pair.get("txns") or {}).get("h24") or {}
    buys_24h = int(txns_24h.get("buys") or 0)
    sells_24h = int(txns_24h.get("sells") or 0)
    url = pair.get("url", "")

    status, action, reasons, score = classify_signal(
        liquidity_usd, volume_24h, price_change_24h, buys_24h, sells_24h
    )

    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "📊 LGNS 자동 분석 리포트",
        f"⏰ KST: {now_kst}",
        "",
        f"체인: {chain_id}",
        f"DEX: {dex_id}",
        f"페어: {base.get('symbol', '?')}/{quote.get('symbol', '?')}",
        f"가격: ${price_usd:.6f}",
        f"유동성: {format_usd(liquidity_usd)}",
        f"24시간 거래량: {format_usd(volume_24h)}",
        f"24시간 가격변동: {price_change_24h:.2f}%",
        f"24시간 매수/매도: {buys_24h}/{sells_24h}",
        "",
        f"신호: {status}",
        f"점수: {score}",
        f"판단: {action}",
        "",
        "근거:",
    ]

    for reason in reasons:
        lines.append(f"- {reason}")

    lines.extend([
        "",
        f"pairAddress: {pair_addr}",
    ])

    if url:
        lines.append(f"차트: {url}")

    return "\n".join(lines)


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
        report = build_report(pair)
    except Exception as e:
        report = f"❌ LGNS 분석 실패\n오류: {e}"

    send_telegram(report)


if __name__ == "__main__":
    main()
