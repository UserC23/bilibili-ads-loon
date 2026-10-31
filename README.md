# bilibiliads-loon

哔哩哔哩 iOS 去广告 Loon 插件。

- 抓包基线：**build 91601100**（iOS 9.16.x）／ iPhone 17 Pro ／ iOS 27.0.1
- 需要：**开启 MITM + 安装证书 + 在「证书信任设置」里开启完全信任**
- 当前版本：**v1**
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
https://fastly.jsdelivr.net/gh/UserC23/bilibiliads-loon@main/BilibiliAds.plugin
```

> 国内访问 `raw.githubusercontent.com` 一般不通，用上面的 jsDelivr 地址。
> 如果装了新版本却毫无变化，改用固定 commit 地址（见文末「CDN 地址」），
> jsDelivr 对 `@main` 有缓存。

### 3. 彻底杀掉 App

B站**上滑杀掉**再重开。只切后台无效 —— 开屏和信息流 JSON 都有缓存。

---

## 做了什么

| # | 层 | 手段 | 作用对象 | 默认 |
|---|---|---|---|---|
| 1 | `reject-dict` | 开屏四接口：`splash/list`、`splash/show`、`splash/brand/list`、`splash/event/list2` | 开屏广告（`list` 一次下发 83 条素材 / 1.7MB） | ✅ |
| 2 | `reject-dict` | `feed/index/story/cart` | 竖屏 story 购物车广告锚点（响应体只有一条 `data.anchor.ad_info`） | ✅ |
| 3 | `reject-dict` | `vip/ads/material/report`、`GetWidgetBannerList` | 大会员页广告上报、直播间挂件广告位 | ✅ |
| 4 | `[Rule]` | `DOMAIN,cm.bilibili.com,REJECT` | 广告计费与转化回传（抓包里 38 条） | ✅ |
| 5 | `response-body-json-jq` | 删卡 | 首页信息流广告卡 | ✅ |
| 6 | `response-body-json-jq` | 删卡 | 竖屏 story 广告卡（`vertical_ad_av`） | ✅ |
| 7 | `response-body-json-jq` | 删卡 | 直播首页 `banner_v2` 轮播、`activity_card_v1` 活动卡 | ✅ |
| 8 | `response-body-json-jq` | 删字段 | 直播间 `activity_banner_info`、`ad_livegame_info` | ✅ |

`reject-dict` 返回 HTTP 200 + `{}`，App 解析成「这轮没有广告」，容器渲染为空，不会白屏也不会弹网络异常。

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

| 地址 | 实测 |
|---|---|
| `fastly.jsdelivr.net/gh/UserC23/bilibiliads-loon@<commit>/BilibiliAds.plugin` | ✅ 推荐，内容寻址，永远拿到确切版本 |
| `gcore.jsdelivr.net/gh/UserC23/bilibiliads-loon@<commit>/BilibiliAds.plugin` | ✅ |
| `ghproxy.net/https://raw.githubusercontent.com/UserC23/bilibiliads-loon/main/BilibiliAds.plugin` | ✅ 实时，依赖第三方代理 |
| `...@main/BilibiliAds.plugin` | ⚠ 有 CDN 缓存，改完规则可能还拿到旧版本 |
| `raw.githubusercontent.com/...` | ❌ 国内直连不通 |

---

## 文件结构

```
BilibiliAds.plugin               Loon 插件 v1（主文件，直接装这个）
rules/BilibiliAds.list           纯域名规则（Surge/Shadowrocket/Stash 可用，不含 MITM 部分）
docs/mitm-guide.md               安装、验证、定位残留广告、排错
docs/analysis.md                 抓包分析：接口、字段、证据
tools/analyze_har.py             HAR 分析脚本（--check / --splash / --feed / --scan-ads）
CHANGELOG.md                     版本记录
```

## 隐私提示

插件生效的前提是 Loon 能解密 `app.bilibili.com` / `api.bilibili.com` / `api.live.bilibili.com`，
也就是说这三条链路上的**登录态和播放地址会经过 Loon**。请只使用你自己看得懂、来源可信的规则文件，
不要随手安装来路不明的"全App去广告"插件。

## 免责

规则基于本项目抓包逐条核对字段写成，随 App 版本变化可能失效。
仅供个人学习自用，请自行评估风险。
