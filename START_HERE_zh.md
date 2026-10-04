# Beverage Demand & Supply Intelligence — 第一个可运行 Pipeline

目标：从新加坡政府 API 取回公共假日，保存原始 JSON，使用 Python 校验和整理，写入 MySQL，再用 SQL 查询和导出结果。运行成功后，你拥有可复用的外部数据接入模块；预测、库存建议和 AI 问答是后续阶段。

本教程沿用 Windows + PowerShell + MySQL。Python 3.10 以上（建议 3.12），MySQL Server 8.0 以上；MySQL 服务需要已经安装并运行。MySQL Workbench 只是客户端，安装 Python 驱动也不会安装 MySQL Server。

## 0. 先解释你遇到的错误

- `NameError: name 'requests' is not defined`：当前 Python 文件或当前 Notebook 会话没有先执行 `import requests`。
- `ModuleNotFoundError: No module named 'requests'`：当前运行代码的 Python 环境没有安装 requests。
- `NameError: name 'url' is not defined`：使用 url 之前没有给这个变量赋值。
- `requests.get(...)` 中的 `...` 不是网址。上一轮它只是示意，不能直接作为完整程序运行。

安装和导入是两件事：安装让环境拥有这个包，import 让当前程序能使用它。不要把文件命名为 `requests.py`、`mysql.py`、`json.py`，这些名字会遮住要导入的包。

## 1. 把文件放到现有项目

保留你已经写好的 README.md。将压缩包中的以下内容放进同一个项目根目录：

| 文件 | 用途 |
|---|---|
| requirements.txt | 安装两个第三方依赖 |
| scripts/holiday_pipeline.py | 完整可运行 Python 程序 |
| sql/00_create_database.sql | 首次建立项目数据库 |
| sql/01_verify_and_analyse.sql | 在 MySQL 中验证并分析 |
| START_HERE_zh.md | 本说明 |
| docs/data_contract.md | 字段定义及下一步数据库接口 |
| docs/validation_notes.md | 已完成和仍需本地完成的检查 |
| tests/test_holiday_pipeline.py | 可选的离线逻辑测试 |
| .gitignore | 避免提交环境、密码文件和运行产物 |

如果已有同名 requirements.txt 或 .gitignore，将新条目合并进去；不要直接覆盖原文件。原始 JSON、整理后的 CSV 和分析输出会在运行时自动生成，不需要手动建目录。

VS Code → File → Open Folder → 选择你的项目文件夹 → Terminal → New Terminal。下文标注 PowerShell 的命令都在这个终端运行。先用 `Get-Location` 查看位置，用 `Get-ChildItem` 确认能看到 `requirements.txt` 和 `scripts`。

不要在 `mysql>` 或 Python 的 `>>>` 后面运行 PowerShell 命令。已进入 Python 交互模式时，先执行 `exit()` 返回 PowerShell。

## 2. 安装依赖（PowerShell）

依次执行：

```powershell
py --version
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import requests; import mysql.connector; print('Imports OK')"
```

最后一行应出现 `Imports OK`。如果 `py` 无法识别，但 `python --version` 能显示 Python 3.10 以上，将前两行的 `py` 换成 `python`。如果两者都无法识别，需要先安装 Python 并重新打开 VS Code。已有可用 `.venv` 时可以跳过创建步骤。

本教程直接指定 `.venv` 中的 Python，无须激活环境，因此也无需修改 PowerShell 执行策略。后面的每次运行都用同一个解释器。不要只用一个不确定属于哪个 Python 的 `pip install`。

## 3. 单独看清 requests.get 的完整用法（可选练习）

以下代码是完整的 API 小实验，没有省略变量或 import。保存为 `scripts/api_smoke_test.py` 后运行：

```python
import json
import requests

url = "https://data.gov.sg/api/action/datastore_search"
params = {
    "resource_id": "d_8ef23381f9417e4d4254ee8b4dcdb176",
    "limit": 5,
    "offset": 0,
}

response = requests.get(url, params=params, timeout=30)
response.raise_for_status()
payload = response.json()

if payload.get("success") is not True:
    raise RuntimeError(f"API returned an error: {payload}")

records = payload["result"]["records"]
print("HTTP status:", response.status_code)
print("Total source rows:", payload["result"]["total"])
print(json.dumps(records, ensure_ascii=False, indent=2))
```

```powershell
.\.venv\Scripts\python.exe scripts\api_smoke_test.py
```

这只是预览前 5 行。完整程序会处理分页。数据集网页给出的字段是 `date`、`day`、`holiday`，接口另带 `_id`。

| 表达式 | 实际含义 |
|---|---|
| requests.get(...) | 发出 HTTP GET 请求，拿到 HTTP 响应对象 |
| response.raise_for_status() | HTTP 错误时停止，避免把错误页面当成数据 |
| response.json() | 把 JSON 响应解析为 Python dict/list |
| payload["result"]["records"] | 从响应外层信息中取出业务记录列表 |
| json.dumps(...) | 把 Python 对象序列化为 JSON 文本，方便展示或保存 |

API 网页显示 HTTP 200 并不保证业务成功，所以还要检查 `success`。JSON 是数据交换格式，不是数据库；`response.json()` 也不会自动写入 SQL。

## 4. 跑通 API → JSON → Python（PowerShell）

运行包里已经写好的完整脚本：

```powershell
.\.venv\Scripts\python.exe scripts\holiday_pipeline.py --extract-only
```

这个模式不连接 MySQL。它执行：

1. 调用官方 API，按 `_id` 排序，逐页获取，每页最多 100 条。
2. 保存每页原始响应到 `data/raw/本次运行时间/`。
3. 核对实际取得行数与 API 声明的总数，检查跨页 `_id` 重复。
4. 校验日期格式与假日名称；只去掉完全相同的国家、日期、名称组合。
5. 生成 `data/processed/sg_public_holidays.csv`。

2026-10-04 的实际运行日志：

```text
Fetched 100/104 records
Fetched 104/104 records
Validated 104 rows; removed 0 exact duplicates
Date range: 2020-01-01 to 2027-12-25
EXTRACT OK. Next: create the database, then run without --extract-only.
```

路径信息和前 5 行也会打印出来。104 是这次实际取得的行数，不是永久写死的答案。官方更新以后可能变化，程序按 API 的总数检查。

最后一个假日日期为 2027-12-25，不代表数据只覆盖到 12 月 25 日：官网标注覆盖至 2027 年 12 月。覆盖范围和最后一条事件日期是不同概念。

如果这一步失败，先处理报错，不要继续建销售模型。原始 JSON 保存的是成功收到的响应；若中途失败，可能留下不完整的运行目录，没有 manifest.json 的目录不代表一次完整取数。

## 5. 创建数据库（MySQL Workbench 或 mysql>）

打开你现有的本地 MySQL 连接，新建 SQL 查询窗口，运行：

```sql
CREATE DATABASE IF NOT EXISTS beverage_intelligence
  CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE beverage_intelligence;
SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;
```

也可以打开 `sql/00_create_database.sql`，运行整个文件。你应看到数据库名 `beverage_intelligence` 和服务器版本。

此时还没有假日表，这是正常的：下一步 Python 会创建 `stg_public_holidays`。如果你用的是 MySQL 命令行，可在独立 PowerShell 窗口运行 `mysql -u root -p`；如果 `mysql` 不在 PATH，直接使用已安装的 MySQL Workbench 即可，不需要为此修改本教程。

## 6. 跑通完整链路（回到 PowerShell）

```powershell
.\.venv\Scripts\python.exe scripts\holiday_pipeline.py
```

程序会重新取数和清洗，然后提示：

```text
MySQL password for root:
```

输入你本机 MySQL 的密码并按 Enter。输入时不显示字符是正常现象。密码不是 GitHub 密码，也不会写入脚本。

默认连接参数：host=`127.0.0.1`，port=`3306`，user=`root`，database=`beverage_intelligence`。这是沿用你本地学习环境的默认值。若已有专用 MySQL 用户或端口，使用参数，比如用户名确实为 beverage_user、端口确实为 3307 时：

```powershell
.\.venv\Scripts\python.exe scripts\holiday_pipeline.py --user beverage_user --port 3307
```

这条命令不会创建该用户。使用的账户须能在项目库中 CREATE、SELECT、INSERT、DELETE。不要为了运行脚本向别人发送密码。

程序创建假日暂存表，然后在同一个事务里刷新这个来源的 SG 假日数据。写入数量不一致或 SQL 失败时回滚数据刷新。建表属于独立步骤，失败后可能保留一张空表，这是预期的。

重复运行时，先删除**这个来源在这张暂存表中的 SG 快照**，再写入新快照，因此来源更正或删掉的假日不会残留。不是追加日志；不要在这张表里手工维护其他 SG 来源。原始 JSON 每次另存。请一次只运行一个实例。

成功后应出现：

```text
Committed 104 rows to beverage_intelligence.stg_public_holidays
calendar_year | holiday_records | holiday_dates
```

随后是各年统计、输出 CSV 路径以及 `PIPELINE OK`。这里的 104 随来源更新变化。最终生成 `outputs/holiday_summary.csv`，可用 Excel 打开。

注意：如果已经看到 `Committed`，随后 CSV 导出报错，数据可能已经成功入库。比如 Excel 正占用输出文件时，先关闭它再运行；不用删除数据库重来。

## 7. 用 SQL 验证并分析（MySQL）

打开 `sql/01_verify_and_analyse.sql`，运行全部查询。至少确认：

- `row_count` 等于 Python 输出的有效行数。
- 前 10 行有国家、日期、假日名、取数时间。
- 每年的 `holiday_records` 和 `holiday_dates` 能正常返回。
- 再跑一次完整脚本后，来源没有变化时，总行数不翻倍。

同一天可能对应两个不同假日，`COUNT(*)` 是假日记录数，`COUNT(DISTINCT holiday_date)` 才是假日日期数。不能把两者混为一谈。

本阶段的 analytics 是日历覆盖与假日分布分析。它还不能回答“假日让啤酒销量提高多少”，因为我们还没有销售数据。也不能把节假日前后销量差异直接称为因果效果。

## 8. 下一步数据库怎么衔接

当前表名的 `stg` 表示 staging：整理过的来源数据层。它不是完整日期维度，因为只含假日，没有普通工作日。

下一步先定义业务场景、数据来源与表的粒度，再设计：

- `dim_date`：每天一行，包含完整日期序列。
- `dim_product`：每个 SKU 一行；单瓶、整箱等单位要明确定义。
- `dim_location`：门店/仓库身份及类型，后续按业务需要拆分。
- `fact_sales`：先确定日 × SKU × 销售地点等粒度。
- `fact_inventory`：日 × SKU × 仓库的库存快照。
- `fact_forecast`：保留预测生成日、预测目标日、SKU/地点，方便真正的回测。

假日数据将生成新加坡日历标记。将假日先按国家和日期聚合成每天一行，或使用 EXISTS，再标记销售日期；不能直接把销售表 JOIN 到未聚合的假日表，导致同一天多个假日把销量复制多次。

假日来源覆盖范围以外的日期应为未知，不应自动标记为“非假日”。公共假日也不等于所有供应商、门店和仓库的休息日；后续需要独立业务日历。

数据场景需要纠正：Kaggle Store Sales 是厄瓜多尔的真实零售数据，不能直接贴上新加坡日期、天气来解释真实需求。为了做新加坡饮料场景，我们可以构造明确标注 synthetic 的销售、库存、交期数据；如果选择 Kaggle 的真实数据，就采用其真实国家和历史时间范围。模拟数据不能用于声称获得真实 APB 收益。

## 9. 整个平台分阶段推进

| 阶段 | 交付内容 | 完成标准 |
|---|---|---|
| 1 当前 | 假日 API → MySQL → SQL 分析 | PIPELINE OK，行数正确，重复运行不累加 |
| 2 | 业务问题、数据字典、数据库设计 | 每张表的粒度、主外键、单位和来源明确 |
| 3 | 销售、库存和交期接入 | 日期与 SKU 对齐，库存和销售口径可核对 |
| 4 | 基础预测与补货规则 | 按时间切分回测、与简单基线比较；考虑在途和到货日 |
| 5 | Power BI | 业务指标可追溯到 SQL，展示异常与建议 |
| 6 | AI 查询助手 | 通过受控查询引用真实计算结果，缺数据时说明限制 |
| 7 | Business case、UAT、演示 | 模拟收益与实测指标区分，验收测试和用户操作演示完整 |

先把一个场景做成可演示的最小版本，再扩展天气、复杂模型、云端部署。此包仅完成阶段 1 所需代码，不应把后续功能写成已完成。

## 10. 放入 GitHub

如果已经是 clone 下来的 GitHub 仓库，并已经配置 remote，可以在项目根目录执行：

```powershell
git status
git add .gitignore requirements.txt scripts/holiday_pipeline.py sql/00_create_database.sql sql/01_verify_and_analyse.sql START_HERE_zh.md docs tests
git diff --cached --stat
git commit -m "Add Singapore holiday API to MySQL pipeline"
git push
```

先检查暂存内容，确认没有密码、`.venv` 或无关文件。`git push` 如果提示没有 upstream 或 remote，请把报错给我，根据现有分支处理，不要猜测仓库地址。未 clone 的仓库也不必为本阶段先解决 Git；本地跑通后再上传。

README 更新建议在本地 MySQL 验收通过后使用：

> Implemented a paginated Singapore public-holiday API pipeline with raw JSON snapshots, Python validation, transactional MySQL staging refreshes, and SQL calendar summaries. Demand forecasting, inventory planning and an AI assistant are planned next.

如果只完成了 --extract-only，就只写 API extraction and validation，不要写已经完成 MySQL 链路。

## 11. 排错表

| 报错/现象 | 处理 |
|---|---|
| requests is not defined | 当前脚本顶部加 import requests；完整运行文件，不要只选中一行 |
| No module named requests/mysql | 用 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` 安装，然后用同一个解释器运行 |
| py 无法识别 | 尝试 python --version；都不可用时安装 Python 并重开终端 |
| can't open file | 检查当前目录与文件名，确认不是 `.py.txt` |
| MySQL 1045 Access denied | 核对用户名和本地 MySQL 密码；不要贴出密码 |
| MySQL 1049 Unknown database | 先在同一台 MySQL 服务器运行建库 SQL |
| MySQL 2003 / 10061 | 检查 MySQL Server 服务、host 和 port；Workbench 能否连接 |
| MySQL 1142 permission denied | 使用有项目库建表和读写权限的已有账户 |
| HTTP 429 | 请求限流，脚本会有限重试；不要反复立即运行 |
| HTTP 403/404/5xx | 检查数据集官网是否可用及错误文本，不要把空响应入库 |
| SSLError / timeout | 检查网络、代理和系统时间；不要通过关闭 TLS 校验来解决 |
| Pagination/schema validation error | API 结构或数据可能变化，把错误文本和 manifest/字段名发来检查 |
| PermissionError 导出 CSV | 关闭 Excel 中正在打开的输出文件后重跑 |
| 看不到 MySQL 密码输入 | getpass 默认不回显字符，正常输入后回车 |

本地运行失败时，请发运行命令、完整 Traceback 和 Python 版本，不要发送密码。

## 12. 来源与验证边界

核对日期：2026-10-04。

- 数据来源：[MOM — Singapore Public Holidays (consolidated)](https://data.gov.sg/datasets/d_8ef23381f9417e4d4254ee8b4dcdb176/view)。来源页面注明 2020–2027，104 行，Singapore Open Data Licence。引用数据时保留来源与获取日期。
- [官方分页 API 文档](https://guide.data.gov.sg/developer-guide/dataset-apis/search-and-filter-within-dataset)。API 参数为 resource_id、limit、offset、sort。
- [官方 API 概览](https://guide.data.gov.sg/developer-guide/api-overview)。本示例无需 API key 即可测试；已在本次实际匿名请求中验证。
- [MySQL 官方 Connector/Python 连接文档](https://dev.mysql.com/doc/connector-python/en/connector-python-example-connecting.html)。

已经实际完成外部 API 取数、两页 JSON 保存、104 行清洗及 7 项离线逻辑检查。当前执行环境没有 MySQL Server，因此没有宣称真实 MySQL 集成测试通过；真实 SQL 语法执行、账户权限、连接和事务行为需按上文在你本机完成验收。离线测试使用模拟连接，不等同于真实数据库测试。

以下附录给出文件的完整内容；正常操作只需要运行包内脚本，不需要从附录重新抄写。


## 附录 A：完整 Python 程序

文件：`scripts/holiday_pipeline.py`

```python
"""Singapore holiday API -> JSON -> validated Python rows -> MySQL -> CSV.

Python 3.10+; local MySQL 8.0+. Run from a terminal, not a SQL editor.
Run only one instance at a time. This is a learning/local portfolio pipeline.
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime, timezone
from getpass import getpass
from pathlib import Path

import mysql.connector
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://data.gov.sg/api/action/datastore_search"
DATASET_ID = "d_8ef23381f9417e4d4254ee8b4dcdb176"
DATABASE = "beverage_intelligence"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stg_public_holidays (
    country_code CHAR(2) NOT NULL,
    holiday_date DATE NOT NULL,
    holiday_name VARCHAR(200) NOT NULL,
    source_dataset_id VARCHAR(50) NOT NULL,
    fetched_at_utc DATETIME(6) NOT NULL,
    PRIMARY KEY (country_code, holiday_date, holiday_name),
    INDEX idx_holiday_source (source_dataset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
"""

SUMMARY_SQL = """
SELECT YEAR(holiday_date) AS calendar_year,
       COUNT(*) AS holiday_records,
       COUNT(DISTINCT holiday_date) AS holiday_dates
FROM stg_public_holidays
WHERE country_code = %s AND source_dataset_id = %s
GROUP BY YEAR(holiday_date)
ORDER BY calendar_year
"""


def fetch_holidays():
    """Fetch all pages; keep original response payloads for inspection."""
    fetched_at = datetime.now(timezone.utc)
    run_dir = ROOT / "data" / "raw" / fetched_at.strftime("%Y%m%dT%H%M%S_%fZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    records = []
    offset = 0
    expected_total = None
    retry = Retry(total=3, backoff_factor=1,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"], respect_retry_after_header=True)

    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        while True:
            response = session.get(
                API_URL,
                params={"resource_id": DATASET_ID, "limit": 100,
                        "offset": offset, "sort": "_id asc"},
                timeout=(10, 30),
            )
            response.raise_for_status()
            payload = response.json()
            (run_dir / f"page_{offset:06d}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise ValueError("API returned success=false or an unexpected structure.")
            result = payload.get("result")
            if not isinstance(result, dict):
                raise ValueError("API response is missing the result object.")
            batch = result.get("records")
            total = result.get("total")
            if not isinstance(batch, list) or type(total) is not int or total <= 0:
                raise ValueError("Missing records/total or an empty source dataset.")
            if expected_total is None:
                expected_total = total
            if total != expected_total:
                raise ValueError("Source row count changed during pagination. Run again.")
            if not batch:
                raise ValueError("Pagination ended before all source rows were received.")
            records.extend(batch)
            offset += len(batch)
            print(f"Fetched {offset}/{total} records")
            if offset == total:
                break
            if offset > total:
                raise ValueError("Received more rows than the API total.")

    ids = [row.get("_id") for row in records if isinstance(row, dict)]
    if len(ids) != len(records) or any(x is None for x in ids):
        raise ValueError("Source rows are missing their _id values.")
    if len(set(ids)) != len(ids):
        raise ValueError("Repeated source row IDs across pages; rerun the extract.")
    (run_dir / "manifest.json").write_text(json.dumps({
        "api_url": API_URL, "dataset_id": DATASET_ID,
        "fetched_at_utc": fetched_at.isoformat(), "source_rows": len(records),
    }, indent=2), encoding="utf-8")
    print(f"Raw JSON: {run_dir}")
    return records, fetched_at


def clean_holidays(records, fetched_at):
    """Grain: one country, one date, one named holiday (not just one date)."""
    cleaned = {}
    for record in records:
        row = {str(k).strip().lower(): v for k, v in record.items()}
        if not isinstance(row.get("date"), str) or not isinstance(row.get("holiday"), str):
            raise ValueError("Every source row must have text date and holiday fields.")
        day = date.fromisoformat(row["date"].strip())
        name = " ".join(row["holiday"].split())
        if not name or len(name) > 200:
            raise ValueError("Holiday name is empty or exceeds 200 characters.")
        key = ("SG", day, name)
        cleaned[key] = (*key, DATASET_ID, fetched_at.replace(tzinfo=None))
    if not cleaned:
        raise ValueError("No validated rows; refusing to refresh the database.")
    rows = [cleaned[key] for key in sorted(cleaned)]
    path = ROOT / "data" / "processed" / "sg_public_holidays.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["country_code", "holiday_date", "holiday_name",
                         "source_dataset_id", "fetched_at_utc"])
        writer.writerows(rows)
    print(f"Validated {len(rows)} rows; removed {len(records) - len(rows)} exact duplicates")
    print(f"Date range: {rows[0][1]} to {rows[-1][1]}")
    print(f"Clean CSV: {path}")
    for row in rows[:5]:
        print(row[:3])
    return rows


def load_and_analyse(rows, host, port, user):
    password = getpass(f"MySQL password for {user}: ")
    connection = mysql.connector.connect(
        host=host, port=port, user=user, password=password,
        database=DATABASE, charset="utf8mb4", connection_timeout=10,
        autocommit=False,
    )
    cursor = connection.cursor()
    try:
        cursor.execute(CREATE_TABLE_SQL)
        connection.commit()  # DDL is outside the data-refresh transaction.
        connection.start_transaction()
        try:
            # Replace only this source's SG staging snapshot, atomically.
            cursor.execute(
                "DELETE FROM stg_public_holidays "
                "WHERE country_code = %s AND source_dataset_id = %s",
                ("SG", DATASET_ID),
            )
            cursor.executemany(
                "INSERT INTO stg_public_holidays "
                "(country_code, holiday_date, holiday_name, "
                "source_dataset_id, fetched_at_utc) VALUES (%s, %s, %s, %s, %s)",
                rows,
            )
            cursor.execute(
                "SELECT COUNT(*) FROM stg_public_holidays "
                "WHERE country_code = %s AND source_dataset_id = %s",
                ("SG", DATASET_ID),
            )
            if cursor.fetchone()[0] != len(rows):
                raise ValueError("Database row-count validation failed.")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        print(f"Committed {len(rows)} rows to {DATABASE}.stg_public_holidays")

        cursor.execute(SUMMARY_SQL, ("SG", DATASET_ID))
        summary = cursor.fetchall()
        output = ROOT / "outputs" / "holiday_summary.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([column[0] for column in cursor.description])
            writer.writerows(summary)
        print("calendar_year | holiday_records | holiday_dates")
        for year, record_count, date_count in summary:
            print(f"{year} | {record_count} | {date_count}")
        print(f"Analysis CSV: {output}")
    finally:
        cursor.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-only", action="store_true",
                        help="Fetch and clean data without connecting to MySQL")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    args = parser.parse_args()
    records, fetched_at = fetch_holidays()
    rows = clean_holidays(records, fetched_at)
    if args.extract_only:
        print("EXTRACT OK. Next: create the database, then run without --extract-only.")
        return
    load_and_analyse(rows, args.host, args.port, args.user)
    print("PIPELINE OK")


if __name__ == "__main__":
    try:
        main()
    except (requests.RequestException, mysql.connector.Error, ValueError, OSError) as exc:
        print(f"ERROR [{type(exc).__name__}]: {exc}", file=sys.stderr)
        sys.exit(1)
```


## 附录 B：完整依赖清单

文件：`requirements.txt`

```text
requests==2.34.2
mysql-connector-python==26.7.0
```


## 附录 C：完整建库 SQL

文件：`sql/00_create_database.sql`

```sql
-- Run in MySQL Workbench or at the mysql> prompt, not in PowerShell.
CREATE DATABASE IF NOT EXISTS beverage_intelligence
  CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE beverage_intelligence;
SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;
```


## 附录 D：完整验证与分析 SQL

文件：`sql/01_verify_and_analyse.sql`

```sql
USE beverage_intelligence;

-- Preview the source staging table.
SELECT country_code, holiday_date, holiday_name, fetched_at_utc
FROM stg_public_holidays
ORDER BY holiday_date, holiday_name
LIMIT 10;

-- Compare row_count with the Python 'Validated ... rows' message.
SELECT COUNT(*) AS row_count,
       MIN(holiday_date) AS earliest_holiday,
       MAX(holiday_date) AS latest_holiday
FROM stg_public_holidays
WHERE country_code = 'SG'
  AND source_dataset_id = 'd_8ef23381f9417e4d4254ee8b4dcdb176';

-- Calendar exploration: these are NOT sales or demand results.
SELECT YEAR(holiday_date) AS calendar_year,
       COUNT(*) AS holiday_records,
       COUNT(DISTINCT holiday_date) AS holiday_dates
FROM stg_public_holidays
WHERE country_code = 'SG'
GROUP BY YEAR(holiday_date)
ORDER BY calendar_year;

-- Count holiday dates in each month of the planning year.
SELECT MONTH(holiday_date) AS calendar_month,
       COUNT(DISTINCT holiday_date) AS holiday_dates
FROM stg_public_holidays
WHERE country_code = 'SG'
  AND holiday_date >= '2026-01-01' AND holiday_date < '2027-01-01'
GROUP BY MONTH(holiday_date)
ORDER BY calendar_month;

-- Multiple holidays on a date are valid, not necessarily duplicates.
SELECT holiday_date, COUNT(*) AS names_on_date
FROM stg_public_holidays
WHERE country_code = 'SG'
GROUP BY holiday_date
HAVING COUNT(*) > 1;
```
