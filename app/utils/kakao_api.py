"""
카카오맵 로컬 검색 API 호출 유틸리티
- 위치 기반 동물병원 검색 (좌표 + 반경 직접 지원)
- 페이지네이션으로 최대 45개까지 가져옴
"""

import os
import asyncio
import aiohttp


# ============================================
# 환경 변수
# ============================================
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")


# ============================================
# 1. 카카오 로컬 키워드 검색 API (단일 페이지)
# ============================================
async def _search_one_page(
    session: aiohttp.ClientSession,
    query: str,
    lat: float,
    lng: float,
    radius: int,
    page: int = 1,
) -> dict:
    """
    카카오 로컬 키워드 검색 - 한 페이지
    
    Returns:
        {"documents": [...], "is_end": True/False}
    """
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {
        "Authorization": f"KakaoAK {KAKAO_REST_API_KEY}",
    }
    params = {
        "query": query,
        "x": str(lng),       # 카카오: x=경도, y=위도
        "y": str(lat),
        "radius": str(min(radius, 20000)),  # 카카오 최대 20km
        "size": 15,          # 한 페이지 15개 (최대)
        "page": page,        # 1~3 (총 45개)
        "sort": "distance",  # 거리순
        "category_group_code": "HP8",  # 병원 카테고리 (동물병원 포함)
    }
    
    try:
        async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=5)) as response:
            if response.status != 200:
                return {"documents": [], "is_end": True}
            data = await response.json()
        
        return {
            "documents": data.get("documents", []),
            "is_end": data.get("meta", {}).get("is_end", True),
        }
    except (asyncio.TimeoutError, aiohttp.ClientError):
        return {"documents": [], "is_end": True}


# ============================================
# 2. 카카오 동물병원 검색 (전체)
# ============================================
async def search_hospitals_kakao(
    lat: float,
    lng: float,
    radius: int = 3000,
) -> list[dict]:
    """
    카카오 로컬 검색으로 근처 동물병원 가져오기
    - 위치 기반 (좌표 + 반경)
    - 거리순 정렬
    - 페이지네이션으로 최대 45개
    
    Returns:
        [{
          "name": "OO동물병원",
          "address": "서울 ...",
          "phone": "02-XXX-XXXX",
          "latitude": 37.4935,
          "longitude": 127.0245,
          "kakao_distance": 1234,  # 카카오가 알려주는 직선 거리(m)
        }, ...]
    """
    async with aiohttp.ClientSession() as session:
        # 첫 페이지 호출
        first = await _search_one_page(session, "동물병원", lat, lng, radius, page=1)
        all_documents = first["documents"]
        
        # is_end가 False면 추가 페이지도 가져오기 (최대 3페이지 = 45개)
        if not first["is_end"]:
            tasks = [
                _search_one_page(session, "동물병원", lat, lng, radius, page=p)
                for p in [2, 3]
            ]
            extra_results = await asyncio.gather(*tasks, return_exceptions=False)
            for result in extra_results:
                all_documents.extend(result["documents"])
                if result["is_end"]:
                    break
    
    # 응답 파싱
    results = []
    seen_ids = set()  # 중복 제거 (페이지 간)
    for doc in all_documents:
        place_id = doc.get("id")
        if place_id in seen_ids:
            continue
        seen_ids.add(place_id)
        
        try:
            longitude = float(doc.get("x", 0))
            latitude = float(doc.get("y", 0))
            distance = int(doc.get("distance", 0))  # 카카오는 미터 단위
        except (ValueError, TypeError):
            continue
        
        results.append({
            "name": doc.get("place_name", ""),
            "address": doc.get("road_address_name") or doc.get("address_name", ""),
            "phone": doc.get("phone", ""),
            "latitude": latitude,
            "longitude": longitude,
            "kakao_distance": distance,
        })
    
    return results