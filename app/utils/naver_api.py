"""
네이버 API 호출 유틸리티
- 지역검색 API (개발자 센터): 근처 동물병원 검색
- Directions 5 API (클라우드 플랫폼): 실제 거리/시간 계산
- 비동기 호출로 여러 병원의 거리를 동시 계산 (asyncio)
"""

import os
import re
import asyncio
import aiohttp
from typing import Optional


# ============================================
# 환경 변수
# ============================================
NAVER_DEV_CLIENT_ID = os.getenv("NAVER_DEV_CLIENT_ID")
NAVER_DEV_CLIENT_SECRET = os.getenv("NAVER_DEV_CLIENT_SECRET")
NAVER_CLOUD_CLIENT_ID = os.getenv("NAVER_CLOUD_CLIENT_ID")
NAVER_CLOUD_CLIENT_SECRET = os.getenv("NAVER_CLOUD_CLIENT_SECRET")

# ============================================
# 0. Reverse Geocoding (좌표 → 행정구역명)
# ============================================
async def reverse_geocode(lat: float, lng: float) -> dict:
    """
    좌표를 행정구역 이름으로 변환
    
    Returns:
        {"city": "서울특별시", "district": "중구"}
        실패 시: {"city": None, "district": None}
    """
    url = "https://maps.apigw.ntruss.com/map-reversegeocode/v2/gc"
    headers = {
        "x-ncp-apigw-api-key-id": NAVER_CLOUD_CLIENT_ID,
        "x-ncp-apigw-api-key": NAVER_CLOUD_CLIENT_SECRET,
    }
    params = {
        "coords": f"{lng},{lat}",   # 네이버 형식: 경도,위도
        "output": "json",
        "orders": "admcode",        # 행정동 코드
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status != 200:
                    return {"city": None, "district": None}
                data = await response.json()
        
        results = data.get("results", [])
        if not results:
            return {"city": None, "district": None}
        
        # 첫 번째 결과의 region 정보
        region = results[0].get("region", {})
        area1 = region.get("area1", {}).get("name")  # 예: "서울특별시"
        area2 = region.get("area2", {}).get("name")  # 예: "중구"
        
        return {"city": area1, "district": area2}
    except (asyncio.TimeoutError, aiohttp.ClientError):
        return {"city": None, "district": None}


# ============================================
# 1. 네이버 지역검색 API
# ============================================
async def search_animal_hospitals(query: str = "동물병원", display: int = 30) -> list[dict]:
    """
    네이버 지역검색 API로 동물병원 목록 가져오기
    
    Returns:
        [{
          "name": "OO동물병원",
          "address": "서울 서초구 ...",
          "phone": "02-XXX-XXXX",
          "latitude": 37.4935,
          "longitude": 127.0245
        }, ...]
    """
    url = "https://openapi.naver.com/v1/search/local.json"
    headers = {
        "X-Naver-Client-Id": NAVER_DEV_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_DEV_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": display,  # 최대 30개
        "sort": "comment",   # 카페/블로그 리뷰 많은 순 (popular한 병원)
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status != 200:
                raise Exception(f"네이버 지역검색 API 실패: {response.status}")
            data = await response.json()
    
    # 응답 파싱
    items = data.get("items", [])
    results = []
    for item in items:
        # 네이버 응답 정리
        # title에 <b>태그 들어있어서 제거
        name = re.sub(r"<[^>]+>", "", item.get("title", ""))
        
        # mapx, mapy는 KATEC 좌표가 아닌 위경도 (네이버가 1e7 곱한 정수로 줌)
        mapx = item.get("mapx", "0")
        mapy = item.get("mapy", "0")
        try:
            longitude = int(mapx) / 1e7
            latitude = int(mapy) / 1e7
        except (ValueError, TypeError):
            continue  # 좌표 이상하면 스킵
        
        results.append({
            "name": name,
            "address": item.get("roadAddress") or item.get("address", ""),
            "phone": item.get("telephone", ""),
            "latitude": latitude,
            "longitude": longitude,
        })
    

    return results

# ============================================
# 1-2. 검색어 다양화 - 여러 검색어 병렬 호출 + 중복 제거
# ============================================
async def search_hospitals_with_multiple_queries(district: str, city: str = None) -> list[dict]:
    """
    네이버 지역검색 API의 5개 한계를 극복하기 위해
    여러 검색어로 동시 호출 + 중복 제거
    
    예: district="중구"
        → "중구 동물병원", "중구 수의사", "중구 24시 동물병원", "중구 강아지 병원"
        → 총 4 × 5 = 최대 20개 (중복 제거 후 보통 10~15개)
    """
    # 검색어 4개 생성
    if district:
        queries = [
            f"{district} 동물병원",
            f"{district} 수의사",
            f"{district} 24시 동물병원",
            f"{district} 강아지 병원",
        ]
    elif city:
        queries = [
            f"{city} 동물병원",
            f"{city} 수의사",
            f"{city} 24시 동물병원",
            f"{city} 강아지 병원",
        ]
    else:
        # fallback
        queries = ["동물병원", "수의사", "24시 동물병원", "강아지 병원"]
    
    # 4개 검색어 병렬 호출 (asyncio.gather)
    tasks = [search_animal_hospitals(query=q) for q in queries]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 결과 합치기 + 중복 제거 (이름 + 좌표 기준)
    seen = set()
    merged = []
    for results in results_list:
        # 예외 발생한 경우 스킵
        if isinstance(results, Exception):
            continue
        for hospital in results:
            # 중복 키: 이름 + 좌표 (소수점 4자리)
            key = (
                hospital["name"].replace(" ", ""),
                round(hospital["latitude"], 4),
                round(hospital["longitude"], 4),
            )
            if key not in seen:
                seen.add(key)
                merged.append(hospital)
    
    return merged


# ============================================
# 2. 네이버 Directions 5 API (단일 호출)
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
# 3. 여러 병원의 거리 동시 계산 (asyncio.gather)
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