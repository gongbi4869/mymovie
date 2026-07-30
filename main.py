import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 1. 페이지 설정 및 제목
st.set_page_config(page_title="박스오피스 대시보드", layout="wide")
st.title("🎬 날짜별 & 장르별 박스오피스 대시보드")

# 2. 비밀 금고에서 인증키 꺼내기
KOBIS_KEY = st.secrets["KOBIS_KEY"]

# 3. 사이드바 - 날짜 선택 (기본값: 한국 시간 기준 어제)
today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date()
default_date = today_kst - timedelta(days=1)

st.sidebar.header("🔍 조회 조건 설정")
selected_date = st.sidebar.date_input(
    "조회 날짜 선택",
    value=default_date,
    max_value=default_date # 오늘 데이터는 집계 전일 수 있으므로 어제까지만 선택 가능
)

# KOBIS API용 날짜 포맷팅 (YYYYMMDD)
target_dt = selected_date.strftime("%Y%m%d")
st.caption(f"📅 조회 기준일: {selected_date.strftime('%Y년 %m월 %d일')}")

# 4. 박스오피스 API 요청 함수 (캐싱 적용)
@st.cache_data(ttl=3600)
def get_daily_boxoffice(key, dt):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    res = requests.get(url, params={"key": key, "targetDt": dt}, timeout=10)
    if res.status_code != 200:
        return None, f"요청 실패 (상태코드: {res.status_code})"
    
    data = res.json()
    if "faultInfo" in data:
        return None, "인증키가 올바르지 않습니다. Secrets의 KOBIS_KEY를 확인해 주세요."
        
    box_list = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
    if not box_list:
        return None, "해당 날짜의 박스오피스 데이터가 없습니다."
        
    return box_list, None

# 5. 영화 상세정보(장르) 조회 함수 (캐싱 적용)
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

# 데이터 불러오기
box_list, error_msg = get_daily_boxoffice(KOBIS_KEY, target_dt)

if error_msg:
    st.error(error_msg)
    st.stop()

# 6. 데이터프레임 변환 및 전처리
df = pd.DataFrame(box_list)

# 숫자형 컬럼 변환
for col in ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]:
    df[col] = pd.to_numeric(df[col])

# 각 영화별 장르 조회 (Spinner로 로딩 표시)
with st.spinner("장르 정보를 불러오는 중입니다..."):
    df["genre"] = df["movieCd"].apply(lambda x: get_movie_genres(KOBIS_KEY, x))

# 7. 사이드바 - 장르 필터 설정
# 추출된 전체 장르 목록 만들기 (쉼표로 구분된 장르들을 모두 분리)
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
    st.warning(f"선택하신 장르(**{selected_genre}**)에 해당하는 영화가 목록에 없습니다.")
    st.stop()

# 8. 주요 지표 카드 표시 (필터링된 목록 중 1위)
top = filtered_df.sort_values("rank").iloc[0]
c1, c2, c3 = st.columns(3)
c1.metric("선택 범위 1위", top["movieNm"])
c2.metric("당일 관객수", f"{top['audiCnt']:,}명")
c3.metric("누적 관객수", f"{top['audiAcc']:,}명")

st.markdown("---")

# 9. 표 레이아웃 정리 및 출력
table = filtered_df[["rank", "movieNm", "genre", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
table.columns = ["순위", "영화명", "장르", "개봉일", "관객수", "누적관객", "스크린수"]
table = table.sort_values("순위").reset_index(drop=True)

st.subheader(f"📋 박스오피스 목록 ({'전체' if selected_genre == '전체' else selected_genre})")
st.dataframe(table, use_container_width=True)

# 10. 시각화 (관객수 상위 영화)
st.subheader("📈 관객수 상위 영화")
top_chart = table.sort_values("관객수", ascending=False).head(5)
st.bar_chart(top_chart.set_index("영화명")["관객수"])
