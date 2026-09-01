import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from statsmodels.tsa.stattools import adfuller
import quantstats_lumi as qs
import math

def plot_etf_trade(etf_tick_min_df, stock_minute_df, stock_list, etf_code, date):
        """
        ETF 누적 매수체결과 구성종목별 누적 등락률을 시각화하는 함수 
        :param etf_tick_min_df: ETF 분봉 데이터프레임 (time, etf_code, accumulated_buy_initiated)
        :param stock_minute_df: 종목별 분봉 데이터프레임 (time, stock_code, price, open)
        :param stock_list: 분석할 종목 코드 리스트
        :param etf_code: 분석할 ETF 코드
        :param date: 분석할 날짜 (YYYYMMDD 형식)
        """

        # 1. ETF tick - 09:00~15:30 필터링 (resampled_time 기준)
        etf_day = etf_tick_min_df[
            (etf_tick_min_df['resampled_time'] >= pd.Timestamp(f"{date} 09:00", tz='Asia/Seoul')) &
            (etf_tick_min_df['resampled_time'] <= pd.Timestamp(f"{date} 15:30", tz='Asia/Seoul')) &
            (etf_tick_min_df['etf_code'] == etf_code)
        ].copy()

        # 2. 종목 분봉 - 3/19 09:00~15:30 필터링
        stock_day = stock_minute_df[
            (stock_minute_df['time'] >= pd.Timestamp(f"{date} 09:00", tz='Asia/Seoul')) &
            (stock_minute_df['time'] <= pd.Timestamp(f"{date} 15:30", tz='Asia/Seoul')) &
            (stock_minute_df['stock_code'].isin(stock_list))
        ].copy()

        # 3. 종목별 09시 시가 기준 누적 등락률
        open_price = stock_day[stock_day['time'] == pd.Timestamp(f"{date} 09:00", tz='Asia/Seoul')]\
            .set_index('stock_code')['open']

        stock_day['cum_return'] = stock_day.apply(
            lambda x: (x['price'] - open_price.get(x['stock_code'], x['open'])) / open_price.get(x['stock_code'], x['open']),
            axis=1
        )

        # 4. 플롯
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # accumulated_buy_initiated
        fig.add_trace(
            go.Scatter(
                x=etf_day['resampled_time'], y=etf_day['accumulated_buy_initiated'],
                name='ETF 누적 매수 체결',
                line=dict(color='royalblue', width=2)
            ),
            secondary_y=False
        )

        # 종목별 누적 등락률    
        colors = ['tomato', 'orange', 'green', 'purple', 'pink', 'brown']
        for i, code in enumerate(stock_list):
            d = stock_day[stock_day['stock_code'] == code]
            fig.add_trace(
                go.Scatter(
                    x=d['time'], y=d['cum_return'],
                    name=code,
                    line=dict(color=colors[i % len(colors)], width=1, dash='dot')
                ),
                secondary_y=True
            )

        fig.update_layout(
            title=f'{etf_code} ETF 누적 매수체결 vs 구성종목 누적 등락률 ({date})',
            template='plotly_dark',
            height=600,
            xaxis_title='시간'
        )
        fig.update_yaxes(title_text='ETF 누적 매수체결', secondary_y=False)
        fig.update_yaxes(title_text=' 구성종목 누적 등락률', secondary_y=True)
        # 0 기준선 추가
        fig.add_hline(y=0, secondary_y=True, line=dict(color='white', width=1, dash='dash'))
        return fig

def plot_etf_correlation(etf_tick_min_df, stock_minute_df, stock_list, etf_code, date, window=20, lags=range(-10, 11)):

    
    # 데이터 필터링 (resampled_time 기준으로 필터링/인덱싱 → stock 분봉 time과 정렬됨)
    etf_day = etf_tick_min_df[
        (etf_tick_min_df['resampled_time'] >= pd.Timestamp(f"{date} 09:00", tz='Asia/Seoul')) &
        (etf_tick_min_df['resampled_time'] <= pd.Timestamp(f"{date} 15:30", tz='Asia/Seoul')) &
        (etf_tick_min_df['etf_code'] == etf_code)
    ].set_index('resampled_time')['accumulated_buy_initiated']

    stock_day = stock_minute_df[
        (stock_minute_df['time'] >= pd.Timestamp(f"{date} 09:00", tz='Asia/Seoul')) &
        (stock_minute_df['time'] <= pd.Timestamp(f"{date} 15:30", tz='Asia/Seoul')) &
        (stock_minute_df['stock_code'].isin(stock_list))
    ].copy()

    open_price = stock_day[stock_day['time'] == pd.Timestamp(f"{date} 09:00", tz='Asia/Seoul')]\
        .set_index('stock_code')['open']
    stock_day['cum_return'] = stock_day.apply(
        lambda x: (x['price'] - open_price.get(x['stock_code'], x['open'])) / open_price.get(x['stock_code'], x['open']),
        axis=1
    )

    colors = ['tomato', 'orange', 'green', 'purple', 'pink', 'brown', 'cyan', 'magenta', 'yellow', 'white']

    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=['Rolling Correlation (window=20min)', 'Lagged Correlation'],
        vertical_spacing=0.15
    )

    for i, code in enumerate(stock_list):
        stock_series = stock_day[stock_day['stock_code'] == code].set_index('time')['cum_return']
        merged = pd.concat([etf_day, stock_series], axis=1).dropna()
        merged.columns = ['etf', 'stock']

        # Rolling Correlation
        rolling_corr = merged['etf'].rolling(window).corr(merged['stock'])
        fig.add_trace(
            go.Scatter(x=rolling_corr.index, y=rolling_corr.values, name=f'{code}',
                      legendgroup=code,
                      line=dict(color=colors[i % len(colors)], width=1)),
            row=1, col=1
        )

        # Lagged Correlation
        lag_corrs = [merged['etf'].corr(merged['stock'].shift(lag)) for lag in lags]
        fig.add_trace(
            go.Scatter(x=list(lags), y=lag_corrs, name=f'{code}',
                      legendgroup=code,
                      line=dict(color=colors[i % len(colors)], width=1),
                      showlegend=False),
            row=2, col=1
        )
    fig.add_hline(y=0, row=1, col=1, line=dict(color='white', width=1, dash='dash'))
    fig.add_hline(y=0, row=2, col=1, line=dict(color='white', width=1, dash='dash'))
    fig.add_vline(x=0, row=2, col=1, line=dict(color='white', width=1, dash='dash'))

    fig.update_layout(
        title=f'{etf_code} ETF vs 구성종목 상관관계 ({date})',
        template='plotly_dark',
        height=800,
    )
    fig.update_xaxes(title_text='시간', row=1, col=1)
    fig.update_xaxes(title_text='Lag (분) - 음수: 종목 선행, 양수: ETF 선행', row=2, col=1)
    fig.update_yaxes(title_text='Correlation', row=1, col=1)
    fig.update_yaxes(title_text='Correlation', row=2, col=1)

    return fig

def make_bar(fig, df, col, color_pos, color_neg, row, col_, fmt):
    if df.empty:
        return
    labels = [name if pd.notna(name) else code for name, code in zip(df['구성종목명'], df.index)]
    values = df[col].tolist()
    colors = [color_pos if pd.notna(v) and v >= 0 else color_neg for v in values]
    text   = [fmt(v) if pd.notna(v) else '' for v in values]
    fig.add_trace(
        go.Bar(x=labels, y=values, marker_color=colors, text=text,
               textposition='outside', showlegend=False),
        row=row, col=col_
    )

def plot_etf_changes(records, etf_code):
    for r in records:
        new_in, new_out = r['new_in'], r['new_out']
        w_inc,  w_dec   = r['weight_increase'], r['weight_decrease']

        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=[
                f'신규 편입 ({len(new_in)}종목)',  f'신규 편출 ({len(new_out)}종목)',
                f'비중 증가 ({len(w_inc)}종목)',    f'비중 축소 ({len(w_dec)}종목)',
            ],
            vertical_spacing=0.18, horizontal_spacing=0.12,
        )

        pct  = lambda v: f'{v:.2%}'        # 당일 수익률: 소수 → %
        pp   = lambda v: f'{v:+.2f}%p'    # 비중변화: 이미 %p 단위

        make_bar(fig, new_in,  '당일 수익률', 'tomato', 'royalblue', 1, 1, pct)
        make_bar(fig, new_out, '당일 수익률', 'tomato', 'royalblue', 1, 2, pct)
        make_bar(fig, w_inc,   '비중변화',    'tomato', 'royalblue', 2, 1, pp)
        make_bar(fig, w_dec,   '비중변화',    'tomato', 'royalblue', 2, 2, pp)

        fig.update_layout(
            title=f'{etf_code}  1행: 편출입 당일수익률 2행: 비중변화  |  {r["date"]}',
            template='plotly_dark', height=700,
        )
        fig.update_yaxes(tickformat='.2%', row=1, col=1)
        fig.update_yaxes(tickformat='.2%', row=1, col=2)
        fig.show()

def get_etf_changes(market_df, etf_code):
    """
    특정 ETF에 대해 편출입 및 비중변화 종목을 분석하는 함수
    """
    df = market_df[market_df['etf_code'] == etf_code].copy()
    df['date'] = df['time'].dt.tz_convert('Asia/Seoul').dt.date
    dates = sorted(df['date'].unique())

    records = []
    for prev_d, curr_d in zip(dates[:-1], dates[1:]):
        prev = df[df['date'] == prev_d].set_index('종목코드')
        curr = df[df['date'] == curr_d].set_index('종목코드')

        prev_set, curr_set = set(prev.index), set(curr.index)

        # 신규 편출/ 편입 종목
        new_in  = curr.loc[list(curr_set - prev_set), ['구성종목명', '비중', '당일 수익률']]
        new_out = prev.loc[list(prev_set - curr_set), ['구성종목명', '비중', '당일 수익률']]

        # 비중 증가/ 축소는 가격이 올라서 있는 경우도 포함되므로 전일자 PDF CU당 수량과 비교
        common = list(prev_set & curr_set)
        weight_diff = (curr.loc[common, '비중'] - prev.loc[common, '비중']).rename('비중변화')
        weight_chg = curr.loc[common, ['구성종목명', '비중', '당일 수익률']].join(weight_diff)
        weight_chg = weight_chg[weight_chg['비중변화'] != 0].sort_values('비중변화')

        pdf_diff= (curr.loc[common, 'shares'] - prev.loc[common, 'shares']).rename('pdf_shares_chg')
        pdf_chg = curr.loc[common, ['구성종목명', 'shares', '당일 수익률']].join(pdf_diff)



        records.append({
            'date': f"{prev_d} → {curr_d}",
            'new_in':  new_in.sort_values('당일 수익률', ascending=False),
            'new_out': new_out.sort_values('당일 수익률', ascending=False),
            'weight_increase': weight_chg[(weight_chg['비중변화'] > 0) & (pdf_chg['pdf_shares_chg'] > 0)].sort_values('비중변화', ascending=False),
            'weight_decrease': weight_chg[(weight_chg['비중변화'] < 0) & (pdf_chg['pdf_shares_chg'] < 0)],
        })
    return records

def check_stationarity(series, window, pval_threshold=0.1):
    """
    주어진 series 에 대해 rolling ADF 검정을 수행하여 각 시점에서 정상성 여부를 판단하는 함수
    """
    # 1. Rolling ADF p-value
    rolling_adf_pval = series.rolling(window).apply(
        lambda x: adfuller(x, autolag='AIC')[1], raw=True
    )
    is_stationary = rolling_adf_pval < pval_threshold
    return is_stationary

def check_correlation(series1, series2, window):
    """
    주어진 두 series 간의 rolling 상관관계를 계산하는 함수
    """
    # 2. Rolling correlation
    rolling_corr = series1.rolling(window).corr(series2)
    corr_std  = rolling_corr.rolling(window).std()
    corr_upper = rolling_corr + 2 * corr_std
    corr_lower = rolling_corr - 2 * corr_std

    return (rolling_corr >= corr_lower , rolling_corr, corr_upper, corr_lower)

def generate_mr_signal(regime, spread, window):

    rolling_mean = spread.rolling(window).mean()
    rolling_std  = spread.rolling(window).std()
    spread_upper = rolling_mean + 2 * rolling_std
    spread_lower = rolling_mean - 2 * rolling_std

    # 6. 상태 기반 시그널 (진입 + exit)
    mr_signal = pd.Series(0, index=spread.index)
    position = 0

    # 평균 회귀 전략 : stationary하고 단기 correlation이 무너지지 않을때 밴드2std/-2std 돌파 시 진입, 롤링 평균 회귀 시 청산
    for i in range(len(spread)):
        if not regime.iloc[i]:
            position = 0
        elif position == 0:
            if spread.iloc[i] > spread_upper.iloc[i]:
                position = -1   # 보통주 숏, 우선주 롱
            elif spread.iloc[i] < spread_lower.iloc[i]:
                position = 1    # 보통주 롱, 우선주 숏
        elif position == -1:
            if spread.iloc[i] < rolling_mean.iloc[i]:   # rolling mean 도달 시 청산
                position = 0
        elif position == 1:
            if spread.iloc[i] > rolling_mean.iloc[i]:   # rolling mean 도달 시 청산
                position = 0
        mr_signal.iloc[i] = position

    return (mr_signal, rolling_mean, spread_upper, spread_lower)

def minus_transaction_cost( pos, tc_rate=0.002):
    pos_diff = pos.diff().abs().fillna(0)
    transaction_cost = pos_diff * tc_rate
    return transaction_cost

def minus_borrowing_cost(pos, borrow_rate=0.0003):
    """
    숏 레그 대여수수료 차감
    - pos=+1: preferred 숏 → 해당 일 borrow_rate/365 차감
    - pos=-1: common 숏 → 해당 일 borrow_rate/365 차감
    - pos=0: 포지션 없음 → 0
    """
    daily_borrow_cost = borrow_rate / 365
    borrowing_cost = pos.abs() * daily_borrow_cost
    return borrowing_cost

def performance_statistics(returns: pd.Series, freq: int = 252):
    """
    Parameters
    ----------
    returns : pd.Series (일별 단순 수익률)
    freq    : 연간 거래일 수 (기본 252)
    """

    # ── 기본 지표 ──────────────────────────────────────────
    cum_returns = (1 + returns).cumprod() # 추후 MDD 계산에 활용
    
    ann_return  = qs.stats.cagr(returns, periods=freq)
    ann_vol     = qs.stats.volatility(returns, periods=freq)
    sharpe      = qs.stats.sharpe(returns, periods=freq)
    var         = qs.stats.var(returns)
    cvar        = qs.stats.cvar(returns)


    # ── MDD ────────────────────────────────────────────────
    # rolling_max     = cum_returns.cummax()
    # drawdown        = (cum_returns - rolling_max) / rolling_max
    mdd             = qs.stats.max_drawdown(cum_returns)
    dd            = qs.stats.to_drawdown_series(returns)
    recovery_factor = qs.stats.recovery_factor(returns) # MDD 대비 누적 수익률

    # # MDD 회복 기간
    dd_details = qs.stats.drawdown_details(dd)
    max_dd = dd_details['max drawdown'].idxmin()
    recovery_days = dd_details.loc[max_dd, 'days'] # MDD 회복 기간 (일 단위)



    return {
        'ann_return'    : ann_return,
        'ann_vol'       : ann_vol,
        'sharpe'        : sharpe,
        'var'           : var,
        'cvar'          : cvar,
        'mdd'           : mdd,
        'recovery_days' : recovery_days,
        'recovery_factor' : recovery_factor
    }

def ceil_to_tick(price: float) -> int:
    """
    호가가격단위 기준 절상.
    KOSPI/KOSDAQ 동일 기준 (넥스트레이드 제외).
    """
    if price < 2000:        tick = 1
    elif price < 5000:      tick = 5
    elif price < 20000:     tick = 10
    elif price < 50000:     tick = 50
    elif price < 100000:    tick = 100
    elif price < 200000:    tick = 100
    elif price < 500000:    tick = 500
    else:                   tick = 1000

    return int(math.ceil(price / tick) * tick)

def etf_ceil_to_tick(price: float) -> int:
    """
    ETF 호가가격단위 기준 절상.
    2천원 미만: 1원, 2천원 이상: 5원
    """
    tick = 1 if price < 2000 else 5
    return int(math.ceil(price / tick) * tick)


def _to_num(x):
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int,float,np.number)):
        return float(x)
    
    s = str(x).strip()
    if s in {"","-"}:
        return np.nan
    return pd.to_numeric(s.replace(",",""), errors='coerce')
