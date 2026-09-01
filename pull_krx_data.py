import requests
from pykrx.website.comm import webio
from pykrx.website.krx import etx
from pykrx import stock
import pandas as pd
from settings import config 

KRX_ID = config("KRX_ID")
KRX_PW = config("KRX_PW")

# 1. 공유 세션 생성 및 pykrx에 주입
_session = requests.Session()

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

_ORIGIN = "https://data.krx.co.kr"

# ETF PDF/구성종목 메뉴 referer
_ETF_PDF_REFERER = "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201030108"


def _merge_headers(base, extra):
    h = {}
    if base:
        h.update(base)
    h.update(extra)
    return h


def _session_post_read(self, **params):
    headers = dict(getattr(self, "headers", {}) or {})

    # KRX JSON 엔드포인트일 때 ETF PDF 메뉴 context 강제 주입
    if "data.krx.co.kr/comm/bldAttendant/getJsonData.cmd" in self.url:
        headers = _merge_headers(headers, {
            "User-Agent": _UA,
            "Origin": _ORIGIN,
            "Referer": _ETF_PDF_REFERER,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        })
    else:
        headers = _merge_headers(headers, {
            "User-Agent": _UA,
        })

    return _session.post(self.url, headers=headers, data=params, timeout=15)


def _session_get_read(self, **params):
    headers = dict(getattr(self, "headers", {}) or {})
    headers = _merge_headers(headers, {
        "User-Agent": _UA,
    })
    return _session.get(self.url, headers=headers, params=params, timeout=15)


webio.Post.read = _session_post_read
webio.Get.read = _session_get_read


def warmup_etf_pdf_menu():
    """
    ETF PDF 메뉴 페이지를 한 번 열어
    mdc.client_session 같은 쿠키/컨텍스트를 맞춤
    """
    _session.get(
        _ETF_PDF_REFERER,
        headers={
            "User-Agent": _UA,
            "Referer": _ETF_PDF_REFERER,
        },
        timeout=15,
    )


def login_krx(login_id: str, login_pw: str) -> bool:
    """
    KRX data.krx.co.kr 로그인 후 세션 쿠키(JSESSIONID)를 갱신합니다.
    """
    _LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
    _LOGIN_JSP  = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
    _LOGIN_URL  = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"

    # 초기 세션 발급
    _session.get(_LOGIN_PAGE, headers={"User-Agent": _UA}, timeout=15)
    _session.get(_LOGIN_JSP, headers={"User-Agent": _UA, "Referer": _LOGIN_PAGE}, timeout=15)

    payload = {
        "mbrNm": "", "telNo": "", "di": "", "certType": "",
        "mbrId": login_id, "pw": login_pw,
    }
    headers = {"User-Agent": _UA, "Referer": _LOGIN_PAGE}

    # 로그인 POST
    resp = _session.post(_LOGIN_URL, data=payload, headers=headers, timeout=15)
    data = resp.json()
    error_code = data.get("_error_code", "")

    # CD011 중복 로그인 처리
    if error_code == "CD011":
        payload["skipDup"] = "Y"
        resp = _session.post(_LOGIN_URL, data=payload, headers=headers, timeout=15)
        data = resp.json()
        error_code = data.get("_error_code", "")

    ok = (error_code == "CD001")

    # 로그인 성공 시 ETF 메뉴 워밍업
    if ok:
        warmup_etf_pdf_menu()

    return ok


def pull_etf_pdf(date, code):
    # 꽤 오래걸림
    # 혹시 세션이 약하면 한 번 더 워밍업

    login_krx(KRX_ID, KRX_PW)

    pdf = etx.get_etf_portfolio_deposit_file(date, code)
    if pdf is None or pdf.empty:
        return pdf
    pdf.reset_index(inplace=True)
    pdf["PDF 적용일자"] = date
    pdf["ETF 코드"] = code
    pdf.rename(columns={"티커": "종목코드"}, inplace=True)
    pdf = pdf[["PDF 적용일자", "ETF 코드", "종목코드", "구성종목명", "계약수", "비중"]]
    pdf['PDF 적용일자'] = pd.to_datetime(pdf['PDF 적용일자'], format="%Y%m%d")
    return pdf

if __name__ == "__main__":
    print("script started")
    print(pull_etf_pdf("20260310", "0163Y0"))
    print(stock.get_market_ohlcv('20251022',market='KOSDAQ'))