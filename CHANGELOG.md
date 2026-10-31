# CHANGELOG

## v2 — 2026-10-31

修 v1 的卡顿。用户反馈"去广告达到效果，但首页刷新、点进视频后评论区刷新很慢"，开关插件对比确认由插件引起。

### 定位方法

把每个被 `response-body-json-jq` 命中的端点按真实响应体体积排序。Loon 的 body 改写必须整包收完 → 解析 → 改写 → 再发出，期间不能流式返回，所以"匹配到的包越大、越靠前，体感越卡"。

| 端点 | 体积 | 条目 | 实际广告 |
|---|---|---|---|
| `feed/index/relate/story` | **634 KB** | 20 | **0** |
| `xlive/app-interface/v2/index/feed` | 479 KB | 24 | 1 |
| `feed/index/story` | 233 KB | 6 | 2 |
| `feed/index` | 212 KB | 10 | 0 |
| `feed/index/story/cart` | 12 KB | — | 整包只有广告 |

### 改动

| # | 改动 | 原因 |
|---|---|---|
| 1 | `feed/index/relate/story` 的整包改写**默认关闭**（降为可选行） | 634 KB，每次进视频都拉，20 条里 0 条广告 —— 全插件最大的纯开销 |
| 2 | `[MITM]` 去掉 `api.bilibili.com` | 该域名承载 `x/web-interface/view`（视频详情）、`x/player/wbi/playurl`（播放地址）、`x/kv-frontend/namespace/data`（页面配置，单份抓包被调 16 次）。为了拦一条广告上报而解密整条链路不划算 |
| 3 | `x/vip/ads/material/report` 规则降为可选 | 它需要 `api.bilibili.com` 在 MITM 里，与第 2 条冲突 |
| 4 | `[MITM]` 仅保留 `app.bilibili.com`、`api.live.bilibili.com` | 只解密真正要改的两个域名 |

### 效果

- 单次进视频页少改写 **634 KB**；首页刷新不再经过任何 `api.bilibili.com` 解密。
- 去广告范围不变：开屏四条接口、首页广告卡、竖屏 story 广告、story 购物车锚点、直播首页轮播/活动卡、直播间 banner 与挂件、`cm.bilibili.com` 计费回传全部保留。
- 真实响应回放验证：`feed/index` 10→10（零误删）、`feed/index/story` 6→4（精确删 2 条 `vertical_ad_av`）、`xlive/index/feed` 24→22、`relate/story` 不再命中。

### 如果还想更快

首页要极致顺滑可注释掉 D1（首页信息流改写）——广告卡会回来，但首页刷新彻底不走 body 改写。

## v1 — 2026-10-31

首版。基于 iOS B站 `build 91601100` 的一份完整冷启动 + 首页/直播浏览抓包（1205 请求，1080 条带响应体）逐条核对字段写成。

### 覆盖

| 位置 | 手段 | 依据 |
|---|---|---|
| 开屏广告 | `reject-dict` × 4 接口 | `splash/list` 单次下发 83 条素材 / 1.7MB，`source=928`，67 条落地页指向京东 DSP / 阿里妈妈 |
| 首页信息流广告卡 | `response-body-json-jq` | `is_ad` / `ad_info.creative_id` / `card_goto` 前缀 |
| 竖屏 story 广告卡 | `response-body-json-jq` | `card_goto = vertical_ad_av`（正常卡是 `vertical_av`） |
| story 购物车广告锚点 | `reject-dict` | 该接口整个响应体只有 `data.anchor.ad_info`（红果短剧 / 穿山甲） |
| 直播首页轮播 + 活动卡 | `response-body-json-jq` | 24 张卡里 `banner_v2`（5 帧，带 `ad_order_id`）与 `activity_card_v1` |
| 直播间活动 banner | `response-body-json-jq` | `data.activity_banner_info`（`pendant_banner` 号位 3615）、`data.ad_livegame_info` |
| 直播间挂件广告 | `reject-dict` | `GetWidgetBannerList` 只服务挂件位（号位 3602） |
| 广告计费 / 曝光回传 | `DOMAIN,cm.bilibili.com,REJECT` | 38 条请求，含 `splashId`、`ad_cb`、设备指纹 |
| 大会员页广告上报 | `reject-dict` | `x/vip/ads/material/report`，5 条全是明文 HTTP |

### 两个写规则时踩到的坑（已写进注释，防止后人重犯）

1. **首页正常直播卡也带 `ad_info`**
   `{"resource":1890,"source":1891,"is_ad_loc":true,...}` —— 没有 `is_ad`、没有 `creative_id`。
   按「`ad_info` 是否存在」删卡，会把正常直播推荐一起删掉。
   本版只认 `is_ad == true` / `ad_info.creative_id > 0` / `card_goto` 前缀。
   用真实响应验证：`feed/index` 10 条 → 10 条（零误删），`story` 6 条 → 4 条（精确删掉 2 条 `vertical_ad_av`）。

2. **开屏是四条接口，不是一条**
   `list`（素材清单）+ `show`（今日展示队列）+ `brand/list`（品牌开屏）+ `event/list2`（事件）。
   只拦 `show` 的话，`list` 照样把 1.7MB 素材拉下来，下次冷启动照样弹。

### 已知无法覆盖

`grpc.biliapi.net` 上的 Protobuf 接口：动态页 `DynAll`、搜索 `Search/DefaultWords`、热门 `Popular/Index`。
Loon 的 `response-body-json-jq` 只能改 JSON，改不了二进制 Protobuf。
域名级 REJECT 会连带废掉动态、搜索、热门、评论，不做。详见 `docs/analysis.md` 第七节。

### 验证方式

```bash
python tools/analyze_har.py 抓包.har --check     # MITM 是否解密
python tools/analyze_har.py 抓包.har --splash    # 开屏素材条数
python tools/analyze_har.py 抓包.har --feed      # 信息流逐条标广告
```
