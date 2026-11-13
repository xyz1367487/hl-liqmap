## 2026-11-13 本轮增量白名单（仅主线程部署）

本节取代以下历史上传清单。本地public/private目录是远端main最新源码的独立实施副本，不可整目录上传。本轮不上传任何state、snapshots、evidence、日志、baseline或真实样本，不重跑初始化，不新增Secrets/服务，不修改调度，不删除文件/历史。本次由主线程先部署公开读旧新前端及同步验证器，核验后再部署私有模块，等待既定自动触发。

公开相对路径：`.github/workflows/checks.yml`、`README.md`、`MIGRATION.md`、`VERIFICATION.md`、`UPLOAD_CHECKLIST.md`、`aggregate.py`、`chart-core.js`、`harvest.py`、`index.html`、`position_scan.py`、`private_export.py`、`tests/test_aggregate.py`、`tests/test_position_selection.py`、`tests/aggregate-loading.test.cjs`、`tests/chart-core.test.cjs`、`tests/lev-stack.test.cjs`、`tests/load-core.cjs`。

私有相对路径：`README.md`、`aggregate.py`、`harvest.py`、`position_scan.py`、`private_export.py`、`tests/test_position_selection.py`。其他文件与基线一致，不需上传；生产`chart-ui.js`及`chart.css`原样保留。队列state由私有任务在现存state内生成，随当前workflow自动回写；不要用本地旧state覆盖线上state。

部署前再次读取两个main和活动workflow，基于最新main合并这些代码，保留线上新增state与已有功能；变更collect.yml不在本轮白名单内。本地逐文件SHA256由交接根REVIEW_MANIFEST.json及UPLOAD_SHA256.txt给出，仅作为主线程审查材料，不上传公开。

# MCP 上传清单（分阶段记录；public index 尚未切换）

2026-11-11 北京时间（UTC+08:00）更新：本轮仅整理本地文档，不执行上传、push、dispatch、删除或历史改写。旧公开任务已 guard，不再定时写入；新私有任务每6小时收割、每30分钟快照并导出，首次私有 state 回写已成功。单仓库 deploy key 自动发布 aggregate 的实现已交付，真实 SSH 发布结果仍待主线程核验；public index 尚未切换，后续主线程确认时再改状态。旧公开 data/ 和 snap 仍可访问，历史未重写，不能称全流程上线已成功。

本轮后续可审查的文档范围仅 README.md、MIGRATION.md、VERIFICATION.md、UPLOAD_CHECKLIST.md。中文任务状态及 SSH_PUBLISH_HANDOFF.md 是本地交接，不上传。以下旧上传清单保留作阶段追溯，不是本轮执行指令；尤其不重复上传 state/seed、不切换 index、不上传任何真实地址、token 或 key 正文。

## SSH 后端增量上传（2026-11-10 UTC 准备记录，待主线程核验结果）

已有私有 state 已由 operator 报告回写成功，本轮不重复初始化、不上传旧 state/seed/日志，也不运行 initialize-private.sh。先核实私有仓库及远端文件版本，按以下白名单小批上传，collect.yml 最后：

| 本地根 | 相对路径 | 目标 |
| --- | --- | --- |
| ../hl-liqmap-private-preparation/repository | publish_aggregate.py、README.md、tests/test_publish_ssh.py | 私有 main 同路径 |
| ../hl-liqmap-private-preparation/repository | .github/workflows/collect.yml | 私有 main，最后上传，触发一次已授权 harvest/snapshot/export/发布验证 |
| 本 checkout | publish_aggregate.py、tests/test_publish_ssh.py、deploy/private-collect.yml、MIGRATION.md、VERIFICATION.md、UPLOAD_CHECKLIST.md | 公开 main 同路径，均不含真实凭据或原始数据 |

PUBLIC_AGGREGATE_SSH_KEY 公钥只挂公开 hl-liqmap，启用 Allow write access；私钥仅存私有采集库 Actions secret。自动发布通道已实现；本轮仅依据交接整理，安装及真实发布验收仍待主线程核验。SSH key 优先，token 备选；任一非空即打开发布 gate，两项只在发布 step 注入。主线程等待这次 workflow 验证固定 aggregate 分支唯一 data/aggregate.json、父提交与真实发布成功，不再额外 dispatch。deploy key 是仓库级读写，脚本执行单分支/单文件约束。

根状态文件与 SSH_PUBLISH_HANDOFF.md 仅本地交接，不上传公开数据目录。下方为先前初始化历史清单，本轮增量以上述表为准。

## 新私有仓库 main（历史初始化清单）

本地根：`../hl-liqmap-private-preparation/repository/`，相对路径与目标相同，共16份：

```text
.github/workflows/collect.yml
.gitignore
LICENSE
README.md
initialize-private.sh
harvest.py
aggregate.py
private_export.py
publish_aggregate.py
state/addresses.json
state/accounts.json
state/coins.json
state/volume_cache.json
state/snapshot.json
snapshots/seed/snapshot.json
snapshots/seed/marks.json
```

上传前先核实目标 private=true。主线程刷新远端 main:data/addresses.json、data/accounts.json、data/coins.json、data/volume_cache.json，分别映射到私有 state 同名文件，不能用旧本地池覆盖新远端数据。state/snapshot.json 和 snapshots/seed/snapshot.json 当前仅为2026-11-10种子；marks 仅为当时算法对照行情，不声称最新。若刷新 snap，保留 seed 原样并注明来源，避免把旧 marks 宣称为新快照同刻行情。

一次 MCP main 初始化提交包含 collect.yml 即自动触发一次 harvest → snapshot → export。不要再手动 dispatch，也不要拆多次修改 collect.yml/initialize-private.sh。push 限 main 且仅这两个路径；state/snapshots 写回不触发。普通 harvest cron 只写池，下次 snapshot cron 生成快照；cron 和采样参数未增加。以后修改这两个初始化路径也会触发一次完整流程。

首次私有运行（2026-11-11 北京时间）尚无发布凭据，公开发布跳过，采集/归档及 state 回写成功。当前 job env ENABLE_PUBLIC_EXPORT 为 SSH key 或 token 任一非空的布尔表达式，export 成功后自动发布；凭据仅注入发布 step，不需要 repository 变量，不能再仅凭 token 缺失判定跳过。

## 原公开仓库 main（2026-11-10 UTC 原始计划；非本轮上传指令）

本地根：本清单所在 checkout。以下14份为先前计划清单，保留追溯；其中 public index 尚未切换，后续由主线程确认。本轮不重传代码、guard 或 index，仅整理文档：

```text
index.html
aggregate.py
harvest.py
private_export.py
publish_aggregate.py
.github/workflows/harvest.yml
.github/workflows/snapshot.yml
.github/workflows/checks.yml
deploy/private-collect.yml
deploy/init-private.sh
tests/test_aggregate.py
MIGRATION.md
VERIFICATION.md
UPLOAD_CHECKLIST.md
```

旧公开任务已部署 guard，无 schedule，仅 workflow_dispatch 的通知 job，contents:read，无采集、无写数据；guard 不会自动终止此前已在运行的任务，旧运行结束情况须单独核验。公开检查只跑合成测试，不配置私有凭据。候选前端读取 aggregate 分支单个 JSON，不再自动请求旧地址池/候选池/snap；Watchlist 自填地址功能保留。public index 尚未切换，这不是线上前端已停止读取旧数据的证明。

不上传本地 audit、state、snapshots、原始样本或 seed-sha256.json 到公开仓库。现存公开 data 与历史保持原样；不执行 git add .，不整目录同步。

## 原公开仓库 aggregate 分支

唯一目标：`data/aggregate.json`。

首个已审查种子输出本地路径：`../hl-liqmap-private-preparation/aggregate-reviewed.json`。该文件是2026-11-10样本，87市场、1092桶、126090字节；不是最新采集结果。可用于初始化公开聚合，界面可能按时间显示陈旧提示。主线程优先审查首次真实私有运行的 exports/<run-id>-<attempt>/aggregate.json；若 secret 尚缺，可单文件上传该新聚合。已有 aggregate 分支先读取当前内容，不覆盖未知文件或丢弃历史。

先由主线程核验真实 SSH 发布 step、公开 aggregate JSON 可访问、唯一文件 tree、schema/地址检查、生成时间与父提交，再确认 public index 切换。候选前端采用固定参考价、30分钟聚合获取、旧缓存拒绝与失败保留，公开全部原算法非空桶，包括单人贡献桶；实时行情不使真实桶精确重分。首次私有 Actions 已成功，后续 SSH run 的最终发布与 Pages 切换尚未核实，不得把本地测试或私有采集成功写成全流程上线成功。

## 2026-11-10 UTC 部署配置阶段本地变更范围（历史）

两份 collect 工作流、两份初始化脚本、私有 README、MIGRATION.md、VERIFICATION.md、本清单和工作区根的清算地图迁移任务状态.md。未修改采集算法、发布器、前端及原 data；旧 guard 本轮仅核查。根状态文件只留本地，不属于公开上传清单。


## 2026-11-11 线上切换完成记录（北京时间）

私有运行 42857496914 已成功完成收割、快照、归档、state 回写与 SSH 聚合发布；私有 state 提交为 75bd2c10f2c56528f5eb60b4c611a66d3ccf561a。公开 aggregate 初次提交 ffc46e6cb522540554f0ef9d1d3d6ba581d063a1 只有 data/aggregate.json；真实输出 87 市场、1108 桶，生成时间 00:55:32，严格 schema 通过，地址模式 0 处。上述数量为该次快照，不是固定值。

公开前端已由 9bcfcf59d7434460f7525f493ffb8db3a9904de2 切换到聚合入口；源码 CI 42859744810、Pages 42859743580 均成功。线上浏览器已读取该新聚合时间，资源记录没有旧 accounts/addresses/snap 请求。两处残留三账户门槛说明已修正为全部非空桶公开；实际导出此前已经无该门槛。本条记录取代前文“前端尚未切换/SSH 发布待验证”的阶段状态。

旧公开 main:data/addresses.json、main:data/accounts.json 和 snap:data/snapshot.json 仍保留，待用户确认具体移除操作；Git 历史未重写。这次切换停止未来公开采集地址，但不代表旧地址数据已经保密。公开聚合不提供绝对匿名保证。
