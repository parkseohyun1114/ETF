"""ETF 괴리율 경보기 (Streamlit)

실행:  streamlit run app.py
"""
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
from krx_api import get_key

st.set_page_config(page_title="ETF 괴리율 경보기", page_icon="🚨", layout="wide")

PRESETS = {
    "TIGER 2차전지TOP10레버리지": "412570",
    "TIGER 반도체TOP10레버리지": "488080",
    "KODEX K방산TOP10레버리지": "0100K0",
    "KODEX 200 (대조군)": "069500",
}


# ---------------------------------------------------------------- 데이터 준비
@st.cache_data(ttl=3600, show_spinner=False)
def load(_refresh_token: int, offline: bool):
    df = core.load_cache()
    if offline:   # 발표장 네트워크 장애 대비: 저장된 데이터만 사용, KRX 호출 없음
        return core.add_signals(df), [], None
    bar = st.progress(0.0, text="KRX에서 최신 거래일 확인 중…")

    def prog(i, n, d):
        bar.progress((i + 1) / max(n, 1), text=f"KRX Open API 수집 중: {d:%Y-%m-%d} ({i + 1}/{n})")

    df, got, err = core.update_cache(df, get_key(), progress=prog)
    bar.empty()
    return core.add_signals(df), got, err


if "refresh" not in st.session_state:
    st.session_state.refresh = 0
# 주소 끝에 ?offline=1 을 붙이면 처음부터 오프라인 모드
if "offline" not in st.session_state:
    st.session_state.offline = st.query_params.get("offline") == "1"
with st.spinner("데이터 준비 중…"):
    sig, got, err = load(st.session_state.refresh, st.session_state.offline)

latest = sig["일자"].max()
names = sig.sort_values("일자").groupby("종목코드")["종목명"].last()

# 경보 표에서 종목을 누르면 다음 실행 때 화면을 바꾼다 (위젯 생성 전에 상태 변경)
if "pending_code" in st.session_state:
    st.session_state.code = st.session_state.pop("pending_code")
    st.session_state.page = "종목 분석"
    st.session_state.pop("alarm_table", None)   # 선택 초기화 (경보 화면으로 돌아와도 다시 튕기지 않게)

# ---------------------------------------------------------------- 사이드바
with st.sidebar:
    st.title("🚨 ETF 괴리율 경보기")
    st.caption("KRX 공식 Open API · ETF 일별매매정보")
    page = st.radio("화면", ["오늘의 경보", "종목 분석", "검증"], key="page")
    st.toggle("오프라인 백업 모드", key="offline",
              help="KRX에 접속하지 않고 미리 저장한 데이터로만 실행해요. 발표장 인터넷이 안 될 때 켜세요.")
    st.divider()
    st.markdown(f"**기준일** {latest:%Y-%m-%d}  \n**ETF** {sig.loc[sig['일자'] == latest, '종목코드'].nunique():,}개  \n"
                f"**보관 데이터** {sig['일자'].min():%Y-%m-%d} ~")
    if st.session_state.offline:
        st.info("📦 오프라인 모드: 저장된 데이터로 실행 중")
    elif got:
        st.success(f"방금 KRX에서 {len(got)}거래일 새로 받음 ({got[-1]:%m/%d}까지)")
    if err:
        st.warning(err)
    if st.button("🔄 KRX에서 다시 확인", disabled=st.session_state.offline):
        st.session_state.refresh += 1
        st.cache_data.clear()
        st.rerun()
    with st.expander("판정 기준"):
        st.markdown(
            "- 괴리율 = (종가 − NAV) / NAV × 100\n"
            "- Z = (오늘 괴리율 − 직전 20거래일 평균) ÷ 직전 20거래일 표준편차\n"
            "- **위험일** = Z > 2 이고 괴리율 > 0 (평소보다 유난히 비싸게 거래)\n"
            "- 거래량 0인 날(거래정지 등)과 KRX 휴장일 빈 행은 제외")


def fmt_pct(v, d=2, sign=True):
    return "–" if pd.isna(v) else (f"{v:+.{d}f}%" if sign else f"{v:.{d}f}%")


# ---------------------------------------------------------------- 화면 1
def page_alarm():
    st.header(f"오늘의 경보 · {latest:%Y년 %m월 %d일}")
    day = sig[sig["일자"] == latest]
    min_gap = st.slider("최소 괴리율(%) — Z가 높아도 괴리 자체가 작으면 손해가 작아서 숨겨요", 0.0, 3.0, 0.5, 0.1)
    alarms = core.scan(sig, latest)
    alarms = alarms[alarms["괴리율"] >= min_gap]
    pool = core.pooled_stats(sig, latest)

    c = st.columns(4)
    c[0].metric("경보 ETF (Z>2)", f"{len(alarms)}개", help=f"괴리율 {min_gap}% 이상만")
    c[1].metric("괴리율 1% 초과", f"{(day['괴리율'].abs() > 1).sum()}개")
    c[2].metric("거래 정지·무거래 제외", f"{(day['거래량'].fillna(0) == 0).sum()}개")
    c[3].metric("과거 1년 위험일 5일 뒤 회복", fmt_pct(pool['회복5'], 0, False),
                help=f"전체 ETF의 최근 1년 위험일 {pool['위험일수']:,}건 중 5거래일 뒤 괴리율이 줄어든 비율")

    st.markdown(
        f"> 최근 1년 전체 ETF에서 위험일은 **{pool['위험일수']:,}번**({pool['종목수']}개 종목) 있었고, "
        f"그 뒤 괴리율이 줄어든 비율은 1일 뒤 **{pool['회복1']:.0f}%**, 5일 뒤 **{pool['회복5']:.0f}%**, "
        f"20일 뒤 **{pool['회복20']:.0f}%**. 즉 경보가 뜬 날 사면 괴리만큼 손해 볼 가능성이 커요.")

    if alarms.empty:
        st.info("오늘은 경보 ETF가 없어요.")
    else:
        show = pd.DataFrame({
            "종목코드": alarms["종목코드"], "종목명": alarms["종목명"],
            "괴리율(%)": alarms["괴리율"].round(2), "평소(20일 평균, %)": alarms["기준평균"].round(2),
            "Z": alarms["Z"].round(1), "과거 1년 위험일": alarms["과거위험일"],
            "그때 5일 뒤 회복률(%)": alarms["과거5일회복률"].round(0),
            "거래량": alarms["거래량"].astype("Int64"),
        })
        st.caption("행을 누르면 종목 분석으로 이동해요.")
        ev = st.dataframe(show, hide_index=True, use_container_width=True, on_select="rerun",
                          selection_mode="single-row", key="alarm_table",
                          column_config={"Z": st.column_config.ProgressColumn("Z", min_value=0,
                                         max_value=float(max(10, show["Z"].max())), format="%.1f")})
        if ev.selection.rows:
            st.session_state.pending_code = show.iloc[ev.selection.rows[0]]["종목코드"]
            st.rerun()

    with st.expander(f"오늘 전체 괴리율 분포 ({len(day):,}개)"):
        v = day.loc[day["거래량"].fillna(0) > 0, "괴리율"].clip(-5, 5)
        fig = go.Figure(go.Histogram(x=v, nbinsx=80, marker_color="#4C78A8"))
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="괴리율(%) (±5%에서 자름)", yaxis_title="ETF 수")
        st.plotly_chart(fig, use_container_width=True)
        live = day[day["거래량"].fillna(0) > 0]
        top = live.reindex(live["괴리율"].abs().sort_values(ascending=False).index).head(15)
        st.dataframe(top[["종목코드", "종목명", "괴리율", "Z", "거래량"]].round(2), hide_index=True,
                     use_container_width=True)


# ---------------------------------------------------------------- 화면 2
def page_ticker():
    st.header("종목 분석")
    codes = list(names.index)
    label = lambda c: f"{c}  {names.get(c, '')}"
    default = st.session_state.get("code", "412570")
    cols = st.columns(len(PRESETS))
    for col, (nm, cd) in zip(cols, PRESETS.items()):
        if col.button(nm, use_container_width=True):
            st.session_state.code = cd
            st.rerun()
    code = st.selectbox("종목 (코드나 이름으로 검색)", codes,
                        index=codes.index(default) if default in codes else 0, format_func=label)
    st.session_state.code = code

    lo, hi = sig["일자"].min().date() + timedelta(days=35), latest.date()
    rng = st.date_input("기간 (기본 최근 1년)", (max(lo, hi - timedelta(days=365)), hi),
                        min_value=lo, max_value=hi)
    if not isinstance(rng, (tuple, list)) or len(rng) != 2:
        st.stop()
    t = core.ticker_view(sig, code, *rng)
    if t.empty:
        st.warning("이 기간에 데이터가 없어요.")
        return
    risk = t[t["위험일"]]
    last = t.iloc[-1]

    c = st.columns(4)
    c[0].metric("최근 괴리율", fmt_pct(last["괴리율"]), help=f"{last['일자']:%Y-%m-%d}")
    c[1].metric("최근 Z", "–" if pd.isna(last["Z"]) else f"{last['Z']:.2f}")
    c[2].metric("기간 내 위험일", f"{len(risk)}일", help=f"거래일 {len(t)}일 중")
    rec5 = (risk["괴리변화5"].dropna() < 0).mean() * 100 if len(risk) else np.nan
    c[3].metric("위험일 5일 뒤 괴리 줄어든 비율", fmt_pct(rec5, 0, False))

    # 괴리율 추이 + 경보선 + 위험일
    fig = go.Figure()
    upper = t["기준평균"] + core.Z_TH * t["기준표준편차"]
    fig.add_trace(go.Scatter(x=t["일자"], y=upper, name="경보선 (평균+2σ)",
                             line=dict(color="#E45756", dash="dot", width=1)))
    fig.add_trace(go.Scatter(x=t["일자"], y=t["기준평균"], name="20일 평균",
                             line=dict(color="#999", width=1)))
    fig.add_trace(go.Scatter(x=t["일자"], y=t["괴리율"], name="괴리율", line=dict(color="#4C78A8", width=2)))
    fig.add_trace(go.Scatter(x=risk["일자"], y=risk["괴리율"], mode="markers", name="위험일",
                             marker=dict(color="#E45756", size=10, symbol="triangle-up")))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="괴리율(%)",
                      title=f"{names.get(code, code)} 괴리율 추이", legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, use_container_width=True)

    if risk.empty:
        st.info("이 기간에는 위험일이 없어서 회귀 분석을 할 수 없어요. 기간을 넓혀 보세요.")
        return

    left, right = st.columns([1, 1])
    with left:
        st.subheader("위험일 뒤 괴리율 평균 경로")
        p = core.recovery_path(t)
        normal = t.loc[~t["위험일"] & t["Z"].notna(), "괴리율"].mean()
        f2 = go.Figure(go.Scatter(x=p["경과일"], y=p["평균 괴리율"], mode="lines+markers",
                                  line=dict(color="#E45756"), name="위험일 이후"))
        f2.add_hline(y=normal, line_dash="dash", line_color="#999",
                     annotation_text=f"평소 평균 {normal:.2f}%")
        f2.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                         xaxis_title="위험일 뒤 거래일", yaxis_title="평균 괴리율(%)")
        st.plotly_chart(f2, use_container_width=True)
    with right:
        st.subheader("1·5·20일 회귀 분석")
        es = core.event_study(t)
        st.dataframe(es.round(3), hide_index=True, use_container_width=True)
        r5 = es.iloc[1]
        st.markdown(
            f"위험일 {len(risk)}번 중 5거래일 뒤 괴리율이 줄어든 비율은 **{r5['괴리율 줄어든 비율(%)']:.0f}%**, "
            f"그 사이 시장가 수익률은 NAV보다 평균 **{r5['위험일 뒤 시장-NAV 수익률차(%p)']:+.2f}%p** "
            f"(평소 {r5['평소 시장-NAV 수익률차(%p)']:+.2f}%p)였어요. "
            "음수면 비싸게 산 만큼 따라잡지 못하고 손해 봤다는 뜻이에요.")

    st.subheader("위험일 목록")
    st.dataframe(risk[["일자", "종가", "NAV", "괴리율", "Z", "괴리변화1", "괴리변화5", "괴리변화20"]]
                 .assign(일자=lambda x: x["일자"].dt.date).round(3),
                 hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- 화면 3
def page_check():
    st.header("검증")
    st.subheader("1. KRX 공시값 대조")
    st.caption("KRX ETF 일별매매정보 API에는 괴리율 필드가 없어요. 그래서 같은 응답에 들어 있는 KRX 공시 필드를 "
               "앱이 원자료(종가·대비·상장좌수)로 다시 계산해 맞는지 봐요. 괴리율 공식에 쓰는 종가를 "
               "올바르게 읽고 있다는 근거가 됩니다. 거래량 0인 종목은 제외.")
    raw, src = None, ""
    if not st.session_state.offline:
        try:
            from krx_api import fetch_day_raw, get_key
            raw = fetch_day_raw(latest.strftime("%Y%m%d"), get_key())
            src = f"방금 KRX에서 받은 {latest:%Y-%m-%d} 원본"
        except Exception as e:
            st.warning(f"KRX 호출 실패, 저장된 원본으로 대조해요: {e}")
    if raw is None or raw.empty:
        raw = pd.read_parquet(core.SNAPSHOT)
        src = f"저장된 원본 ({raw['BAS_DD'].iloc[0]})"
    st.markdown(f"대조 대상: **{src}**")
    st.dataframe(core.check_krx_fields(raw), hide_index=True, use_container_width=True)

    st.subheader("2. 결과보고서 재현")
    st.caption("보고서 방식(2025-11-04~2026-11-03 데이터만으로 Z 계산, 첫 20거래일은 판정 안 함)으로 위험일 수를 다시 세요. "
               "KRX가 휴장일에도 빈 행을 주는데, 이 행을 지우지 않으면 숫자가 어긋났던 문제를 고친 결과예요.")
    st.dataframe(core.check_report(core.load_cache()), hide_index=True, use_container_width=True)
    st.caption("참고: 앱의 경보 화면은 기간 시작 전 20거래일도 기준선에 쓰기 때문에 첫 20일도 판정해요. "
               "그래서 같은 기간이라도 종목 분석 화면의 위험일 수는 보고서보다 조금 많을 수 있어요(예: 2차전지 12일).")

    st.subheader("3. 데이터 정제")
    days = sig["일자"].nunique()
    st.markdown(
        f"- 보관 기간 평일 중 KRX가 빈 행만 준 휴장일은 자동으로 버렸고, 남은 거래일은 **{days}일**이에요.\n"
        f"- 최근 거래일 거래량 0(거래정지 등) ETF **{int((sig.loc[sig['일자'] == latest, '거래량'].fillna(0) == 0).sum())}개**는 "
        "괴리율이 멈춘 가격으로 계산돼 비정상이라 경보에서 뺐어요 (예: ACE 러시아).")


{"오늘의 경보": page_alarm, "종목 분석": page_ticker, "검증": page_check}[page]()
