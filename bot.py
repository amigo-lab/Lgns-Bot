import os
import json
import requests
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

CHAIN_ID = "polygon"
PAIR_ADDRESS = "0x882df4b0fb50a229c3b4124eb18c759911485bfb"

PAIR_URL = f"https://api.dexscreener.com/latest/dex/pairs/{CHAIN_ID}/{PAIR_ADDRESS}"
HISTORY_FILE = "history.json"

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


def avg(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return sum(nums) / len(nums)


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def fetch_pair():
    resp = requests.get(PAIR_URL, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    pairs = data.get("pairs") or []
    if not pairs:
        raise RuntimeError("DexScreener에서 LGNS 페어 데이터를 찾지 못했습니다.")

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


def score_liquidity_size(liquidity_usd):
    if liquidity_usd >= 300_000_000:
        return 0, "유동성 매우 큼"
    elif liquidity_usd >= 100_000_000:
        return 1, "유동성 양호"
    else:
        return 2, "유동성 낮음"


def score_volume_size(volume_24h):
    if volume_24h >= 20_000_000:
        return 0, "24시간 거래량 높음"
    elif volume_24h >= 5_000_000:
        return 1, "24시간 거래량 보통"
    else:
        return 2, "24시간 거래량 약함"


def score_price_change(price_change_24h):
    abs_change = abs(price_change_24h)
    if abs_change < 5:
        return 0, "가격 변동 안정"
    elif abs_change < 15:
        return 1, "가격 변동 주의"
    else:
        return 2, "가격 변동 큼"


def calc_sell_ratio(buys_24h, sells_24h):
    total = buys_24h + sells_24h
    if total == 0:
        return 0.0
    return sells_24h / total


def score_sell_ratio(sell_ratio):
    if sell_ratio >= 0.80:
        return 3, "매도 비율 매우 높음"
    elif sell_ratio >= 0.70:
        return 2, "매도 비중 높음"
    elif sell_ratio >= 0.55:
        return 1, "매도 우세"
    else:
        return 0, "매수/매도 균형 무난"


def score_liquidity_trend(curr_liq, history):
    if not history:
        return 0, "유동성 추세 데이터 부족", None, None

    prev_liq = history[-1].get("liquidity_usd")
    liq_change_prev = pct_change(curr_liq, prev_liq)

    recent_liqs = [h.get("liquidity_usd") for h in history[-3:] if h.get("liquidity_usd") is not None]
    liq_avg_3 = avg(recent_liqs)
    liq_change_avg = pct_change(curr_liq, liq_avg_3)

    score = 0
    reasons = []

    if liq_change_prev is not None:
        if liq_change_prev <= -5:
            score += 2
            reasons.append("직전 대비 유동성 급감")
        elif liq_change_prev <= -2:
            score += 1
            reasons.append("직전 대비 유동성 감소")
        else:
            reasons.append("직전 대비 유동성 안정")

    if liq_change_avg is not None:
        if liq_change_avg <= -5:
            score += 2
            reasons.append("3회 평균 대비 유동성 급감")
        elif liq_change_avg <= -2:
            score += 1
            reasons.append("3회 평균 대비 유동성 약화")
        else:
            reasons.append("3회 평균 대비 유동성 안정")

    score = min(score, 3)
    return score, " / ".join(reasons), liq_change_prev, liq_change_avg


def score_volume_trend(curr_vol, history):
    if not history:
        return 0, "거래량 추세 데이터 부족", None, None

    prev_vol = history[-1].get("volume_24h")
    vol_change_prev = pct_change(curr_vol, prev_vol)

    recent_vols = [h.get("volume_24h") for h in history[-3:] if h.get("volume_24h") is not None]
    vol_avg_3 = avg(recent_vols)
    vol_change_avg = pct_change(curr_vol, vol_avg_3)

    score = 0
    reasons = []

    if vol_change_prev is not None:
        if vol_change_prev <= -35:
            score += 2
            reasons.append("직전 대비 거래량 급감")
        elif vol_change_prev <= -15:
            score += 1
            reasons.append("직전 대비 거래량 감소")
        else:
            reasons.append("직전 대비 거래량 안정")

    if vol_change_avg is not None:
        if vol_change_avg <= -35:
            score += 2
            reasons.append("3회 평균 대비 거래량 급감")
        elif vol_change_avg <= -15:
            score += 1
            reasons.append("3회 평균 대비 거래량 약화")
        else:
            reasons.append("3회 평균 대비 거래량 안정")

    score = min(score, 3)
    return score, " / ".join(reasons), vol_change_prev, vol_change_avg


def score_sell_ratio_trend(curr_sell_ratio, history):
    if len(history) < 2:
        return 0, "매도 비율 연속 추세 데이터 부족"

    prev1 = history[-1].get("sell_ratio")
    prev2 = history[-2].get("sell_ratio")

    if prev1 is None or prev2 is None:
        return 0, "매도 비율 연속 추세 데이터 부족"

    if curr_sell_ratio > prev1 > prev2:
        return 2, "매도 비율 2회 연속 악화"
    elif curr_sell_ratio > prev1:
        return 1, "매도 비율 상승"
    else:
        return 0, "매도 비율 추세 안정"


def classify(total_score):
    if total_score <= 3:
        return "🟢 유지", "기존 보유자는 추세 관찰"
    elif total_score <= 7:
        return "🟡 주의", "부분 출금 또는 원금 회수 검토"
    else:
        return "🔴 위험", "신규 진입 보수적 접근, 출금 우선 검토"


def get_alert_message(price_change_24h, liq_change_ref, sell_ratio):
    if liq_change_ref is None:
        liq_change_ref = 0

    if price_change_24h <= -20 and liq_change_ref <= -5 and sell_ratio >= 0.80:
        return "🚨🚨🚨 탈출 신호: 가격 급락 + 유동성 급감 + 매도 폭증", 4, "가격 -20% 이하 + 유동성 -5% 이하 + 매도비율 80% 이상"
    elif price_change_24h <= -15 and liq_change_ref <= -3 and sell_ratio >= 0.75:
        return "🔥 긴급 경고: 가격 급락 + 유동성 감소 + 매도 심화", 3, "가격 -15% 이하 + 유동성 -3% 이하 + 매도비율 75% 이상"
    elif price_change_24h <= -10 and liq_change_ref <= -2 and sell_ratio >= 0.70:
        return "⚠️ 경고: 가격 하락 + 유동성 약화 + 매도 증가", 2, "가격 -10% 이하 + 유동성 -2% 이하 + 매도비율 70% 이상"
    elif price_change_24h <= -20:
        return "🚨 가격 단독 탈출 신호: -20% 급락", 3, "가격 -20% 이하 단독 급락"
    elif price_change_24h <= -15:
        return "🔥 가격 긴급 경고: -15% 급락", 2, "가격 -15% 이하 단독 급락"
    elif price_change_24h <= -10:
        return "⚠️ 가격 경고: -10% 급락", 1, "가격 -10% 이하 단독 급락"

    return "", 0, ""


def build_report(pair, history):
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
    sell_ratio = calc_sell_ratio(buys_24h, sells_24h)

    s1, r1 = score_liquidity_size(liquidity_usd)
    s2, r2 = score_volume_size(volume_24h)
    s3, r3 = score_price_change(price_change_24h)
    s4, r4 = score_sell_ratio(sell_ratio)
    s5, r5, liq_change_prev, liq_change_avg = score_liquidity_trend(liquidity_usd, history)
    s6, r6, vol_change_prev, vol_change_avg = score_volume_trend(volume_24h, history)
    s7, r7 = score_sell_ratio_trend(sell_ratio, history)

    liq_change_ref = liq_change_avg if liq_change_avg is not None else liq_change_prev
    alert_msg, extra_score, extra_reason = get_alert_message(price_change_24h, liq_change_ref, sell_ratio)

    total_score = s1 + s2 + s3 + s4 + s5 + s6 + s7 + extra_score
    status, action = classify(total_score)

    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    report_lines = [
        "📊 LGNS 복합위험 감지 리포트",
        f"⏰ KST: {now_kst}",
        "",
        f"체인: {chain_id}",
        f"DEX: {dex_id}",
        f"페어: {base.get('symbol', '?')}/{quote.get('symbol', '?')}",
        f"가격: ${price_usd:.6f}",
        f"유동성: {format_usd(liquidity_usd)}",
        f"직전 대비 유동성 변화: {format_pct(liq_change_prev)}",
        f"3회 평균 대비 유동성 변화: {format_pct(liq_change_avg)}",
        f"24시간 거래량: {format_usd(volume_24h)}",
        f"직전 대비 거래량 변화: {format_pct(vol_change_prev)}",
        f"3회 평균 대비 거래량 변화: {format_pct(vol_change_avg)}",
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
        f"- {r7} ({s7}점)",
    ]

    if extra_reason:
        report_lines.append(f"- 복합 경고: {extra_reason} ({extra_score}점)")

    if alert_msg:
        report_lines.insert(0, "")
        report_lines.insert(0, alert_msg)

    new_entry = {
        "timestamp": now_kst,
        "liquidity_usd": liquidity_usd,
        "volume_24h": volume_24h,
        "sell_ratio": sell_ratio
    }

    return "\n".join(report_lines), new_entry


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
        history = load_history()

        report, new_entry = build_report(pair, history)

        history.append(new_entry)
        history = history[-20:]
        save_history(history)

    except Exception as e:
        report = f"❌ LGNS 분석 실패\n오류: {e}"

    send_telegram(report)


if __name__ == "__main__":
    main()
