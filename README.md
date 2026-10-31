# bilibili-ads-loon

哔哩哔哩 iOS 去广告 Loon 插件。

- 抓包基线：**build 91601100**（iOS 9.16.x）／ iPhone 17 Pro ／ iOS 27.0.1
- 需要：**开启 MITM + 安装证书 + 在「证书信任设置」里开启完全信任**
- 当前版本：**v2**（v2 修的是 v1 的卡顿，去广告范围不变，见[性能](#v2-为什么变快)）
- 详细说明：[docs/mitm-guide.md](docs/mitm-guide.md) ｜ 抓包分析：[docs/analysis.md](docs/analysis.md)

---

## 安装

### 1. 先开 MITM（这步不做，插件一行都不执行）

Loon → 设置 → **MitM** → 打开开关
Loon → 设置 → **证书管理** → 生成并安装证书
→ 系统「设置 → 通用 → VPN与设备管理」安装描述文件
→ **系统「设置 → 通用 → 关于本机 → 证书信任设置」打开 Loon 证书的完全信任**

> 最后一步最容易漏。只在「VPN与设备管理」里看到证书**不算信任**。

### 2. 添加插件

Loon → 配置 → 插件 → 右上角 `+` → 从 URL 添加：

```
https://fastly.jsdelivr.net/gh/UserC23/bilibili-ads-loon@4034572256a5c1cf30ad215e512cca72e739c5a4/BilibiliAds.plugin
```

> 国内访问 `raw.githubusercontent.com` 一般不通，用上面的 jsDelivr 地址。
> 地址里那一串是**固定 commit**，不是 `@main` —— jsDelivr 对 `@main` 有缓存，
> 改完规则可能还发旧版本给你。固定 SHA 是内容寻址的，永远拿到确切版本。

### 3. 彻底杀掉 App

B站**上滑杀掉**再重开。只切后台无效 —— 开屏和信息流 JSON 都有缓存。

---

## 做了什么

| # | 手段 | 作用对象 | 响应体 | 默认 |
|---|---|---|---|---|
| 1 | `reject-dict` | 开屏四接口：`splash/list`、`splash/show`、`splash/brand/list`、`splash/event/list2` | 省掉 1.7MB 素材 | ✅ |
| 2 | `reject-dict` | `feed/index/story/cart` | 12 KB | ✅ |
| 3 | `reject-dict` | `GetWidgetBannerList`（直播间挂件广告位） | 小 | ✅ |
| 4 | `[Rule]` | `DOMAIN,cm.bilibili.com,REJECT`（广告计费与转化回传，抓包里 38 条） | — | ✅ |
| 5 | `response-body-json-jq` | 首页信息流删卡 | 212 KB | ✅ |
| 6 | `response-body-json-jq` | 竖屏 story 删卡（`vertical_ad_av`） | 233 KB | ✅ |
| 7 | `response-body-json-jq` | 直播首页 `banner_v2` 轮播、`activity_card_v1` 活动卡 | 479 KB | ✅ |
| 8 | `response-body-json-jq` | 直播间 `activity_banner_info`、`ad_livegame_info` | 196 KB | ✅ |
| 9 | `response-body-json-jq` | `feed/index/relate/story` 相关推荐竖屏 | **634 KB** | ❌ 默认关 |

`reject-dict` 返回 HTTP 200 + `{}`，App 解析成「这轮没有广告」，容器渲染为空，不会白屏也不会弹网络异常。

### v2 为什么变快

Loon 的 body 改写是**整包处理**：要把响应收完 → 解析 JSON → 改写 → 重新发出，期间这条请求不能流式返回。所以「被改写的包越大、越靠前，体感越卡」。

v1 把 `relate/story` 也一起改了，而它是全插件最大的包：

```
/x/v2/feed/index/relate/story    634 KB    20 条    广告 0 条
```

每次点进视频都会拉这个包，20 条里一条广告都没有 —— 纯开销。v2 直接停掉它。

第二刀砍在 MITM 范围上。v1 为了拦 `x/vip/ads/material/report` 一条上报，把整个 `api.bilibili.com` 都解密了，而这个域名上是：

| 接口 | 作用 | 抓包里出现次数 |
|---|---|---|
| `x/kv-frontend/namespace/data` | 页面配置（表情、皮肤、开关） | 16 |
| `x/player/wbi/playurl` | 播放地址 | 3 |
| `x/web-interface/view` | 视频详情 | 1 |
| `open/monitor/apm/report` | 性能上报 | 6 |

v2 只解密 `app.bilibili.com` 和 `api.live.bilibili.com` 两个域名，视频详情与播放地址不再经过解密。那条上报规则降为可选（要用得把 `api.bilibili.com` 加回 MITM）。

**还想更快**：注释掉 D1 那行（首页信息流改写），首页刷新就完全不走 body 改写了，代价是首页广告卡回来。

### 为什么不能"看到 ad 就删"

抓包里有一个**正常直播卡**也带了 `ad_info`：

```json
{"resource":1890,"source":1891,"is_ad_loc":true,"card_index":1}
```

真广告卡才多出这两个字段：

```json
{"creative_id":4124685618,"is_ad":true,"is_ad_loc":true}
```

所以规则只认 `is_ad == true`、`ad_info.creative_id > 0`、`card_goto` 命中 `^ad|_ad_|^vertical_ad`。
按「有没有 `ad_info`」来删，会把首页的正常直播推荐全删掉。

同理，竖屏广告卡是 `vertical_ad_av`，正常卡是 `vertical_av` —— 差一个 `_ad_`。

---

## 覆盖边界（说清楚，免得你以为是没装好）

| 位置 | 状态 | 原因 |
|---|---|---|
| 开屏广告 | ✅ 已去掉 | 四条接口全拦 |
| 首页信息流广告卡 | ✅ 已去掉 | JSON 定点删卡 |
| 竖屏 story 广告 | ✅ 已去掉 | JSON 定点删卡 |
| story 购物车广告锚点 | ✅ 已去掉 | 整包拒绝 |
| 直播首页轮播 / 活动卡 | ✅ 已去掉 | JSON 定点删卡 |
| 直播间挂件 / 活动 banner | ✅ 已去掉 | 拒绝 + 删字段 |
| 广告计费、曝光回传 | ✅ 已掐断 | `cm.bilibili.com` REJECT |
| 大会员页广告上报 | ⚠ 默认不拦 | 需要把 `api.bilibili.com` 加回 MITM，v2 为性能放弃了 |
| **动态页广告卡** | ❌ 去不掉 | 走 `grpc.biliapi.net` 的 Protobuf，Loon 的 `response-body-json-jq` 只能改 JSON |
| **搜索热词 / 搜索广告** | ❌ 去不掉 | 同上，`Search/DefaultWords` 是 gRPC |
| **热门页、分区页广告** | ❌ 去不掉 | 同上，`Popular/Index` 是 gRPC |

> gRPC 这三处只能靠 `DOMAIN,grpc.biliapi.net,REJECT` —— 但那是**整个 App 的主接口**，
> 拦掉动态、搜索、热门、评论全都没了。插件里没有默认开启，也不建议。

---

## 有残留广告怎么办

别猜字段，用脚本定位：

```bash
python tools/analyze_har.py 抓包.har --check      # 先确认 MITM 真的在解密
python tools/analyze_har.py 抓包.har --splash     # 开屏专项：素材条数 / 落地页
python tools/analyze_har.py 抓包.har --feed       # 信息流逐条体检，标出广告卡
python tools/analyze_har.py 抓包.har --scan-ads   # 定位广告字段的 JSON 路径
```

`--check` 是前置条件：如果输出 `❌ 所有请求都没有响应体`，说明 MITM 没生效，
此时任何分析都没有意义 —— 插件里的 `[Rewrite]` 一条都不会执行。

抓包注意两点：

1. 开屏广告只在**冷启动**时请求，录之前先彻底杀掉 App。
2. 信息流广告要多刷几页才出现，只录开屏往往看不到。

详细流程见 [docs/mitm-guide.md 第四节](docs/mitm-guide.md#四还有广告怎么办)。

---

## CDN 地址

| 地址 | 说明 |
|---|---|
| `fastly.jsdelivr.net/gh/UserC23/bilibili-ads-loon@4034572/BilibiliAds.plugin` | ✅ 推荐，内容寻址 |
| `gcore.jsdelivr.net/gh/UserC23/bilibili-ads-loon@4034572/BilibiliAds.plugin` | ✅ 备用节点 |
| `ghproxy.net/https://raw.githubusercontent.com/UserC23/bilibili-ads-loon/main/BilibiliAds.plugin` | ✅ 实时，依赖第三方代理 |
| `...@main/BilibiliAds.plugin` | ⚠ 有 CDN 缓存，改完规则可能还拿到旧版本 |
| `raw.githubusercontent.com/...` | ❌ 国内直连不通 |

更新版本时，`git log --format=%H -1` 拿到新 commit，把上面的 `4034572` 换掉即可。

---

## 文件结构

```
BilibiliAds.plugin               Loon 插件 v2（主文件，直接装这个）
rules/BilibiliAds.list           纯域名规则（Surge/Shadowrocket/Stash 可用，不含 MITM 部分）
docs/mitm-guide.md               安装、验证、定位残留广告、排错
docs/analysis.md                 抓包分析：接口、字段、证据
tools/analyze_har.py             HAR 分析脚本（--check / --splash / --feed / --scan-ads）
CHANGELOG.md                     版本记录
```

## 隐私提示

插件生效的前提是 Loon 能解密 `app.bilibili.com` 与 `api.live.bilibili.com`，
也就是说这两条链路上的**登录态会经过 Loon**。
（v2 起 `api.bilibili.com` 不再解密，视频详情与播放地址不经过 Loon。）

请只使用你自己看得懂、来源可信的规则文件，不要随手安装来路不明的"全App去广告"插件。

## 免责

规则基于本项目抓包逐条核对字段写成，随 App 版本变化可能失效。
仅供个人学习自用，请自行评估风险。
