from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NormalizedLocation:
    raw_value: str
    normalized_country: str | None
    normalized_province: str | None
    normalized_city: str | None
    normalized_district: str | None
    is_unknown: bool = False


CITY_TO_PROVINCE = {
    "北京": "北京",
    "上海": "上海",
    "天津": "天津",
    "重庆": "重庆",
    "广州": "广东",
    "深圳": "广东",
    "佛山": "广东",
    "东莞": "广东",
    "杭州": "浙江",
    "宁波": "浙江",
    "南京": "江苏",
    "苏州": "江苏",
    "成都": "四川",
    "武汉": "湖北",
    "西安": "陕西",
    "郑州": "河南",
    "长沙": "湖南",
    "合肥": "安徽",
    "青岛": "山东",
    "福州": "福建",
    "厦门": "福建",
    "泉州": "福建",
    "漳州": "福建",
}
PROVINCES = {
    "福建",
    "上海",
    "北京",
    "天津",
    "重庆",
    "广东",
    "浙江",
    "江苏",
    "四川",
    "湖北",
    "陕西",
    "河南",
    "湖南",
    "安徽",
    "山东",
}
UNKNOWN_MARKERS = {"", "未知", "unknown", "UNKNOWN", "海外", "境外", "其他"}


def normalize_location_text(value: object) -> NormalizedLocation:
    raw = _clean(value)
    if raw in UNKNOWN_MARKERS:
        return NormalizedLocation(
            raw_value=raw,
            normalized_country=None,
            normalized_province=None,
            normalized_city=None,
            normalized_district=None,
            is_unknown=True,
        )

    text = _normalize_text(raw)
    city = _find_city(text)
    if city is not None:
        return NormalizedLocation(
            raw_value=raw,
            normalized_country="中国",
            normalized_province=CITY_TO_PROVINCE[city],
            normalized_city=city,
            normalized_district=None,
            is_unknown=False,
        )

    province = _find_province(text)
    if province is not None:
        municipality_city = province if province in {"北京", "上海", "天津", "重庆"} else None
        return NormalizedLocation(
            raw_value=raw,
            normalized_country="中国",
            normalized_province=province,
            normalized_city=municipality_city,
            normalized_district=None,
            is_unknown=False,
        )

    return NormalizedLocation(
        raw_value=raw,
        normalized_country=None,
        normalized_province=None,
        normalized_city=None,
        normalized_district=None,
        is_unknown=True,
    )


def _clean(value: object) -> str:
    return str(value or "").strip()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("省", "").replace("市", "")


def _find_city(text: str) -> str | None:
    for city in CITY_TO_PROVINCE:
        if city in text:
            return city
    return None


def _find_province(text: str) -> str | None:
    for province in PROVINCES:
        if province in text:
            return province
    return None
