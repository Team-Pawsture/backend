"""
네이버 API 호출 유틸리티
- Directions 5 API (클라우드 플랫폼): 실제 거리/시간 계산
- 비동기 호출로 여러 병원의 거리를 동시 계산 (asyncio)
- ⚠️ 지역검색 API(개발자 센터)는 1차 배포에서 카카오로 대체됨 → 관련 코드 제거됨
"""

import os
import asyncio
import aiohttp


# ============================================
# 환경 변수
# ============================================
NAVER_CLOUD_CLIENT_ID = os.getenv("NAVER_CLOUD_CLIENT_ID")
NAVER_CLOUD_CLIENT_SECRET = os.getenv("NAVER_CLOUD_CLIENT_SECRET")


# ============================================
# 1. 네이버 Directions 5 API (단일 호출)
# ============================================
async def get_distance_and_duration(
    session: aiohttp.ClientSession,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> dict:
    """
    출발지 → 도착지 실제 운전 거리/시간 계산

    Returns:
        {"distance_meters": 184, "duration_seconds": 145}
        실패 시: {"distance_meters": None, "duration_seconds": None}
    """
    url = "https://maps.apigw.ntruss.com/map-direction/v1/driving"
    headers = {
        "x-ncp-apigw-api-key-id": NAVER_CLOUD_CLIENT_ID,
        "x-ncp-apigw-api-key": NAVER_CLOUD_CLIENT_SECRET,
    }
    params = {
        "start": f"{start_lng},{start_lat}",   # 네이버 형식: 경도,위도
        "goal": f"{end_lng},{end_lat}",
    }

    try:
        async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=5)) as response:
            if response.status != 200:
                return {"distance_meters": None, "duration_seconds": None}
            data = await response.json()

        # 응답 파싱
        route = data.get("route", {})
        traoptimal = route.get("traoptimal", [])
        if not traoptimal:
            return {"distance_meters": None, "duration_seconds": None}

        summary = traoptimal[0].get("summary", {})
        return {
            "distance_meters": summary.get("distance"),
            "duration_seconds": summary.get("duration", 0) // 1000,  # 네이버는 ms 단위
        }
    except (asyncio.TimeoutError, aiohttp.ClientError):
        return {"distance_meters": None, "duration_seconds": None}


# ============================================
# 2. 여러 병원의 거리 동시 계산 (asyncio.gather)
# ============================================
async def calculate_distances_parallel(
    user_lat: float,
    user_lng: float,
    hospitals: list[dict],
) -> list[dict]:
    """
    여러 병원의 거리를 동시에 계산 (병렬 처리)
    asyncio.gather로 N개 API 호출을 한 번에
    """
    async with aiohttp.ClientSession() as session:
        tasks = [
            get_distance_and_duration(
                session,
                user_lat, user_lng,
                hosp["latitude"], hosp["longitude"]
            )
            for hosp in hospitals
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    # 거리 정보를 각 병원에 합치기
    for hosp, dist_info in zip(hospitals, results):
        hosp["distance_meters"] = dist_info["distance_meters"]
        hosp["duration_seconds"] = dist_info["duration_seconds"]

    return hospitals
