import numpy as np
import pandas as pd
import xlwings as xw
from pykrx.stock import stock_api
from scipy.stats import norm

from pull_krx_data import login_krx
from settings import config
from utils import ceil_to_tick
import exchange_calendars as ecals

xkrx = ecals.get_calendar("XKRX")

KRX_ID = config("KRX_ID")
KRX_PW = config("KRX_PW")
login_krx(KRX_ID, KRX_PW)  # KRX 로그인

PRICE_CACHE = {}


def get_prices(stock_code, end_dt, days=200):
    key = (stock_code, pd.Timestamp(end_dt).normalize(), days)

    if key in PRICE_CACHE:
        return PRICE_CACHE[key]

    start_dt = pd.Timestamp(end_dt) - pd.Timedelta(days=days)

    prices = stock_api.get_market_ohlcv_by_date(
        start_dt, end_dt, stock_code, adjusted=False
    )

    PRICE_CACHE[key] = prices
    return prices


@xw.func
def calc_vol(caller):
    # 변동성 계산 로직을 여기에 작성

    stock_code = caller.sheet.range("C2").value  # 주식 코드
    end_dt = caller.sheet.range("G2").value  # 오늘 날짜

    # KRX에서 unadjusted 가격을 가져와서 변동성 계산
    prices = get_prices(stock_code, end_dt)
    vol = np.std(prices["등락률"] / 100) * np.sqrt(252)

    return vol

def _calc_base_price(prices, ref_dt, discount, capital_increase_ratio, face_value, market_code):
    """
    1,2차 발행가액을 계산하는 공통 helper 함수
    
    """
    ref_dt = pd.to_datetime(ref_dt)
    mon_start  = ref_dt - pd.DateOffset(months=1) + pd.Timedelta(days=1)
    week_start = ref_dt - pd.DateOffset(weeks=1)  + pd.Timedelta(days=1)
    # 1개월 가중평균주가계산
    mon_wp = ceil_to_tick(prices.loc[mon_start:ref_dt]['거래대금'].sum() /
                          prices.loc[mon_start:ref_dt]['거래량'].sum())
    # 1주일 가중평균주가계산
    week_wp = ceil_to_tick(prices.loc[week_start:ref_dt]['거래대금'].sum() /
                           prices.loc[week_start:ref_dt]['거래량'].sum())
    if market_code == "KOSPI":
        # 기산일 종가
        close = prices.loc[:ref_dt]['종가'].iloc[-1]
    else: # KOSDAQ
        close = ceil_to_tick(prices.loc[ref_dt]['거래대금'].sum() /
                           prices.loc[ref_dt]['거래량'].sum())

    base = min(np.mean([mon_wp, week_wp, close]), close)
    result = ceil_to_tick((base * (1 - discount)) / (1 + (capital_increase_ratio * discount)))
    return max(result, face_value)  # 액면가 미만 방지


@xw.func(volatile=True) # 셀이 바뀌면 자동으로 재계산
def calc_issue_price(caller):
    today      = pd.to_datetime(caller.sheet.range("G2").value)
    market_code = caller.sheet.range("C1").value
    stock_code = caller.sheet.range("C2").value

    first_fix_dt  = pd.to_datetime(caller.sheet.range("B9").value) # 1차 발행가액 확정일
    second_fix_dt = pd.to_datetime(caller.sheet.range("B13").value) # 2차 발행가액 확정일
    final_fix_dt  = pd.to_datetime(caller.sheet.range("B14").value) # 최종 발행가액 확정일 

    face_value             = caller.sheet.range("G5").value # 액면가
    capital_increase_ratio = caller.sheet.range("G11").value # 자본증자비율
    first_fix_discount     = caller.sheet.range("G15").value # 1차 발행가액 할인율
    second_fix_discount    = caller.sheet.range("G16").value # 2차 발행가액 할인율
    final_fix_discount     = caller.sheet.range("G17").value # 최종 발행가액 할인율

    # final_fix_dt 이후도 커버하도록 충분한 범위로 한 번만 fetch
    prices = get_prices(stock_code, max(today, final_fix_dt), days=400)

    if today <= first_fix_dt:
        # 1차 확정 전: today 기준 추정 (first_fix_dt 데이터 없을 수 있음)
        return _calc_base_price(prices, today, first_fix_discount, capital_increase_ratio, face_value, market_code)

    # 이 아래부터는 first_fix_dt가 과거 → 가격 데이터 존재
    first_issue_price = _calc_base_price(prices, first_fix_dt, first_fix_discount, capital_increase_ratio, face_value, market_code)

    if today < second_fix_dt:
        # 1차 확정 후 ~ 2차 확정 전: 1차 픽스 / 2차 today 기준 추정
        second_est = _calc_base_price(prices, today, second_fix_discount, capital_increase_ratio, face_value, market_code)
        return min(second_est, first_issue_price)

    # 이 아래부터는 second_fix_dt도 과거 → 가격 데이터 존재
    second_issue_price = _calc_base_price(prices, second_fix_dt, second_fix_discount, capital_increase_ratio, face_value, market_code)

    if today <= final_fix_dt:
        # 2차 확정 후 ~ 최종 확정 전: 1차·2차 픽스 / 최종 today 기준 추정
        calc_day  = prices.loc[today - pd.DateOffset(days=5) : today - pd.DateOffset(days=3)]
        day_wp    = ceil_to_tick(calc_day['거래대금'].sum() / calc_day['거래량'].sum())
        final_est = ceil_to_tick(day_wp * (1 - final_fix_discount))
        return max(min(first_issue_price, second_issue_price), final_est)

    else:
        # 최종 확정 후: 모두 픽스
        calc_day      = prices.loc[final_fix_dt - pd.DateOffset(days=5) : final_fix_dt - pd.DateOffset(days=3)]
        day_wp        = ceil_to_tick(calc_day['거래대금'].sum() / calc_day['거래량'].sum())
        final_issue_price = ceil_to_tick(day_wp * (1 - final_fix_discount))
        return max(min(first_issue_price, second_issue_price), final_issue_price)
    

@xw.func
def update_dates(pre_dates = 5):
    # 신주인수권 증권은 일반적으로 5영업일 거래되나 그 이상도 가능

    ws = xw.Book.caller().sheets.active
    
    filing_effective_start = ws.range("B8").value # 증권신고서 제출일
    preemptive_right_start = ws.range("B12").value # 신주인수권 거래 시작일
    record_date            = ws.range("B11").value # 배정 기준일
    list_end = ws.range("C16").value # 신주 상장 예정일
    
    ws.range("C8").value = xkrx.sessions_window(filing_effective_start, 11)[-1].strftime("%Y-%m-%d") # 증권신고서 효력발생일 (신고서 제출일로부터 10영업일째)
    ws.range("C12").value = xkrx.sessions_window(preemptive_right_start, pre_dates)[-1].strftime("%Y-%m-%d") # 신주인수권 거래 시작일로부터 5영업일째(마지막 날)
    ws.range("B16").value = xkrx.sessions_window(list_end, -3)[0].strftime("%Y-%m-%d") # 신주 상장 예정일 2영업일 전 (권리 매도 가능)
    ws.range("B10").value = xkrx.sessions_window(record_date, -2)[0].strftime("%Y-%m-%d") # 권리락일


@xw.func  # 엑셀 UDF로 등록
def bs_warrant(S, K, r, sigma, T):
    """
    신주인수권 블랙숄즈 가격
    S: 현물가격
    K: 1차 발행가액
    r: 무위험이자율
    sigma: 연간변동성
    T: 만기(년)
    """
    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    C = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return C

def _apply_dividend(S, r, record_date, dividend_amount, today):
    """배당 할인 적용 (내부 helper)"""
    if pd.notna(record_date) and pd.notna(dividend_amount):
        dividend_time = (pd.to_datetime(record_date) - pd.to_datetime(today)).days / 365
        S -= dividend_amount * np.exp(-r * dividend_time)
    return S


@xw.func(volatile=True)
def bs_discrete_dividend(S, K, r, sigma, T, caller):
    """배당이 있는 경우 신주인수권 블랙숄즈 가격"""
    record_date     = caller.sheet.range("B20").value
    dividend_amount = caller.sheet.range("D20").value
    today           = caller.sheet.range("G2").value

    S = _apply_dividend(S, r, record_date, dividend_amount, today)
    return bs_warrant(S, K, r, sigma, T)


@xw.func(volatile=True)
def bs_warrant_diluted(S, K, r, sigma, T, capital_increase_rate, caller):
    """희석효과 + 배당 반영"""
    record_date     = caller.sheet.range("B20").value
    dividend_amount = caller.sheet.range("D20").value
    today           = caller.sheet.range("G2").value

    S = _apply_dividend(S, r, record_date, dividend_amount, today)
    C = bs_warrant(S, K, r, sigma, T)
    return C / (1 + capital_increase_rate)


if __name__ == "__main__":
    # p = get_prices('009830','20260331')
    # print(p)
    
    xw.serve()
