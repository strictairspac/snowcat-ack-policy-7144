# 雪榆山场·压雪班同步写入窗口

回放夜间压雪班的副本落盘和答复时间，识别故障时可恢复的工作凭条及降级确认风险。

## 业务流程

1. 雪道值班台
2. 维护剧本
3. 确认回放
4. 交班风险

顺序落盘离散时间模型、同步确认门槛和目标副本缺失核算。

值守过去只盯备机总体延迟，交班时无法区分可降级和必保写入、找不到在故障前真正答复的凭条，还会把另一台机房的持久化能力错算给计划恢复机房。上游输入是压雪班次提交记录和机房维护窗，下游由场务与值守共同决定是否授权降级。

21:00 打开 snow-grooming-window-1124.json 对应的北坡维护卷。21:05 检查两条副本的中断区间。21:08 标记 SN-109 必须同步。21:10 设置 25 毫秒降级等待。21:15 回放 105 毫秒故障点。21:17 核对北坡恢复缺失 SN-108 与 SN-110。21:20 改从山脚对照并导出交班证据。

本机按到达顺序串行落盘。备机收到本机已落盘的记录后，也按该顺序消耗自己的持续服务时间，中断期间暂停。第 N 快备机落盘时点是严格同步答复点。可降级记录到达本机落盘后超时可本地答复。故障前已答复且目标未落盘才计入该目标的确认损失。模拟将落盘和答复时点等于故障时刻的事件计入已发生。

这是应用策略和有序复制的时间演练。恢复来源由剧本给定，未启动真实备机，也不执行选主或引擎级同步模式切换。

## 启动

```sh
cp -n .env.example .env
docker compose config --quiet
docker compose up -d --build --wait
```

打开 <http://localhost:18314>。OpenAPI 在 <http://localhost:19314/docs>，数据库映射到本机 17814。所有暴露端口只绑定回环地址。Compose 启动 frontend、backend、worker、db、redis，各自通过健康探针检查。数据库、Redis 和共享产物目录各有命名卷；任务状态及导出内容以数据库中的证据为准。

首次启动时幂等载入演示数据。手动载入可运行 `docker compose exec -T backend python -m scripts.seed_demo`。常规停止可用 `docker compose down`。验收环境清理才加 `-v`，它会删除本项目的数据卷。

## 角色与交接

演示账号共用口令 `Demo-DbWorkbench-2026`。

| 登录名 | 角色 | 可执行操作 |
|---|---|---|
| operator | 资料操作员 | 登记业务资料、设置「可降级写入的等待时限（毫秒）」、提交、查看和下载结果 |
| reviewer | 业务复核员 | 查看执行证据、签署单次复核、下载交接单 |
| viewer | 只读观察员 | 查看资料、执行结果及审计，下载证据 |

选用「snow-grooming-window-1124.json」对应的演示资料，保存一份复演资料，再以默认参数 25 提交。worker 保存结果摘要、业务明细和 SHA-256。复核员登录后在「交班风险」签署。

## 续演与正式交班

已完成（`done`）的故障批次可以作为下一场的来源。交班时只读取选定副本在故障时刻（含等于故障点）已经落盘的凭条，并按原顺序作为下一场的继承补齐队列；模拟时先处理这段继承队列，再处理新剧本写入，两段都使用下一场剧本中的维护窗。

前一场已答复、但选定副本在故障时仍缺失的凭条会进入正式交班清单。清单按丢失事件累积而不是按凭条号去重，因此同号重写不会删除旧记录；每条记录保留来源批次、资料和「丢失场次」。跨多场续演时，旧丢失记录会继续带到后续交班清单。

每个来源批次只能形成一份正式交班和一个正式续演批次。操作员可在证据页的「正式交班与续演」提交下一场剧本，也可使用：

- `GET /runs/{run_id}/handoff/preview?replica=...`：预览交班清单；
- `POST /runs/{run_id}/continue`：提交续演，重复请求返回同一批次；
- `POST /runs/{run_id}/handoff` 与 `POST /handoffs/{handoff_id}/continue`：分两步办理正式交班；
- `POST /runs/{run_id}/retry`：将失败批次按原 ID 重新入队，不新增批次。

并发续演由来源批次行锁和 `handoffs.source_run_id` 唯一约束兜底；竞争失败的同请求重试会读取首份正式交班及其批次。

## 开发说明

| 部分 | 实现 |
|---|---|
| 前端 | 原生 HTML、CSS、JavaScript ES Modules、Nginx |
| 后端 | Python 3.11、FastAPI、SQLAlchemy、JWT |
| 数据库 | PostgreSQL 16 |
| 后台执行 | Redis 通知、数据库持久任务队列和行锁、Python worker |

从 `backend/src/domain/scenario.py` 修改业务入口和演示口径，运行 `docker compose up -d --build --wait` 查看变更。数据库表结构在 `backend/src/models` 和 `backend/migrations`，输入模型在 `backend/src/schemas`。业务页和请求接口在 `frontend/src/pages`、`frontend/src/api`。资料、执行、复核三个工作流实体各有独立表和 API；场景输入及结果保留在所属资料和批次中。

角色枚举在 `backend/src/constants/roles.py`、`frontend/src/constants/roles.js`，用于服务端访问控制、账号初始化、前端导航与签署。批次状态在 `backend/src/constants/job_state.py`、`frontend/src/constants/states.js`，用于队列、状态 API、状态标记与轮询。登记、提交、完成和签署事件写入审计表。

`COMPOSE_PROJECT_NAME` 设置栈名，`FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT` 设置端口。通过 `DB_PASSWORD`、`JWT_SECRET`、`DEMO_PASSWORD` 配置本地凭据。设置 `SEED_DEMO=false` 可关闭演示数据载入，此时数据库初始没有演示账号。数据库密码调整后，已有数据卷需在数据库内同步修改用户密码。

## 验收范围

对两条副本和指定故障时点做时序模拟。Compose 的 PostgreSQL 用于持久化演练数据。 当前界面用 JSON 编辑业务资料，以 JSON 下载证据。过程和截图保存在批次的 [验收记录](../../test-artifacts/gb-6113/TESTING.md)。

[MIT License](LICENSE)
