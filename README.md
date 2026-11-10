# HL 清算地图（hl-liqmap）

静态前端 + 私有采集 + 公开聚合快照。阶段状态更新于北京时间 2026-11-11（UTC+08:00）：私有采集、快照、导出和 state 回写已核实成功；旧公开任务已改为 guard，不再定时写入。单仓库 deploy key 自动发布 aggregate 的通道已实现，真实 SSH 发布结果仍待主线程核验。public index 尚未切换，不能据此称全流程上线成功。旧公开 main 的 data/、snap 快照和 Git 历史仍公开，未清理、未重写。

下文描述迁移候选前端：浏览器直连 Hyperliquid 公开行情 API，展示估算层、本机 Watchlist 及聚合真实层。候选页面只读取公开聚合，不自动读取地址池或逐账户快照，不增加登录功能；此行为尚不能代表线上 public index。

## 架构

- `index.html`：实时行情、估算开关/多空滑块、币种切换、平方根条形、聚合快照及本机 Watchlist。
- `harvest.py`：原采样规则的收割与逐账户快照，只在指定 PRIVATE_DATA_DIR 的私有侧运行。
- `aggregate.py`：同原图14档距离分桶，公开全部非空桶，不设贡献账户数或金额筛桶门槛，严格白名单 schema。
- `private_export.py`：保存私有原始快照与行情参考价，产生可审查的公开桶输出。
- `publish_aggregate.py`：私有侧专用发布器，导出成功且发布凭据非空时自动追加写公开 aggregate 分支的 data/aggregate.json，无强推，不要求额外 repository 变量。
- `deploy/private-collect.yml`：私有工作流模板，仅 private=true 运行；每6小时收割、每30分钟快照并导出。发布在 SSH key 或 token 任一非空且导出成功时自动执行，凭据仅注入发布 step。
- `.github/workflows/`：公开代码检查与迁移 guard，不检出私有数据。

候选前端的真实桶绑定导出时固定参考价 reference_mark；行情每10秒刷新，聚合每30分钟获取，不随最新行情精确重分真实桶。相同输入与参考价下，金额、仓位数、价格极值算法与原图一致；汇总包括全部可定位非空桶，单人贡献桶也公开，无法定位强平价的仓位不计入地图汇总。公开格式不含逐账户明细，但单人贡献、价格极值、链上关联和跨期差分仍可能推断个别账户，不承诺绝对匿名。

自动发布使用只挂目标公开仓库的 deploy key；这是仓库级读写权限，固定 aggregate 分支及唯一 data/aggregate.json 由发布器约束，并非 GitHub 分支级 key。私钥仅存私有库 Actions secret，私有 state 回写使用私有库自带 GITHUB_TOKEN。不要把地址池、逐账户快照、日志、token 或 key 正文提交到公开仓库；本地采集须指定私有 PRIVATE_DATA_DIR，不沿用旧公开 data 回写方式。

## 验证

```sh
python3 -B -m unittest discover -s tests -v
python3 -B aggregate.py --validate path/to/aggregate.json
python3 -B tests/browser_harness.py --aggregate path/to/aggregate.json
```

浏览器验证器只暴露前端和校验过的聚合，拒绝访问 data/；行情与 Watchlist 为确定性合成响应，不能当作交易行情。

详见 [迁移指南](MIGRATION.md) 的字段契约、业务规则、隐私边界、私有初始化、生产切换与逐项待批准操作，以及 [验证记录](VERIFICATION.md)。.gitignore 不移除已有跟踪数据，本次仍保留旧 data/ 文件和所有历史。

## 许可证

[GNU Affero General Public License v3.0](LICENSE)，© 2026 xyz1367487。


## 2026-11-11 线上切换完成记录（北京时间）

私有运行 42857496914 已成功完成收割、快照、归档、state 回写与 SSH 聚合发布；私有 state 提交为 75bd2c10f2c56528f5eb60b4c611a66d3ccf561a。公开 aggregate 初次提交 ffc46e6cb522540554f0ef9d1d3d6ba581d063a1 只有 data/aggregate.json；真实输出 87 市场、1108 桶，生成时间 00:55:32，严格 schema 通过，地址模式 0 处。上述数量为该次快照，不是固定值。

公开前端已由 9bcfcf59d7434460f7525f493ffb8db3a9904de2 切换到聚合入口；源码 CI 42859744810、Pages 42859743580 均成功。线上浏览器已读取该新聚合时间，资源记录没有旧 accounts/addresses/snap 请求。两处残留三账户门槛说明已修正为全部非空桶公开；实际导出此前已经无该门槛。本条记录取代前文“前端尚未切换/SSH 发布待验证”的阶段状态。

旧公开 main:data/addresses.json、main:data/accounts.json 和 snap:data/snapshot.json 仍保留，待用户确认具体移除操作；Git 历史未重写。这次切换停止未来公开采集地址，但不代表旧地址数据已经保密。公开聚合不提供绝对匿名保证。
