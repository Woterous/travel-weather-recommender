# travel-weather-recommender

基于天气数据的旅游出行推荐与可视化系统。

## 技术栈

- Python 3.13
- Flask
- pandas
- requests + BeautifulSoup4
- SQLite
- HTML / CSS / JavaScript / ECharts

## 功能范围

- 固定 10 城市未来天气推荐
- 历史月度统计分析
- 规则型旅游适宜度评分
- 偏好设置
- 首页兼排行榜
- 城市详情
- 双城市对比
- 历史分析

## 数据策略

- 页面默认只读取本地 SQLite
- 不会在每次打开页面时实时抓取
- 未来天气通过手动刷新更新
- 历史月度统计长期保存在本地
- 抓取失败时保留最近一次成功数据

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

## 刷新数据

```bash
python scripts/crawl_all.py
```

执行后会：

- 抓取未来天气网页数据
- 使用公开 API 补充未来天气风力与降水字段
- 获取历史归档数据并聚合为月度统计
- 保存原始 JSON
- 生成处理后的 CSV
- 写入 `data/db/weather_recommender.sqlite3`

## 启动项目

```bash
python app.py
```

浏览器访问：

```text
http://127.0.0.1:5000/
```

## 主要目录

```text
config/     配置
crawler/    抓取与解析
service/    清洗、评分、排行、历史分析
web/        Flask 路由、模板、静态资源
data/       原始数据、处理数据、SQLite
scripts/    手动执行脚本
docs/       需求、执行规范、验收清单、页面草图
```
