# Travel Weather Recommender

[English README](README.en.md)

基于天气数据的旅游出行推荐与可视化系统。项目使用 Flask + SQLite 构建本地 Web 应用，结合未来天气、空气质量、历史天气和用户偏好，为可搜索城市生成旅游适宜度排行、城市详情、双城市对比、历史分析和问答式辅助决策。

## 功能概览

- **首页推荐**：按日期和用户偏好展示城市推荐排行、评分构成、天气摘要和 ECharts 图表。
- **城市搜索与城市库**：支持本地行政区划索引和 Open-Meteo Geocoding 查询，搜索到的城市可加入本地城市库。
- **城市详情**：展示单城市未来天气、评分拆解、机器学习预测结果和刷新入口。
- **双城市对比**：按同一天、同一偏好对比两个城市的天气、AQI、规则评分和机器学习预测分。
- **历史分析**：基于历史日天气聚合月度稳定性、舒适天比例和降雨情况。
- **偏好设置**：支持降雨敏感度、温度偏好、风力敏感度、旅行风格和 AQI 敏感度调整。
- **实时刷新进度**：全量刷新和单城市刷新都会通过进度弹窗展示当前阶段。
- **可选自动刷新**：默认关闭；开启后，首页打开时会检查今天是否已经刷新过，过期才自动刷新。
- **本地问答助手**：默认基于 SQLite 中的推荐、AQI、对比和历史数据回答；也预留外部模型接口。

## 技术栈

- Python 3.13
- Flask
- pandas
- requests + BeautifulSoup4
- pypinyin
- SQLite
- HTML / CSS / JavaScript / ECharts

## 数据来源

系统以本地 SQLite 作为页面展示的主数据源。刷新数据时会按城市采集或复用缓存：

- 未来天气网页：tianqi.com 页面数据。
- 未来天气 API：Open-Meteo Forecast API，用于补充温度、降水、风速等字段，也作为网页源不可用时的兜底。
- 空气质量：Open-Meteo Air Quality API。
- 历史天气：Open-Meteo Archive API，用于月度统计和机器学习预测样本。
- 城市搜索：本地 `service/reference/china_admin_geocodes.csv`，必要时再调用 Open-Meteo Geocoding API。

刷新过程会写入 `data/db/weather_recommender.sqlite3`，并保留原始 JSON 与处理后的 CSV。若部分上游数据失败，系统会尽量复用本地缓存或 API 兜底结果，并在刷新日志中记录状态。

## 安装与启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

启动后访问：

```text
http://127.0.0.1:5000/
```

## 刷新数据

### 页面刷新

- 首页按钮可以触发全量刷新。
- 搜索城市或城市详情页可以只刷新单个城市。
- 刷新过程中会显示当前阶段、进度和下一步说明。

### 命令行刷新

```powershell
python scripts/crawl_all.py
```

或：

```powershell
python scripts/build_processed_data.py
```

两个脚本都会调用同一套 `refresh_all_data()` 流程，更新本地 SQLite、原始 JSON 和处理后的 CSV。

### 自动刷新开关

自动刷新默认关闭。需要开启时，修改 `config/refresh.py`：

```python
AUTO_REFRESH_ON_HOME_OPEN = 0  # 默认关闭
AUTO_REFRESH_ON_HOME_OPEN = 1  # 开启首页过期数据自动刷新
```

开启后，只有当最近一次成功或部分成功的刷新记录不是今天时，首页才会自动触发刷新；如果今天已经刷新过，则不会重复请求外部接口。

## 机器学习与评分

系统先用规则权重计算旅游适宜度，再使用历史日天气样本训练轻量 KNN 预测未来天气字段，最后对预测天气重新评分。页面中的对比重点是：

- API 未来天气评分。
- 历史样本预测出的天气字段。
- 机器学习预测天气对应的评分。
- 预测置信度和历史样本量。

评分权重会受用户偏好影响，AQI 不可用时会自动调整权重。详细依据见 `docs/aqi-and-weight-basis.md`。

## 问答助手配置

默认情况下，问答助手只使用本地 SQLite 数据回答，不需要外部密钥。若需要接入外部模型，可通过环境变量或 `config/local_ai.json` 配置：

```powershell
$env:TRAVEL_AI_API_KEY="your-api-key"
$env:TRAVEL_AI_ENDPOINT="https://open.bigmodel.cn/api/paas/v4/chat/completions"
$env:TRAVEL_AI_MODEL="glm-4-flash-250414"
```

可用配置项：

- `TRAVEL_AI_API_KEY` / `GLM_API_KEY` / `ZHIPUAI_API_KEY`
- `TRAVEL_AI_ENDPOINT` / `GLM_ENDPOINT`
- `TRAVEL_AI_MODEL` / `GLM_MODEL`
- `TRAVEL_AI_TIMEOUT` / `GLM_TIMEOUT`
- `TRAVEL_AI_DISABLE=1` 可强制关闭外部模型调用

## 测试

```powershell
python -m pytest
```

当前测试覆盖刷新缓存、城市搜索、偏好权重、机器学习预测、助手接口、页面路由和自动刷新开关等核心行为。

## 主要目录

```text
app.py          Flask 应用入口
config/         城市、数据源、偏好、权重和刷新配置
crawler/        外部天气、空气质量、历史数据抓取
service/        数据清洗、SQLite、评分、排行、搜索、预测和问答逻辑
web/            Flask 路由、模板、静态资源
data/           原始数据、处理数据和 SQLite 数据库
scripts/        手动刷新脚本
docs/           需求、说明、截图和展示材料
tests/          自动化测试
```

## 使用限制

- 外部免费 API 可能限流或临时不可用，项目通过本地缓存和兜底数据降低影响。
- 页面默认读取 SQLite，不会在每次访问时强制全量抓取。
- 自动刷新默认关闭，适合课程演示时按需手动开启。
- 机器学习预测依赖历史样本覆盖情况，样本不足时预测置信度会降低。
