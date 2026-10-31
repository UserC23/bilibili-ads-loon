# 抓包分析（v1 基线）

本文件记录 `BilibiliAds.plugin` 每一条规则的**字段级依据**。改规则前先看这里，别凭"ad"这个词猜。

## 一、抓包基本信息

| 项 | 值 |
|---|---|
| 采集工具 | Loon（HAR 里 `creator.name = Loon`） |
| App | 哔哩哔哩 iOS，`build/91601100`，`channel/pink_overseas` |
| 设备 | iPhone 17 Pro，iOS 27.0.1 |
| 时间 | 2026-10-31 |
| 请求数 | 1205（HTTPS 1167 / HTTP 38） |
| 有响应体 | 1080（可解析 JSON 255） |
| MITM | 已生效（能读到 HTTPS 响应体，且 B站接口返回明文 JSON） |

> 38 条 HTTP 明文请求里，有 **5 条是 `api.bilibili.com/x/vip/ads/material/report`**（大会员页广告曝光上报）。
> 也就是说这条上报链路连 TLS 都没走，直接明文出去。

域名分布（前 12）：

| 次数 | 域名 | 性质 |
|---|---|---|
| 312 | i2.hdslb.com | 封面图 CDN |
| 104 | data.bilibili.com | 埋点 |
| 84 | cn-hbyc-ct-01-02.bilivideo.com | 视频流 |
| 79 | dataflow.biliapi.com | 埋点 |
| 64 | api.live.bilibili.com | 直播接口 |
| 63 | api.bilibili.com | 主接口 |
| 54 | grpc.biliapi.net | gRPC（动态/搜索/热门） |
| 38 | **cm.bilibili.com** | **广告计费与转化** |
| 34 | app.bilibili.com | 首页/开屏接口 |

---

## 二、广告点位清单

| # | 接口 | 本次条数 | 证据字段 | 处理 |
|---|---|---|---|---|
| 1 | `app.bilibili.com/x/v2/splash/list` | 2 | `data.list[]` 83/84 条，`source=928`，落地页 67 条京东 DSP | `reject-dict` |
| 2 | `app.bilibili.com/x/v2/splash/show` | 2 | `data.show[].ad_cb` | `reject-dict` |
| 3 | `app.bilibili.com/x/v2/splash/brand/list` | 1 | `data.list[]` 21 条品牌开屏 | `reject-dict` |
| 4 | `app.bilibili.com/x/v2/splash/event/list2` | 1 | 开屏事件配置 | `reject-dict` |
| 5 | `app.bilibili.com/x/v2/feed/index` | 2 | `data.items[]` 内 `card_goto` / `ad_info` | jq 删卡 |
| 6 | `app.bilibili.com/x/v2/feed/index/story` | 1 | `data.items[]` 6 条里 2 条 `vertical_ad_av` | jq 删卡 |
| 7 | `app.bilibili.com/x/v2/feed/index/story/cart` | 2 | 响应体只有 `data.anchor.ad_info`（红果短剧 / 穿山甲） | `reject-dict` |
| 8 | `api.live.bilibili.com/xlive/app-interface/v2/index/feed` | 1 | `data.card_list[]` 24 张卡里 `banner_v2` + `activity_card_v1` | jq 删卡 |
| 9 | `api.live.bilibili.com/xlive/app-room/v1/index/getInfoByRoom` | 2 | `data.activity_banner_info`、`data.ad_livegame_info` | jq 删字段 |
| 10 | `api.live.bilibili.com/xlive/play-interface/widgetService/GetWidgetBannerList` | 4 | 直播间挂件广告位（号位 3602） | `reject-dict` |
| 11 | `api.bilibili.com/x/vip/ads/material/report` | 5 | `event_type=show` 上报 | `reject-dict` |
| 12 | `cm.bilibili.com/cm/api/conversion/mobile/v2` | 27 | 带 `splashId` / `ad_cb` / 设备指纹 | 域名 REJECT |
| 13 | `cm.bilibili.com/cm/api/fees/wise` | 11 | `event=show|video_play|video_play_3s` 计费打点 | 域名 REJECT |

---

## 三、开屏：为什么只拦 `show` 没用

`splash/list` 单次响应解码后 **1.7MB**，里面是完整的素材清单：

```
data.max_time        = 30      # 最长展示 30s
data.pull_interval   = 900     # 15 分钟拉一次
data.keep_ids[]      = 38 条
data.list[]          = 83 条   # 素材本体
data.show[]          = 4 条    # 今天该展示哪几条（带 ad_cb 回执）
```

`data.list[]` 的构成高度一致，说明这个接口**只服务广告**：

| 字段 | 分布 |
|---|---|
| `source` | `928` × 83（全部） |
| `type` | `1` × 83（全部） |
| `card_type` | `39` × 72，`14` × 11 |

单条素材长这样：

```json
{
  "id": 91935, "type": 1, "card_type": 39,
  "duration": 5, "skip": 1,
  "thumb": "https://i0.hdslb.com/bfs/sycp_brand/img/202610/....webp",
  "uri": "https://ccc-wt.jd.com/dsp/cl?v=707&wts=2&log=...&oaid=__OAID__&caid=...",
  "video_url": "...", "video_width": ..., "video_height": ...
}
```

`uri` 是落地页，83 条里 67 条命中 `jd.com / taobao / alimama / snssdk` 等电商与穿山甲链路，
并且带 `__OAID__`、`__IDFA__`、`__CAID__` 这类设备标识占位符 —— 这是标准的竞价广告模板。

**结论**：这四条接口合起来才是一次开屏。只 reject `splash/show`，`list` 照样把 1.7MB 素材拉下来，
下一次冷启动照样弹。

---

## 四、首页信息流：一个必须避开的误伤陷阱

首页 `/x/v2/feed/index` 的 `data.items[]` 里，**正常直播卡也带 `ad_info`**：

```json
// 正常直播卡（card_type=small_cover_v9, card_goto=live, 标题「大号冲前十」）
"ad_info": {"resource":1890,"source":1891,"request_id":"...","index":1,
            "is_ad_loc":true,"card_index":1,"client_ip":"..."}
```

而真广告卡（竖屏 story 里抓到的样本）：

```json
"ad_info": {"creative_id":4124685618,"is_ad":true,"is_ad_loc":true,"resource":4352,...}
```

区别只有两点：`is_ad: true` 和 `creative_id`。

所以规则用了 5 个条件做「或」，刻意**不**用 `ad_info` 存在性：

```
.is_ad == true
.ad_info.is_ad == true
.ad_info.creative_id > 0
card_goto / goto 命中 ^ad | _ad_ | ^vertical_ad
card_type 命中 ^ad
```

实测效果（真实响应跑一遍 jq）：

| 响应 | 原始卡片 | 删后 | 删掉的 |
|---|---|---|---|
| `feed/index`（第 1 次） | 10 | 10 | 无（含 1 张正常直播卡，保留） |
| `feed/index`（第 2 次） | 9 | 9 | 无（含 1 张 `banner_v8` 运营轮播，保留） |
| `feed/index/story` | 6 | 4 | 2 张 `vertical_ad_av` |

第 2 次里的 `banner_v8` 是首页顶部轮播（内容为 KPL 直播推荐，`cm_mark: 0`），属于运营位不是商业广告，
默认保留；想更干净可以打开插件末尾的「高级 1」。

---

## 五、竖屏 story：`vertical_ad_av` vs `vertical_av`

`/x/v2/feed/index/story` 6 条卡里 2 条是广告：

| idx | card_goto | ad_info |
|---|---|---|
| 1 | `vertical_ad_av` | `creative_id: 4124685618`, `is_ad: true` |
| 4 | `vertical_ad_av` | `creative_id: 4005252472`, `is_ad: true` |

其余 4 条是 `vertical_av`（正常竖屏视频）。正则写 `vertical.*av` 会把正常的也删掉，
所以插件用的是 `^ad|_ad_|^vertical_ad`。

`/x/v2/feed/index/story/cart` 更彻底 —— 整个响应体只有一个键：

```json
{"code":0,"data":{"anchor":{"request_id":"...","cm_mark":0,
  "ad_info":{"creative_id":1200076899473178624,"card_type":128,
    "creative_content":{"title":"红果免费短剧","url":"https://apps.apple.com/cn/app/id6451407032",
      "click_url":"https://open.snssdk.com/ug/ad/display/clicks?ad_platform=bilibili&..."}}}}}
```

没有任何业务数据，直接整包 `reject-dict`。副作用是竖屏模式下底部那个"购物车"入口消失。

---

## 六、直播：三个位置

**直播首页** `/xlive/app-interface/v2/index/feed`，24 张卡：

| card_type | 数量 | 性质 |
|---|---|---|
| `small_card_v1` | 20 | 正常直播间（`is_ad: false`） |
| `banner_v2` | 1 | 顶部轮播，5 帧，带 `ad_order_id` / `session_id` |
| `activity_card_v1` | 1 | 活动卡 |
| `my_idol_v1` / `area_entrance_v3` | 各 1 | 功能卡，保留 |

**直播间** `getInfoByRoom`：

- `data.activity_banner_info` 下 `pendant_banner`（号位 3615）、`top` / `bottom` / `superBanner` / `revenue_banner` 等，全是活动位
- `data.ad_livegame_info.is_ad` —— 直播小游戏广告位

**挂件** `GetWidgetBannerList` 返回 `data.list["3602"]`，即直播间右侧挂件广告（本次是"10.31 北京首钢园 B站创新节"）。
这个接口只服务挂件位，直接 `reject-dict`。

---

## 七、覆盖不到的部分（不要以为装了没效果）

`grpc.biliapi.net` 上有 54 条请求，其中和广告相关的是：

| gRPC 方法 | 承载内容 |
|---|---|
| `bilibili.app.dynamic.v2.Dynamic/DynAll` | 动态页信息流（含推广卡） |
| `bilibili.app.interface.v1.Search/DefaultWords` | 搜索默认词（含热词广告） |
| `bilibili.app.show.v1.Popular/Index` | 热门页 |
| `bilibili.app.nativeact.v1.NativeAct/Index` | 原生活动页 |

这些走 Protobuf 二进制，Loon 的 `response-body-json-jq` 只能处理 JSON，**改不了**。
理论上可以用 Loon 脚本把 Protobuf 解出来再重组，但字段一改版就会崩，且需要逐条逆 schema，收益不值。
唯一"能用"的办法是 `DOMAIN,grpc.biliapi.net,REJECT` —— 等于把动态、搜索、热门、评论一起废掉。不推荐。

---

## 八、复现步骤

```bash
# 1. 先确认 MITM 生效
python tools/analyze_har.py 抓包.har --check

# 2. 看开屏到底下发了多少素材
python tools/analyze_har.py 抓包.har --splash

# 3. 信息流逐条体检（会直接标出哪张是广告卡）
python tools/analyze_har.py 抓包.har --feed

# 4. 定位所有广告字段的 JSON 路径
python tools/analyze_har.py 抓包.har --scan-ads
```

抓包技巧：

1. 开屏只在**冷启动**请求 —— 录之前上滑杀掉 App。
2. 信息流广告要多刷几页；`--feed` 里如果 `广告卡 0 / N`，说明这次没刷到，不是插件的问题。
3. 录完先跑 `--check`，`有响应体` 为 0 就是 MITM 没解密，后面所有分析都没有意义。
