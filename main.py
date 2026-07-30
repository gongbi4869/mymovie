날짜를 단일 날짜 선택에서 시작일~종료일 기간 선택으로 바꾸고, 지정한 기간 동안의 누적 박스오피스 데이터를 합산하여 집계하도록 수정한 전체 코드입니다.

KOBIS API 특성상 기간 조회가 따로 없으므로, 선택한 기간 동안 날짜별 데이터를 순회하며 받아온 뒤 합산하도록 구현했습니다.

app.py 수정 코드
Python
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 1. 페이지 설정 및 제목
st.set_page_config(page_title="박스오피스 대시보드", layout="wide")
st.title("🎬 기간별 & 장르별 박스오피스 대시보드")

# 2. 비밀 금고에서 인증키 꺼내기
KOBIS_KEY = st.secrets["KOBIS_KEY"]

# 3. 사이드바 - 날짜 기간 선택 (기본값: 최근 7일간)
today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date()
default_end = today_kst - timedelta(days=1)
default_start = default_end - timedelta(days=6)

st.sidebar.header("🔍 조회 조건 설정")
selected_dates = st.sidebar.date_input(
    "조회 기간 선택 (시작일 ~ 종료일)",
    value=(default_start, default_end),
    max_value=default_end # 오늘 데이터는 집계 전일 수 있어 어제까지만 선택 가능
)

# date_input이 범위(튜플)로 반환될 때 처리
if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
else:
    st.info("💡 시작일과 종료일을 모두 선택해 주세요.")
    st.stop()

if start_date > end_date:
    st.error("시작일은 종료일보다 이전이어야 합니다.")
    st.stop()

# 너무 긴 기간 조회 시 API 호출 지연 방지 (최대 31일 제한)
date_diff = (end_date - start_date).days + 1
if date_diff > 31:
    st.warning("⚠️ 안정적인 조회를 위해 최대 31일(1개월) 이내의 기간만 선택해 주세요.")
    st.stop()

st.caption(f"📅 조회 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')} (총 {date_diff}일간)")

# 4. 단일 날짜 박스오피스 조회 함수 (캐싱)
@st.cache_data(ttl=3600)
def fetch_daily_boxoffice(key, target_dt):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    try:
        res = requests.get(url, params={"key": key, "targetDt": target_dt}, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if "faultInfo" not in data:
                return data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
    except:
        pass
    return []

# 5. 기간 내 전체 데이터 수집 및 합산 함수
@st.cache_data(ttl=3600)
def get_period_boxoffice(key, start, end):
    all_rows = []
    curr = start
    while curr <= end:
        dt_str = curr.strftime("%Y%m%d")
        daily_list = fetch_daily_boxoffice(key, dt_str)
        for item in daily_list:
            all_rows.append({
                "movieCd": item["movieCd"],
                "movieNm": item["movieNm"],
                "openDt": item["openDt"],
                "audiCnt": int(item["audiCnt"]),
                "audiAcc": int(item["audiAcc"]), # 가장 최근일 기준 값 활용
                "scrnCnt": int(item["scrnCnt"])
            })
        curr += timedelta(days=1)
    
    if not all_rows:
        return pd.DataFrame()

    df_raw = pd.DataFrame(all_rows)
    
    # 기간 동안 영화별 관객수 합산 및 평균 스크린수 계산
    grouped = df_raw.groupby(["movieCd", "movieNm", "openDt"]).agg({
        "audiCnt": "sum",       # 기간 내 총 관객수 합산
        "audiAcc": "max",       # 가장 최근 누적 관객수
        "scrnCnt": "max"        # 기간 중 최대 스크린수
    }).reset_index()

    # 기간 내 관객수 기준으로 순위 다시 집계
    grouped = grouped.sort_values(by="audiCnt", ascending=False).reset_index(drop=True)
    grouped["rank"] = grouped.index + 1
    return grouped

# 6. 영화 상세정보(장르) 조회 함수
@st.cache_data(ttl=86400)
def get_movie_genres(key, movie_cd):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieInfo.json"
    try:
        res = requests.get(url, params={"key": key, "movieCd": movie_cd}, timeout=5)
        if res.status_code == 200:
            movie_info = res.json().get("movieInfoResult", {}).get("movieInfo", {})
            genres = [g["genreNm"] for g in movie_info.get("genres", [])]
            return ", ".join(genres) if genres else "기타"
    except:
        pass
    return "정보 없음"

# 데이터 로딩
with st.spinner("선택하신 기간의 박스오피스 데이터를 수집 및 집계하는 중입니다..."):
    df = get_period_boxoffice(KOBIS_KEY, start_date, end_date)

if df.empty:
    st.error("해당 기간의 데이터를 가져오지 못했습니다. KOBIS_KEY 또는 날짜 범위를 확인해 주세요.")
    st.stop()

# 장르 정보 추가
with st.spinner("장르 정보를 불러오는 중입니다..."):
    df["genre"] = df["movieCd"].apply(lambda x: get_movie_genres(KOBIS_KEY, x))

# 7. 사이드바 - 장르 필터 설정
all_genres = set()
for g_str in df["genre"].dropna():
    for g in g_str.split(", "):
        if g != "정보 없음":
            all_genres.add(g)

genre_options = ["전체"] + sorted(list(all_genres))
selected_genre = st.sidebar.selectbox("장르 선택", genre_options)

# 장르 필터링 적용
if selected_genre != "전체":
    filtered_df = df[df["genre"].str.contains(selected_genre, na=False)].copy()
else:
    filtered_df = df.copy()

if filtered_df.empty:
    st.warning(f"선택하신 장르(**{selected_genre}**)에 해당하는 영화가 해당 기간 내에 없습니다.")
    st.stop()

# 8. 주요 지표 카드 표시 (선택 기간 내 관객수 1위)
top = filtered_df.iloc[0]
c1, c2, c3 = st.columns(3)
c1.metric("기간 내 1위 영화", top["movieNm"])
c2.metric("기간 총 관객수", f"{top['audiCnt']:,}명")
c3.metric("최신 누적 관객수", f"{top['audiAcc']:,}명")

st.markdown("---")

# 9. 표 레이아웃 정리 및 출력
table = filtered_df[["rank", "movieNm", "genre", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
table.columns = ["순위", "영화명", "장르", "개봉일", "기간내 관객수", "누적관객", "최대 스크린수"]

st.subheader(f"📋 기간 누적 박스오피스 목록 ({'전체' if selected_genre == '전체' else selected_genre})")
st.dataframe(table, use_container_width=True)

# 10. 시각화 (기간내 관객수 상위 영화)
st.subheader("📈 기간 내 관객수 상위 5편")
top_chart = table.head(5)
st.bar_chart(top_chart.set_index("영화명")["기간내 관객수"])
