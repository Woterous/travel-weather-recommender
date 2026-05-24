# AQI 与评分权重方案

## 论文与指标依据

权重设计参考三类研究：

- Mieczkowski 的 Tourism Climatic Index，核心思想是把热舒适、降水、日照和风速组合成旅游气候指数。
- Holiday Climate Index / 后续旅游气候指数研究，继续强调热舒适、审美天气条件、降水和风对旅游体验的影响。
- 中国旅游空气污染研究显示，PM2.5/AQI 会影响游客到访和旅游体验，因此在中国城市旅游推荐中需要加入空气质量指标。

参考来源：

- Open-Meteo Air Quality API: https://open-meteo.com/en/docs/air-quality-api
- Mieczkowski, Z. (1985). The Tourism Climatic Index: https://doi.org/10.1177/004728758502300402
- Holiday Climate Index 相关研究: https://www.mdpi.com/2073-4433/7/6/80
- 空气污染与旅游需求研究: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0304315

## 项目指标映射

| 论文指标 | 项目字段 | 项目评分维度 |
|---|---|---|
| 热舒适 | `avg_temp` | 温度舒适度 |
| 降水 | `precipitation_mm`, `rain_flag` | 降雨风险 |
| 风速 | `wind_speed_kmh`, `wind_level` | 风力舒适度 |
| 日照 / 审美天气 | `weather_type`, `weather_detail` | 天气类型 |
| 目的地气候稳定性 | `history_monthly` | 历史稳定性 |
| 空气污染 | `aqi` | AQI 空气质量 |

## 默认权重

有 AQI 数据时：

| 维度 | 权重 |
|---|---:|
| 温度舒适度 | 0.30 |
| 降雨风险 | 0.22 |
| 历史稳定性 | 0.18 |
| 风力舒适度 | 0.10 |
| 天气类型 | 0.10 |
| AQI 空气质量 | 0.10 |

无 AQI 数据时：

| 维度 | 权重 |
|---|---:|
| 温度舒适度 | 0.33 |
| 降雨风险 | 0.25 |
| 历史稳定性 | 0.20 |
| 风力舒适度 | 0.10 |
| 天气类型 | 0.12 |

系统仍保留用户偏好调节。偏好会在这套论文基础权重上小幅调整，然后统一归一化，保证总权重为 1。
