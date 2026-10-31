# 安装与排错

## 一、先搞清楚这件事：插件不生效，90% 是 MITM 没配好

Loon 插件里的 `[Rewrite]` 只有在 **MITM 解密之后** 才能改写响应体。
没开 MITM 时，插件照样"安装成功"，但一行都不会执行 —— 表现就是"装了跟没装一样"。

必须同时满足三条：

| # | 操作 | 位置 |
|---|---|---|
| 1 | 打开 MitM 开关 | Loon → 设置 → MitM |
| 2 | 生成并安装证书 | Loon → 设置 → 证书管理 → 生成证书 → 点证书安装描述文件 |
| 3 | **在系统里开启完全信任** | 设置 → 通用 → 关于本机 → **证书信任设置** → 打开 Loon 的开关 |

> 第 3 步是最常漏的一步。
> 在「设置 → 通用 → VPN与设备管理」里能看到证书，**不代表**它被信任。
> 必须去「关于本机 → 证书信任设置」把开关打开。

---

## 二、安装插件

Loon → 配置 → 插件 → 右上角 `+` → 从 URL 添加：

```
https://fastly.jsdelivr.net/gh/UserC23/bilibili-ads-loon@COMMIT_SHA/BilibiliAds.plugin
```

装完确认插件详情里能看到这几段：

```
[MITM]     hostname = app.bilibili.com, api.live.bilibili.com
[Rewrite]  7 条（3 条 reject-dict + 4 条 response-body-json-jq）
[Rule]     DOMAIN,cm.bilibili.com,REJECT
```

> v2 起 `api.bilibili.com` 不再出现在 `[MITM]` 里 —— 视频详情、播放地址、页面配置都不再解密，
> 这是 v1 卡顿的主要原因之一。看到它没在里面**不是装错了**。

然后 **上滑彻底杀掉 B站** 再重开。只切后台不生效，开屏和信息流都有本地缓存。

---

## 三、怎么确认它真的在工作

### 方法 1：看开屏

杀掉 App → 冷启动。正常应该是**直接进首页**，没有 5 秒倒计时。
如果还有开屏，先看第四节。

### 方法 2：录一份抓包自查

用 Loon 或 Stream 录 1 分钟，导出 HAR，然后：

```bash
python tools/analyze_har.py 抓包.har --check
python tools/analyze_har.py 抓包.har --splash
```

判断标准：

- `--check` 输出 `✅ 抓包可用` → MITM 正常
- `--splash` 里 `splash/list` 显示 `无 list / show 字段…已被插件 reject-dict 清空` → 插件生效了
- 如果 `splash/list` 还是 `素材清单 83 条` → 插件没生效，或者抓到的是旧缓存

### 方法 3：看 Loon 日志

Loon → 首页 → 请求记录，找 `app.bilibili.com/x/v2/splash/list`，
状态应该显示被 rewrite 处理（返回 200 + `{}`）。

---

## 四、还有广告怎么办

按这个顺序排查，**不要跳步**：

### 1. 先排除"根本没生效"

```bash
python tools/analyze_har.py 抓包.har --check
```

- `❌ 所有请求都没有响应体` → MITM 没解密，回到第一节
- `✅ 抓包可用` 但广告还在 → 继续往下

### 2. 确认广告到底从哪个接口来的

```bash
python tools/analyze_har.py 抓包.har --hosts
python tools/analyze_har.py 抓包.har --scan-ads
```

`--scan-ads` 会打出「接口 → 广告字段 → JSON 路径」，比如：

```
app.bilibili.com/x/v2/feed/index/story   creative_id → $.data.items[].ad_info.creative_id   4
```

拿到路径后，往插件的 jq 表达式里加一条 `del(...)` 就行。

### 3. 如果接口在 `grpc.biliapi.net` 上

那就是覆盖不到的部分（动态页、搜索、热门页），Protobuf 改不了。
`docs/analysis.md` 第七节有说明，别浪费时间试。

### 4. 如果是同一个接口上新加的广告位

先看它跟正常内容混没混在一起：

- **整个响应都是广告** → 加一条 `reject-dict`
- **混在列表里** → 加 jq，但先确认正常数据长什么样，别重复 `ad_info` 那个坑

改完把插件 URL 后面的 `@main` 换成一个新的固定 commit，
否则 jsDelivr 可能还给你旧版本，你会以为改的规则没效果。

---

## 五、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 装了没任何变化 | MITM 没开 / 证书没完全信任 | 第一节三步全做一遍 |
| 开屏没了，但首页还有广告卡 | 正常，信息流广告要多刷几页才出现 | 继续刷，或看 `--feed` |
| 首页少了正常直播推荐 | 规则被改坏了（按 `ad_info` 存在性删卡） | 用回仓库原版规则 |
| 直播首页顶部轮播没了 | 预期行为，`banner_v2` 是运营位 | 想保留就把 D3 里 `banner_v2` 那段删掉 |
| 竖屏底部"购物车"入口消失 | 预期行为，那个入口整包就是一条广告 | 想保留就注释 `story/cart` 那行 |
| 视频播放卡顿 / 登录异常 | 多半不是本插件，检查有没有别的 B站规则在打架 | 只保留一个 B站插件 |
| 改了规则但没生效 | jsDelivr 对 `@main` 有缓存 | 换固定 commit 地址 |

---

## 六、卸载 / 回滚

Loon → 配置 → 插件 → 左滑删除 `哔哩哔哩去广告 Pro`，然后杀掉 App 重开。

插件只做三件事：拒绝若干接口、改若干 JSON、REJECT 一个域名。
删除后不会留下任何残留配置。`cm.bilibili.com` 的 REJECT 是写在 `[Rule]` 里的，
删插件即恢复。
