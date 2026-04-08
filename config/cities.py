from dataclasses import dataclass


@dataclass(frozen=True)
class CityConfig:
    slug: str
    name: str
    pinyin: str
    latitude: float
    longitude: float


CITIES = [
    CityConfig("beijing", "北京", "beijing", 39.9042, 116.4074),
    CityConfig("shanghai", "上海", "shanghai", 31.2304, 121.4737),
    CityConfig("hangzhou", "杭州", "hangzhou", 30.2741, 120.1551),
    CityConfig("nanjing", "南京", "nanjing", 32.0603, 118.7969),
    CityConfig("chengdu", "成都", "chengdu", 30.5728, 104.0668),
    CityConfig("chongqing", "重庆", "chongqing", 29.5630, 106.5516),
    CityConfig("xiamen", "厦门", "xiamen", 24.4798, 118.0894),
    CityConfig("qingdao", "青岛", "qingdao", 36.0671, 120.3826),
    CityConfig("xian", "西安", "xian", 34.3416, 108.9398),
    CityConfig("sanya", "三亚", "sanya", 18.2528, 109.5120),
]

CITY_BY_SLUG = {city.slug: city for city in CITIES}
DEFAULT_CITY_SLUG = CITIES[0].slug


def get_city(slug: str) -> CityConfig:
    return CITY_BY_SLUG[slug]
