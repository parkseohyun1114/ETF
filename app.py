"""ETF 괴리율 경보기 (Streamlit)

실행:  streamlit run app.py
"""
from datetime import timedelta
from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import strategy as S
from krx_api import get_key

st.set_page_config(page_title="ETF 괴리율 경보기", page_icon="🚨", layout="centered",
                   initial_sidebar_state="collapsed")

RED, GREEN, BLUE, GRAY = "#D63B3B", "#1E8E5A", "#2F6DB5", "#8A8F98"
PRESETS = {"2차전지 레버리지": "412570", "반도체 레버리지": "488080",
           "방산 레버리지": "0100K0", "KODEX 200 (대조군)": "069500"}

st.markdown(f"""
<style>
html, body, [class*="css"] {{ font-size: 17px; }}
.block-container {{ padding-top: 3.6rem; padding-bottom: 3rem; max-width: 820px; }}
h1, h2, h3 {{ letter-spacing: -0.02em; }}
.sub {{ color: {GRAY}; font-size: 0.92rem; margin: -0.3rem 0 0.8rem; }}
.hero {{ border-radius: 16px; padding: 1.1rem 1.2rem; margin: 0.4rem 0 1rem; }}
.hero.red {{ background: #FDECEC; border: 1px solid #F5C2C2; }}
.hero.green {{ background: #E9F6EF; border: 1px solid #BFE3CF; }}
.hero .big {{ font-size: 1.7rem; font-weight: 800; line-height: 1.25; }}
.hero .one {{ font-size: 1.02rem; margin-top: 0.45rem; line-height: 1.55; }}
.card {{ border: 1px solid #E3E5E8; border-radius: 14px; padding: 0.8rem 1rem; margin-bottom: 0.25rem; background: #fff; }}
.card .name {{ font-weight: 700; font-size: 1.05rem; }}
.card .code {{ color: {GRAY}; font-size: 0.85rem; margin-left: 0.3rem; }}
.card .row {{ display: flex; align-items: baseline; gap: 0.8rem; flex-wrap: wrap; margin-top: 0.2rem; }}
.card .gap {{ font-size: 1.6rem; font-weight: 800; }}
.card .note {{ color: #444; font-size: 0.92rem; }}
.pill {{ display: inline-block; border-radius: 999px; padding: 0.1rem 0.6rem; font-size: 0.8rem; font-weight: 700; }}
.pill.red {{ background: #FDECEC; color: {RED}; }} .pill.green {{ background: #E9F6EF; color: {GREEN}; }}
.pill.blue {{ background: #EAF1FA; color: {BLUE}; }}
.lead {{ font-size: 1.05rem; line-height: 1.6; background: #F6F7F9; border-radius: 12px; padding: 0.8rem 1rem; margin: 0.4rem 0 0.8rem; }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- 데이터 준비
@st.cache_data(ttl=3600, show_spinner=False)
def load(_refresh_token: int, offline: bool, engine_version: int):
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
if "offline" not in st.session_state:   # 주소 끝에 ?offline=1 → 처음부터 오프라인 모드
    st.session_state.offline = st.query_params.get("offline") == "1"
if "pending_code" in st.session_state:  # 카드에서 '자세히'를 누르면 화면 전환 (위젯 생성 전에 처리)
    st.session_state.code = st.session_state.pop("pending_code")
    st.session_state.page = "🔎 종목 분석"

with st.spinner("데이터 준비 중…"):
    sig, got, err = load(st.session_state.refresh, st.session_state.offline, core.ENGINE_VERSION)
if not {"NAV주도", "극단일", "일수익률"} <= set(sig.columns):   # 혹시 옛 캐시가 남아 있으면 비우고 다시
    st.cache_data.clear()
    st.rerun()

latest = sig["일자"].max()
names = sig.sort_values("일자").groupby("종목코드")["종목명"].last()
n_today = sig.loc[sig["일자"] == latest, "종목코드"].nunique()

# ---------------------------------------------------------------- 사이드바 (설정·상태)
with st.sidebar:
    st.subheader("설정")
    st.toggle("오프라인 백업 모드", key="offline",
              help="KRX에 접속하지 않고 미리 저장한 데이터로만 실행해요. 발표장 인터넷이 안 될 때 켜세요.")
    min_gap = st.slider("경보 최소 괴리율(%)", 0.0, 3.0, 0.5, 0.1,
                        help="Z가 높아도 괴리 자체가 작으면 손해가 작아서 숨겨요.")
    if st.button("🔄 KRX에서 다시 확인", disabled=st.session_state.offline, use_container_width=True):
        st.session_state.refresh += 1
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption(f"보관 데이터 {sig['일자'].min():%Y-%m-%d} ~ {latest:%Y-%m-%d}")
    with st.expander("판정 기준"):
        st.markdown(
            "- 괴리율 = (종가 − NAV) / NAV × 100\n"
            "- Z = (오늘 괴리율 − 직전 20거래일 평균) ÷ 직전 20거래일 표준편차\n"
            "- **위험일** = Z > 2 이고 괴리율 > 0\n"
            "- **할인일** = Z < −2 이고 괴리율 < 0\n"
            "- **극단일** = 하루 등락이 가격제한폭(일반 ±30%, 2배 ±60%)의 80% 이상\n"
            "- 거래량 0(거래정지)과 KRX 휴장일 빈 행은 제외")

# ---------------------------------------------------------------- 상단 내비게이션
PAGES = ["🚨 오늘의 경보", "🔎 종목 분석", "🧪 전략 실험", "✅ 검증"]
if st.session_state.get("page") not in PAGES:   # 옛 버전 세션에 남은 화면 이름 대비
    st.session_state.page = PAGES[0]
page = st.radio("화면", PAGES, key="page",
                horizontal=True, label_visibility="collapsed")
status = "📦 오프라인 모드 · 저장 데이터" if st.session_state.offline else \
    (f"🟢 KRX 실시간 · 방금 {len(got)}거래일 새로 받음" if got else "🟢 KRX 연결됨 · 최신 상태")
if err:
    status = "📦 " + err
st.markdown(f'<div class="sub">{latest:%Y년 %m월 %d일} 기준 · ETF {n_today:,}개 · {escape(status)}</div>',
            unsafe_allow_html=True)


def pct(v, d=2, sign=True):
    return "–" if pd.isna(v) else (f"{v:+.{d}f}%" if sign else f"{v:.{d}f}%")


def style_fig(fig, h=300):
    fig.update_layout(height=h, margin=dict(l=8, r=8, t=8, b=8), font=dict(size=14),
                      plot_bgcolor="white", paper_bgcolor="white", hovermode="x unified",
                      legend=dict(orientation="h", y=1.08, x=0, font=dict(size=13)))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#EEF0F2", zerolinecolor="#C9CDD2", ticksuffix="%")
    return fig


# ---------------------------------------------------------------- 화면 1
def page_alarm():
    all_alarms = core.scan(sig, latest)
    all_alarms = all_alarms[all_alarms["괴리율"] >= min_gap]
    alarms = all_alarms[~all_alarms["NAV주도"]]       # 가격이 튀어서 생긴 경보
    nav_led = all_alarms[all_alarms["NAV주도"]]       # NAV가 떨어져서 생긴 경보
    disc = core.scan_discount(sig, latest, min_gap)
    pool = core.pooled_stats(sig, latest)

    if len(alarms):
        st.markdown(f"""<div class="hero red"><div class="big">⚠️ 오늘 주의할 ETF {len(alarms)}개</div>
<div class="one">평소보다 <b>유난히 비싸게</b> 거래된 ETF예요. 지난 1년 이런 날 뒤 <b>5일 안에 {pool['회복5']:.0f}%</b>가
원래 가격 차이로 돌아왔어요. <b>오늘 사면 그만큼 비싸게 사는 셈</b>이에요.</div></div>""", unsafe_allow_html=True)
    if len(nav_led):
        st.caption(f"가격은 그대로인데 NAV가 떨어져 생긴 괴리 {len(nav_led)}개는 아래 '확인 필요'에 따로 모았어요.")
    else:
        st.markdown('<div class="hero green"><div class="big">✅ 오늘은 주의할 ETF가 없어요</div>'
                    '<div class="one">평소보다 유난히 비싸게 거래된 ETF가 없어요.</div></div>', unsafe_allow_html=True)

    for _, r in alarms.head(5).iterrows():
        hist = (f"과거 1년 위험일 {r['과거위험일']}번 중 5일 뒤 {r['과거5일회복률']:.0f}% 회복"
                if r["과거위험일"] and pd.notna(r["과거5일회복률"]) else "과거 1년 위험일 없음 (처음 튐)")
        st.markdown(f"""<div class="card"><span class="name">{escape(r['종목명'])}</span><span class="code">{r['종목코드']}</span>
<div class="row"><span class="gap" style="color:{RED}">{r['괴리율']:+.2f}%</span>
<span class="note">평소 {r['기준평균']:+.2f}% · <span class="pill red">Z {r['Z']:.1f}</span></span></div>
<div class="note">{hist}</div></div>""", unsafe_allow_html=True)
        if st.button("자세히 보기 →", key=f"go_{r['종목코드']}"):
            st.session_state.pending_code = r["종목코드"]
            st.rerun()

    if len(alarms) > 5:
        with st.expander(f"주의 ETF 전체 {len(alarms)}개 보기"):
            st.dataframe(pd.DataFrame({
                "종목명": alarms["종목명"], "괴리율(%)": alarms["괴리율"].round(2),
                "평소(%)": alarms["기준평균"].round(2), "Z": alarms["Z"].round(1),
                "과거 위험일": alarms["과거위험일"]}), hide_index=True, use_container_width=True)

    if len(nav_led):
        with st.expander(f"🟡 확인 필요: NAV가 떨어져 생긴 괴리 {len(nav_led)}개"):
            st.markdown("가격은 거의 안 움직였는데 **NAV가 하루에 떨어져서** 괴리율이 커진 ETF예요. "
                        "채권·커버드콜·고배당처럼 분배금을 주는 ETF가 많아서, 분배금이 NAV에 먼저 반영된 "
                        "날일 가능성이 커요. 이 경우는 실제로 비싸게 사는 게 아닐 수 있어 경보와 분리했어요.")
            st.dataframe(pd.DataFrame({"종목명": nav_led["종목명"], "괴리율(%)": nav_led["괴리율"].round(2),
                                       "가격 하루 변화(%)": nav_led["일수익률"].round(2), "Z": nav_led["Z"].round(1)}),
                         hide_index=True, use_container_width=True)

    st.markdown("### 💙 유난히 싸게 거래된 ETF")
    if disc.empty:
        st.caption("오늘은 없어요.")
    else:
        st.markdown(f'<div class="lead">평소보다 <b>싸게</b> 거래된 ETF {len(disc)}개예요(할인일). '
                    '사는 쪽엔 유리해 보이지만, 거래가 적거나 해외 시장 시차 때문일 수 있어 원인을 먼저 확인하세요.</div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"종목명": disc["종목명"], "괴리율(%)": disc["괴리율"].round(2),
                                   "평소(%)": disc["기준평균"].round(2), "Z": disc["Z"].round(1)}),
                     hide_index=True, use_container_width=True)

    with st.expander(f"오늘 ETF {n_today:,}개 괴리율 분포"):
        day = sig[(sig["일자"] == latest) & (sig["거래량"].fillna(0) > 0)]
        st.markdown(f"괴리율 1% 넘는 ETF **{(day['괴리율'].abs() > 1).sum()}개**, 2% 넘는 ETF "
                    f"**{(day['괴리율'].abs() > 2).sum()}개**. 대부분은 0 근처예요.")
        fig = go.Figure(go.Histogram(x=day["괴리율"].clip(-5, 5), nbinsx=60, marker_color=BLUE))
        style_fig(fig, 240).update_layout(hovermode=False)
        fig.update_xaxes(title="괴리율 (±5%에서 자름)", ticksuffix="%")
        fig.update_yaxes(ticksuffix="")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ---------------------------------------------------------------- 화면 2
def page_ticker():
    pick = st.pills("보고서 종목 바로가기", list(PRESETS), key="preset", label_visibility="collapsed")
    if pick and st.session_state.get("_last_pick") != pick:
        st.session_state._last_pick = pick
        st.session_state.code = PRESETS[pick]
    codes = list(names.index)
    default = st.session_state.get("code", "412570")
    code = st.selectbox("종목 검색 (코드나 이름)", codes, index=codes.index(default) if default in codes else 0,
                        format_func=lambda c: f"{names.get(c, '')} ({c})")
    st.session_state.code = code

    lo, hi = sig["일자"].min().date() + timedelta(days=35), latest.date()
    with st.expander("기간 바꾸기 (기본: 최근 1년)"):
        rng = st.date_input("기간", (max(lo, hi - timedelta(days=365)), hi), min_value=lo, max_value=hi)
    if not isinstance(rng, (tuple, list)) or len(rng) != 2:
        st.stop()
    t = core.ticker_view(sig, code, *rng)
    if t.empty:
        st.warning("이 기간에 데이터가 없어요.")
        return
    risk, last = t[t["위험일"]], t.iloc[-1]
    ext = t[t["극단일"]]

    # 지금 상태 카드
    danger = bool(last["위험일"])
    z = "–" if pd.isna(last["Z"]) else f"{last['Z']:.1f}"
    st.markdown(f"""<div class="hero {'red' if danger else 'green'}">
<div class="big">{'🔴 지금 주의' if danger else '🟢 지금 정상'} · 괴리율 {pct(last['괴리율'])}</div>
<div class="one">{escape(names.get(code, code))} · {last['일자']:%m월 %d일} 기준 · 평소 {pct(last['기준평균'])} · Z {z}</div></div>""",
                unsafe_allow_html=True)

    # 결론 한 줄
    if risk.empty:
        st.markdown('<div class="lead">이 기간에는 위험일이 없었어요. 기간을 넓혀 보세요.</div>', unsafe_allow_html=True)
    else:
        es = core.event_study(t)
        r5 = es.iloc[1]
        n5 = int(r5["표본(위험일)"])
        k5 = int(round(r5["괴리율 줄어든 비율(%)"] / 100 * n5)) if n5 else 0
        st.markdown(f"""<div class="lead">📌 <b>결론</b> · 이 기간 위험일 <b>{len(risk)}번</b>.
그 뒤 5일 안에 <b>{n5}번 중 {k5}번</b> 괴리가 줄었어요. 위험일에 샀다면 5일 동안 NAV보다
<b>{abs(r5['위험일 뒤 시장-NAV 수익률차(%p)']):.1f}%p {'덜' if r5['위험일 뒤 시장-NAV 수익률차(%p)'] < 0 else '더'} 벌었어요</b>
(평소 {r5['평소 시장-NAV 수익률차(%p)']:+.2f}%p).</div>""", unsafe_allow_html=True)

    # 괴리율 추이
    st.markdown("### 괴리율 추이")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t["일자"], y=t["기준평균"] + core.Z_TH * t["기준표준편차"], name="경보선",
                             line=dict(color=RED, dash="dot", width=1.2), hovertemplate="%{y:.2f}%"))
    fig.add_trace(go.Scatter(x=t["일자"], y=t["괴리율"], name="괴리율", line=dict(color=BLUE, width=2),
                             hovertemplate="%{y:.2f}%"))
    fig.add_trace(go.Scatter(x=risk["일자"], y=risk["괴리율"], mode="markers", name=f"위험일 {len(risk)}",
                             marker=dict(color=RED, size=11, symbol="triangle-up"), hovertemplate="%{y:.2f}%"))
    if len(ext):
        fig.add_trace(go.Scatter(x=ext["일자"], y=ext["괴리율"], mode="markers", name=f"극단일 {len(ext)}",
                                 marker=dict(color="#111", size=11, symbol="x"),
                                 customdata=ext["일수익률"], hovertemplate="%{y:.2f}% (하루 %{customdata:+.1f}%)"))
    st.plotly_chart(style_fig(fig, 320), use_container_width=True, config={"displayModeBar": False})
    st.caption("빨간 점선을 넘으면 위험일이에요. ✕는 하루 등락이 가격제한폭 근처였던 극단일로, "
               "가격이 제한폭에 묶여 괴리가 기계적으로 커질 수 있어 따로 표시했어요.")

    if risk.empty:
        return

    st.markdown("### 위험일 뒤 어떻게 됐나")
    p = core.recovery_path(t)
    normal = t.loc[~t["위험일"] & t["Z"].notna(), "괴리율"].mean()
    f2 = go.Figure(go.Scatter(x=p["경과일"], y=p["평균 괴리율"], mode="lines+markers", name="위험일 뒤 평균",
                              line=dict(color=RED, width=2.5), hovertemplate="%{x}일 뒤 %{y:.2f}%"))
    f2.add_hline(y=normal, line_dash="dash", line_color=GRAY, annotation_text=f"평소 {normal:.2f}%",
                 annotation_position="top right")
    f2.update_xaxes(title="위험일 뒤 거래일")
    st.plotly_chart(style_fig(f2, 260), use_container_width=True, config={"displayModeBar": False})

    simple = pd.DataFrame({
        "언제": es["기간"].str.replace("거래일 뒤", "일 뒤"),
        "괴리 줄어듦": es["괴리율 줄어든 비율(%)"].map(lambda v: pct(v, 0, False)),
        "위험일 매수 (평소)": [f"{pct(x, 1).replace('%', '%p')} ({pct(y, 1).replace('%', '')})"
                           for x, y in zip(es["위험일 뒤 시장-NAV 수익률차(%p)"], es["평소 시장-NAV 수익률차(%p)"])],
        "유의": es["p값(Welch t)"].map(lambda v: "–" if pd.isna(v) else ("✔" if v < 0.05 else "✗")),
    })
    st.dataframe(simple, hide_index=True, use_container_width=True)
    st.caption("'위험일 매수'는 그날 샀을 때 시장가 수익률이 NAV 수익률보다 얼마나 덜(−)/더(+) 났는지예요. "
               "'유의 ✔'는 위험일과 평소의 차이가 우연이 아닐 가능성이 높다는 뜻이에요(Welch t-검정 p < 0.05).")

    with st.expander(f"위험일 {len(risk)}일 목록과 원자료"):
        lst = risk[["일자", "괴리율", "Z", "괴리변화1", "괴리변화5", "괴리변화20", "극단일"]].copy()
        lst["일자"] = lst["일자"].dt.date
        lst["극단일"] = lst["극단일"].map({True: "✕ 제한폭 근처", False: ""})
        st.dataframe(lst.rename(columns={"괴리변화1": "1일 뒤 변화", "괴리변화5": "5일 뒤 변화",
                                         "괴리변화20": "20일 뒤 변화"}).round(2),
                     hide_index=True, use_container_width=True)
        st.dataframe(es.round(3), hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- 화면 3
def page_check():
    rep = core.check_report(core.load_cache())
    raw, src = None, ""
    if not st.session_state.offline:
        try:
            from krx_api import fetch_day_raw
            key = get_key()
            if key:
                raw = fetch_day_raw(latest.strftime("%Y%m%d"), key)
                src = f"방금 KRX에서 받은 {latest:%Y-%m-%d} 원본"
        except Exception as e:
            st.warning(f"KRX 호출 실패, 저장된 원본으로 대조해요: {e}")
    if raw is None or raw.empty:
        raw = pd.read_parquet(core.SNAPSHOT)
        src = f"저장된 원본 ({raw['BAS_DD'].iloc[0]})"
    chk = core.check_krx_fields(raw)
    ok_rep = (rep["결과"].str.contains("일치") & ~rep["결과"].str.contains("불일치")).all()
    ok_chk = (chk["일치율(%)"] == 100).all()
    good = ok_rep and ok_chk
    st.markdown(f"""<div class="hero {'green' if good else 'red'}"><div class="big">{'✅ 검증 통과' if good else '⚠️ 확인 필요'}</div>
<div class="one">KRX 공시값 대조 {len(chk)}개 항목 {'모두 100% 일치' if ok_chk else '일부 불일치'} ·
보고서 위험일 수 {'그대로 재현' if ok_rep else '재현 실패'}</div></div>""", unsafe_allow_html=True)

    st.markdown("### 1. KRX 공시값 대조")
    st.markdown('<div class="lead">KRX ETF API에는 괴리율 필드가 없어요. 그래서 같은 응답의 공시값(등락률·시가총액·고가·저가)을 '
                '앱이 원자료로 다시 계산해 맞는지 봐요. 맞으면 괴리율 계산에 쓰는 종가를 제대로 읽고 있다는 뜻이에요.</div>',
                unsafe_allow_html=True)
    st.caption(f"대조 대상: {src} · 거래량 0인 종목 제외")
    st.dataframe(chk[["검증 항목(앱 계산)", "일치", "일치율(%)"]].rename(columns={"검증 항목(앱 계산)": "앱이 계산한 값 → KRX 공시값"}),
                 hide_index=True, use_container_width=True)

    st.markdown("### 2. 결과보고서 재현")
    st.markdown('<div class="lead">보고서와 같은 방식(2025-11-04~2026-11-03, 첫 20거래일 판정 안 함)으로 위험일 수를 다시 세요. '
                'KRX가 휴장일에 주는 빈 행을 지우지 않으면 이 숫자가 어긋났던 문제를 고친 결과예요.</div>',
                unsafe_allow_html=True)
    st.dataframe(rep[["종목명", "보고서 위험일", "앱 재계산", "결과"]].assign(
        종목명=rep["종목명"].str.replace("TOP10레버리지", "")).rename(columns={"보고서 위험일": "보고서", "앱 재계산": "앱"}),
                 hide_index=True, use_container_width=True)
    st.caption("앱의 종목 분석은 기간 시작 전 20거래일도 기준선에 쓰기 때문에 첫 20일도 판정해서, "
               "같은 기간이라도 위험일이 조금 많을 수 있어요(예: 2차전지 12일).")

    st.markdown("### 3. 데이터 정제")
    halted = int((sig.loc[sig["일자"] == latest, "거래량"].fillna(0) == 0).sum())
    st.markdown(f"- KRX가 빈 행만 준 휴장일은 버렸고, 남은 거래일은 **{sig['일자'].nunique()}일**이에요.\n"
                f"- 최근 거래일 거래량 0(거래정지 등) ETF **{halted}개**는 괴리율이 비정상이라 경보에서 뺐어요 (예: ACE 러시아).\n"
                f"- 하루 등락이 가격제한폭 근처였던 극단일 **{int(sig['극단일'].sum())}건**은 차트에 ✕로 따로 표시해요.")


# ---------------------------------------------------------------- 화면 4: 전략 실험
REPORT4 = list(PRESETS.values())


@st.cache_data(show_spinner="1년치 전략 계산 중…")
def run_strategies(scope: str, last_day, engine_version: int):
    sig_all = sig if scope == "전체 ETF" else sig[sig["종목코드"].isin(REPORT4)]
    start = last_day - pd.Timedelta(days=365)
    gap = 0.5 if scope == "전체 ETF" else 0.0
    bt = S.timing_backtest(sig_all, start, last_day)
    d0 = S.discount_strategy(sig_all, start, last_day, min_gap=gap, lag=0)
    d1 = S.discount_strategy(sig_all, start, last_day, min_gap=gap, lag=1)
    return bt, d0, d1


@st.cache_data(show_spinner="민감도 격자 계산 중…")
def run_sensitivity(last_day, engine_version: int):
    return S.sensitivity(core.load_cache(), REPORT4, last_day - pd.Timedelta(days=365), last_day)


def short_name(code):
    return {v: k.replace(" (대조군)", "") for k, v in PRESETS.items()}.get(code, names.get(code, code))


def page_lab():
    st.markdown(f'<div class="lead">지난 1년({(latest - pd.Timedelta(days=365)):%Y-%m-%d} ~ {latest:%Y-%m-%d}) 데이터로 '
                '경보를 실제로 썼다면 어땠을지 세 가지로 실험해요. 성과는 모두 <b>NAV 대비</b>로 재요. '
                '시장이 오르내린 효과는 빼고, 괴리 때문에 생긴 이득·손해만 보기 위해서예요.</div>', unsafe_allow_html=True)
    scope = st.pills("대상", ["보고서 4종", "전체 ETF"], default="보고서 4종", key="lab_scope")
    scope = scope or "보고서 4종"
    bt, d0, d1 = run_strategies(scope, latest, core.ENGINE_VERSION)
    tab1, tab2, tab3 = st.tabs(["① 매수 타이밍", "② 할인일 전략", "③ 민감도"])

    with tab1:
        s = S.summarize_timing(bt)
        if not s["n"]:
            st.info("이 기간에 위험일이 없어요.")
        else:
            st.markdown(f"""<div class="hero green"><div class="big">하루만 기다려도 평균 {s['절약1']:.2f}%p 덜 비싸게</div>
<div class="one">위험일 {s['n']:,}번 중 <b>{s['유리1']:.0f}%</b>에서 다음 날 사는 게 프리미엄이 더 작았어요.
Z가 1 아래로 내려올 때까지(최대 {S.MAX_WAIT}일, 평균 {s['대기일']:.1f}일) 기다리면 평균 <b>{s['절약N']:.2f}%p</b> 절약,
<b>{s['유리N']:.0f}%</b>에서 유리했어요.</div></div>""", unsafe_allow_html=True)
            g = bt.groupby("종목코드").agg(위험일=("일자", "size"), 하루대기=("1일 대기 절약", "mean"),
                                         정상화대기=("정상화 대기 절약", "mean")).reset_index()
            g.insert(0, "종목", g.pop("종목코드").map(short_name))
            g = g.sort_values("위험일", ascending=False).head(15)
            st.dataframe(g.rename(columns={"하루대기": "하루 대기", "정상화대기": "정상화까지"}).round(2),
                         hide_index=True, use_container_width=True)
            st.caption("표의 숫자는 평균 절약(%p). 절약 = 위험일 괴리율 − 실제로 산 날 괴리율. 장중에는 실시간 iNAV로 괴리율을 볼 수 있어서 "
                       "'위험일인 걸 알고 그날 안 산다'는 가정이 가능해요. 기다리는 동안 시장 자체가 움직이는 위험은 "
                       "NAV에 그대로 반영되므로 여기서는 빼고 봤어요.")

    with tab2:
        a0, a1 = S.summarize_discount(d0), S.summarize_discount(d1)
        if not a0["n"]:
            st.info("이 기간에 할인일이 없어요.")
        else:
            st.markdown(f"""<div class="hero {'green' if a1.get('순초과', 0) > 0 else 'red'}">
<div class="big">당일 매수 {a0['순초과']:+.2f}%p · 다음 날 매수 {a1['순초과']:+.2f}%p</div>
<div class="one">할인일(Z&lt;−2)에 사서 괴리가 평소 수준으로 돌아오면 파는 전략, 거래 {a0['n']:,}번
(평균 {a0['보유일']:.1f}일 보유). 거래비용 {S.COST:.2f}%p를 뺀 NAV 대비 순이익이에요.
<b>다음 날 사면 이익이 크게 줄어요.</b> 괴리 대부분이 하루 만에 회복되기 때문이에요.</div></div>""",
                        unsafe_allow_html=True)
            tbl = pd.DataFrame({
                "매수": ["당일", "다음 날"],
                "거래": [a0["n"], a1.get("n", 0)],
                "순이익": [pct(a0["순초과"]).replace("%", "%p"), pct(a1.get("순초과", np.nan)).replace("%", "%p")],
                "승률": [pct(a0["승률"], 0, False), pct(a1.get("승률", np.nan), 0, False)],
                "가격 수익률": [pct(a0["가격"]), pct(a1.get("가격", np.nan))],
            })
            st.dataframe(tbl, hide_index=True, use_container_width=True)
            st.caption(f"순이익 = 거래비용을 뺀 NAV 대비 이익. 매도 = 괴리율이 매수 때 기준(직전 20일 평균) 이상으로 돌아온 첫날, 최대 {S.MAX_HOLD}거래일. "
                       f"거래비용 {S.COST:.2f}%p(수수료+호가 차이)는 가정값이에요. '가격 수익률'은 시장 방향까지 포함한 "
                       "손익이라 NAV 대비 이익과 달라요. 전체 ETF에서는 괴리율 0.5% 이상 할인일만 써요. "
                       "거래가 적은 ETF는 표시된 가격에 실제로 사고팔기 어려울 수 있어요.")
            with st.expander("거래 목록 (당일 매수)"):
                show = d0[["종목코드", "매수일", "보유일", "매수 괴리율", "초과수익", "순초과수익"]].copy()
                show.insert(0, "종목", show.pop("종목코드").map(short_name))
                show["매수일"] = show["매수일"].dt.date
                st.dataframe(show.sort_values("매수일", ascending=False).round(2), hide_index=True,
                             use_container_width=True)

    with tab3:
        sens = run_sensitivity(latest, core.ENGINE_VERSION)
        st.markdown('<div class="lead"><b>창</b>은 "평소"를 정하는 기간이에요. 10일은 기준이 빨리 바뀌어 경보가 많고, '
                    '60일은 안정적이지만 서서히 커지는 괴리는 늦게 잡아요. <b>Z 기준</b>은 얼마나 튀어야 경보인지예요. '
                    '★가 보고서 기본값(20일, Z&gt;2)이에요.</div>', unsafe_allow_html=True)
        avg = sens.groupby(["창", "Z"]).agg(위험일=("위험일", "sum"), 축소5=("축소5", "mean"),
                                           수익률차=("5일 수익률차", "mean")).reset_index()
        lo5, hi5 = avg["축소5"].min(), avg["축소5"].max()
        st.markdown(f"""<div class="hero green"><div class="big">9가지 설정 모두 5일 뒤 {lo5:.0f}~{hi5:.0f}% 괴리 축소</div>
<div class="one">설정을 바꾸면 위험일 수는 {int(avg['위험일'].min())}~{int(avg['위험일'].max())}번(4종 합계)으로 크게 달라지지만,
"위험일 뒤 괴리가 줄어든다"는 결론은 그대로예요.</div></div>""", unsafe_allow_html=True)
        pv = avg.assign(칸=[f"{'★ ' if (w == 20 and z == 2.0) else ''}{n}일 · {r:.0f}%" for w, z, n, r in
                           zip(avg["창"], avg["Z"], avg["위험일"], avg["축소5"])])
        grid = pv.pivot(index="창", columns="Z", values="칸")
        grid.index = [f"창 {w}일" for w in grid.index]
        grid.columns = [f"Z>{z}" for z in grid.columns]
        st.markdown("**위험일 수 · 5일 뒤 괴리 줄어든 비율** (4종 합계·평균)")
        st.dataframe(grid, use_container_width=True)
        pick = st.pills("종목별로 보기", [short_name(c) for c in REPORT4], key="sens_pick")
        if pick:
            code = {short_name(c): c for c in REPORT4}[pick]
            one = sens[sens["종목코드"] == code]
            one = one.assign(설정=[f"{'★ ' if (w == 20 and z == 2.0) else ''}{w}일·Z>{z}" for w, z in zip(one["창"], one["Z"])])
            st.dataframe(one[["설정", "위험일", "축소1", "축소5", "축소20", "5일 수익률차"]].rename(columns={
                "축소1": "1일 축소%", "축소5": "5일 축소%", "축소20": "20일 축소%", "5일 수익률차": "5일 NAV 대비(%p)"}).round(1),
                hide_index=True, use_container_width=True)
        st.caption("60일 창은 보관 데이터 시작(2025-09-01) 때문에 기간 초반 며칠은 판정하지 못해요.")


{"🚨 오늘의 경보": page_alarm, "🔎 종목 분석": page_ticker, "🧪 전략 실험": page_lab, "✅ 검증": page_check}[page]()
