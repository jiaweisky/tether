# QQ 机器人 api-v2 参考（本地镜像）

> **本地、精选镜像**：本文件是 QQ 机器人开放平台 **api-v2** 官方文档的本地精选镜像，仅用于离线参考。
>
> - **非官方**：本文件非腾讯/QQ 官方发布产物，如有出入请以官方文档为准。
> - **官方文档根地址（canonical root）**：https://bot.q.qq.com/wiki/develop/api-v2/
> - **抓取日期**：2026-10-16
> - **表格 / schema / 示例**均按原文逐字复制，未做翻译或改写。
> - 有意**排除**「频道 / guild」历史管理集群，仅镜像「单聊 / 群 / 协议 / 相关」内容集合。

---

## 1. 起步指南

### 启动接入

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/getting-started.html

# 启动接入

## 账号注册

QQ 机器人：一个机器人可以被添加到 `群聊/频道` 内互动对话，QQ 用户也可以直接跟机器人 `单独对话`。

注册地址：[QQ 开放平台官网 (opens new window)](https://q.qq.com/#/)

## 接入票据

注册创建机器人后：获得的开发机器人接入票据 `AppID` `AppSecret`

名称

描述

备注

AppID

机器人 ID

必须使用

AppSecret

机器人密钥

用于请求签名的密钥

Token 的鉴权方式已废弃，请使用更安全的 `Access Token` 鉴权方式。

开发过程中如遇任何问题，可联系 QQ 机器人反馈助手反馈。

## SDK DEMO

快速搭建机器人服务端可参考以下 SDK DEMO。（SDK 仅提供接入参考，详情能力以官方文档能力描述为准）

Go: [botgo (opens new window)](https://github.com/tencent-connect/botgo)

Python: [botpy (opens new window)](https://github.com/tencent-connect/botpy)

NodeJs: [bot-node-sdk (opens new window)](https://github.com/tencent-connect/bot-node-sdk)

### 获取访问凭证

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html

# 获取访问凭证

QQ 机器人开放平台提供以下类型的访问凭证：

凭证类型

是否需要用户授权

说明

access\_token

否

机器人身份调用 API 时使用的凭证，可读写的数据范围由机器人的权限范围决定。适用于机器人主动发消息、管理群聊等场景。

## 获取 access\_token

### 请求

基本

HTTP URL

https://api.bot.qq.com/app/getAppAccessToken

HTTP Method

POST

### 请求参数

**属性**

**类型**

**必填**

**说明**

appId

string

是

在开放平台管理端上获得。

clientSecret

string

是

在开放平台管理端上获得。

### 返回参数

**成功响应**

**属性**

**类型**

**说明**

access\_token

string

获取到的凭证。

expires\_in

number

凭证有效时间，单位：秒。目前是 7200 秒之内的值。

**失败响应**

**属性**

**类型**

**说明**

code

number

错误码，取值见下方「业务错误码」。

message

string

错误信息，仅用于人工排查，内容可能随时调整。

注意

该接口的业务错误通过响应体的 `code` 返回，即使调用失败，HTTP 返回码仍为 `200`。请优先依据 `code` 判断请求是否成功，不要只依赖 HTTP 返回码；也不要依据 `message` 判定错误类型。详见下方「错误返回码」。

### 错误码

#### 业务错误码

**错误码**

**错误信息**

**排查指南**

100001

Too many requests

请求过于频繁，请降低调用频率后重试

100007

appid invalid

AppID 无效，或机器人状态不正常（被封禁或已删除），请检查 AppID 是否正确以及机器人状态

100016

invalid appid or secret

AppID 或 ClientSecret 不正确，请检查传入的 appId 和 clientSecret 是否与开放平台管理端一致

10004

机器人不存在

AppID 对应的机器人不存在，请确认 AppID 是否正确

### 调用示例

```
curl --location 'https://api.bot.qq.com/app/getAppAccessToken' \
--header 'Content-Type: application/json' \
--data '{
  "appId": "APPID",
  "clientSecret": "CLIENTSECRET"
}'
```

### 返回示例

**成功**

```
{
  "access_token": "ACCESS_TOKEN",
  "expires_in": "7200"
}
```

**失败**

```
{
  "code": 100007,
  "message": "appid invalid"
}
```

## 凭证有效期与刷新

目前 `access_token` 生命周期默认 `7200` 秒（2 小时），开发者需要在过期后自行刷新 `access_token`，保证调用链路权限正常。

-   每次请求不会刷新新的 `access_token`，在有效期内重复获取会返回相同的值
-   在上一个 `access_token` 接近过期时间 `60` 秒内，获取 `access_token` 时，会获得一个新的 `access_token`，老的 `access_token` 在这个 `60` 秒内仍然有效
-   建议开发者在服务端设置定时刷新凭证的业务逻辑，以防止过期

## 使用访问凭证

在每次调用 OpenAPI 开放接口时，需要在 HTTP 请求头中引入 `access_token` 进行调用权限验证。

**请求头**：

名称

类型

必填

描述

Authorization

string

是

格式值：`QQBot ACCESS_TOKEN`

**示例**：

```
curl --location 'https://api.bot.qq.com/users/@me' \
--header 'Authorization: QQBot ACCESS_TOKEN'
```

注意

为了安全考虑，请勿在应用前端使用访问凭证。请在应用服务端发起 API 访问请求。

### API 调用指南

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html

# API 调用指南

QQ 机器人开放平台提供了基于 HTTPS 协议的 OpenAPI 接口，开发者可以通过这些接口实现消息收发、群聊管理、频道管理等功能。

## 调用方式

### 统一请求地址

```
https://api.bot.qq.com
```

### 鉴权方式

调用 API 时，需要将 access\_token 放入请求 Header 中：

```
Authorization: QQBot {ACCESS_TOKEN}
```

### 请求示例

以发送单聊消息为例：

```
curl -X POST 'https://api.bot.qq.com/v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages' \
-H 'Authorization: QQBot {ACCESS_TOKEN}' \
-H 'Content-Type: application/json; charset=utf-8' \
-d '{
  "content": "Hello World",
  "msg_type": 0,
  "msg_id": "previous_msg_id"
}'
```

### 响应结构

API 调用成功时，响应体直接返回业务数据；调用失败时，响应体包含 `err_code`、`message` 等错误信息：

-   **err\_code**：错误码。成功时为 0
-   **message**：错误信息
-   **trace\_id**：链路追踪 ID，用于问题排查

**成功响应示例**：

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "timestamp": "2026-07-21T10:30:00+08:00"
}
```

**失败响应示例**：

```
{
  "err_code": 40034005,
  "message": "回复消息msg_id已过期",
  "trace_id": "4a8a61565b909f199b1ec169fdd6f49e"
}
```

注意

请不要依据 `message` 来判定一个请求是否失败，`message` 可能会随时调整，建议根据 `err_code` 判断请求是否失败。

## 唯一身份机制

不同的 `bot(AppID)` 获取到的用户 `openid`，群 `openid`，频道 `openid` 均不相同，若跨业务有关联用户身份需求，后续提供跨 `AppID` 绑定后，使用类似 `unionid` 的机制打通身份。

举例

-   不同 `bot` 在单聊场景，获取到的用户唯一识别 `openid` 不一样，称为 `user_openid`
-   不同 `bot` 在群聊场景，获取到的群唯一识别号 `openid` 不一样，称为 `group_openid`
-   `bot` 在群聊场景，获取到用户在群内的唯一识别号，称为 `member_openid`

## 全链路追踪

平台的链路追踪 `TraceID` 可通过两种方式获取：

-   **HTTP 响应头**：`X-Tps-trace-ID` 字段
-   **响应 Body**：返回体中的 `trace_id` 字段

如果开发者有无法自行定位的问题，需要找平台协助时，可提取该 ID 提交给平台方，方便查询相关日志。

## OpenAPI 错误码

错误码分为两部分：

-   HTTP 状态码
-   HTTP Body 返回的 JSON 中的 `err_code`

### HTTP 状态码

值

含义

200

成功

204

成功，但是无包体，一般用于删除操作

201, 202

异步操作成功，虽然说成功，但是会返回一个 error body，需要特殊处理

401

认证失败

404

未找到 API

405

HTTP Method 不允许

429

频率限制

500

处理失败

504

处理失败

### 公共错误码

> 以下为所有接口通用的公共错误码。各接口特有的错误码请查阅具体接口文档中的「错误码」章节。

值

含义

10001

UnknownAccount 账号异常

10003

UnknownChannel 子频道异常

10004

UnknownGuild 频道异常

11281

ErrorCheckAdminFailed 检查是否是管理员失败，系统错误，一般重试一次会好，最多只能重试一次

11282

ErrorCheckAdminNotPass 检查是否是管理员未通过，该接口需要管理员权限，但是用户在添加机器人的时候并未授予该权限，属于逻辑错误，可以提示用户进行授权

11251

ErrorWrongAppid 参数中的 appid 错误，开发者填的 token 错误，appid 无法识别

11252

ErrorCheckAppPrivilegeFailed 检查应用权限失败，系统错误，一般重试一次会好，最多只能重试一次

11253

ErrorCheckAppPrivilegeNotPass 检查应用权限不通过，该机器人应用未获得调用该接口的权限，需要向平台申请

11254

ErrorInterfaceForbidden 应用接口被封禁，该机器人虽然获得了该接口权限，但是被封禁了

11261

ErrorWrongAppid 参数中缺少 appid，同 11251

11262

ErrorCheckRobot 当前接口不支持使用机器人 Bot Token 调用

11263

ErrorCheckGuildAuth 检查频道权限失败，系统错误，一般重试一次会好，最多只能重试一次

11264

ErrorGuildAuthNotPass 检查小站权限未通过，管理员添加机器人的时候未授予该接口权限，属于逻辑错误，可提示用户进行授权，如果已经给予授权，请检查传递的 guild id 是否正确

11265

ErrorRobotHasBaned 机器人已经被封禁

11241

ErrorWrongToken 参数中缺少 token

11242

ErrorCheckTokenFailed 校验 token 失败，系统错误，一般重试一次会好，最多只能重试一次

11243

ErrorCheckTokenNotPass 校验 token 未通过，用户填充的 token 错误，需要开发者进行检查

11273

ErrorCheckUserAuth 检查用户权限失败，当前接口不支持使用 Bearer Token 调用

11274

ErrorUserAuthNotPass 检查用户权限未通过，用户 OAuth 授权时未给与该接口权限，可提示用户重新进行授权

11275

ErrorWrongAppid 无 appid，同 11251

11301

ErrorGetHTTPHeader HTTP Header 无效

11302

ErrorGetHeaderUIN HTTP Header 无效

11303

ErrorGetNick 获取昵称失败

11304

ErrorGetAvatar 获取头像失败

11305

ErrorGetGuildID 获取频道 ID 失败

11306

ErrorGetGuildInfo 获取频道信息失败

12001

ReplaceIDFailed 替换 id 失败

12002

RequestInvalid 请求体错误

12003

ResponseInvalid 回包错误

20028

ChannelHitWriteRateLimit 子频道消息触发限频

50006

CannotSendEmptyMessage 消息为空

50035

InvalidFormBody form-data 内容异常

50037

带有 markdown 消息只支持 markdown 或者 keyboard 组合

50038

非同频道同子频道

50039

获取消息失败

50040

消息模版类型错误

50041

markdown 有空值

50042

markdown 列表长达最大值

50043

guild\_id 转换失败

50045

不能回复机器人自己产生的消息

50046

非 at 机器人消息

50047

非机器人产生的消息 或者 at 机器人消息

50048

message id 不能为空

50049

只能修改含有 keyboard 元素的消息

50050

修改消息时，keyboard 元素不能为空

50051

只能修改机器人自己发送的消息

50053

修改消息错误

50054

markdown 模版参数错误

50055

无效的 markdown content

50056

不允许发送 markdown content

50057

markdown 参数只支持原生语法或者模版二选一

301000~301099

子频道权限错误

301000

参数错误

301001

查询频道信息错误

301002

查询子频道权限错误

301003

修改子频道权限错误

301004

私密子频道关联的人数到达上限

301005

调用 Rpc 服务失败

301006

非群成员没有查询权限

301007

参数超过数量限制

302000

参数错误

302001

查询频道信息错误

302002

查询日程列表失败

302003

查询日程失败

302004

修改日程失败

302005

删除日程失败

302006

创建日程失败

302007

获取创建者信息失败

302008

子频道 ID 不能为空

302009

频道系统错误，请联系客服

302010

暂无修改日程权限

302011

日程活动已被删除

302012

每天只能创建 10 个日程，明天再来吧！

302013

创建日程触发安全打击

302014

日程持续时间超过 7 天，请重新选择

302015

开始时间不能早于当前时间

302016

结束时间不能早于开始时间

302017

Schedule 对象为空

302018

参数类型转换失败

302019

调用下游失败，请联系客服

302020

日程内容违规、账号违规

302021

频道内当日新增活动达上限

302022

不能绑定非当前频道的子频道

302023

开始时跳转不可绑定日程子频道

302024

绑定的子频道不存在

304003

URL\_NOT\_ALLOWED url 未报备

304004

ARK\_NOT\_ALLOWED 没有发 ark 消息权限

304005

EMBED\_LIMIT embed 长度超限

304006

SERVER\_CONFIG 后台配置错误

304007

GET\_GUILD 查询频道异常

304008

GET\_BOT 查询机器人异常

304009

GET\_CHENNAL 查询子频道异常

304010

CHANGE\_IMAGE\_URL 图片转存错误

304011

NO\_TEMPLATE 模板不存在

304012

GET\_TEMPLATE 取模板错误

304014

TEMPLATE\_PRIVILEGE 没有模板权限

304016

SEND\_ERROR 发消息错误

304017

UPLOAD\_IMAGE 图片上传错误

304018

SESSION\_NOT\_EXIST 机器人没连上 gateway

304019

AT\_EVERYONE\_TIMES @全体成员 次数超限

304020

FILE\_SIZE 文件大小超限

304021

GET\_FILE 下载文件错误

304022

PUSH\_TIME 推送消息时间限制

304023

PUSH\_MSG\_ASYNC\_OK 推送消息异步调用成功，等待人工审核

304024

REPLY\_MSG\_ASYNC\_OK 回复消息异步调用成功，等待人工审核

304025

BEAT 消息被打击

304026

MSG\_ID 回复的消息 id 错误

304027

MSG\_EXPIRE 回复的消息过期

304028

MSG\_PROTECT 非 At 当前用户的消息不允许回复

304029

CORPUS\_ERROR 调语料服务错误

304030

CORPUS\_NOT\_MATCH 语料不匹配

304031

私信已关闭

304032

私信不存在

304033

拉私信错误

304034

不是私信成员

304035

推送消息超过子频道数量限制

304036

没有 markdown 模板的权限

304037

没有发消息按钮组件的权限

304038

消息按钮组件不存在

304039

消息按钮组件解析错误

304040

消息按钮组件消息内容错误

304044

取消息设置错误

304045

子频道主动消息数限频

304046

不允许在此子频道发主动消息

304047

主动消息推送超过限制的子频道数

304048

不允许在此频道发主动消息

304049

私信主动消息数限频

304050

私信主动消息总量限频

304051

消息设置引导请求构造错误

304052

发消息设置引导超频

306001

param invalid 撤回消息参数错误

306002

msgid error 消息 id 错误

306003

fail to get message 获取消息错误(可重试)

306004

no permission to delete message 没有撤回此消息的权限

306005

retract message error 消息撤回失败(可重试)

306006

fail to get channel 获取子频道失败(可重试)

501000~501999

公告错误

501001

参数校验失败

501002

创建子频道公告失败(可重试)

501003

删除子频道公告失败(可重试)

501004

获取频道信息失败(可重试)

501005

MessageID 错误

501006

创建频道全局公告失败(可重试)

501007

删除频道全局公告失败(可重试)

501008

MessageID 不存在

501009

MessageID 解析失败

501010

此条消息非子频道内消息

501011

创建精华消息失败(可重试)

501012

删除精华消息失败(可重试)

501013

精华消息超过最大数量

501014

安全打击

501015

此消息不允许设置

501016

频道公告子频道推荐超过最大数量

501017

非频道主或管理员

501018

推荐子频道 ID 无效

501019

公告类型错误

501020

创建推荐子频道类型频道公告失败

502000~502099

禁言相关错误

502001

频道 id 无效

502002

频道 id 为空

502003

用户 id 无效

502004

用户 id 为空

502005

timestamp 不合法

502006

timestamp 无效

502007

参数转换错误

502008

rpc 调用失败

502009

安全打击

502010

请求头错误

503001

频道 id 无效

503002

频道 id 为空

503003

获取子频道信息失败

503004

超出发布帖子的频次限制

503005

帖子标题为空

503006

帖子内容为空

503007

帖子ID为空

503008

获取X-Uin失败

503009

帖子ID无效或不合法

503010

通过Uin获取TinyID失败

503011

帖子ID里面的时间戳无效或不合法

503012

帖子不存在或已删除

503013

服务器内部错误

503014

帖子JSON内容解析失败

503015

帖子内容转换失败

503016

链接数量超过限制

503017

字数超过限制

503018

图片数量超过限制

503019

视频数量超过限制

503020

标题长度超过限制

504000~504999

消息频率相关错误

504001

请求参数无效错误

504002

获取 HTTP 头失败

504003

获取 BOT UIN 错误

504004

获取消息频率设置信息错误

610000-619999

频道权限错误

610001

获取频道 ID 失败

610002

获取 HTTP 头失败

610003

获取机器人号码失败

610004

获取机器人角色失败

610005

获取机器人角色内部错误

610006

拉取机器人权限列表失败

610007

机器人不在频道内

610008

无效参数

610009

获取 API 接口详情失败

610010

API 接口已授权

610011

获取机器人信息失败

610012

限频失败

610013

已限频

610014

api 授权链接发送失败

620001-629999

表情表态错误

620001

表情表态无效参数

620002

已经达到表情反应的类型数量上限

620003

已经设置过该表情表态

620004

没有设置过该表情表态

620005

没有权限设置表情表态

620006

操作限频

620007

表情表态操作失败，请重试

630001-639999

互动回调数据更新

630001

互动回调数据更新无效参数

630002

互动回调数据更新获取AppID失败

630003

互动回调数据AppID不匹配

630004

互动回调数据更新内部存储错误

630005

互动回调数据更新内部存储读取错误

630006

互动回调数据更新读取请求AppID失败

630007

互动回调数据太大

1000000~2999999

发消息错误

1100100

安全打击：消息被限频

1100101

安全打击：内容涉及敏感，请返回修改

1100102

安全打击：抱歉，暂未获得新功能体验资格

1100103

安全打击

1100104

安全打击：该群已失效或当前群已不存在

1100300

系统内部错误

1100301

调用方不是群成员

1100302

获取指定频道名称失败

1100303

主页频道非管理员不允许发消息

1100304

@次数鉴权失败

1100305

TinyId 转换 Uin 失败

1100306

非私有频道成员

1100307

非白名单应用子频道

1100308

触发频道内限频

1100499

其他错误

3000000~3999999

编辑消息错误

3300006

安全打击

### 通用数据结构

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html

# 通用数据结构

`payload` 指的是在 `webhook` 或 `websocket` 连接上传输的数据，网关的上下行消息采用的都是同一个结构，如下：

```
{
  "id":"event_id",
  "op": 0,
  "d": {},
  "s": 42,
  "t": "GATEWAY_EVENT_NAME"
}
```

字段

描述

id

事件id

op

指的是 opcode，参考连接维护

s

下行消息都会有一个序列号，标识消息的唯一性，客户端需要再发送心跳的时候，携带客户端收到的最新的 s

t

代表事件类型。主要用在 op 为 0 Dispatch 的时候

d

代表事件内容，不同事件类型的事件内容格式都不同，请注意识别。主要用在 op 为 0 Dispatch 的时候

## OpCode 含义

所有 `opcode` 列表如下：

**CODE**

**名称**

**接入方式**

**客户端行为**

**描述**

0

Dispatch

webhook/websocket

Receive

服务端进行消息推送

1

Heartbeat

websocket

Send/Receive

客户端或服务端发送心跳

2

Identify

websocket

Send

客户端发送鉴权

6

Resume

websocket

Send

客户端恢复连接

7

Reconnect

websocket

Receive

服务端通知客户端重新连接

9

Invalid Session

websocket

Receive

当 identify 或 resume 的时候，如果参数有错，服务端会返回该消息

10

Hello

websocket

Receive

当客户端与网关建立 ws 连接之后，网关下发的第一条消息

11

Heartbeat ACK

websocket

Receive/Reply

当发送心跳成功之后，就会收到该消息

12

HTTP Callback ACK

webhook

Reply

仅用于 http 回调模式的回包，代表机器人收到了平台推送的数据

13

回调地址验证

webhook

Receive

开放平台对机器人服务端进行验证

客户端行为含义如下：

-   `Receive` 客户端接收到服务端 `push` 的消息
-   `Send` 客户端发送消息
-   `Reply` 客户端接收到服务端发送的消息之后的回包（HTTP 回调模式）

## 事件订阅 Intents

事件的 `intents` 是一个标记位，每一位都代表不同的事件，如果需要接收某类事件，就将该位置为 `1`。

每个 `intents` 位代表的是一类事件，可以使用 `websocket` 传输的数据中的 `t` 字段的值来区分。

事件和位移的关系如下：

```
GUILDS (1 << 0)
  - GUILD_CREATE           // 当机器人加入新guild时
  - GUILD_UPDATE           // 当guild资料发生变更时
  - GUILD_DELETE           // 当机器人退出guild时
  - CHANNEL_CREATE         // 当channel被创建时
  - CHANNEL_UPDATE         // 当channel被更新时
  - CHANNEL_DELETE         // 当channel被删除时

GUILD_MEMBERS (1 << 1)
  - GUILD_MEMBER_ADD       // 当成员加入时
  - GUILD_MEMBER_UPDATE    // 当成员资料变更时
  - GUILD_MEMBER_REMOVE    // 当成员被移除时

GUILD_MESSAGES (1 << 9)    // 消息事件，仅 *私域* 机器人能够设置此 intents。
  - MESSAGE_CREATE         // 发送消息事件，代表频道内的全部消息，而不只是 at 机器人的消息。内容与 AT_MESSAGE_CREATE 相同
  - MESSAGE_DELETE         // 删除（撤回）消息事件

GUILD_MESSAGE_REACTIONS (1 << 10)
  - MESSAGE_REACTION_ADD    // 为消息添加表情表态
  - MESSAGE_REACTION_REMOVE // 为消息删除表情表态

DIRECT_MESSAGE (1 << 12)
  - DIRECT_MESSAGE_CREATE   // 当收到用户发给机器人的私信消息时
  - DIRECT_MESSAGE_DELETE   // 删除（撤回）消息事件

GROUP_AND_C2C_EVENT (1 << 25)
  - C2C_MESSAGE_CREATE      // 用户单聊发消息给机器人时候
  - FRIEND_ADD              // 用户添加使用机器人
  - FRIEND_DEL              // 用户删除机器人
  - C2C_MSG_REJECT          // 用户在机器人资料卡手动关闭"主动消息"推送
  - C2C_MSG_RECEIVE         // 用户在机器人资料卡手动开启"主动消息"推送开关
  - GROUP_AT_MESSAGE_CREATE // 用户在群里@机器人时收到的消息
  - GROUP_ADD_ROBOT         // 机器人被添加到群聊
  - GROUP_DEL_ROBOT         // 机器人被移出群聊
  - GROUP_MSG_REJECT        // 群管理员主动在机器人资料页操作关闭通知
  - GROUP_MSG_RECEIVE       // 群管理员主动在机器人资料页操作开启通知

INTERACTION (1 << 26)
  - INTERACTION_CREATE     // 互动事件创建时

MESSAGE_AUDIT (1 << 27)
  - MESSAGE_AUDIT_PASS     // 消息审核通过
  - MESSAGE_AUDIT_REJECT   // 消息审核不通过

FORUMS_EVENT (1 << 28)  // 论坛事件，仅 *私域* 机器人能够设置此 intents。
  - FORUM_THREAD_CREATE     // 当用户创建主题时
  - FORUM_THREAD_UPDATE     // 当用户更新主题时
  - FORUM_THREAD_DELETE     // 当用户删除主题时
  - FORUM_POST_CREATE       // 当用户创建帖子时
  - FORUM_POST_DELETE       // 当用户删除帖子时
  - FORUM_REPLY_CREATE      // 当用户回复评论时
  - FORUM_REPLY_DELETE      // 当用户回复评论时
  - FORUM_PUBLISH_AUDIT_RESULT      // 当用户发表审核通过时

AUDIO_ACTION (1 << 29)
  - AUDIO_START             // 音频开始播放时
  - AUDIO_FINISH            // 音频播放结束时
  - AUDIO_ON_MIC            // 上麦时
  - AUDIO_OFF_MIC           // 下麦时

PUBLIC_GUILD_MESSAGES (1 << 30) // 消息事件，此为公域的消息事件
  - AT_MESSAGE_CREATE       // 当收到@机器人的消息时
  - PUBLIC_MESSAGE_DELETE   // 当频道的消息被删除时
```

### 举例

如开发者需要接收用户 at 机器人的消息，那么就需要在 `intents` 中设置接收 `PUBLIC_GUILD_MESSAGES`。则需要先计算 `1 << 30` 的值。然后与 `0` 做位或操作，得到最终需要传递的 `intents`。

如果涉及到多个事件类型的接收，则需要将多个结果做位或操作，如：`0|1<<30|1<<1` 代表订阅 `PUBLIC_GUILD_MESSAGES` 和 `GUILD_MEMBERS` 这两类事件。

### 权限

事件类型的订阅，是有权限控制的，除了 `GUILDS`，`PUBLIC_GUILD_MESSAGES`，`GUILD_MEMBERS` 事件是基础的事件，默认有权限订阅之外，其他的特殊事件，都需要经过申请才能够使用，如果在鉴权的时候传递了无权限的 `intents`，`websocket` 会报错，并直接关闭连接。请开发者注意订阅事件的范围需要控制在自己所需要的范围之内。

如果拥有的某个特殊事件类型的权限被取消，则在当前连接上不会报错，但是将不会收到对应的事件类型，如果重新连接，则报错，所以如果开发者的事件类型权限被取消，请及时调整监听事件代码，避免报错导致的无法连接。

### WebSocket 方式

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/websocket.html

# WebSocket 方式

## 发起连接到 Gateway

第一步先调用 [获取通用WSS 接入点](/wiki/develop/api-v2/openapi/wss/url_get.html) 或 [获取带分片WSS 接入点](/wiki/develop/api-v2/openapi/wss/shard_url_get.html) 接口获取网关地址。

会得到一个类似下面这样的地址：

```
wss://api.bot.qq.com/websocket/
```

然后进行 `websocket` 长连接建立，一旦连接成功，就会返回 OpCode 10 Hello 消息。这个消息主要的内容是心跳周期，单位毫秒(milliseconds)，如下：

```
{
  "op": 10,
  "d": {
    "heartbeat_interval": 45000
  }
}
```

## 登录鉴权获得 Session

`websocket` 长连接建立之后，需要进行登录鉴权，登录鉴权成功后会获得一个 session 会话 id，只有登录成功后，QQ 后台才会下发事件通知。

发送一个 OpCode 2 Identify 消息，`payload` 如下：

```
{
  "op": 2,
  "d": {
    "token": "token string",
    "intents": 513,
    "shard": [0, 4],
    "properties": {
      "$os": "linux",
      "$browser": "my_library",
      "$device": "my_library"
    }
  }
}
```

**字段**

**描述**

token

格式为 "QQBot {AccessToken}"

intents

是此次连接所需要接收的事件，具体可参考 [事件订阅 Intents](/wiki/develop/api-v2/dev-prepare/event-emit/payload.html#事件订阅-intents)

shard

考虑到开发者事件接收时可以实现负载均衡，QQ 提供了分片逻辑，事件通知会落在不同的分片上，该参数是个拥有两个元素的数组。例如：`[0,4]`，代表分为四个片，当前链接是第 0 个片，业务稍后应该继续建立 `shard` 为 `[1,4]`, `[2,4]`, `[3,4]` 的链接，才能完整接收事件，更多详细的内容可以参考 [Shard 机制](#%E5%88%86%E7%89%87%E8%BF%9E%E6%8E%A5-loadbalance)。若无需分片，使用 `[0, 1]` 即可。

properties

目前无实际作用，可以按照自己的实际情况填写，也可以留空

鉴权成功之后，QQ 后台会下发一个 Ready Event，`payload` 如下：

```
{
  "op": 0,
  "s": 1,
  "t": "READY",
  "d": {
    "version": 1,
    "session_id": "082ee18c-0be3-491b-9d8b-fbd95c51673a",
    "user": {
      "id": "6158788878435714165",
      "username": "群pro测试机器人",
      "bot": true
    },
    "shard": [0, 0]
  }
}
```

## 发送心跳 Ack

鉴权成功之后，就需要按照周期进行心跳发送。d 为客户端收到的最新的消息的 s，如果是首次连接，d 为传 null，`payload` 如下：

```
{
  "op": 1,
  "d": 251
}
```

心跳发送成功之后会收到 OpCode 11 Heartbeat ACK 消息，`payload` 如下：

```
{
  "op": 11
}
```

## 恢复登录态 Session

有很多原因可能会导致 `websocket` 长连接断开，断开之后短时间内重连会补发中间遗漏的事件，以保障业务逻辑的正确性。断开重连 gateway 后不需要发送重新登录 OpCode 2 Identify 请求。在连接到 `Gateway` 之后，需要发送 OpCode 6 Resume 消息，`payload` 如下：

```
{
  "op": 6,
  "d": {
    "token": "my_token",
    "session_id": "session_id_i_stored",
    "seq": 1337
  }
}
```

其中 `seq` 指的是在接收事件时候的 `s` 字段，我们推荐开发者在处理过事件之后记录下 `s` 这样可以在 `resume` 的时候传递给 `websocket`，`websocket` 会自动补发这个 seq 之后的事件。

恢复成功之后，就开始补发遗漏事件，所有事件补发完成之后，会下发一个 `Resumed Event`，`payload` 如下：

```
{
  "op": 0,
  "s": 2002,
  "t": "RESUMED",
  "d": ""
}
```

## 分片连接 LoadBalance

随着 bot 的增长并被添加到越来越多的频道中，事件越来越多，业务有必要对事件进行水平分割，实现负载均衡。机器人网关实现了一种用户可控制的分片方法，该方法允许跨多个网关连接拆分事件。分片完全由用户控制，并且不需要在单独的连接之间进行状态共享。

要在连接上启用分片，需要在建立连接的时候指定分片参数，具体参考 [gateway](/wiki/develop/api-v2/dev-prepare/interface-framework/reference.html)

### 获得合适的分片数

使用 [/gateway/bot](/wiki/develop/api-v2/openapi/wss/shard_url_get.html) 接口获取网关地址的时候，会同时返回一个建议的 `shard` 数，及最大并发限制。

```
{
  "url": "wss://api.bot.qq.com/websocket",
  "shards": 1,
  "session_start_limit": {
    "total": 1000,
    "remaining": 1000,
    "reset_after": 86400000,
    "max_concurrency": 1
  }
}
```

### 分片规则

分片是按照频道 id 进行哈希的，同一个频道的信息会固定从同一个链接推送。具体哈希计算规则如下：

```
shard_id = (guild_id >> 22) % num_shards
```

### 最大连接数

每个机器人创建的连接数不能超过 `remaining` 剩余连接数。

## WebSocket 错误码

值

含义

是否可以重试 RESUME

是否可以重试 IDENTIFY

4001

无效的 opcode

否

否

4002

无效的 payload

否

否

4007

seq 错误

否

**是**

4006

无效的 session id，无法继续 resume，请 identify

否

**是**

4008

发送 payload 过快，请重新连接，并遵守连接后返回的频控信息

**是**

**是**

4009

连接过期，请重连并执行 resume 进行重新连接

**是**

**是**

4010

无效的 shard

否

否

4011

连接需要处理的 guild 过多，请进行合理的分片

否

否

4012

无效的 version

否

否

4013

无效的 intent

否

否

4014

intent 无权限

否

否

4900~4913

内部错误，请重连

否

**是**

4914

机器人已下架，只允许连接沙箱环境，请断开连接，检验当前连接环境

否

否

4915

机器人已封禁，不允许连接，请断开连接，申请解封后再连接

否

否

针对 WebSocket 错误码的简单处理逻辑：

-   4009 可以重新发起 resume
-   4914，4915 不可以连接，请联系官方解封
-   其他错误，请重新发起 identify

### Webhook 方式

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html

# Webhook 方式

QQ 机器人开放平台支持通过使用 HTTP 接口接收事件。开发者可通过[管理端 (opens new window)](https://q.qq.com/qqbot/#/developer/webhook-setting)设定回调地址，监听事件等。

目前回调地址允许配置的端口号为：80、443、8080、8443。

## 签名校验

机器人服务端需要对回调请求进行签名验证以保证数据没有被篡改过。[签名算法](/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html)

## 回调地址及事件监听配置

开发者需要提供一个 HTTPS 回调地址。并选定监听的事件类型。开放平台会将事件通过回调的方式推送给机器人。

![event_subscription](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/webhook_new.b24ed4d6.png)

配置回调地址后，开放平台会对回调地址进行验证：

-   请求结构(Payload.d)

**字段**

**描述**

plain\_token

需要计算签名的字符串

event\_ts

计算签名使用时间戳

-   返回结果

**字段**

**描述**

plain\_token

需要计算签名的字符串

signature

签名

计算过程如下(golang)：

```
func handleValidation(rw http.ResponseWriter, r *http.Request, botSecret string) {
	httpBody, err := io.ReadAll(r.Body)
	if err != nil {
		log.Println("read http body err", err)
		return
	}
	payload := &Payload{}
	if err = json.Unmarshal(httpBody, payload); err != nil {
		log.Println("parse http payload err", err)
		return
	}
	validationPayload := &ValidationRequest{}
	if 	err = json.Unmarshal(payload.Data, validationPayload);err != nil {
		log.Println("parse http payload failed:", err)
		return
	}
	seed := botSecret
	for len(seed) < ed25519.SeedSize {
		seed = strings.Repeat(seed, 2)
	}
	seed = seed[:ed25519.SeedSize]
	reader := strings.NewReader(seed)
	// GenerateKey 方法会返回公钥、私钥，这里只需要私钥进行签名生成不需要返回公钥
	_, privateKey, err := ed25519.GenerateKey(reader)
	if err != nil {
		log.Println("ed25519 generate key failed:", err)
		return
	}
	var msg bytes.Buffer
	msg.WriteString(validationPayload.EventTs)
	msg.WriteString(validationPayload.PlainToken)
	signature := hex.EncodeToString(ed25519.Sign(privateKey, msg.Bytes()))
	if err != nil {
		log.Println("generate signature failed:", err)
		return
	}
	rspBytes, err := json.Marshal(
		&ValidationResponse{
			PlainToken: validationPayload.PlainToken,
			Signature:  signature,
		})
	if err != nil {
		log.Println("handle validation failed:", err)
		return
	}
	rw.Write(rspBytes)
}
```

例如机器人账号

```
appid: 11111111
secret: DG5g3B4j9X2KOErG
```

回调验证请求：

```
headers: User-Agent:[QQBot-Callback] X-Bot-Appid:[11111111]
body: {"d":{"plain_token":"Arq0D5A61EgUu4OxUvOp","event_ts":"1725442341"},"op":13},
```

机器人应返回：

```
body: {"plain_token": "Arq0D5A61EgUu4OxUvOp","signature": "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"}
```

### opcode

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html

# opcode

所有opcode列表如下：

CODE

名称

客户端操作

描述

0

Dispatch

Receive

服务端进行消息推送

1

Heartbeat

Send/Receive

客户端或服务端发送心跳

2

Identify

Send

客户端发送鉴权

6

Resume

Send

客户端恢复连接

7

Reconnect

Receive

服务端通知客户端重新连接

9

Invalid Session

Receive

当identify或resume的时候，如果参数有错，服务端会返回该消息

10

Hello

Receive

当客户端与网关建立ws连接之后，网关下发的第一条消息

11

Heartbeat ACK

Receive/Reply

当发送心跳成功之后，就会收到该消息

12

HTTP Callback ACK

Reply

仅用于 http 回调模式的回包，代表机器人收到了平台推送的数据()

13

回调地址验证

Receive

开放平台对机器人服务端进行验证

客户端操作含义如下：

-   `Receive` 客户端接收到服务端 push 的消息
-   `Send` 客户端发送消息
-   `Reply` 客户端接收到服务端发送的消息之后的回包（HTTP 回调模式）

### 事件订阅与通知

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html

# 事件订阅与通知

说明

当用户在QQ平台内的一些行为操作或某些接口的有异步返回通知确认机制的场景的时候，QQ 会通过"事件"的方式，通知到开发者服务器，开发者可自行根据具体事件通知来进行下一步响应。譬如用户跟机器人发消息，用户添加机器人好友，机器人被拉入群聊等等事件。

## 通用数据结构 Payload

`payload` 指的是在 `webhook`或`websocket` 连接上传输的数据，网关的上下行消息采用的都是同一个结构，如下：

```
{
  "id":"event_id",
  "op": 0,
  "d": {},
  "s": 42,
  "t": "GATEWAY_EVENT_NAME"
}
```

字段

描述

id

事件id

op

指的是 opcode，参考连接维护

s

下行消息都会有一个序列号，标识消息的唯一性，客户端需要再发送心跳的时候，携带客户端收到的最新的s

t

代表事件类型。主要用在op为 0 Dispatch 的时候

d

代表事件内容，不同事件类型的事件内容格式都不同，请注意识别。主要用在op为 0 Dispatch 的时候

### OpCode 含义

所有 `opcode` 列表如下：

**CODE**

**名称**

接入方式

**客户端行为**

**描述**

0

Dispatch

webhook/websocket

Receive

服务端进行消息推送

1

Heartbeat

websocket

Send/Receive

客户端或服务端发送心跳

2

Identify

websocket

Send

客户端发送鉴权

6

Resume

websocket

Send

客户端恢复连接

7

Reconnect

websocket

Receive

服务端通知客户端重新连接

9

Invalid Session

websocket

Receive

当 identify 或 resume 的时候，如果参数有错，服务端会返回该消息

10

Hello

websocket

Receive

当客户端与网关建立 ws 连接之后，网关下发的第一条消息

11

Heartbeat ACK

websocket

Receive/Reply

当发送心跳成功之后，就会收到该消息

12

HTTP Callback ACK

webhook

Reply

仅用于 http 回调模式的回包，代表机器人收到了平台推送的数据

13

回调地址验证

webhook

Receive

开放平台对机器人服务端进行验证

客户端行为含义如下：

`Receive` 客户端接收到服务端 `push` 的消息

`Send` 客户端发送消息

`Reply` 客户端接收到服务端发送的消息之后的回包（HTTP 回调模式）

## Webhook方式

QQ机器人开放平台支持通过使用HTTP接口接收事件。开发者可通过[管理端 (opens new window)](https://q.qq.com/qqbot/#/developer/webhook-setting)设定回调地址，监听事件等。

目前回调地址允许配置的端口号为： 80、443、8080、8443。

### 签名校验

机器人服务端需要对回调请求进行签名验证以保证数据没有被篡改过。 [签名算法](/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html)

### 回调地址及事件监听配置

开发者需要提供一个HTTPS回调地址。并选定监听的事件类型。开放平台会将事件通过回调的方式推送给机器人。

![event_subscription](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/webhook_new.b24ed4d6.png)

配置回调地址后，开放平台会对回调地址进行验证：

-   请求结构(Payload.d)

**字段**

**描述**

plain\_token

需要计算签名的字符串

event\_ts

计算签名使用时间戳

-   返回结果

**字段**

**描述**

plain\_token

需要计算签名的字符串

signature

签名

计算过程如下(golang)：

```
func handleValidation(rw http.ResponseWriter, r *http.Request, botSecret string) {
	httpBody, err := io.ReadAll(r.Body)
	if err != nil {
		log.Println("read http body err", err)
		return
	}
	payload := &Payload{}
	if err = json.Unmarshal(httpBody, payload); err != nil {
		log.Println("parse http payload err", err)
		return
	}
	validationPayload := &ValidationRequest{}
	if 	err = json.Unmarshal(payload.Data, validationPayload);err != nil {
		log.Println("parse http payload failed:", err)
		return
	}
	seed := botSecret
	for len(seed) < ed25519.SeedSize {
		seed = strings.Repeat(seed, 2)
	}
	seed = seed[:ed25519.SeedSize]
	reader := strings.NewReader(seed)
	// GenerateKey 方法会返回公钥、私钥，这里只需要私钥进行签名生成不需要返回公钥
	_, privateKey, err := ed25519.GenerateKey(reader)
	if err != nil {
		log.Println("ed25519 generate key failed:", err)
		return
	}
	var msg bytes.Buffer
	msg.WriteString(validationPayload.EventTs)
	msg.WriteString(validationPayload.PlainToken)
	signature := hex.EncodeToString(ed25519.Sign(privateKey, msg.Bytes()))
	if err != nil {
		log.Println("generate signature failed:", err)
		return
	}
	rspBytes, err := json.Marshal(
		&ValidationResponse{
			PlainToken: validationPayload.PlainToken,
			Signature:  signature,
		})
	if err != nil {
		log.Println("handle validation failed:", err)
		return
	}
	rw.Write(rspBytes)
}

```

例如机器人账号

```
appid: 11111111
secret: DG5g3B4j9X2KOErG
```

回调验证请求：

```
headers: User-Agent:[QQBot-Callback] X-Bot-Appid:[11111111]
body: {"d":{"plain_token":"Arq0D5A61EgUu4OxUvOp","event_ts":"1725442341"},"op":13},
```

机器人应返回：

```
body: {"plain_token": "Arq0D5A61EgUu4OxUvOp","signature": "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"}
```

## WebSocket方式

### 发起连接到 Gateway

第一步先调用 [获取通用WSS 接入点 | QQ机器人文档](/wiki/develop/api-v2/openapi/wss/url_get.html) 或 [获取带分片WSS 接入点 | QQ机器人文档](/wiki/develop/api-v2/openapi/wss/shard_url_get.html) 接口获取网关地址。

会得到一个类似下面这样的地址：

```
wss://api.bot.qq.com/websocket/
```

然后进行 `websocket` 长连接建立，一旦连接成功，就会返回 [OpCode 10 Hello](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) 消息。这个消息主要的内容是心跳周期，单位毫秒(milliseconds)，如下：

```
{
  "op": 10,
  "d": {
    "heartbeat_interval": 45000
  }
}
```

### 登录鉴权获得 Session

`websocket` 长连接建立之后，需要进行登录鉴权，登录鉴权成功后会获得一个 session 会话 id，只有登录成功后，QQ后台才会下发事件通知，

发送一个 OpCode 2 Identify 消息， `payload` 如下：

```
{
  "op": 2,
  "d": {
    "token": "token string",
    "intents": 513,
    "shard": [0, 4],
    "properties": {
      "$os": "linux",
      "$browser": "my_library",
      "$device": "my_library"
    }
  }
}

```

**字段**

**描述**

token

格式为"QQBot {AccessToken}"

intents

是此次连接所需要接收的事件，具体可参考 **Intents** \[事件订阅intents\\

shard

考虑到开发者事件接收时可以实现负载均衡，QQ 提供了分片逻辑，事件通知会落在不同的分片上，该参数是个拥有两个元素的数组。  
例如：\[0,4\]，代表分为四个片，当前链接是第 0 个片，业务稍后应该继续建立 `shard` 为\[1,4\],\[2,4\],\[3,4\]的链接，才能完整接收事件，更多详细的内容可以参考 **Shard** \[Shard机制\\

properties

目前无实际作用，可以按照自己的实际情况填写，也可以留空

鉴权成功之后，QQ 后台会下发一个 Ready Event， `payload` 如下：

```
{
  "op": 0,
  "s": 1,
  "t": "READY",
  "d": {
    "version": 1,
    "session_id": "082ee18c-0be3-491b-9d8b-fbd95c51673a",
    "user": {
      "id": "6158788878435714165",
      "username": "群pro测试机器人",
      "bot": true
    },
    "shard": [0, 0]
  }
}
```

### 发送心跳 Ack

鉴权成功之后，就需要按照周期进行心跳发送。d 为客户端收到的最新的消息的 s，如果是首次连接，d 为传 null， `payload` 如下：

```
{
  "op": 1,
  "d": 251
}
```

心跳发送成功之后会收到 [OpCode 11 Heartbeat ACK](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) 消息， `payload` 如下：

```
{
  "op": 11
}
```

### 恢复登录态 Session

有很多原因可能会导致 `websocket` 长连接断开，断开之后短时间内重连会补发中间遗漏的事件，以保障业务逻辑的正确性。断开重连 gateway 后不需要发送重新登录 [Opcode 2 Identify](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html)请求。在连接到 `Gateway` 之后，需要发送 [Opcode 6 Resume](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html)消息， `payload` 如下：

```
{
  "op": 6,
  "d": {
    "token": "my_token",
    "session_id": "session_id_i_stored",
    "seq": 1337
  }
}
```

其中 `seq` 指的是在接收事件时候的 `s` 字段，我们推荐开发者在处理过事件之后记录下 `s` 这样可以在 `resume` 的时候传递给 `websocket`， `websocket` 会自动补发这个 seq 之后的事件。

恢复成功之后，就开始补发遗漏事件，所有事件补发完成之后，会下发一个 `Resumed Event`， `payload` 如下：

```
{
  "op": 0,
  "s": 2002,
  "t": "RESUMED",
  "d": ""
}
```

### 事件订阅Intents

事件的 `intents` 是一个标记位，每一位都代表不同的事件，如果需要接收某类事件，就将该位置为 `1`。

每个 `intents` 位代表的是一类事件，可以使用使用 `websocket` 传输的数据中的 `t` 字段的值来区分。

事件和位移的关系如下：

```
GUILDS (1 << 0)
  - GUILD_CREATE           // 当机器人加入新guild时
  - GUILD_UPDATE           // 当guild资料发生变更时
  - GUILD_DELETE           // 当机器人退出guild时
  - CHANNEL_CREATE         // 当channel被创建时
  - CHANNEL_UPDATE         // 当channel被更新时
  - CHANNEL_DELETE         // 当channel被删除时

GUILD_MEMBERS (1 << 1)
  - GUILD_MEMBER_ADD       // 当成员加入时
  - GUILD_MEMBER_UPDATE    // 当成员资料变更时
  - GUILD_MEMBER_REMOVE    // 当成员被移除时

GUILD_MESSAGES (1 << 9)    // 消息事件，仅 *私域* 机器人能够设置此 intents。
  - MESSAGE_CREATE         // 发送消息事件，代表频道内的全部消息，而不只是 at 机器人的消息。内容与 AT_MESSAGE_CREATE 相同
  - MESSAGE_DELETE         // 删除（撤回）消息事件

GUILD_MESSAGE_REACTIONS (1 << 10)
  - MESSAGE_REACTION_ADD    // 为消息添加表情表态
  - MESSAGE_REACTION_REMOVE // 为消息删除表情表态

DIRECT_MESSAGE (1 << 12)
  - DIRECT_MESSAGE_CREATE   // 当收到用户发给机器人的私信消息时
  - DIRECT_MESSAGE_DELETE   // 删除（撤回）消息事件


GROUP_AND_C2C_EVENT (1 << 25)
  - C2C_MESSAGE_CREATE      // 用户单聊发消息给机器人时候
  - FRIEND_ADD              // 用户添加使用机器人
  - FRIEND_DEL              // 用户删除机器人
  - C2C_MSG_REJECT          // 用户在机器人资料卡手动关闭"主动消息"推送
  - C2C_MSG_RECEIVE         // 用户在机器人资料卡手动开启"主动消息"推送开关
  - GROUP_AT_MESSAGE_CREATE // 用户在群里@机器人时收到的消息
  - GROUP_ADD_ROBOT         // 机器人被添加到群聊
  - GROUP_DEL_ROBOT         // 机器人被移出群聊
  - GROUP_MSG_REJECT        // 群管理员主动在机器人资料页操作关闭通知
  - GROUP_MSG_RECEIVE       // 群管理员主动在机器人资料页操作开启通知

INTERACTION (1 << 26)
  - INTERACTION_CREATE     // 互动事件创建时

MESSAGE_AUDIT (1 << 27)
  - MESSAGE_AUDIT_PASS     // 消息审核通过
  - MESSAGE_AUDIT_REJECT   // 消息审核不通过

FORUMS_EVENT (1 << 28)  // 论坛事件，仅 *私域* 机器人能够设置此 intents。
  - FORUM_THREAD_CREATE     // 当用户创建主题时
  - FORUM_THREAD_UPDATE     // 当用户更新主题时
  - FORUM_THREAD_DELETE     // 当用户删除主题时
  - FORUM_POST_CREATE       // 当用户创建帖子时
  - FORUM_POST_DELETE       // 当用户删除帖子时
  - FORUM_REPLY_CREATE      // 当用户回复评论时
  - FORUM_REPLY_DELETE      // 当用户回复评论时
  - FORUM_PUBLISH_AUDIT_RESULT      // 当用户发表审核通过时

AUDIO_ACTION (1 << 29)
  - AUDIO_START             // 音频开始播放时
  - AUDIO_FINISH            // 音频播放结束时
  - AUDIO_ON_MIC            // 上麦时
  - AUDIO_OFF_MIC           // 下麦时

PUBLIC_GUILD_MESSAGES (1 << 30) // 消息事件，此为公域的消息事件
  - AT_MESSAGE_CREATE       // 当收到@机器人的消息时
  - PUBLIC_MESSAGE_DELETE   // 当频道的消息被删除时
```

#### 举例

如开发者需要接收用户 at 机器人的消息，那么就需要在 `intents` 中设置接收 `PUBLIC_GUILD_MESSAGES`。则需要先计算 `1 << 30` 的值。然后与 `0` 做位或操作，得到最终需要传递的 `intents`。

如果涉及到多个事件类型的接收，则需要将多个结果做位或操作，如：`0|1<<30|1<<1` 代表订阅 `PUBLIC_GUILD_MESSAGES` 和 `GUILD_MEMBERS` 这两类事件。

#### 权限

事件类型的订阅，是有权限控制的，除了 `GUILDS`，`PUBLIC_GUILD_MESSAGES`，`GUILD_MEMBERS` 事件是基础的事件，默认有权限订阅之外，其他的特殊事件，都需要经过申请才能够使用，如果在鉴权的时候传递了无权限的 `intents`， `websocket` 会报错，并直接关闭连接。请开发者注意订阅事件的范围需要控制在自己所需要的范围之内。

如果拥有的某个特殊事件类型的权限被取消，则在当前连接上不会报错，但是将不会收到对应的事件类型，如果重新连接，则报错，所以如果开发者的事件类型权限被取消，请及时调整监听事件代码，避免报错导致的无法连接。

### 分片连接LoadBalance

随着`bot`的增长并被添加到越来越多的频道中，事件越来越多，业务有必要对事件进行水平分割，实现负载均衡。机器人网关实现了一种用户可控制的分片方法，该方法允许跨多个网关连接拆分事件。 分片完全由用户控制，并且不需要在单独的连接之间进行状态共享。

要在连接上启用分片，需要在建立连接的时候指定分片参数，具体参考[gateway](/wiki/develop/api-v2/dev-prepare/interface-framework/reference.html)

#### 获得合适的分片数

使用[/gateway/bot](/wiki/develop/api-v2/openapi/wss/shard_url_get.html)接口获取网关地址的时候，会同时返回一个建议的 `shard`数，及最大并发限制。

```
{
  "url": "wss://api.bot.qq.com/websocket",
  "shards": 1,
  "session_start_limit": {
    "total": 1000,
    "remaining": 1000,
    "reset_after": 86400000,
    "max_concurrency": 1
  }
}
```

#### 分片规则

分片是按照频道id进行哈希的，同一个频道的信息会固定从同一个链接推送。具体哈希计算规则如下：

```
shard_id = (guild_id >> 22) % num_shards
```

#### 最大连接数

每个机器人创建的连接数不能超过`remaining`剩余连接数

### 接口调用与鉴权

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/api-use.html

# 接口调用与鉴权

说明

`QQ 机器人` 服务端开放的 `openapi` 接口，均使用 `https` 方式进行调用，通过 `AccessToken` 机制实现对 `openapi` 接口调用的鉴权。

## 获取调用凭证

-   **请求**

基本

HTTP URL

https://api.bot.qq.com/app/getAppAccessToken

HTTP Method

POST

-   **请求参数**

**属性**

**类型**

**必填**

**说明**

appId

string

是

在开放平台管理端上获得。

clientSecret

string

是

在开放平台管理端上获得。

-   **返回参数**

**属性**

**类型**

**说明**

access\_token

string

获取到的凭证。

expires\_in

number

凭证有效时间，单位：秒。目前是7200秒之内的值。

-   **错误码**

**错误码**

**错误码取值**

0

ok

-   **调用示例**

```
curl --location 'https://api.bot.qq.com/app/getAppAccessToken' \
--header 'Content-Type: application/json' \
--data '{
  "appId": "APPID",
  "clientSecret": "CLIENTSECRET"
}'
```

-   **返回示例**

```
{
  "access_token": "ACCESS_TOKEN",
  "expires_in": "7200"
}
```

-   **其他说明**

目前 `access_token` 生命周期默认 `7200` 秒，每次请求不会刷新新的 `access_token`，开发者需要在过期后自行刷新 `access_token`，保证调用链路权限正常。

在上一个 `access_token` 接近过期时间 `60` 秒内，获取 `access_token` 时，会获得一个新的 `access_token`，老的 `access_token` 在这个`60`秒内仍然有效。

## 鉴权方式

在每次调用 https 的 openapi 开放接口请求的时候，需要在 header 内引入 `access_token` 进行调用权限验证。

**统一地址**

```
https://api.bot.qq.com
```

**请求头**

名称

类型

必填

描述

Authorization

string

是

格式值："QQBot ACCESS\_TOKEN"

**示例**

```
{
  "headers": {
    "Authorization": "QQBot {ACCESS_TOKEN}"
  }
}
```

### 安全和授权

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html

# 安全和授权

开发者需要对每一次回调请求，根据回调中的签名等信息验证请求者身份，避免安全隐患。目前签名算法使用Ed25519。

## 安全凭证

开发者平台的 Bot Secret 用于加密签名字符串和服务器端验证签名字符串的密钥。用户必须严格保管安全凭证，避免泄露。

## 验证签名

### 1. 签名验证参数

字段名

说明

参考值

X-Signature-Ed25519

HTTP Header 中透传 Signature

3ecd\*\*\*（64字节）

X-Signature-Timestamp

HTTP Header 透传的签名时间戳

1636373772

HTTP Body

HTTP 请求中 Body 值

{"msg":"hello"}

### 2. 验证签名过程

以下代码以Go语言为例,引用 `crypto/ed25519` 包实现 `Ed25519` 算法

-   根据开发者平台的 Bot Secret 值进行repeat操作得到签名32字节的 seed ,根据 seed 调用 Ed25519 算法生成32字节公钥

```
  // 根据botSecret进行repeat操作后得到seed值计算出公钥
  seed := botSecret
  for len(seed) < ed25519.SeedSize {
    seed = strings.Repeat(seed, 2)
  }
  rand := strings.NewReader(seed[:ed25519.SeedSize])
  publicKey, privateKey, err := ed25519.GenerateKey(rand)
```

DEMO

```
【输入】
secret: naOC0ocQE3shWLAfffVLB1rhYPG7
seed: naOC0ocQE3shWLAfffVLB1rhYPG7naOC
【输出】
publicKey: [215 195 98 254 120 174 248 31 242 50 135 180 147 98 139 93 176 42 60 79 227 11 33 94 77 25 96 155 93 118 103 58]
privateKey: [110 97 79 67 48 111 99 81 69 51 115 104 87 76 65 102 102 102 86 76 66 49 114 104 89 80 71 55 110 97 79 67 215 195 98 254 120 174 248 31 242 50 135 180 147 98 139 93 176 42 60 79 227 11 33 94 77 25 96 155 93 118 103 58]
```

-   获取 HTTP Header 中 X-Signature-Ed25519 的值进行 hec (十六进制解码)操作后的得到 Signature 并进行校验

```
  // 取HTTP header中X-Signature-Ed25519(进行hex解码)并校验 
  signature := req.Header.Get("X-Signature-Ed25519")
  if signature == "" {
    return false
  }
  sig, err := hex.DecodeString(signature)
  if err != nil {
    return false
  }
  if len(sig) != ed25519.SignatureSize || sig[63]&224 != 0 {
    return false
  }
```

-   获取 HTTP Header 中 X-Signature-Timestamp 的和 HTTP Body 的值按照 timestamp+body 顺序进行组合成签名体msg

```
    // 取HTTP header中 X-Signature-Timestamp 并校验
  timestamp := req.Header.Get("X-Signature-Timestamp")
  if timestamp == "" {
    return false
  }
  httpBody, err := io.ReadAll(req.Body)
  if err != nil {
    return false
  }
  // 按照timestamp+Body顺序组成签名体
  var msg bytes.Buffer
  msg.WriteString(timestamp)
  msg.Write(httpBody)
  if err != nil {
    return false
  }
```

-   根据公钥、Signature、签名体调用 Ed25519 算法进行验证

```
  ed25519.Verify(publicKey, msg.Bytes(), sig)
```

DEMO

```
【输入】
secret: naOC0ocQE3shWLAfffVLB1rhYPG7
body: { "op": 0,"d": {}, "t": "GATEWAY_EVENT_NAME"}
timestamp: 1725442341

【输出】
sig: 865ad13a61752ca65e26bde6676459cd36cf1be609375b37bd62af366e1dc25a8dc789ba7f14e017ada3d554c671a911bfdf075ba54835b23391d509579ed002

```

### 使用 Websocket 接入

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/reference.html

# 使用 Websocket 接入

### payload

payload 指的是在 websocket 连接上传输的数据，网关的上下行消息采用的都是同一个结构，如下：

```
{
  "op": 0,
  "d": {},
  "s": 42,
  "t": "GATEWAY_EVENT_NAME"
}
```

`op` 指的是 opcode，全部 opcode 列表参考 [opcode](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html)。

`s` 下行消息都会有一个序列号，标识消息的唯一性，客户端需要再发送心跳的时候，携带客户端收到的最新的`s`。

`t`和`d` 主要是用在`op`为 `0 Dispatch` 的时候，`t` 代表事件类型，`d` 代表事件内容，不同事件类型的事件内容格式都不同，请注意识别。

### 1.连接到 Gateway

第一步先调用 [/gateway](/wiki/develop/api-v2/openapi/wss/url_get.html) 或 [/gateway/bot](/wiki/develop/api-v2/openapi/wss/shard_url_get.html) 接口获取网关地址。 会得到一个类似下面这样的地址：

```
wss://api.bot.qq.com/websocket/
```

然后进行 websocket 连接，一旦连接成功，就会返回 [OpCode 10 Hello](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) 消息。这个消息主要的内容是心跳周期，单位毫秒(milliseconds)，如下：

```
{
  "op": 10,
  "d": {
    "heartbeat_interval": 45000
  }
}
```

### 2.鉴权连接

建立 websocket 连接之后，就需要进行鉴权了，需要发送一个 [OpCode 2 Identify](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) 消息，如下：

```
{
  "op": 2,
  "d": {
    "token": "my_token",
    "intents": 513,
    "shard": [0, 4],
    "properties": {
      "$os": "linux",
      "$browser": "my_library",
      "$device": "my_library"
    }
  }
}
```

`token` 是创建机器人的时候分配的，格式为`Bot {appid}.{app_token}`

`intents` 是此次连接所需要接收的事件，具体可参考 [Intents](/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html#事件类型Intents)

`shard` 该参数是用来进行水平分片的。该参数是个拥有两个元素的数组。例如：`[0,4]`，代表分为四个片，当前链接是第 0 个片，业务稍后应该继续建立 shard 为`[1,4]`,`[2,4]`,`[3,4]`的链接，才能完整接收事件。更多详细的内容可以参考[Shard](/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html#分片连接LoadBalance)。

`properties` 目前无实际作用，可以按照自己的实际情况填写，也可以留空

鉴权成功之后，后台会下发一个 `Ready Event`，结构如下：

```
{
  "op": 0,
  "s": 1,
  "t": "READY",
  "d": {
    "version": 1,
    "session_id": "082ee18c-0be3-491b-9d8b-fbd95c51673a",
    "user": {
      "id": "6158788878435714165",
      "username": "群pro测试机器人",
      "bot": true
    },
    "shard": [0, 0]
  }
}
```

### 3.发送心跳

鉴权成功之后，就需要按照周期进行心跳发送。`d`为客户端收到的最新的消息的`s`，如果是第一次连接，传`null`。

```
{
  "op": 1,
  "d": 251
}
```

心跳发送成功之后会收到 [OpCode 11 Heartbeat ACK](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) 消息，如下：

```
{
  "op": 11
}
```

### 4.恢复连接

有很多原因都会导致连接断开，断开之后短时间内重连会补发中间遗漏的事件，以保障业务逻辑的正确性。断开重连不需要发送`Identify`请求。在连接到 Gateway 之后，需要发送 [Opcode 6 Resume](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html)消息，结构如下：

```
{
  "op": 6,
  "d": {
    "token": "my_token",
    "session_id": "session_id_i_stored",
    "seq": 1337
  }
}
```

其中 `seq` 指的是在接收事件时候的 `s` 字段，我们推荐开发者在处理过事件之后记录下 `s` 这样可以在 resume 的时候传递给 websocket，websocket 会自动补发这个 seq 之后的事件。

恢复成功之后，就开始补发遗漏事件，所有事件补发完成之后，会下发一个 `Resumed Event`，结构如下：

```
{
  "op": 0,
  "s": 2002,
  "t": "RESUMED",
  "d": ""
}
```

### WebSocket（错误码）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/error-trace/websocket.html

# WebSocket

### 错误码 code

值

含义

是否可以重试 RESUME

是否可以重试 IDENTIFY

4001

无效的 opcode

否

否

4002

无效的 payload

否

否

4007

seq 错误

否

**是**

4006

无效的 session id，无法继续 resume，请 identify

否

**是**

4008

发送 payload 过快，请重新连接，并遵守连接后返回的频控信息

**是**

**是**

4009

连接过期，请重连并执行 resume 进行重新连接

**是**

**是**

4010

无效的 shard

否

否

4011

连接需要处理的 guild 过多，请进行合理的分片

否

否

4012

无效的 version

否

否

4013

无效的 intent

否

否

4014

intent 无权限

否

否

4014

intent 无权限

否

否

4900~4913

内部错误，请重连

否

**是**

4914

机器人已下架,只允许连接沙箱环境,请断开连接,检验当前连接环境

否

否

4915

机器人已封禁,不允许连接,请断开连接,申请解封后再连接

否

否

### 针对 WebSocket 错误码的简单处理逻辑

-   4009 可以重新发起 resume
-   4914，4915 不可以连接，请联系官方解封
-   其他错误，请重新发起 identify

## 2. 网关与鉴权

### 获取通用 WSS 接入点（autogen/api gateway.get）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/gateway.get.html

# 获取通用 WSS 接入点

获取 WSS 接入地址，通过该地址可建立 WebSocket 长连接。

## 请求

### 基础信息

字段

值

HTTP URL

/gateway

HTTP Method

GET

接口频率限制

2 QPM / 10 QPM burst

### 请求示例

**获取通用WSS接入点**

```
GET /gateway
```

## 响应

### 响应体

名称

类型

描述

url

string

WebSocket 连接地址

## 响应示例

**获取WSS网关地址成功**

```
{
  "url": "wss://qqbot-api.example.com/websocket"
}
```

### 获取通用 WSS 接入点（openapi/wss/url_get）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/url_get.html

# 获取通用 WSS 接入点

### 接口

```
GET /gateway
```

### 功能描述

用于获取 WSS 接入地址，通过该地址可建立 `websocket` 长连接。

### Content-Type

```
application/json
```

### 返回

返回一个用于连接 `websocket` 的地址。

### 错误码

详见[错误码](/wiki/develop/api-v2/openapi/error/error.html)。

### 示例

响应数据包

```
{
  "url": "wss://api.bot.qq.com/websocket/"
}
```

### 获取带分片 WSS 接入点

> Source: https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/shard_url_get.html

# 获取带分片 WSS 接入点

### 接口

```
GET /gateway/bot
```

### 功能描述

用于获取 WSS 接入地址及相关信息，通过该地址可建立 `websocket` 长连接。相关信息包括：

-   建议的分片数。
-   目前连接数使用情况。

### Content-Type

```
application/json
```

### 返回

字段名

类型

描述

url

string

WebSocket 的连接地址

shards

int

建议的 shard 数

session\_start\_limit

[SessionStartLimit](#sessionstartlimit)

创建 Session 限制信息

### SessionStartLimit

字段名

类型

描述

total

int

每 24 小时可创建 Session 数

remaining

int

目前还可以创建的 Session 数

reset\_after

int

重置计数的剩余时间(ms)

max\_concurrency

int

每 5s 可以创建的 Session 数

### 错误码

详见[错误码](/wiki/develop/api-v2/openapi/error/error.html)。

### 示例

```
{
  "wss://api.bot.qq.com/websocket/",
  "shards": 9,
  "session_start_limit": {
    "total": 1000,
    "remaining": 999,
    "reset_after": 14400000,
    "max_concurrency": 1
  }
}
```

### 获取用户详情

> Source: https://bot.q.qq.com/wiki/develop/api-v2/openapi/user/me.html

# 获取用户详情

### 接口

```
GET /users/@me
```

### 功能描述

用于获取当前用户（机器人）详情。

### Content-Type

```
application/json
```

### 返回

返回 [User](/wiki/develop/api-v2/openapi/user/model.html#user) 对象。

### 错误码

详见[错误码](/wiki/develop/api-v2/openapi/error/error.html)。

### 示例

响应数据包

```
{
  "id": "11586990140073229091",
  "username": "gitsub",
  "avatar": "https://thirdqq.qlogo.cn/g?b=oidb&k=M5TibpXicS7Jt4z89BZxiamAA&s=100&t=1641802698",
  "union_openid": "74F138F7F3AF68C4B8E8325013FCA295",
  "union_user_account": ""
}
```

### 用户对象(User)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/openapi/user/model.html

# 用户对象(User)

用户对象中所涉及的 ID 类数据，都仅在机器人场景流通，与真实的 ID 无关。请不要理解为真实的 ID

### User

字段名

类型

描述

id

string

用户 id

username

string

用户名

avatar

string

用户头像地址

bot

bool

是否是机器人

union\_openid

string

特殊关联应用的 openid，需要特殊申请并配置后才会返回。如需申请，请联系平台运营人员。

union\_user\_account

string

机器人关联的互联应用的用户信息，与union\_openid关联的应用是同一个。如需申请，请联系平台运营人员。

### 提示

`union_openid` 与 `union_user_account` 只有在单独拉取 member 信息的时候才会提供，在其他的事件中所携带的 user 对象，均无这两个字段的内容。

### websocket 错误

> Source: https://bot.q.qq.com/wiki/develop/api-v2/gateway/error/error.html

# websocket 错误

### code

值

含义

是否可以重试 RESUME

是否可以重试 IDENTIFY

4001

无效的 opcode

否

否

4002

无效的 payload

否

否

4007

seq 错误

否

**是**

4006

无效的 session id，无法继续 resume，请 identify

否

**是**

4008

发送 payload 过快，请重新连接，并遵守连接后返回的频控信息

**是**

**是**

4009

连接过期，请重连并执行 resume 进行重新连接

**是**

**是**

4010

无效的 shard

否

否

4011

连接需要处理的 guild 过多，请进行合理的分片

否

否

4012

无效的 version

否

否

4013

无效的 intent

否

否

4014

intent 无权限

否

否

4014

intent 无权限

否

否

4900~4913

内部错误，请重连

否

**是**

4914

机器人已下架,只允许连接沙箱环境,请断开连接,检验当前连接环境

否

否

4915

机器人已封禁,不允许连接,请断开连接,申请解封后再连接

否

否

### 针对 websocket 错误码的简单处理逻辑

-   4009 可以重新发起 resume
-   4914，4915 不可以连接，请联系官方解封
-   其他错误，请重新发起 identify

### 业务报错返回的数据信息(Data)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/gateway/error/data/model.html

# 业务报错返回的数据信息(Data)

### Data

字段名

类型

描述

message\_audit

[MessageAudited](/wiki/develop/api-v2/gateway/message/model.html#messageaudited) 对象

消息审核信息，只会填充该对象的 audit\_id 字段

## 3. 消息收发（单聊/群）

### 消息收发概述

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html

# 消息收发概述

机器人可在 QQ 单聊、群聊、频道三种场景下收发消息。本页介绍基础概念与通用规则，具体接口与事件请参考对应子分类。

## 收发场景

场景

发送消息

接收事件

QQ 单聊

[发送单聊消息](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html) / [流式消息](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_stream_messages.post.html)

[C2C\_MESSAGE\_CREATE](/wiki/develop/api-v2/autogen/event/c2c_message_create.html)

QQ 群聊

[发送群消息](/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html)

[GROUP\_AT\_MESSAGE\_CREATE](/wiki/develop/api-v2/autogen/event/group_at_message_create.html) / [GROUP\_MESSAGE\_CREATE](/wiki/develop/api-v2/autogen/event/group_message_create.html)

频道

[发送子频道消息](/wiki/develop/api-v2/server-inter/channel/message/send.html) / [频道私信](/wiki/develop/api-v2/server-inter/channel/message/dms.html)

[频道消息事件](/wiki/develop/api-v2/server-inter/channel/message/event.html)

### 对话场景图示

说明

机器人可以被添加各种聊天场景下

单聊

群聊

文字子频道

频道私信

![单聊](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/chat-single.c4f33531.jpg)

![群聊](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/chat-group.d5318db5.jpg)

![文字子频道](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/chat-text-channel.6dfae006.jpg)

![频道私信](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/chat-c2c.33e2820c.jpg)

## 主动消息与被动消息

类型

特征

说明

主动消息

无任何条件

机器人主动触达用户，用户可在客户端关闭「允许主动发送」开关，关闭后主动消息将发送失败

互动召回消息

`is_wakeup=true`

用户主动与机器人对话之后每个周期内可下发 1 条召回消息

被动消息（回复用户）

携带 `msg_id`

对用户消息的回复

被动消息（响应事件）

携带 `event_id`

对事件的回复

## 消息类型

通过 `msg_type` 指定消息内容格式：

msg\_type

类型

内容字段

发送

接收

0

文本

`content`

✅

✅

2

Markdown

`markdown`

✅

\-

7

富媒体

`media`（需先上传文件获取 `file_info`）

✅

✅

除上述之外，响应中还可能收到图片、视频、语音、表情、卡片等类型，详见 [消息类型](/wiki/develop/api-v2/server-inter/message/type/overview.html)。

## 富媒体消息

图片、视频、语音、文件等富媒体需先上传获取 `file_info`，再通过发消息接口（`msg_type=7`）携带 `media.file_info` 发送。

上传方式：

-   **分片上传**：推荐使用，无需开发者提供公网 CDN 地址，参考 [分片上传流程](/wiki/develop/api-v2/server-inter/message/rich-media.html#分片上传（推荐）)
-   **整文件上传**：[单聊上传](/wiki/develop/api-v2/server-inter/message/rich-media.html#url-上传) / [群聊上传](/wiki/develop/api-v2/server-inter/message/rich-media.html#url-上传)

> -   `file_info` 有时效性（`ttl`），过期需重新上传。
> -   单聊和群聊的文件上传接口不互通。

## 频率与时效规则

### 被动消息

场景

有效期

每条消息可回复次数

单聊

60 分钟

4 次

群聊

5 分钟

5 次

频道

5 分钟

\-

### 主动消息

主动消息与被动消息说明： QQ 用户可以在 QQ 客户端主动设置是否接收机器人发送的主动消息，如果设置了关闭，主动消息一律发送失败。

#### 单聊

-   主动消息发送频率限制（HTTP接口）

认证类型

场景

Bot 维度频控

单关系维度频控

每日上限

企业认证

单聊

10/qps

20/qpm

1000 条/用户

个人认证

单聊

10/qps

20/qpm

1000 条/用户

未认证

单聊

5/qps & 30/qpm

20/qpm

1000 条/用户

-   互动召回消息：在用户主动与机器人对话之后，机器人在未来 30 天内可下发互动召回消息给用户（消息类型与当前机器人拥有的消息类型权限一致），每个周期内可下发一条。分别为：当天、1 - 3 天、3 - 7 天、7 - 30 天，合计：4 个周期。在发消息接口中使用 is\_wakeup 字段声明使用该能力。

#### 群聊

-   主动消息发送频率限制（HTTP接口）

认证类型

场景

Bot 维度频控

单关系维度频控

每日上限

企业认证

群

60/qpm

20/qpm

1000 条/群

个人认证

群

60/qpm

20/qpm

1000 条/群

未认证

群

30/qpm

20/qpm

1000 条/群

#### 文字子频道

-   主动消息在频道主或管理设置了情况下，按设置的数量进行限频。在未设置的情况遵循如下限制:
    -   主动推送消息，默认每天往每个子频道可推送的消息数是 20 条，超过会被限制。
    -   主动推送消息在每个频道中，每天可以往 2 个子频道推送消息。超过后会被限制。
-   不论主动消息还是被动消息，在一个子频道中，每秒 最多可发送 5 条 消息。
-   被动回复消息有效期为 5 分钟，超时会发送失败。
-   发送消息接口要求机器人接口需要连接到 WebSocket 上保持在线状态
-   有关主动消息审核，可以通过 事件订阅 Intents 中审核事件 MESSAGE\_AUDIT 返回 MessageAudited 对象获取结果。

#### 频道私信

-   私信场景下，每个机器人每天可以对一个用户发 2 条 主动消息。
-   私信场景下，每个机器人每天累计可以发 200 条 主动消息。
-   被动回复消息有效期为 5 分钟，超时会发送失败。

## 消息去重

相同 `msg_id` 可能多次推送，请结合 `msg_seq` 去重。被动回复时，相同的 `msg_id + msg_seq` 重复发送会失败，可递增 `msg_seq` 实现对同一消息的多次回复。

## 撤回消息

机器人可撤回自己发送的消息（发送超过 **2 分钟**不可撤回）：

-   [撤回单聊消息](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages_message_id.delete.html)
-   [撤回群聊消息](/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages_message_id.delete.html)
-   [撤回频道消息](/wiki/develop/api-v2/server-inter/channel/message/recall.html) / [撤回频道私信](/wiki/develop/api-v2/server-inter/channel/message/dms.html#撤回私信)

### 获取机器人详情（users/@me）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/users_me.get.html

# 获取机器人详情

获取当前用户（机器人）的详情信息。

-   union\_openid 和 union\_user\_account 需特殊申请并配置后才会返回
-   这两个字段仅在单独拉取 member 信息时提供

## 请求

### 基础信息

字段

值

HTTP URL

/users/@me

HTTP Method

GET

接口频率限制

50 QPS

### 请求示例

**获取当前用户信息**

```
GET /users/@me
```

## 响应

### 响应体

名称

类型

描述

id

string

用户 ID

username

string

用户名

avatar

string

头像 URL

bot

boolean

是否为机器人

union\_openid

string

跨应用统一用户 OpenID（需特殊申请）

union\_user\_account

string

跨应用统一用户账号（需特殊申请）

## 响应示例

**获取当前用户信息成功**

```
{
  "id": "5777414462219517083",
  "username": "阳光小助手",
  "avatar": "https://thirdqq.qlogo.cn/g?b=oidb&k=AbCdEfGhIjKlMnOpQrStUv&kti=xyzABC&s=0&t=1781676795",
  "bot": true,
  "union_openid": "9F2E872045CCCC5948BEAF5B5FCCDF22",
  "union_user_account": "",
  "share_url": "https://qun.qq.com/qunpro/robot/qunshare?robot_uin=3889007780&robot_appid=102083127&biz_type=0",
  "welcome_msg": "欢迎加入我们的群聊"
}
```

### 发送单聊消息

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html

# 发送单聊消息

向指定用户发送私聊消息。

-   被动消息有效时间 **60 分钟**，每个消息最多回复 **4 次**
-   主动消息频控规则:
    -   Bot 维度（发送方）：企业认证/个人身份证认证 **10/qps**；未认证 **5/qps** 且 **30/qpm**
    -   单关系维度（接收方）：**20/qpm**，每个好友 1 天最多接收 **1000** 条
-   互动召回消息：在用户主动与机器人对话之后，机器人在未来 30 天内可下发互动召回消息给用户（消息类型与当前机器人拥有的消息类型权限一致），每个周期内可下发一条。分别为：当天、1 - 3 天、3 - 7 天、7 - 30 天，合计：4 个周期。在发消息接口中使用 is\_wakeup 字段声明使用该能力。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/users/{user\_openid}/messages

HTTP Method

POST

接口频率限制

100 QPS，包括主动、被动等所有消息类型

## 路径参数

名称

类型

必填

描述

user\_openid

string

是

用户 OpenID

## 请求体

名称

类型

必填

描述

msg\_type

integer

否

消息类型。决定哪个内容字段生效: 0=纯文本(content) 2=Markdown(markdown) 6=输入中状态（input\_notify) 7=富媒体(media)

content

string

否

文本内容。msg\_type=0 时为全文 注意: 传了 markdown 后此字段必须为空

markdown

[MessageMarkdown](#schema-messagemarkdown)

否

Markdown 消息。msg\_type=2 时必填 注意: 填写此字段后 content/ark 必须全为空

keyboard

[Keyboard](#schema-keyboard)

否

内嵌键盘。短形式只传 id，长形式传 content.rows

msg\_id

string

否

被动回复的消息 ID。从 C2C\_MESSAGE\_CREATE 等事件的 d.id 获取，5 分钟内有效

event\_id

string

否

被动回复的事件 ID。从事件最外层的id获取。与 msg\_id 二选一，支持事件："INTERACTION\_CREATE"、"C2C\_MSG\_RECEIVE"、"FRIEND\_ADD"

msg\_seq

integer

否

回复消息的序号，与 msg\_id 联合使用，避免相同消息 id 回复重复发送，不填默认是 1。相同的 msg\_id + msg\_seq 重复发送会失败。

media

[MediaInfo](#schema-mediainfo)

否

富媒体消息。msg\_type=7 时填写，file\_info 来自 /v2/users/{user\_openid}/files

message\_reference

[MessageReference](#schema-messagereference)

否

引用回复。填写后以引用形式展示，关联上下文

is\_wakeup

boolean

否

指明发送消息为互动召回消息，与 msg\_id，event\_id 互斥使用

input\_notify

[InputNotify](#schema-inputnotify)

否

输入中状态，msg\_type=6时使用

**MessageMarkdown**

名称

类型

必填

描述

template\_id

integer

否

【已废弃】平台 Markdown 模板 ID。使用模板时填写，非模板不传

content

string

否

Markdown 内容。支持的格式参考文档：[Markdown (opens new window)](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html)

custom\_template\_id

string

否

【已废弃】自定义模板 ID，与 template\_id 二选一

force\_verify\_image\_resource

boolean

否

是否校验图片转存结果，当为true时，如果出现图片转存失败，则会返回错误，消息不会发送。 默认为false

**Keyboard**

名称

类型

必填

描述

id

string

否

内嵌键盘模板 ID。使用平台预设模板时填写此字段

content

[KeyboardContent](#schema-keyboardcontent)

否

自定义键盘布局。与 id 互斥，用于自定义按钮

**KeyboardContent**

名称

类型

必填

描述

rows

\[\][Row](#schema-row)

否

按钮行列表

**Row**

名称

类型

必填

描述

buttons

\[\][Button](#schema-button)

否

行内按钮，从左到右排列

**Button**

名称

类型

必填

描述

id

string

否

按钮 ID。同一键盘内唯一

render\_data

[RenderData](#schema-renderdata)

否

按钮渲染

action

[Action](#schema-action)

否

按钮点击行为

group\_id

string

否

分组ID, 同一分组内有一个按钮操作后, 其它按钮则变灰不可点击 注意:只有当action.type = 1 时才有效

**RenderData**

名称

类型

必填

描述

label

string

否

按钮文字，最多 10 字符

visited\_label

string

否

点击后文字，不传则保持不变

style

integer

否

0：灰色线框，1：蓝色线框 3: 白色背景+红色字体, 4:蓝色背景+白色字体

**Action**

名称

类型

必填

描述

type

integer

否

0：跳转按钮：http 或 小程序 1：回调按钮：回调后台接口, data 传给后台， 2：指令按钮：自动在输入框插入 @bot data

permission

[Permission](#schema-permission)

否

操作权限

data

string

否

回调数据。type=1/2 时必填

click\_limit

integer

否

【已废弃】可点击次数限制。0=无限

unsupport\_tips

string

否

版本过低时提示文案

enter

boolean

否

指令按钮可用，点击按钮后直接自动发送 data，仅单聊可用，默认 false。支持版本 8983

reply

boolean

否

指令按钮可用，指令是否带引用回复本消息，默认 false。支持版本 8983

anchor

integer

否

本字段仅在指令按钮下有效，设置后后会忽略 action.enter 配置。 设置为 1 时 ，点击按钮自动唤起启手Q选图器，其他值暂无效果。 （仅支持手机端版本 8983+ 的单聊场景，桌面端不支持）

modal

[Modal](#schema-modal)

否

用户点击二次确认操作

**Permission**

名称

类型

必填

描述

type

integer

否

0=指定用户, 1=管理员, 2=所有人

specify\_user\_ids

\[\]string

否

有权限的用户 id 的列表

specify\_role\_ids

\[\]string

否

有权限的身份组 id 的列表（仅频道可用）

**Modal**

名称

类型

必填

描述

content

string

否

二次确认的提示文本,如果不为空则会进行二次确认. 注意:最多40个字符, 不能有URL

confirm\_text

string

否

二次确认提示确认按钮中展示的文字,可以为空, 默认为"确认" 注意:最多4个字符

cancel\_text

string

否

二次确认提示取消按钮中的文字,可以为空,默认为"取消" 注意:最多4个字符

**MediaInfo**

名称

类型

必填

描述

file\_info

string

否

文件数据。来自文件上传接口返回值

**MessageReference**

名称

类型

必填

描述

message\_id

string

否

被引用消息 ID，例如REFIDX\_xxxxxx  
\- 非机器人发的消息，从消息事件的`MessageScene`的`ext`数组，`msg_idx`字段中获取  
\- 机器人自己发的消息，从发消息请求响应`ext_info.ref_idx`获取

**InputNotify**

名称

类型

必填

描述

input\_type

integer

否

填1

input\_second

integer

否

状态持续时间，最长60s

### 请求示例

**文本消息 (msg\_type=0)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages
{
  "content": "你好，欢迎使用机器人助手！",
  "msg_type": 0,
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**Markdown 消息 (msg\_type=2)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages
{
  "msg_type": 2,
  "markdown": {
    "content": "# 今日推荐\n\n**精选文章**\n> 知识就是力量，学习永无止境\n\n[点击查看详情](https://example.com)"
  },
  "keyboard": {
    "id": "1070001"
  },
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**输入状态通知 (msg\_type=6)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages
{
  "msg_type": 6,
  "input_notify": {
    "input_type": 1,
    "input_second": 60
  },
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**富媒体消息 (msg\_type=7)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages
{
  "msg_type": 7,
  "media": {
    "file_info": "AE86C5D3F0E14B238C656C0F6DD1D0479C"
  },
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

## 响应

### 响应体

名称

类型

描述

id

string

消息 ID，可用于后续撤回

timestamp

string

发送时间，RFC3339 东八区

ext\_info

[MessageExtInfo](#schema-messageextinfo)

扩展信息

**MessageExtInfo**

名称

类型

描述

ref\_idx

string

引用消息索引。对应消息时间ext里的msg\_idx与ref\_msg\_idx

## 响应示例

**消息发送成功**

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "timestamp": "2026-07-21T10:30:00+08:00"
}
```

**消息发送成功（含扩展信息）**

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "timestamp": "2026-07-21T10:30:00+08:00",
  "ext_info": {
    "ref_idx": "REFIDX_xxxxxxxxxxxxxxxxxxxx=="
  }
}
```

### 错误码

错误码

描述

排查建议

22006

消息类型与内容不匹配

请检查msg\_type与content是否对应

50059

输入类型错误

请检查输入类型

304004

无权限使用该ARK模板

请先申请ARK模板权限

304061

消息内容无效

请检查消息格式是否符合要求

304062

订阅按钮数量达到上限

请减少按钮数量

304064

订阅消息未授权

请先引导用户授权订阅消息

304080

文件信息无效

请检查文件信息格式是否正确

304103

消息ID已过期，不能回复

请在收到消息后尽快回复

340067

获取机器人信息失败

请检查机器人状态

40034004

富媒体信息转存失败

请重试

40034005

回复消息msg\_id已过期

请在收到消息后尽快回复

40034006

消息内容违规

请修改消息内容后重试

40034008

markdown参数有空值

请确保所有Markdown参数都有值

40034009

markdown参数有换行符

请移除Markdown参数中的换行符

40034010

模版参数中不能含有markdown语法

请使用纯文本参数，不要包含Markdown语法

40034011

无效的markdown内容

请检查Markdown语法是否正确

40034024

请求参数msg\_id无效或越权

请检查msg\_id是否正确

40034025

请求参数event\_id无效

请检查event\_id是否正确

40034026

请求参数event\_id已过期

请在收到事件后尽快回复

40034027

该事件不支持回复消息

请确认事件类型是否支持回复

40034029

内联键盘行/列超限

请减少键盘按钮数量

40034100

主动消息发送超过频控限制

请降低发送频率或等待配额恢复

40034105

主动消息发送失败，无权限

请检查机器人权限设置

40034106

消息不支持该指令类型

请检查消息指令类型

40034108

指令参数长度超限

请缩短指令参数

40034109

指令参数解析失败

请检查指令参数格式

40034122

召回消息已达区间上限

召回消息已达上限，无法继续召回

40034123

不支持召回消息

该消息不支持召回操作

40034124

markdown消息参数错误

请检查Markdown参数格式

40034127

无markdown模板权限

请先申请Markdown模板权限

40034128

被动回复时间或次数超限

请在收到事件后尽快回复

40054004

无好友关系

请先添加好友后再发送私信

40054005

消息被去重

请确保每次请求使用不同的msgseq值

40054006

验证好友关系失败

请重试

40054007

消息长度超限

请缩短消息内容

40054013

用户拒收消息

用户已拒收消息，无法发送

40054016

机器人已下线

请检查机器人状态

40054018

消息过长或异常

请缩短消息内容

50055002

消息发送异常，请稍后重试

请稍后重试

### 流式发送单聊消息

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_stream_messages.post.html

# 流式发送单聊消息

流式分批发送单聊消息。每个分片使用相同 stream\_msg\_id， index 从0递增。支持 markdown 内容格式。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/users/{user\_openid}/stream\_messages

HTTP Method

POST

接口频率限制

50 QPS

## 路径参数

名称

类型

必填

描述

user\_openid

string

是

## 请求体

名称

类型

必填

描述

input\_mode

string

否

输入模式。 append（默认）：ContentRaw 拼接到 Pending。 replace：ContentRaw 为当前全量正文，须以上游已下发前缀 SentContent 开头；合并后 Pending 仅存未下发后缀。

input\_state

integer

否

输入状态。1=生成中，10=生成结束

index

integer

否

分片序号，从0递增

content\_type

string

否

内容格式类型 text: 文本消息 markdown：MarkDown消息

content\_raw

string

否

Markdown 格式的文本内容

event\_id

string

否

被动回复事件ID（与 msg\_id 二选一）

msg\_id

string

否

被动回复消息ID（与 event\_id 二选一）

stream\_msg\_id

string

否

流式消息ID。第一条由服务端生成并返回，后续分片需携带上一分片返回的 id

msg\_seq

integer

否

消息序号，用于去重

is\_wakeup

boolean

否

是否为召回消息。true 时不校验 msg\_id/event\_id 有效期

### 请求示例

**首片消息 (input\_state=1, index=0)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/stream_messages
{
  "input_mode": "replace",
  "input_state": 1,
  "index": 0,
  "content_type": "markdown",
  "content_raw": "正在生成回答，请稍候",
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**续片消息 (input\_state=1, index=1)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/stream_messages
{
  "input_mode": "replace",
  "input_state": 1,
  "index": 1,
  "content_type": "markdown",
  "content_raw": "正在生成回答，请稍候。目前已完成大部分内容",
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "stream_msg_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "msg_seq": 1
}
```

**结束片消息 (input\_state=10)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/stream_messages
{
  "input_mode": "replace",
  "input_state": 10,
  "index": 2,
  "content_type": "markdown",
  "content_raw": "正在生成回答，请稍候。目前已完成全部内容，以下是最终结果。",
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "stream_msg_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "msg_seq": 1
}
```

## 响应

### 响应体

名称

类型

描述

id

string

消息ID。首条返回 stream\_msg\_id，用于后续分片

timestamp

string

消息发送时间，RFC3339 格式

ext\_info

[MessageExtInfo](#schema-messageextinfo)

扩展信息。ref\_idx: 引用消息索引 扩展信息

remain\_msg\_len

integer

流式消息剩余长度（字符数）

**MessageExtInfo**

名称

类型

描述

ref\_idx

string

引用消息索引。对应消息时间ext里的msg\_idx与ref\_msg\_idx

## 响应示例

**首片响应（返回 stream\_msg\_id）**

```
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2026-07-21T10:00:00+08:00",
  "ext_info": {
    "ref_idx": "REFIDX_xxxxxxxxxxxxxxx=="
  }
}
```

**续片/结束片响应**

```
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2026-07-21T10:00:01+08:00",
  "ext_info": {
    "ref_idx": "REFIDX_xxxxxxxxxxxxxxx=="
  }
}
```

### 错误码

错误码

描述

排查建议

40007

已下发内容前缀不可修改

请保持已下发内容前缀一致

50001

服务内部错误

请稍后重试

50002

频率限制

请降低调用频率

### 撤回单聊消息

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages_message_id.delete.html

# 撤回单聊消息

撤回机器人发送给当前用户的消息。发送超过 2 分钟的消息不可撤回。 成功返回 HTTP 200，无响应体。

-   发送超出 **2 分钟**的消息不可撤回

## 请求

### 基础信息

字段

值

HTTP URL

/v2/users/{user\_openid}/messages/{message\_id}

HTTP Method

DELETE

接口频率限制

10 QPS

## 路径参数

名称

类型

必填

描述

user\_openid

string

是

用户 OpenID

message\_id

string

是

消息 ID

### 请求示例

**示例1**

```
DELETE /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages/0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF
```

## 响应

无

## 响应示例

**示例1**

```
{}
```

### 错误码

错误码

描述

排查建议

306009

用户openid无效

请检查user\_openid是否正确

40061001

请求参数无效

请检查请求参数格式

40061002

请求参数msgid无效

请检查msgid格式是否正确

40064004

已超出消息撤回时限

消息发送超过2分钟后不可撤回

### 发送群聊消息

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html

# 发送群聊消息

向指定群发送消息。支持文本/Markdown/富媒体等类型，可附带内嵌键盘。 注意: 群消息不支持流式参数

-   被动消息有效时间 **5 分钟**，每个消息最多回复 **5 次**
-   主动消息频控规则
    -   Bot 维度（发送方）：企业认证/个人身份证认证 **60/qpm**；未认证 **30/qpm**
    -   单关系维度（接收方）：**20/qpm**，每个群 1 天最多接收 **1000** 条

## 请求

### 基础信息

字段

值

HTTP URL

/v2/groups/{group\_openid}/messages

HTTP Method

POST

接口频率限制

100 QPS

## 路径参数

名称

类型

必填

描述

group\_openid

string

是

群 OpenID

## 请求体

名称

类型

必填

描述

msg\_type

integer

否

消息类型。决定哪个内容字段生效: 0=纯文本(content) 2=Markdown(markdown) 7=富媒体(media)

content

string

否

文本内容。msg\_type=0 时为全文 注意: 传了 markdown 后此字段必须为空

markdown

[MessageMarkdown](#schema-messagemarkdown)

否

Markdown 消息。msg\_type=2 时必填 注意: 填写此字段后 content/ark 必须全为空

keyboard

[Keyboard](#schema-keyboard)

否

内嵌键盘。短形式只传 id，长形式传 content.rows

msg\_id

string

否

被动回复的消息 ID。从 GROUP\_AT\_MESSAGE\_CREATE 等事件的 d.id 获取，5 分钟内有效

event\_id

string

否

被动回复的事件 ID。从事件最外层的id获取。与 msg\_id 二选一，支持事件："INTERACTION\_CREATE"、"GROUP\_ADD\_ROBOT"、"GROUP\_MSG\_RECEIVE"

msg\_seq

integer

否

回复消息的序号，与 msg\_id 联合使用，避免相同消息 id 回复重复发送，不填默认是 1。相同的 msg\_id + msg\_seq 重复发送会失败。

media

[MediaInfo](#schema-mediainfo)

否

富媒体消息。msg\_type=7 时填写，file\_info 来自 /v2/groups/{group\_openid}/files

message\_reference

[MessageReference](#schema-messagereference)

否

引用回复。填写后以引用形式展示，关联上下文

**MessageMarkdown**

名称

类型

必填

描述

template\_id

integer

否

【已废弃】平台 Markdown 模板 ID。使用模板时填写，非模板不传

content

string

否

Markdown 内容。支持的格式参考文档：[Markdown (opens new window)](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html)

custom\_template\_id

string

否

【已废弃】自定义模板 ID，与 template\_id 二选一

force\_verify\_image\_resource

boolean

否

是否校验图片转存结果，当为true时，如果出现图片转存失败，则会返回错误，消息不会发送。 默认为false

**Keyboard**

名称

类型

必填

描述

id

string

否

内嵌键盘模板 ID。使用平台预设模板时填写此字段

content

[KeyboardContent](#schema-keyboardcontent)

否

自定义键盘布局。与 id 互斥，用于自定义按钮

**KeyboardContent**

名称

类型

必填

描述

rows

\[\][Row](#schema-row)

否

按钮行列表

**Row**

名称

类型

必填

描述

buttons

\[\][Button](#schema-button)

否

行内按钮，从左到右排列

**Button**

名称

类型

必填

描述

id

string

否

按钮 ID。同一键盘内唯一

render\_data

[RenderData](#schema-renderdata)

否

按钮渲染

action

[Action](#schema-action)

否

按钮点击行为

group\_id

string

否

分组ID, 同一分组内有一个按钮操作后, 其它按钮则变灰不可点击 注意:只有当action.type = 1 时才有效

**RenderData**

名称

类型

必填

描述

label

string

否

按钮文字，最多 10 字符

visited\_label

string

否

点击后文字，不传则保持不变

style

integer

否

0：灰色线框，1：蓝色线框 3: 白色背景+红色字体, 4:蓝色背景+白色字体

**Action**

名称

类型

必填

描述

type

integer

否

0：跳转按钮：http 或 小程序 1：回调按钮：回调后台接口, data 传给后台， 2：指令按钮：自动在输入框插入 @bot data

permission

[Permission](#schema-permission)

否

操作权限

data

string

否

回调数据。type=1/2 时必填

click\_limit

integer

否

【已废弃】可点击次数限制。0=无限

unsupport\_tips

string

否

版本过低时提示文案

enter

boolean

否

指令按钮可用，点击按钮后直接自动发送 data，仅单聊可用，默认 false。支持版本 8983

reply

boolean

否

指令按钮可用，指令是否带引用回复本消息，默认 false。支持版本 8983

anchor

integer

否

本字段仅在指令按钮下有效，设置后后会忽略 action.enter 配置。 设置为 1 时 ，点击按钮自动唤起启手Q选图器，其他值暂无效果。 （仅支持手机端版本 8983+ 的单聊场景，桌面端不支持）

modal

[Modal](#schema-modal)

否

用户点击二次确认操作

**Permission**

名称

类型

必填

描述

type

integer

否

0=指定用户, 1=管理员, 2=所有人

specify\_user\_ids

\[\]string

否

有权限的用户 id 的列表

specify\_role\_ids

\[\]string

否

有权限的身份组 id 的列表（仅频道可用）

**Modal**

名称

类型

必填

描述

content

string

否

二次确认的提示文本,如果不为空则会进行二次确认. 注意:最多40个字符, 不能有URL

confirm\_text

string

否

二次确认提示确认按钮中展示的文字,可以为空, 默认为"确认" 注意:最多4个字符

cancel\_text

string

否

二次确认提示取消按钮中的文字,可以为空,默认为"取消" 注意:最多4个字符

**MediaInfo**

名称

类型

必填

描述

file\_info

string

否

文件数据。来自文件上传接口返回值

**MessageReference**

名称

类型

必填

描述

message\_id

string

否

被引用消息 ID，例如REFIDX\_xxxxxx  
\- 非机器人发的消息，从消息事件的`MessageScene`的`ext`数组，`msg_idx`字段中获取  
\- 机器人自己发的消息，从发消息请求响应`ext_info.ref_idx`获取

### 请求示例

**文本消息 (msg\_type=0)**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages
{
  "msg_type": 0,
  "content": "欢迎使用本群助手，有什么可以帮你的吗？",
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**Markdown + 键盘消息 (msg\_type=2)**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages
{
  "msg_type": 2,
  "markdown": {
    "content": "## 每日签到\n\n今日签到成功！获得 **50** 积分\n连续签到 **7** 天"
  },
  "keyboard": {
    "content": {
      "rows": [
        {
          "buttons": [
            {
              "id": "btn_signin",
              "render_data": {
                "label": "签到",
                "style": 1
              },
              "action": {
                "type": 2,
                "permission": {
                  "type": 2
                },
                "data": "/签到",
                "enter": true
              }
            }
          ]
        }
      ]
    }
  },
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**富媒体消息 (msg\_type=7)**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages
{
  "msg_type": 7,
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 2,
  "media": {
    "file_info": "AE86C5D3F0E14B238C656C0F6DD1D0479C"
  },
  "message_reference": {
    "message_id": "ROBOT1.0_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
  }
}
```

## 响应

### 响应体

名称

类型

描述

id

string

消息 ID，可用于后续撤回

timestamp

string

发送时间，RFC3339 东八区

ext\_info

[MessageExtInfo](#schema-messageextinfo)

扩展信息

**MessageExtInfo**

名称

类型

描述

ref\_idx

string

引用消息索引。对应消息时间ext里的msg\_idx与ref\_msg\_idx

## 响应示例

**发送成功**

```
{
  "id": "ROBOT1.0_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
  "timestamp": "2026-07-21T10:00:00+08:00",
  "ext_info": {
    "ref_idx": "REFIDX_xxxxxxxxxxxxxxx=="
  }
}
```

### 错误码

错误码

描述

排查建议

22006

消息类型与内容不匹配

请检查msg\_type与content是否对应

304004

无权限使用该ARK模板

请先申请ARK模板权限

304036

无Markdown模板权限

请先申请Markdown模板权限

304061

消息内容无效

请检查消息格式是否符合要求

304064

订阅消息未授权

请先引导用户授权订阅消息

304080

文件信息无效

请检查文件信息格式是否正确

304103

消息ID已过期，不能回复

请在收到消息后尽快回复

305007

键盘样式参数错误

请检查keyboard参数

340069

消息类型无效

请检查msg\_type取值

40034004

富媒体信息转存失败

请重试

40034005

回复消息msg\_id已过期

请在收到消息后尽快回复

40034006

消息内容违规

请修改消息内容后重试

40034008

markdown参数有空值

请确保所有Markdown参数都有值

40034009

markdown参数有换行符

请移除Markdown参数中的换行符

40034010

模版参数中不能含有markdown语法

请使用纯文本参数，不要包含Markdown语法

40034011

无效的markdown内容

请检查Markdown语法是否正确

40034024

请求参数msg\_id无效或越权

请检查msg\_id是否正确

40034025

请求参数event\_id无效

请检查event\_id是否正确

40034026

请求参数event\_id已过期

请在收到事件后尽快回复

40034027

该事件不支持回复消息

请确认事件类型是否支持回复

40034029

内联键盘行/列超限

请减少键盘按钮数量

40034100

主动消息发送超过频控限制

请降低发送频率或等待配额恢复

40034101

机器人非群成员

请先将机器人加入群聊

40034105

主动消息发送失败，无权限

请检查机器人权限设置

40034106

消息不支持该指令类型

请检查消息指令类型

40034108

指令参数长度超限

请缩短指令参数

40034109

指令参数解析失败

请检查指令参数格式

40034124

markdown消息参数错误

请检查Markdown参数格式

40034127

无markdown模板权限

请先申请Markdown模板权限

40034128

被动回复时间或次数超限

请在收到事件后尽快回复

40054002

机器人被禁言

请等待解禁后再发送

40054003

机器人不是群成员

请先将机器人加入群聊

40054005

消息被去重

请确保每次请求使用不同的msgseq值

40054007

消息长度超限

请缩短消息内容

40054010

不允许发送URL

请移除消息中的URL

40054016

机器人已下线

请检查机器人状态

50055001

消息发送异常，请稍后重试

请稍后重试

50055006

ARK消息发送异常，请稍后重试

请稍后重试

### 撤回群聊消息

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages_message_id.delete.html

# 撤回群聊消息

撤回群消息。发送超过 2 分钟的消息不可撤回。 成功返回 HTTP 200，无响应体。

-   发送超出 **2 分钟**的消息不可撤回。
-   机器人如果是群管理员，可以撤回机器人自己的消息以及普通群成员的消息，群成员的消息ID从群消息事件`GROUP_AT_MESSAGE_CREATE`或`GROUP_MESSAGE_CREATE`里，`d.id`这个字段中获取。
-   机器人如果是普通成员，只能撤回机器人自己发送的消息，消息ID可以从消息发送接口响应里获取。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/groups/{group\_openid}/messages/{message\_id}

HTTP Method

DELETE

接口频率限制

10 QPS

## 路径参数

名称

类型

必填

描述

group\_openid

string

是

群 OpenID

message\_id

string

是

消息 ID

### 请求示例

**撤回群消息**

```
DELETE /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages/0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF
```

## 响应

无

## 响应示例

**响应示例**

```
{}
```

### 错误码

错误码

描述

排查建议

40061001

请求参数无效

请检查请求参数格式

40062003

无操作权限

请检查机器人是否有操作权限，机器人是否为群管理员或者发消息的用户是否为普通用户

40064004

已超出消息撤回时限

消息发送超过2分钟后不可撤回

50065001

消息撤回失败，请稍后重试

请稍后重试

### 生成分享链接

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_generate_url_link.post.html

# 生成分享链接

生成机器人分享链接，用于邀请用户添加机器人为好友。

生成带自定义参数的机器人分享链接，用于邀请用户添加机器人为好友。用户通过该链接添加机器人时，callback\_data 参数会透传给开发者。callback\_data 最长 32 字符。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/generate\_url\_link

HTTP Method

POST

接口频率限制

50 QPS

## 请求体

名称

类型

必填

描述

callback\_data

string

否

回传给机器人后台的数据

### 请求示例

**生成分享链接**

```
POST /v2/generate_url_link
{
  "callback_data": "custom_data_123"
}
```

## 响应

### 响应体

名称

类型

描述

data

[Data](#schema-data)

**Data**

名称

类型

描述

url

string

生成的分享链接

## 响应示例

**生成分享链接成功**

```
{
  "data": {
    "url": "https://qun.qq.com/qunpro/robot/qunshare?robot_appid=1234567890&robot_uin=12345678&data=xxx"
  }
}
```

### 错误码

错误码

描述

排查建议

10001

请求参数异常

请检查请求参数是否正确

10002

请求头异常

请检查请求头是否正确

10003

查询机器人信息异常

请确认机器人是否存在

10044

从协议头获取uin失败

请检查 Authorization Header 是否正确

11004

生成分享ARK失败

请稍后重试

### 互动事件响应

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/interactions_interaction_id.put.html

# 互动事件响应

收到 INTERACTION\_CREATE 事件后需调用此接口回应，告知 QQ 后台事件已收到。 否则客户端会一直处于 loading 状态直到超时。

仅 type=11（消息按钮）和 type=12（快捷菜单）的互动事件需要调用此接口回应，其他类型无需回应（调用也不会报错）。需在事件触发的有效时间内回应，超时后 interaction\_id 失效。同一 interaction\_id 只能回应一次。code=0 时，对于 type=14（清空会话），后台会下发会话已清空小灰条提示用户。

## 请求

### 基础信息

字段

值

HTTP URL

/interactions/{interaction\_id}

HTTP Method

PUT

接口频率限制

50 QPS

## 路径参数

名称

类型

必填

描述

interaction\_id

string

是

互动事件 ID，从 INTERACTION\_CREATE 事件的 d.id 字段获取，注意该 ID 不带“INTERACTION\_CREATE:”前缀

## 请求体

名称

类型

必填

描述

code

integer

否

回调结果。0=成功, 1=操作失败, 2=操作频繁, 3=重复操作, 4=没有权限, 5=仅管理员操作

### 请求示例

**互动事件响应**

```
PUT /interactions/a1b2c3d4-e5f6-7890-abcd-ef1234567890
{
  "code": 0
}
```

## 响应

无

## 响应示例

**成功**

```
{}
```

### 错误码

错误码

描述

排查建议

630001

param invalid

请检查请求参数是否正确

630002

get appid failed

请检查 Authorization Header 是否正确

630003

appid invalid

AppID 与 interaction\_id 不匹配，请确认使用正确的 Bot Token

630004

set interaction data failed

请稍后重试

630005

get interaction data failed

请稍后重试

630006

get header appid failed

请检查请求 Header

630007

data too large

请减小请求体大小

630008

interaction preprocess failed

请检查请求参数

## 4. 富媒体

### 富媒体消息概述

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/rich-media.html

# 富媒体消息概述

富媒体消息支持发送图片、视频、语音、文件等类型，需先将文件上传获取 `file_info`，再通过发消息接口（`msg_type=7`）携带 `media.file_info` 发送。

## 支持的消息类型

图片

语音

视频

文件

![图片消息](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/image-send.35813305.jpg)

![语音消息](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/voice-send.21dce8bf.jpg)

![视频消息](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/video-send.9416079c.jpg)

![文件消息](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/large-file-transfer.f49ff1e2.jpg)

支持 jpg/png/gif/webp/bmp 格式，发送后直接展示图片

支持 silk/mp3/wav/ogg 格式，发送后展示语音条

支持 mp4 格式，发送后展示视频封面可播放

支持任意格式，发送后展示文件卡片可下载

## 文件类型与限制

file\_type

类型

格式

软限制

硬限制

1

图片

png / jpg

20 MB

200 MB

2

视频

mp4

30 MB

200 MB

3

语音

silk

20 MB

200 MB

4

文件

\-

200 MB

200 MB

超过软限制会降级为文件类型上传，超过硬限制会报错。

## 上传方式

整文件上传使用 [单聊上传](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_files.post.html) / [群聊上传](/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_files.post.html) 接口，直接传入文件 URL；文件较大时使用分片上传，参考 [单聊预上传](/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_prepare.post.html) 开始分片流程。

### 分片上传（推荐）

适用于大文件或本地文件。分四步完成：

```
1. 预上传
   调用 upload_prepare，传入文件信息和校验值
   → 获取 upload_id + block_size + 各分片预签名 URL

2. 分片 PUT
   按 block_size 将文件分片，逐片 HTTP PUT 到对应的预签名 URL

3. 确认分片
   每片 PUT 成功后调用 upload_part_finish，通知服务端该分片完成

4. 完成合并
   全部分片完成后，携带 upload_id 调用上传接口
   → 返回 file_info
```

流程图：

```
 upload_prepare         分片 PUT + part_finish        上传接口（合并）
┌──────────────┐    ┌─────────────────────────┐    ┌──────────────────┐
│ 获取        │    │  for each chunk:        │    │ POST .../files   │
│ upload_id   │───▶│  PUT → presigned_url    │───▶│ { upload_id }   │
│ block_size  │    │  POST → part_finish     │    │ → file_info      │
│ presigned   │    └─────────────────────────┘    └──────────────────┘
│ URLs        │
└──────────────┘
```

### URL 上传

适用于文件已在公网可访问的场景，直接传入文件 URL，平台自动下载转存。

```
POST /v2/users/{user_openid}/files
{
  "file_type": 1,
  "url": "https://example.com/image.png"
}
```

返回 `file_info`，即可用于发消息。

## 使用 file\_info 发送

获取 `file_info` 后，在发消息接口中设置 `msg_type=7`，将 `file_info` 填入 `media` 字段：

```
POST /v2/users/{user_openid}/messages
{
  "msg_type": 7,
  "media": {
    "file_info": "{上一步返回的 file_info}"
  }
}
```

> `srv_send_msg=true` 可在上传的同时直接发送，跳过单独调用发消息接口这一步，但会占用主动消息频次。

## 单聊与群聊隔离

单聊和群聊的文件上传接口相互独立，上传的文件不能跨场景使用：

场景

上传接口

单聊

`/v2/users/{user_openid}/files`

群聊

`/v2/groups/{group_openid}/files`

对应的预上传和分片接口也需使用同场景的端点。

## 注意事项

-   `file_info` 有有效期（`ttl`），过期后需重新上传。
-   `md5_10m`（文件前 10002432 字节，约 9.54 MB 的 MD5）可用于秒传判断，避免重复上传。
-   分片大小默认 5MB，并发数、重试策略由服务端在 `upload_config` 中下发。
-   上传接口超时建议设为 ≥ 5 秒。

### 单聊富媒体上传

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_files.post.html

# 单聊富媒体上传

上传图片/视频/语音到单聊，返回 file\_info 用于发送消息接口的 media 字段。 用单聊接口上传的文件仅能发送到单聊。 文件类型与大小限制:

-   1=图片(png/jpg): 软限制 20MB, 硬限制 200MB
-   2=视频(mp4): 软限制 30MB, 硬限制 200MB
-   3=语音(silk): 软限制 20MB, 硬限制 200MB
-   4=文件: 软限制 200MB, 硬限制 200MB 超过软限制会降级为文件类型上传，超过硬限制会报错。

支持三种上传方式，按实际文件大小和资源来源选择。

## 一、支持的上传方式

方式

说明

限制 / 注意

URL 上传

传入 `url`，由平台下载并转存

服务端下载资源可能因网络等原因失败

分片上传合并

先通过 `upload_prepare` + `upload_part_finish` 完成分片上传，再携带 `upload_id` 调用本接口完成合并

**推荐使用**

直接上传二进制数据

直接传文件二进制内容

数据大小不能超过 5M，超过建议使用分片上传

## 二、推荐流程：分片上传

1.  调用 `upload_prepare`，获取 `upload_id`、`block_size` 以及各分片的预签名 URL。
2.  按 `block_size` 将文件切分为多个分片，逐片通过 HTTP `PUT` 上传到对应的预签名 URL。
3.  每片 `PUT` 成功后，调用 `upload_part_finish` 通知服务端该分片上传完成。
4.  全部分片上传完成后，携带 `upload_id` 调用本接口完成合并，返回 `file_info`。

## 三、注意事项

-   URL 上传存在服务端下载失败的可能，若遇到下载失败，可先将资源下载到本地，再通过**直接上传二进制数据**的方式上传。
-   二进制直传有 5M 大小上限，文件较大时请改用分片上传。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/users/{user\_openid}/files

HTTP Method

POST

接口频率限制

50 QPS

## 路径参数

名称

类型

必填

描述

user\_openid

string

是

用户 OpenID

## 请求体

名称

类型

必填

描述

file\_type

integer

否

媒体类型。1=图片, 2=视频, 3=语音, 4=文件 图片支持 png/jpg，视频支持 mp4，语音支持 silk

url

string

否

媒体资源的 URL，需以 http 开头，平台会下载并转存 分片上传合并时可为空

srv\_send\_msg

boolean

否

true=直接发送消息并占用主动消息频次，返回中包含消息 ID false=仅返回 file\_info，用于后续发送消息接口的 media 字段

upload\_id

string

否

分片上传任务 ID。来自 UploadPrepare 响应的 upload\_id， 传入后走分片上传合并路径，url 可为空

file\_name

string

否

文件名 (分片上传或者二进制上传时必填）

file\_data

string

否

直接上传二进制数据。 直接上传二进制有大小限制，需要在5M以内，如果超过则需要使用URL上传或者分片上传。

### 请求示例

**URL 上传图片**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/files
{
  "file_type": 1,
  "url": "https://example.com/image.png",
  "srv_send_msg": false
}
```

**分片上传合并**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/files
{
  "file_type": 2,
  "srv_send_msg": false,
  "file_name": "video.mp4",
  "upload_id": "upload_a1b2c3d4e5f6"
}
```

**二进制上传**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/files

{
  "file_type": 1,
  "file_name": "111.png",
  "file_data": "xxxx图片的二进制数据"
}
```

## 响应

### 响应体

名称

类型

描述

file\_uuid

string

文件唯一 ID

file\_info

string

文件信息，用于发送消息接口的 media.file\_info 字段。 内部为序列化的二进制数据，开发者无需解析，直接透传即可

ttl

integer

file\_info 有效期（秒）。到期后需重新上传。 0 表示可长期使用

id

string

发送消息的唯一 ID。仅 srv\_send\_msg=true 时返回

raw\_url

string

文件下载链接（COS 预签名 GET URL），有效期与 ttl 一致 仅分片上传合并（upload\_id 路径）且 file\_type 为图片/视频/语音时返回； URL 直传和文件类型(file\_type=4)不返回此字段

## 响应示例

**上传成功**

```
{
  "file_uuid": "uuid_a1b2c3d4e5f6",
  "file_info": "AE86C5D3F0E14B238C656C0F6DD1D0479C",
  "ttl": 300
}
```

### 错误码

错误码

描述

排查建议

850018

群被禁言或者机器人被禁言

请检查机器人是否被禁言

850019

不支持的文件格式

请检查 file\_type 是否正确

850026

下载原始文件失败

请检查 URL 是否可访问或重试

850031

上传文件超过大小限制

请减小文件大小

850027

发送数据超时

请稍后重试

10000

不支持的操作

请检查请求参数

40093001

文件上传失败，请重试

大文件分片上传中 BDH 通道异常，请重试

40093002

超过今天发送文件容量上限

请明天再试或减少文件大小

### 单聊富媒体预上传

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_prepare.post.html

# 单聊富媒体预上传

单聊大文件分片上传前的准备工作。返回 upload\_id、分片预签名 URL 和上传配置。 后续将文件按 block\_size 分片，逐片 PUT 到预签名 URL，每片完成后调用分片完成接口。

大文件分片上传第一步。传入文件大小、MD5/SHA1 校验值，服务端返回 upload\_id 和各分片预签名 URL。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/users/{user\_id}/upload\_prepare

HTTP Method

POST

接口频率限制

10 QPS

## 路径参数

名称

类型

必填

描述

user\_id

string

是

用户 OpenID

## 请求体

名称

类型

必填

描述

file\_type

integer

是

业务类型。1=图片, 2=视频, 3=语音, 4=文件

file\_size

string

是

文件大小（字节）

file\_name

string

是

文件名

md5

string

是

整个文件的 MD5

sha1

string

是

整个文件的 SHA1

md5\_10m

string

是

文件前 10002432 字节（约 10MB）的 MD5 校验值

### 请求示例

**预上传视频文件**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/upload_prepare
{
  "file_type": 2,
  "file_size": "31457280",
  "file_name": "demo.mp4",
  "md5": "d41d8cd98f00b204e9800998ecf8427e",
  "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
  "md5_10m": "c4d8c5f3a2b1e0f9a8b7c6d5e4f3a2b1"
}
```

## 响应

### 响应体

名称

类型

描述

upload\_id

string

上传任务 ID，后续分片上传和完成合并时需携带

block\_size

string

分块大小（字节），默认 5MB。客户端按此大小对文件分片

parts

\[\][UploadPart](#schema-uploadpart)

分片列表，每个分片包含一个预签名上传 URL

upload\_config

[UploadConfig](#schema-uploadconfig)

上传配置，由后台下发控制客户端上传行为

**UploadPart**

名称

类型

描述

index

integer

分片序号，从 0 开始

presigned\_url

string

预签名上传 URL，客户端通过 HTTP PUT 将分片数据上传到此 URL

block\_size

string

该分块的大小（字节）

**UploadConfig**

名称

类型

描述

concurrency

integer

上传并发数，默认 1

retry\_timeout

integer

重试超时时间（秒），默认 300（5分钟）

retry\_delay

integer

重试延迟（秒），默认 1

## 响应示例

**预上传成功（3 个分片）**

```
{
  "upload_id": "upload_a1b2c3d4e5f6",
  "block_size": "10485760",
  "parts": [
    {
      "index": 0,
      "presigned_url": "https://cos.example.com/upload?partNumber=1&sign=aaa",
      "block_size": "10485760"
    },
    {
      "index": 1,
      "presigned_url": "https://cos.example.com/upload?partNumber=2&sign=bbb",
      "block_size": "10485760"
    },
    {
      "index": 2,
      "presigned_url": "https://cos.example.com/upload?partNumber=3&sign=ccc",
      "block_size": "10485760"
    }
  ],
  "upload_config": {
    "concurrency": 1,
    "retry_timeout": 300,
    "retry_delay": 1
  }
}
```

### 错误码

错误码

描述

排查建议

850018

群被禁言或者机器人被禁言

请检查机器人是否被禁言

850019

不支持的文件格式

请检查 file\_type 是否正确

850026

下载原始文件失败

请检查 URL 是否可访问或重试

850031

上传文件超过大小限制

请减小文件大小

850027

发送数据超时

请稍后重试

10000

不支持的操作

请检查请求参数

40093001

文件上传失败，请重试

申请上传失败，请重试

### 单聊分片上传完成

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_part_finish.post.html

# 单聊分片上传完成

通知服务端某个分片已上传完成。全部分片完成后，用 upload\_id 作为 MediaUpload 的 upload\_id 字段调一次上传接口完成合并

分片上传第二步。每个分片 PUT 到预签名 URL 成功后调用，通知服务端该分片已上传完成。 全部分片完成后，携带 upload\_id 调用 /v2/users/{user\_openid}/files 完成合并。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/users/{user\_id}/upload\_part\_finish

HTTP Method

POST

接口频率限制

10 QPS

## 路径参数

名称

类型

必填

描述

user\_id

string

是

用户 OpenID

## 请求体

名称

类型

必填

描述

upload\_id

string

否

上传任务 ID

part\_index

integer

否

分片序号

block\_size

string

否

分块大小（字节）

md5

string

否

分片 MD5

### 请求示例

**通知分片 0 上传完成**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/upload_part_finish
{
  "upload_id": "upload_a1b2c3d4e5f6",
  "part_index": 0,
  "block_size": "10485760",
  "md5": "c4d8c5f3a2b1e0f9a8b7c6d5e4f3a2b1"
}
```

## 响应

无

## 响应示例

**分片完成确认**

```
{}
```

### 错误码

错误码

描述

排查建议

850018

群被禁言或者机器人被禁言

请检查机器人是否被禁言

850019

不支持的文件格式

请检查 file\_type 是否正确

850026

下载原始文件失败

请检查 URL 是否可访问或重试

850031

上传文件超过大小限制

请减小文件大小

850027

发送数据超时

请稍后重试

10000

不支持的操作

请检查请求参数

40093001

文件上传失败，请重试

分片转存 BDH 通道异常，请重试

40093002

超过今天发送文件容量上限

请明天再试或减少文件大小

### 群聊富媒体上传

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_files.post.html

# 群聊富媒体上传

上传图片/视频/语音到群聊，返回 file\_info 用于发送消息接口的 media 字段。 srv\_send\_msg=true 时直接发送消息并占用主动消息频次；false 时仅返回 file\_info。 用群接口上传的文件仅能发送到群聊。 文件类型与大小限制:

-   1=图片(png/jpg): 软限制 20MB, 硬限制 200MB
-   2=视频(mp4): 软限制 30MB, 硬限制 200MB
-   3=语音(silk): 软限制 20MB, 硬限制 200MB
-   4=文件: 软限制 200MB, 硬限制 200MB 超过软限制会降级为文件类型上传，超过硬限制会报错。

支持三种上传方式，按实际文件大小和资源来源选择。

## 一、支持的上传方式

方式

说明

限制 / 注意

URL 上传

传入 `url`，由平台下载并转存

服务端下载资源可能因网络等原因失败

分片上传合并

先通过 `upload_prepare` + `upload_part_finish` 完成分片上传，再携带 `upload_id` 调用本接口完成合并

**推荐使用**

直接上传二进制数据

直接传文件二进制内容

数据大小不能超过 5M，超过建议使用分片上传

## 二、推荐流程：分片上传

1.  调用 `upload_prepare`，获取 `upload_id`、`block_size` 以及各分片的预签名 URL。
2.  按 `block_size` 将文件切分为多个分片，逐片通过 HTTP `PUT` 上传到对应的预签名 URL。
3.  每片 `PUT` 成功后，调用 `upload_part_finish` 通知服务端该分片上传完成。
4.  全部分片上传完成后，携带 `upload_id` 调用本接口完成合并，返回 `file_info`。

## 三、注意事项

-   URL 上传存在服务端下载失败的可能，若遇到下载失败，可先将资源下载到本地，再通过**直接上传二进制数据**的方式上传。
-   二进制直传有 5M 大小上限，文件较大时请改用分片上传。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/groups/{group\_openid}/files

HTTP Method

POST

接口频率限制

50 QPS

## 路径参数

名称

类型

必填

描述

group\_openid

string

是

群 OpenID

## 请求体

名称

类型

必填

描述

file\_type

integer

否

媒体类型。1=图片, 2=视频, 3=语音, 4=文件 图片支持 png/jpg，视频支持 mp4，语音支持 silk,mp3,wav

url

string

否

媒体资源的 URL，需以 http 开头，平台会下载并转存 分片上传合并时可为空

srv\_send\_msg

boolean

否

true=直接发送消息并占用主动消息频次，返回中包含消息 ID false=仅返回 file\_info，用于后续发送消息接口的 media 字段

upload\_id

string

否

分片上传任务 ID。来自 UploadPrepare 响应的 upload\_id， 传入后走分片上传合并路径，url 可为空

file\_name

string

否

文件名 (分片上传或者二进制上传时必填）

file\_data

string

否

直接上传二进制数据。 直接上传二进制有大小限制，需要在5M以内，如果超过则需要使用URL上传或者分片上传。

### 请求示例

**URL 上传图片**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/files
{
  "file_type": 1,
  "url": "https://example.com/image.png",
  "srv_send_msg": false
}
```

**分片上传合并**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/files
{
  "file_type": 2,
  "srv_send_msg": false,
  "file_name": "video.mp4",
  "upload_id": "upload_a1b2c3d4e5f6"
}
```

**二进制上传**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/files
{
  "file_type": 1,
  "file_name": "video.mp4",
  "file_data": "xxxx图片的二进制数据"
}
```

## 响应

### 响应体

名称

类型

描述

file\_uuid

string

文件唯一 ID

file\_info

string

文件信息，用于发送消息接口的 media.file\_info 字段。 内部为序列化的二进制数据，开发者无需解析，直接透传即可

ttl

integer

file\_info 有效期（秒）。到期后需重新上传。 0 表示可长期使用

id

string

发送消息的唯一 ID。仅 srv\_send\_msg=true 时返回

raw\_url

string

文件下载链接（COS 预签名 GET URL），有效期与 ttl 一致 仅分片上传合并（upload\_id 路径）且 file\_type 为图片/视频/语音时返回； URL 直传和文件类型(file\_type=4)不返回此字段

## 响应示例

**上传成功**

```
{
  "file_uuid": "uuid_a1b2c3d4e5f6",
  "file_info": "AE86C5D3F0E14B238C656C0F6DD1D0479C",
  "ttl": 300
}
```

### 错误码

错误码

描述

排查建议

850018

群被禁言或者机器人被禁言

请检查机器人是否被禁言

850019

不支持的文件格式

请检查 file\_type 是否正确

850026

下载原始文件失败

请检查 URL 是否可访问或重试

850031

上传文件超过大小限制

请减小文件大小

850027

发送数据超时

请稍后重试

10000

不支持的操作

请检查请求参数

40093001

文件上传失败，请重试

大文件分片上传中 BDH 通道异常，请重试

40093002

超过今天发送文件容量上限

请明天再试或减少文件大小

### 群聊富媒体预上传

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_id_upload_prepare.post.html

# 群聊富媒体预上传

大文件分片上传前的准备工作。返回 upload\_id、分片预签名 URL 和上传配置。 后续将文件按 block\_size 分片，逐片 PUT 到预签名 URL，每片完成后调用分片完成接口。

大文件分片上传第一步。传入文件大小、MD5/SHA1 校验值，服务端返回 upload\_id 和各分片预签名 URL。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/groups/{group\_id}/upload\_prepare

HTTP Method

POST

接口频率限制

10 QPS

## 路径参数

名称

类型

必填

描述

group\_id

string

是

群 OpenID

## 请求体

名称

类型

必填

描述

file\_type

integer

是

业务类型。1=图片, 2=视频, 3=语音, 4=文件 图片软限制 20MB, 视频软限制 30MB, 语音软限制 20MB, 文件软限制 200MB 超过软限制降级为文件类型，超过 200MB 硬限制报错

file\_size

string

是

文件大小（字节）

file\_name

string

是

文件名

md5

string

是

整个文件的 MD5 校验值

sha1

string

是

整个文件的 SHA1 校验值

md5\_10m

string

是

文件前 10002432 字节（约 10MB）的 MD5 校验值

### 请求示例

**预上传视频文件**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/upload_prepare
{
  "file_type": 2,
  "file_size": "31457280",
  "file_name": "demo.mp4",
  "md5": "d41d8cd98f00b204e9800998ecf8427e",
  "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
  "md5_10m": "c4d8c5f3a2b1e0f9a8b7c6d5e4f3a2b1"
}
```

## 响应

### 响应体

名称

类型

描述

upload\_id

string

上传任务 ID，后续分片上传和完成合并时需携带

block\_size

string

分块大小（字节），默认 5MB。客户端按此大小对文件分片

parts

\[\][UploadPart](#schema-uploadpart)

分片列表，每个分片包含一个预签名上传 URL

upload\_config

[UploadConfig](#schema-uploadconfig)

上传配置，由后台下发控制客户端上传行为

**UploadPart**

名称

类型

描述

index

integer

分片序号，从 0 开始

presigned\_url

string

预签名上传 URL，客户端通过 HTTP PUT 将分片数据上传到此 URL

block\_size

string

该分块的大小（字节）

**UploadConfig**

名称

类型

描述

concurrency

integer

上传并发数，默认 1

retry\_timeout

integer

重试超时时间（秒），默认 300（5分钟）

retry\_delay

integer

重试延迟（秒），默认 1

## 响应示例

**预上传成功（3 个分片）**

```
{
  "upload_id": "upload_a1b2c3d4e5f6",
  "block_size": "10485760",
  "parts": [
    {
      "index": 0,
      "presigned_url": "https://cos.example.com/upload?partNumber=1&sign=aaa",
      "block_size": "10485760"
    },
    {
      "index": 1,
      "presigned_url": "https://cos.example.com/upload?partNumber=2&sign=bbb",
      "block_size": "10485760"
    },
    {
      "index": 2,
      "presigned_url": "https://cos.example.com/upload?partNumber=3&sign=ccc",
      "block_size": "10485760"
    }
  ],
  "upload_config": {
    "concurrency": 1,
    "retry_timeout": 300,
    "retry_delay": 1
  }
}
```

### 错误码

错误码

描述

排查建议

850018

群被禁言或者机器人被禁言

请检查机器人是否被禁言

850019

不支持的文件格式

请检查 file\_type 是否正确

850026

下载原始文件失败

请检查 URL 是否可访问或重试

850031

上传文件超过大小限制

请减小文件大小

850027

发送数据超时

请稍后重试

10000

不支持的操作

请检查请求参数

40093001

文件上传失败，请重试

申请上传失败，请重试

### 群聊分片上传完成

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_id_upload_part_finish.post.html

# 群聊分片上传完成

通知服务端某个分片已上传完成。需在每片 PUT 成功后调用。全部分片完成后，用 upload\_id 作为 MediaUpload 的 upload\_id 字段调一次上传接口完成合并

分片上传第二步。每个分片 PUT 到预签名 URL 成功后调用，通知服务端该分片已上传完成。 全部分片完成后，携带 upload\_id 调用 /v2/groups/{group\_openid}/files 完成合并。

## 请求

### 基础信息

字段

值

HTTP URL

/v2/groups/{group\_id}/upload\_part\_finish

HTTP Method

POST

接口频率限制

10 QPS

## 路径参数

名称

类型

必填

描述

group\_id

string

是

群 OpenID

## 请求体

名称

类型

必填

描述

upload\_id

string

否

上传任务 ID，来自预上传响应

part\_index

integer

否

分片序号，对应 UploadPart.index

block\_size

string

否

该分块的实际大小（字节）

md5

string

否

该分片的 MD5 校验值

### 请求示例

**通知分片 0 上传完成**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/upload_part_finish
{
  "upload_id": "upload_a1b2c3d4e5f6",
  "part_index": 0,
  "block_size": "10485760",
  "md5": "c4d8c5f3a2b1e0f9a8b7c6d5e4f3a2b1"
}
```

## 响应

无

## 响应示例

**分片完成确认**

```
{}
```

### 错误码

错误码

描述

排查建议

850018

群被禁言或者机器人被禁言

请检查机器人是否被禁言

850019

不支持的文件格式

请检查 file\_type 是否正确

850026

下载原始文件失败

请检查 URL 是否可访问或重试

850031

上传文件超过大小限制

请减小文件大小

850027

发送数据超时

请稍后重试

10000

不支持的操作

请检查请求参数

40093001

文件上传失败，请重试

分片转存 BDH 通道异常，请重试

40093002

超过今天发送文件容量上限

请明天再试或减少文件大小

## 5. 消息类型

### 消息类型（overview）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/overview.html

# 消息类型

通过 `msg_type` 指定消息格式，不同的类型对应不同的内容字段和收发能力。

## 发送：msg\_type

发送消息时通过 `msg_type` 指定格式：

msg\_type

类型

内容字段

说明

0

文本

`content`

纯文本消息

2

Markdown

`markdown`

支持 Markdown 语法，详见 [Markdown 消息](/wiki/develop/api-v2/server-inter/message/type/markdown.html)

7

富媒体

`media`

图片/视频/语音/文件，需先上传获取 `file_info`

## 接收：message\_type

收到用户消息时，事件体中的 `message_type` 表示消息内容类型：

message\_type

含义

说明

0

普通文本

`content` 字段携带文本内容

3

结构化卡片

`ark_data` 字段携带卡片数据

103

引用消息

`msg_elements` 字段携带嵌套内容

> 图片、视频、语音、文件等附加内容通过 `attachments` 字段携带（`content_type` 区分具体类型），不通过 `message_type` 单独表示。

## 各场景支持情况

类型

单聊

群聊

频道

**文本**

收发 ✅

收发 ✅

收发 ✅

**Markdown**

发 ✅ / 收 ❌

收发 ✅

发 ✅ / 收 ❌

**图片**

收发 ✅

收发 ✅

收发 ✅

**视频**

收发 ✅

收发 ✅

收发 ✅

**语音**

收发 ✅

收发 ✅

收发 ✅

**文件**

收发 ✅

收发 ✅

❌

**结构化卡片**

发 ❌ / 收 ✅

发 ❌ / 收 ✅

发 ❌ / 收 ❌

**Embed**

❌

❌

发 ✅ / 收 ❌

**表情表态**

❌

❌

收发 ✅

**引用消息**

收 ✅

收 ✅

收 ✅

> -   发送侧只有 msg\_type=0/2/3/7 四种（见上方表格）
> -   富媒体上传流程见 [富媒体使用说明](/wiki/develop/api-v2/server-inter/message/rich-media.html)
> -   表情表态仅频道支持，详见 [表情表态](/wiki/develop/api-v2/server-inter/message/trans/emoji.html)

### Markdown 消息

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html

# Markdown 消息

2026/04/23 能力更新说明

单聊场景、群聊场景自定义 Markdown 消息能力已开放到所有机器人均可使用，无需单独申请 Markdown 模版，频道场景目前需要内邀开通。

## 支持格式

### 标题

```
# 一号标题
## 二号标题
正文
```

### 文字样式

```
**加粗**
__下划线加粗__
_斜体_
*星号斜体*
***加粗斜体***
~~删除线~~

```

### 链接

```
欢迎来到：[🔗腾讯网](https://www.qq.com)  
文档可以访问<https://doc.qq.com>
```

### 图片

对于 markdown 消息内的图片资源，请使用可在公网访问的资源 url，开放平台会下载转存该资源。

```
![text #208px #320px](https://resource5-1255303497.cos.ap-guangzhou.myqcloud.com/abcmouse_word_watch/markdown/building.png)
```

### 有序列表

```
# 有序列表
1. 新人降落桃源岛的欢迎仪式
2. 阳光准则助力建设有温度的频道
3. 岛民分享吹水纳凉
```

### 无序列表

```
# 无序列表
- 新人降落桃源岛的欢迎仪式
- 阳光准则助力建设有温度的频道
- 岛民分享吹水纳凉
```

### 列表嵌套

```
# 有序列表标题
1. 嵌套一层
    - 列表前是普通文本，则需要在列表前用空行隔开，否则无法识别
    - 如果是段落标签比如标题，则无需用空行隔开
2. 嵌套二层
    1. 我是有序列表，二级列表前面需要空4个空格
    2. 无序列表和有序列表可以相互嵌套，但是不建议无限制嵌套。
```

### 块引用

```
> 青青子衿，悠悠我心，但为君故，沉吟至今
> 四月维夏，六月徂暑。先祖匪人，胡宁忍予
> 秋日凄凄，百卉具腓。乱离瘼矣，爰其适归？
诗经《小雅》
```

### 水平分割线

```
这是段落1
***
这是段落2
```

### 换多行

```
第一行

第二行

\u200B
\u200B
第三行
```

## 发送方式

自定义 markdown 消息使用示例：

```
{
  "markdown": {
    "content": "# 标题 \n## 简介很开心 \n内容[🔗腾讯](https://www.qq.com)"
  }
}
```

markdown 模版消息的使用示例：

```
// 模版例子

#{{.title}}

![img#618px #249px]({{.image}})

*{{.para1}}
*{{.para2}}

## {{.desc}}

{{.content}}[{{.link_introduction}}]({{.link}})

// 发送case
{
	"markdown": {
		"custom_template_id": "101993071_1658748972",
		"params": [{
				"key": "title",
				"values": ["标题"]
			},
			{
				"key": "image",
				"values": [
					"https://resource5-1255303497.cos.ap-guangzhou.myqcloud.com/abcmouse_word_watch/other/mkd_img.png"
				]
			},
			{
				"key": "para1",
				"values": ["段落1"]
			},
			{
				"key": "para2",
				"values": ["段落2"]
			},
			{
				"key": "desc",
				"values": ["简介"]
			},
			{
				"key": "content",
				"values": ["在这个子频道非常开心"]
			},
			{
				"key": "link_introduction",
				"values": ["链接介绍"]
			},
			{
				"key": "link",
				"values": ["https://www.qq.com"]
			}
		]
	}
}
```

## 数据结构与协议

消息发送 markdown 字段值是一个 json object，具体字段如下：

**属性**

**类型**

**必填**

**说明**

content

string

否

自定义 markdown 文本内容

custom\_template\_id

string

否

markdown 模版id，申请模版后获得

params

Array

否

{key: xxx, values: xxx}，模版内变量与填充值的kv映射

### 结构化卡片消息

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/ark.html

# 结构化卡片消息

说明

达到准入条件的开发者，向平台运营申请后获得权限。

## 发送方式

选择合适的 结构化卡片消息（ARK） 模板，将模板变量以 key-value 对填充后发送。每个模板定义了自己的变量（`#XXX#`），变量类型可以是字符串、数组、URL 等。

### 数据结构

消息发送接口中 `ark` 字段的结构：

属性

类型

必填

说明

template\_id

int

是

模板 ID，可选 23 / 24 / 37

kv

kv 数组

是

`[{key: "#变量#", value: "填充值"}]`，模板变量与填充值的映射

当变量类型为数组时，kv 元素使用 `obj` 嵌套数组结构：

```
{
  "key": "#LIST#",
  "obj": [
    {
      "obj_kv": [
        { "key": "desc", "value": "文本" },
        { "key": "link", "value": "https://..." }
      ]
    }
  ]
}
```

### 请求示例

```
{
  "ark": {
    "template_id": 23,
    "kv": [
      { "key": "#DESC#", "value": "机器人订阅消息" },
      { "key": "#PROMPT#", "value": "XX机器人" },
      { "key": "#TITLE#", "value": "XX机器人消息" },
      { "key": "#META_URL#", "value": "http://domain.com/" },
      {
        "key": "#META_LIST#",
        "obj": [
          {
            "obj_kv": [
              { "key": "name", "value": "aaa" },
              { "key": "age", "value": "3" }
            ]
          },
          {
            "obj_kv": [
              { "key": "name", "value": "bbb" },
              { "key": "age", "value": "4" }
            ]
          }
        ]
      }
    ]
  }
}
```

## 模板 23 — 链接+文本列表

![23](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/23.dcdba41f.png)

模板 id = 23。

### 模板格式

```
{
  "app": "com.tencent.channel.robot",
  "view": "albumAddPic",
  "ver": "0.0.0.1",
  "desc": "#DESC#",
  "prompt": "[QQ小程序]#PROMPT#",
  "meta": {
    "detail": {
      "list": "#LIST#"
    }
  }
}
```

### 字段说明

变量

类型

描述

#DESC#

string

描述

#PROMPT#

string

提示消息

#LIST#

array

文本列表，每个元素为 `{desc, link}`

**#LIST# 元素结构**：

字段

类型

描述

desc

string

文本内容

link

string

跳转链接（需提前报备），不填则仅显示文本

### 请求示例

```
{
  "ark": {
    "template_id": 23,
    "kv": [
      { "key": "#DESC#", "value": "descaaaaaa" },
      { "key": "#PROMPT#", "value": "promptaaaa" },
      {
        "key": "#LIST#",
        "obj": [
          { "obj_kv": [{ "key": "desc", "value": "需求标题：UI问题解决" }] },
          { "obj_kv": [{ "key": "desc", "value": "当前状态\"体验中\"点击下列动作直接扭转状态到：" }] },
          {
            "obj_kv": [
              { "key": "desc", "value": "已评审" },
              { "key": "link", "value": "https://qun.qq.com" }
            ]
          },
          {
            "obj_kv": [
              { "key": "desc", "value": "已排期" },
              { "key": "link", "value": "https://qun.qq.com" }
            ]
          },
          {
            "obj_kv": [
              { "key": "desc", "value": "开发中" },
              { "key": "link", "value": "https://qun.qq.com" }
            ]
          },
          {
            "obj_kv": [
              { "key": "desc", "value": "增量测试中" },
              { "key": "link", "value": "https://qun.qq.com" }
            ]
          },
          { "obj_kv": [{ "key": "desc", "value": "请关注" }] }
        ]
      }
    ]
  }
}
```

## 模板 24 — 文本+缩略图

![24](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/24.4656049a.png)

模板 id = 24。

### 模板格式

```
{
  "app": "com.tencent.channelrobot.smallpic",
  "view": "albumAddPic",
  "ver": "0.0.0.1",
  "desc": "#DESC#",
  "prompt": "[QQ小程序]#PROMPT#",
  "meta": {
    "detail": {
      "title": "#TITLE#",
      "desc": "#METADESC#",
      "img": "#IMG#",
      "link": "#LINK#",
      "subTitle": "#SUBTITLE#"
    }
  }
}
```

### 字段说明

变量

类型

描述

#DESC#

string

描述

#PROMPT#

string

提示文本

#TITLE#

string

标题

#METADESC#

string

详情描述

#IMG#

string

图片链接

#LINK#

string

跳转链接

#SUBTITLE#

string

来源

### 请求示例

```
{
  "ark": {
    "template_id": 24,
    "kv": [
      { "key": "#DESC#", "value": "..." },
      { "key": "#PROMPT#", "value": "通知信息" },
      { "key": "#TITLE#", "value": "标题" },
      { "key": "#METADESC#", "value": "Meta描述" },
      { "key": "#IMG#", "value": "https://pub.idqqimg.com/pc/misc/files/20190820/2f4e70ae3355ece23d161cf5334d4fc1jzjfmtep.png" },
      { "key": "#LINK#", "value": "https://qq.com" },
      { "key": "#SUBTITLE#", "value": "子标题" }
    ]
  }
}
```

## 模板 37 — 大图

![37](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/37.2955062b.png)

模板 id = 37。

### 模板格式

```
{
  "app": "com.tencent.imagetextbot",
  "view": "index",
  "ver": "1.0.0.11",
  "prompt": "#PROMPT#",
  "meta": {
    "robot": {
      "title": "#METATITLE#",
      "subtitle": "#METASUBTITLE#",
      "cover": "#METACOVER#",
      "jump_url": "#METAURL#"
    }
  }
}
```

### 字段说明

变量

类型

描述

#PROMPT#

string

提示消息

#METATITLE#

string

标题

#METASUBTITLE#

string

子标题

#METACOVER#

string

大图，尺寸 975×540

#METAURL#

string

跳转链接

### 请求示例

```
{
  "ark": {
    "template_id": 37,
    "kv": [
      { "key": "#PROMPT#", "value": "通知提醒" },
      { "key": "#METATITLE#", "value": "标题" },
      { "key": "#METASUBTITLE#", "value": "子标题" },
      { "key": "#METACOVER#", "value": "https://vfiles.gtimg.cn/vupload/20211029/bf0ed01635493790634.jpg" },
      { "key": "#METAURL#", "value": "https://qq.com" }
    ]
  }
}
```

### Embed 消息

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/embed.html

# Embed 消息

**单聊**

**群聊**

**文字子频道**

**频道私信**

机器人接收

\-

\-

\-

\-

机器人发送

不支持

不支持

支持

支持

## 样式

![embed](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/message-embed.18d8bc6d.jpg)

## 数据结构与协议

### Content-Type

```
application/json
```

### 参数

字段名

类型

描述

embed

[MessageEmbed](/wiki/develop/api-v2/server-inter/message/template/model.html#messageembed)

embed 消息详情

-   其中 embed.thumbnail 为选填，没有缩略图的可以不填。
-   embed.fields.name 为文本。

### 返回

返回[Message](/wiki/develop/api-v2/server-inter/message/template/model.html#message)对象。

### 错误码

详见[错误码](/wiki/develop/api-v2/openapi/error/error.html)。

### 示例

请求数据包

```
{
  "embed": {
    "title": "标题",
    "prompt": "消息通知",
    "thumbnail": {
      "url": "xxxxxx"
    },
    "fields": [
      {
        "name": "当前等级：黄金"
      },
      {
        "name": "之前等级：白银"
      },
      {
        "name": "😁继续努力"
      }
    ]
  }
}
```

返回包

```
{
  "id": "xxxxxx",
  "channel_id": "xxxxxx",
  "guild_id": "xxxxxx",
  "timestamp": "2021-12-07T15:24:54+08:00",
  "tts": false,
  "mention_everyone": false,
  "author": {
    "id": "xxxxxx",
    "username": "abc",
    "avatar": "",
    "bot": true
  },
  "embeds": [
    {
      "title": "标题",
      "prompt": "xxxx",
      "description": "",
      "thumbnail": {
        "url": "xxxxxx"
      },
      "fields": [
        {
          "name": "当前等级：黄金"
        },
        {
          "name": "之前等级：白银"
        },
        {
          "name": "😁继续努力"
        }
      ]
    }
  ],
  "pinned": false,
  "type": 0,
  "flags": 0
}
```

### 消息交互概述

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/overview.html

# 消息交互概述

说明

在各种消息场景内，开发者可在消息体上实现自定义一些与用户的交互方式。

消息按钮

文字链

![消息按钮](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/message-btn.94002609.jpg)

![文字链](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/text-chain.b2f9b0fb.jpg)

## 消息按钮互动流程

消息按钮互动的整体流程如下：

1.  **发送带按钮的消息**：机器人下发包含 `keyboard` 字段的消息，用户端看到消息底部挂载的按钮
2.  **用户点击按钮**：平台推送 [`INTERACTION_CREATE`](/wiki/develop/api-v2/autogen/event/interaction_create.html) 事件给机器人
3.  **机器人响应互动**：机器人调用 [PUT /interactions/{interaction\_id}](/wiki/develop/api-v2/autogen/api/interactions_interaction_id.put.html) 回复用户

### 发送消息时携带 keyboard

在消息的 `keyboard` 字段中传入按钮配置，支持模板按钮和自定义按钮两种模式。

-   发送单聊消息：[keyboard 字段参考](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html#schema-keyboard)
-   发送群聊消息：[keyboard 字段参考](/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html#schema-keyboard)

**按钮数据示例**（一处配置缓存一批按钮，动态提取生成行为按钮）：

```
{
  "keyboard": {
    "id": "keyboard_id_xxx",
    "content": {
      "rows": [
        {
          "buttons": [
            {
              "id": "button_1",
              "render_data": {
                "label": "确认",
                "visited_label": "已确认",
                "style": 1
              },
              "action": {
                "type": 2,
                "permission": {
                  "type": 2,
                  "specify_role_ids": [],
                  "specify_user_ids": []
                },
                "click_limit": 1,
                "data": "/action_confirm",
                "at_bot_show_channel_list": false,
                "reply": true,
                "enter": true
              }
            }
          ]
        }
      ]
    }
  }
}
```

### 响应互动

收到 `INTERACTION_CREATE` 事件后，需要在规定时间内调用 [PUT /interactions/{interaction\_id}](/wiki/develop/api-v2/autogen/api/interactions_interaction_id.put.html) 响应，否则会超时。

**响应超时时间**：指令回调类场景为 3 秒。建议收到事件后尽快响应，避免因超时导致用户侧无反馈。

### 文本交互

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/text-chain.html

# 文本交互

说明

QQBot 提供文本消息的交互能力，当开发者使用指定的格式发送消息，用户即可在消息体上进行点击交互操作，例如@某人，跳转链接等。

## 使用 @ 能力

说明

群聊&文字子频道，支持含有文本文字的消息类型，如：文本消息、图文消息、markdown 消息。

1.  @某人｜群聊、文字子频道可用

嵌入文本使用格式：`<qqbot-at-user id="" />` 协议：`<@userid>`即将弃用，请使用上述最新格式。

客户端展示为： @用户 标签

2.  @全部成员｜仅在文字子频道可用

嵌入文本使用格式：`<qqbot-at-everyone />` 协议：`@everyone`即将弃用，请使用上述最新格式。

客户端展示为： @全部成员 标签，需要机器人拥有发送 @全部成员 消息的权限，

## 指令操作

目前仅在 markdown 支持。

**1\. 回车指令格式（点击后，文本直接发送）**

嵌入文本使用格式：

`<qqbot-cmd-enter text="xxx" />`

客户端展示为： /回车指令 用户可点击的标签，群聊和文字子频道不支持该能力。

-   `text` 用户点击后直接发送的文本，参数必填，最大限制 100 字符，传值时需要 urlencode。

**2\. 参数指令格式（点击后，文本插入输入框，用户自行编辑发送）**

嵌入文本使用格式：

`<qqbot-cmd-input text="xxx" show="xxx" reference="false" />`

客户端展示为： /参数指令 用户可点击的标签

-   `text` 用户点击后插入输入框的文本，参数必填，最大限制 100 字符，传值时需要 urlencode。
-   `show` 用户在消息内看到的文本，参数选填，默认取 text 值，最大限制 100 字符，传值时需要 urlencode。
-   `reference` 插入输入框时是否带消息原文回复引用，参数选填，默认为 `false`，填入 `true` 时则带引用回复到输入框中。

## 跳转子频道

仅频道可用。

嵌入文本使用格式：`<#channel_id>`

客户端展示为： #XXX文字子频道 标签，点击可以跳转至子频道，仅支持当前频道内的子频道。

## 表情

仅频道可用，解析为系统表情。 具体表情id参考 [Emoji 列表](/wiki/develop/api-v2/openapi/emoji/model.html#Emoji 列表)。

嵌入文本使用格式：`<emoji:id>`

-   仅支持 `type = 1` 的系统表情。
-   `type = 2` 的 emoji 表情直接按字符串填写即可。

### 消息按钮

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/msg-btn.html

# 消息按钮

说明

在 markdown 消息的基础上，支持消息最底部挂载按钮。

## 发送方式

【申请使用】按钮模版，按钮模版暂时不支持使用变量填充。

```
{
    "keyboard": {
        "id": "123" // 申请模版后获得
    }
}
```

【内邀开通】自定义按钮

```
{
    "keyboard": {
        "content": {
            "rows": [
                {"buttons": [{button}, {button}, {button}, {button}, {button}]},
                {"buttons": [{button}, {button}, {button}, {button}, {button}]},
                {"buttons": [{button}, {button}, {button}, {button}, {button}]},
                {"buttons": [{button}, {button}, {button}, {button}, {button}]},
                {"buttons": [{button}, {button}, {button}, {button}, {button}]},
            ] // 自定义按钮内容，最多可以发送5行按钮，每一行最多5个按钮。
        }
    }
}
```

## 数据结构与协议

消息发送接口 keyboard 字段值是一个 Json Object {}，rows 数组的每个元素表示每一行按钮

每个 button 是一个 Json Object，具体字段如下：

**属性**

**类型**

**必填**

**说明**

id

string

否

按钮ID：在一个keyboard消息内设置唯一

render\_data.label

string

是

按钮上的文字

render\_data.visited\_label

string

是

点击后按钮的上文字

render\_data.style

int

是

按钮样式：0 灰色线框，1 蓝色线框

action.type

int

是

设置 0 跳转按钮：http 或 小程序 客户端识别 scheme，设置 1 回调按钮：回调后台接口, data 传给后台，设置 2 指令按钮：自动在输入框插入 @bot data

action.permission.type

int

是

0 指定用户可操作，1 仅管理者可操作，2 所有人可操作，3 指定身份组可操作（仅频道可用）

action.permission.specify\_user\_ids

array

否

有权限的用户 id 的列表

action.permission.specify\_role\_ids

array

否

有权限的身份组 id 的列表（仅频道可用）

action.data

string

是

操作相关的数据

action.reply

bool

否

指令按钮可用，指令是否带引用回复本消息，默认 false。支持版本 8983

action.enter

bool

否

指令按钮可用，点击按钮后直接自动发送 data，默认 false。支持版本 8983

action.anchor

int

否

本字段仅在指令按钮下有效，设置后后会忽略 action.enter 配置。  
设置为 1 时 ，点击按钮自动唤起启手Q选图器，其他值暂无效果。  
（仅支持手机端版本 8983+ 的单聊场景，桌面端不支持）

action.click\_limit

int

否

【已弃用】可操作点击的次数，默认不限

action.at\_bot\_show\_channel\_list

bool

否

【已弃用】指令按钮可用，弹出子频道选择器，默认 false

action.unsupport\_tips

string

是

客户端不支持本action的时候，弹出的toast文案

示例

```
{
  "rows": [
    {
      "buttons": [
        {
          "id": "1",
          "render_data": {
            "label": "⬅️上一页",
            "visited_label": "⬅️上一页"
          },
          "action": {
            "type": 1,
            "permission": {
              "type": 1,
              "specify_role_ids": [
                "1",
                "2",
                "3"
              ]
            },
            "click_limit": 10,
            "unsupport_tips": "兼容文本",
            "data": "data",
            "at_bot_show_channel_list": true
          }
        },
        {
          "id": "2",
          "render_data": {
            "label": "➡️下一页",
            "visited_label": "➡️下一页"
          },
          "action": {
            "type": 1,
            "permission": {
              "type": 1,
              "specify_role_ids": [
                "1",
                "2",
                "3"
              ]
            },
            "click_limit": 10,
            "unsupport_tips": "兼容文本",
            "data": "data",
            "at_bot_show_channel_list": true
          }
        }
      ]
    },
    {
      "buttons": [
        {
          "id": "3",
          "render_data": {
            "label": "📅 打卡（5）",
            "visited_label": "📅 打卡（5）"
          },
          "action": {
            "type": 1,
            "permission": {
              "type": 1,
              "specify_role_ids": [
                "1",
                "2",
                "3"
              ]
            },
            "click_limit": 10,
            "unsupport_tips": "兼容文本",
            "data": "data",
            "at_bot_show_channel_list": true
          }
        }
      ]
    }
  ]
}
```

## 相关事件与接口

用户点击回调按钮会触发 `INTERACTION_CREATE` 事件，机器人收到事件后需调用 `PUT /interactions/{interaction_id}` 进行回应，否则客户端会一直处于 loading 状态直到超时。

-   事件详情：[INTERACTION\_CREATE](/wiki/develop/api-v2/autogen/event/interaction_create.html)
-   回应接口：[PUT /interactions/{interaction\_id}](/wiki/develop/api-v2/autogen/api/interactions_interaction_id.put.html)

## 6. 事件

### 单聊消息事件（C2C_MESSAGE_CREATE）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/c2c_message_create.html

# 单聊消息事件

用户给机器人发送单聊消息时触发。 为确保消息可达，相同 msg\_id 可能重复推送，开发者需结合 msg\_seq 做去重。

为确保消息可达，相同 msg\_id 可能重复推送，需结合 message\_scene.ext 中的 msg\_idx 做去重。message\_type 决定消息结构：0=纯文本，3=ARK卡片（ark\_data 有值），103=引用消息（msg\_elements 有值，message\_scene.ext 含 ref\_msg\_idx）。

## 事件

字段

值

事件名

C2C\_MESSAGE\_CREATE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### 事件体

名称

类型

描述

id

string

消息 ID，可用于被动回复和撤回

author

[User](#schema-user)

发送者（user\_openid 有值）

content

string

消息文本内容

timestamp

string

消息发送时间，RFC3339 格式

message\_type

integer

消息内容类型: 0=普通文本, 3=结构化卡片, 101=并行消息, 102=聊天记录, 103=引用消息

message\_scene

[MessageScene](#schema-messagescene)

消息场景上下文（含消息索引、鉴权令牌等）

attachments

\[\][MessageAttachment](#schema-messageattachment)

消息附件（图片、文件、语音等）

ark\_data

[ARKData](#schema-arkdata)

结构化卡片消息数据（message\_type=3 时有值）

msg\_elements

\[\][MsgElement](#schema-msgelement)

消息元素列表（message\_type=103 引用消息时包含被引用内容）

**User**

名称

类型

描述

id

string

用户唯一标识（OpenID 格式）

username

string

用户昵称

bot

boolean

是否为机器人

union\_openid

string

跨应用统一用户 OpenID（可能为空）

union\_user\_account

string

跨应用统一用户账号（可能为空）

user\_openid

string

用户 OpenID（单聊场景使用）

member\_openid

string

群成员 OpenID（群聊场景使用）

member\_role

string

群内角色。member=普通成员, admin=管理员, owner=群主

**MessageScene**

名称

类型

描述

source

string

场景来源。default=默认聊天窗口

ext

\[\]string

扩展数据列表，key=value 格式: msg\_idx=消息索引, 用于引用场景 ref\_msg\_idx=引用的消息索引 auth\_token=鉴权令牌

**MessageAttachment**

名称

类型

描述

url

string

附件下载 URL

filename

string

文件名

width

integer

图片宽度（像素），非图片附件无此字段

height

integer

图片高度（像素），非图片附件无此字段

size

integer

文件大小（字节）

content\_type

string

附件内容类型（MIME 类型）: voice=语音消息 image/jpeg=JPEG 图片 image/png=PNG 图片 image/gif=GIF 图片 video/mp4=MP4 视频 file=群文件

voice\_wav\_url

string

语音消息 SILK 等转换后的 WAV 文件 URL

asr\_refer\_text

string

语音消息 ASR 参考结果

**ARKData**

名称

类型

描述

prompt

string

卡片消息中的用户操作提示文本

ark\_type

string

卡片消息类型标识: tuwen = 图文 H5（如快手分享链接） feed = 图文卡片（群相册、频道帖子、分享卡片） miniapp = 小程序（微信小程序、QQ 小程序、哔哩哔哩等） map = 位置卡片 contact\_card = 好友名片 video\_share = 视频分享 music\_together = 一起听歌 picture = 图片

ark\_name

string

卡片消息类型的中文名称，如"图文 H5"、"小程序"、"图文卡片"

fields

object

卡片消息字段，常见键名: tag/tags=来源标签, title=标题, desc=描述, jump\_url=跳转链接, preview=预览图, source=来源名称, source\_logo=来源图标, tag\_icon=标签图标, nickname=昵称, avatar=头像, address=地址

**MsgElement**

名称

类型

描述

msg\_idx

string

消息元素在列表中的引用消息索引

author

[User](#schema-user)

该元素对应的消息发送者

message\_type

integer

消息内容类型: 0=普通文本, 3=结构化卡片, 101=并行消息, 102=聊天记录, 103=引用消息

content

string

消息正文内容

attachments

\[\][MessageAttachment](#schema-messageattachment)

该元素携带的附件

ark\_data

[ARKData](#schema-arkdata)

结构化卡片消息数据（message\_type=3 时有值）

msg\_elements

\[\][MsgElement](#schema-msgelement)

嵌套消息元素列表（递归结构）

### 事件示例

**示例1**

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "author": {
    "id": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "user_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "union_openid": "",
    "username": "",
    "bot": false
  },
  "content": "你好，今天有什么推荐的活动吗？",
  "message_type": 0,
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_xxxxxxxxxxxxxxx=="
    ]
  },
  "timestamp": "2026-07-21T10:00:00+08:00"
}
```

**示例2**

```
{
  "id": "ROBOT1.0_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
  "author": {
    "id": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
    "user_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
    "union_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
    "username": "",
    "bot": false
  },
  "content": "[卡片消息] 小程序\n摘要: [每日打卡]快来完成今日学习打卡",
  "message_type": 3,
  "ark_data": {
    "ark_type": "miniapp",
    "ark_name": "小程序",
    "prompt": "[每日打卡]快来完成今日学习打卡",
    "fields": {
      "title": "快来完成今日学习打卡",
      "source": "学习助手",
      "tag": "微信小程序",
      "preview": "https://pubminishare-30161.picsz.qpic.cn/preview_a1b2c3d4",
      "source_logo": "https://miniapp.gtimg.cn/generated-icon/app_a1b2c3d4.png",
      "tag_icon": "https://miniapp.gtimg.cn/public/miniwx.png"
    }
  },
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_yyyyyyyyyyyyyyy=="
    ]
  },
  "timestamp": "2026-07-21T10:01:00+08:00"
}
```

**示例3**

```
{
  "id": "ROBOT1.0_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
  "author": {
    "id": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "user_openid": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "union_openid": "",
    "username": "",
    "bot": false
  },
  "content": "这个建议很有帮助，谢谢你！",
  "message_type": 103,
  "msg_elements": [
    {
      "msg_idx": "REFIDX_aaaaaaaaaaaaaaa==",
      "message_type": 103,
      "content": "每天坚持阅读半小时，一个月后你会发现自己的变化"
    }
  ],
  "message_scene": {
    "source": "default",
    "ext": [
      "ref_msg_idx=REFIDX_aaaaaaaaaaaaaaa==",
      "msg_idx=REFIDX_zzzzzzzzzzzzzzz=="
    ]
  },
  "timestamp": "2026-07-21T10:02:00+08:00"
}
```

### 群@机器人消息（GROUP_AT_MESSAGE_CREATE）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_at_message_create.html

# 群@机器人消息

用户在群里@机器人发送消息时触发。这是机器人最常接收的事件。 content 字段已自动去除@机器人的前缀。 为确保消息可达，相同 msg\_id 可能重复推送，开发者需结合 msg\_seq 做去重。

## 事件

字段

值

事件名

GROUP\_AT\_MESSAGE\_CREATE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### 事件体

名称

类型

描述

id

string

消息 ID，可用于被动回复和撤回

author

[User](#schema-user)

发送者（member\_openid 有值）

content

string

消息文本内容（已去除@机器人的前缀）

group\_openid

string

群 OpenID

timestamp

string

消息发送时间，RFC3339 格式

message\_type

integer

消息内容类型（同 C2C\_MESSAGE\_CREATE）

message\_scene

[MessageScene](#schema-messagescene)

消息场景上下文

attachments

\[\][MessageAttachment](#schema-messageattachment)

消息附件

mentions

\[\][User](#schema-user)

消息中@的用户列表（不含@机器人自身）

ark\_data

[ARKData](#schema-arkdata)

结构化卡片消息数据

msg\_elements

\[\][MsgElement](#schema-msgelement)

消息元素列表

**User**

名称

类型

描述

id

string

用户唯一标识（OpenID 格式）

username

string

用户昵称

bot

boolean

是否为机器人

union\_openid

string

跨应用统一用户 OpenID（可能为空）

union\_user\_account

string

跨应用统一用户账号（可能为空）

user\_openid

string

用户 OpenID（单聊场景使用）

member\_openid

string

群成员 OpenID（群聊场景使用）

member\_role

string

群内角色。member=普通成员, admin=管理员, owner=群主

**MessageScene**

名称

类型

描述

source

string

场景来源。default=默认聊天窗口

ext

\[\]string

扩展数据列表，key=value 格式: msg\_idx=消息索引, 用于引用场景 ref\_msg\_idx=引用的消息索引 auth\_token=鉴权令牌

**MessageAttachment**

名称

类型

描述

url

string

附件下载 URL

filename

string

文件名

width

integer

图片宽度（像素），非图片附件无此字段

height

integer

图片高度（像素），非图片附件无此字段

size

integer

文件大小（字节）

content\_type

string

附件内容类型（MIME 类型）: voice=语音消息 image/jpeg=JPEG 图片 image/png=PNG 图片 image/gif=GIF 图片 video/mp4=MP4 视频 file=群文件

voice\_wav\_url

string

语音消息 SILK 等转换后的 WAV 文件 URL

asr\_refer\_text

string

语音消息 ASR 参考结果

**ARKData**

名称

类型

描述

prompt

string

卡片消息中的用户操作提示文本

ark\_type

string

卡片消息类型标识: tuwen = 图文 H5（如快手分享链接） feed = 图文卡片（群相册、频道帖子、分享卡片） miniapp = 小程序（微信小程序、QQ 小程序、哔哩哔哩等） map = 位置卡片 contact\_card = 好友名片 video\_share = 视频分享 music\_together = 一起听歌 picture = 图片

ark\_name

string

卡片消息类型的中文名称，如"图文 H5"、"小程序"、"图文卡片"

fields

object

卡片消息字段，常见键名: tag/tags=来源标签, title=标题, desc=描述, jump\_url=跳转链接, preview=预览图, source=来源名称, source\_logo=来源图标, tag\_icon=标签图标, nickname=昵称, avatar=头像, address=地址

**MsgElement**

名称

类型

描述

msg\_idx

string

消息元素在列表中的引用消息索引

author

[User](#schema-user)

该元素对应的消息发送者

message\_type

integer

消息内容类型: 0=普通文本, 3=结构化卡片, 101=并行消息, 102=聊天记录, 103=引用消息

content

string

消息正文内容

attachments

\[\][MessageAttachment](#schema-messageattachment)

该元素携带的附件

ark\_data

[ARKData](#schema-arkdata)

结构化卡片消息数据（message\_type=3 时有值）

msg\_elements

\[\][MsgElement](#schema-msgelement)

嵌套消息元素列表（递归结构）

### 事件示例

**示例1**

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "author": {
    "id": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "member_role": "member",
    "username": "小明",
    "bot": false
  },
  "content": " /今日天气 ",
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "message_type": 0,
  "timestamp": "2026-07-21T10:00:00+08:00",
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_xxxxxxxxxxxxxxx==",
      "auth_token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    ]
  }
}
```

**示例2**

```
{
  "id": "ROBOT1.0_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
  "author": {
    "id": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "member_openid": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "member_role": "member",
    "username": "小红",
    "bot": false
  },
  "content": " 看看这张风景照 ",
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "message_type": 0,
  "timestamp": "2026-07-21T10:05:00+08:00",
  "attachments": [
    {
      "content_type": "image/jpeg",
      "filename": "photo.jpg",
      "url": "https://multimedia.nt.qq.com.cn/download?appid=xxx&fileid=xxx&rkey=xxx&spec=0",
      "width": 1920,
      "height": 1080,
      "size": 256000
    }
  ],
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_yyyyyyyyyyyyyyy==",
      "auth_token=yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
    ]
  }
}
```

**示例3**

```
{
  "id": "ROBOT1.0_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
  "author": {
    "id": "D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1",
    "member_openid": "D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1",
    "member_role": "owner",
    "username": "小华",
    "bot": false
  },
  "content": " ",
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "message_type": 103,
  "timestamp": "2026-07-21T10:10:00+08:00",
  "msg_elements": [
    {
      "content": "=== 消息 1 ===\n[消息内容] 今天的学习计划已完成\n\n=== 消息 2 ===\n[消息内容] 很棒！继续保持，明天继续加油\n\n=== 消息 3 ===\n[消息内容] 好的，一起进步！"
    }
  ],
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_zzzzzzzzzzzzzzz==",
      "auth_token=zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
      "ref_msg_idx=TMP_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    ]
  }
}
```

### 群消息（全量模式）（GROUP_MESSAGE_CREATE）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_message_create.html

# 群消息（全量模式）

当机器人开启了"接收所有消息"功能后，群里的每一条消息（不限于@机器人）都会推送此事件。 各字段含义与 GROUP\_AT\_MESSAGE\_CREATE 完全一致。

## 事件

字段

值

事件名

GROUP\_MESSAGE\_CREATE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### 事件体

名称

类型

描述

id

string

消息 ID，可用于被动回复和撤回

author

[User](#schema-user)

发送者

content

string

消息文本内容（已去除@机器人的前缀）

group\_openid

string

群 OpenID

timestamp

string

消息发送时间，RFC3339 格式

message\_type

integer

消息内容类型

message\_scene

[MessageScene](#schema-messagescene)

消息场景上下文

attachments

\[\][MessageAttachment](#schema-messageattachment)

消息附件

mentions

\[\][User](#schema-user)

消息中@的用户列表

ark\_data

[ARKData](#schema-arkdata)

结构化卡片消息数据

msg\_elements

\[\][MsgElement](#schema-msgelement)

消息元素列表

**User**

名称

类型

描述

id

string

用户唯一标识（OpenID 格式）

username

string

用户昵称

bot

boolean

是否为机器人

union\_openid

string

跨应用统一用户 OpenID（可能为空）

union\_user\_account

string

跨应用统一用户账号（可能为空）

user\_openid

string

用户 OpenID（单聊场景使用）

member\_openid

string

群成员 OpenID（群聊场景使用）

member\_role

string

群内角色。member=普通成员, admin=管理员, owner=群主

**MessageScene**

名称

类型

描述

source

string

场景来源。default=默认聊天窗口

ext

\[\]string

扩展数据列表，key=value 格式: msg\_idx=消息索引, 用于引用场景 ref\_msg\_idx=引用的消息索引 auth\_token=鉴权令牌

**MessageAttachment**

名称

类型

描述

url

string

附件下载 URL

filename

string

文件名

width

integer

图片宽度（像素），非图片附件无此字段

height

integer

图片高度（像素），非图片附件无此字段

size

integer

文件大小（字节）

content\_type

string

附件内容类型（MIME 类型）: voice=语音消息 image/jpeg=JPEG 图片 image/png=PNG 图片 image/gif=GIF 图片 video/mp4=MP4 视频 file=群文件

voice\_wav\_url

string

语音消息 SILK 等转换后的 WAV 文件 URL

asr\_refer\_text

string

语音消息 ASR 参考结果

**ARKData**

名称

类型

描述

prompt

string

卡片消息中的用户操作提示文本

ark\_type

string

卡片消息类型标识: tuwen = 图文 H5（如快手分享链接） feed = 图文卡片（群相册、频道帖子、分享卡片） miniapp = 小程序（微信小程序、QQ 小程序、哔哩哔哩等） map = 位置卡片 contact\_card = 好友名片 video\_share = 视频分享 music\_together = 一起听歌 picture = 图片

ark\_name

string

卡片消息类型的中文名称，如"图文 H5"、"小程序"、"图文卡片"

fields

object

卡片消息字段，常见键名: tag/tags=来源标签, title=标题, desc=描述, jump\_url=跳转链接, preview=预览图, source=来源名称, source\_logo=来源图标, tag\_icon=标签图标, nickname=昵称, avatar=头像, address=地址

**MsgElement**

名称

类型

描述

msg\_idx

string

消息元素在列表中的引用消息索引

author

[User](#schema-user)

该元素对应的消息发送者

message\_type

integer

消息内容类型: 0=普通文本, 3=结构化卡片, 101=并行消息, 102=聊天记录, 103=引用消息

content

string

消息正文内容

attachments

\[\][MessageAttachment](#schema-messageattachment)

该元素携带的附件

ark\_data

[ARKData](#schema-arkdata)

结构化卡片消息数据（message\_type=3 时有值）

msg\_elements

\[\][MsgElement](#schema-msgelement)

嵌套消息元素列表（递归结构）

### 事件示例

**示例1**

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "author": {
    "id": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "member_role": "member",
    "username": "小明",
    "bot": false
  },
  "content": "大家早上好呀",
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "message_type": 0,
  "timestamp": "2026-07-21T08:00:00+08:00",
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_xxxxxxxxxxxxxxx==",
      "auth_token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    ]
  }
}
```

**示例2**

```
{
  "id": "ROBOT1.0_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
  "author": {
    "id": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "member_openid": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "member_role": "owner",
    "username": "小红",
    "bot": false
  },
  "content": "分享一张今天的风景照",
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "message_type": 0,
  "timestamp": "2026-07-21T09:30:00+08:00",
  "attachments": [
    {
      "content_type": "image/jpeg",
      "filename": "photo.jpg",
      "url": "https://multimedia.nt.qq.com.cn/download?appid=xxx&fileid=xxx&rkey=xxx&spec=0",
      "width": 1920,
      "height": 1080,
      "size": 256000
    }
  ],
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_yyyyyyyyyyyyyyy==",
      "auth_token=yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
    ]
  }
}
```

**示例3**

```
{
  "id": "ROBOT1.0_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
  "author": {
    "id": "D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1",
    "member_openid": "D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1",
    "member_role": "admin",
    "username": "小华",
    "bot": false
  },
  "content": " ",
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "message_type": 103,
  "timestamp": "2026-07-21T10:10:00+08:00",
  "msg_elements": [
    {
      "content": "=== 消息 1 ===\n[消息内容] 今天的学习计划已完成\n\n=== 消息 2 ===\n[消息内容] 很棒！继续保持，明天继续加油\n\n=== 消息 3 ===\n[消息内容] 好的，一起进步！"
    }
  ],
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_zzzzzzzzzzzzzzz==",
      "auth_token=zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
      "ref_msg_idx=TMP_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    ]
  }
}
```

### 互动事件（INTERACTION_CREATE）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/interaction_create.html

# 互动事件

用户与机器人的互动操作触发此事件，包括消息按钮点击、快捷菜单回调、消息反馈、清空会话、进出故事集、切换模型、用户/群授权等。 收到事件后需调用 PUT /interactions/{interaction\_id} 接口回应，否则客户端会一直 loading 直到超时。

仅 type=11（消息按钮）和 type=12（快捷菜单）需要调用 PUT /interactions/{interaction\_id} 回应；其他类型（消息反馈、清空会话、进出故事集、切换模型、授权等）无需回应。同一 interaction\_id 只能回应一次，超时后失效。

## 事件

字段

值

事件名

INTERACTION\_CREATE

Intent

INTERACTION (1<<26)

### 事件体

名称

类型

描述

id

string

事件 ID，用于被动消息发送和互动回调

type

integer

互动类型 11 - 消息按钮回调（INLINE\_KEYBOARD）：用户点击消息中的内联键盘按钮 12 - 单聊快捷菜单回调（CALLBACK\_COMMAND）：用户点击单聊场景下的自定义菜单 13 - 消息反馈（MESSAGE\_FEEDBACK）：用户对智能体消息进行点赞/点踩反馈 14 - 清空会话（CLEAR\_SESSION）：用户清空智能体会话历史 15 - 进出故事集（IN\_OUT\_STORY）：用户进入或退出故事集 16 - 切换模型（SWITCH\_MODEL）：用户切换智能体模型 18 - 用户授权（USER\_AUTHORIZE）：用户授权事件 19 - 群授权（GROUP\_AUTHORIZE）：群授权事件 20 - 群授权状态变更（GROUP\_AUTHORIZE\_STATUS）

scene

string

事件发生场景。c2c=单聊, group=群聊, guild=频道

chat\_type

integer

聊天场景。0=频道, 1=群聊, 2=单聊

timestamp

string

触发时间，RFC3339 格式

guild\_id

string

频道 OpenID（仅频道场景有值）

channel\_id

string

子频道 OpenID（仅频道场景有值）

user\_openid

string

用户 OpenID（仅单聊场景有值）

group\_openid

string

群 OpenID（仅群聊场景有值）

group\_member\_openid

string

群成员 OpenID（仅群聊场景有值）

data

[InteractionData](#schema-interactiondata)

互动数据

version

integer

版本号，默认 1

application\_id

string

机器人 AppID

**InteractionData**

名称

类型

描述

type

integer

互动数据类型，与外层 type 含义一致。11=消息按钮点击, 12=快捷菜单点击, 13=消息反馈点击, 14=清空会话点击, 15=故事集点击, 16=切换模型点击

resolved

[InteractionResolved](#schema-interactionresolved)

解析后的互动数据

**InteractionResolved**

名称

类型

描述

button\_data

string

按钮的 data 字段值（发送消息按钮时设置）；消息反馈场景下为回调数据

button\_id

string

按钮的 id 字段值（发送消息按钮时设置）

user\_id

string

操作用户 ID（仅频道场景有值）

feature\_id

string

功能 ID（仅快捷菜单有值，管理端设置）

message\_id

string

操作的消息 ID（频道场景为消息 OpenID；消息反馈场景为机器人消息 ID）

feedback\_opt

string

反馈选项（仅 type=13 消息反馈）。LIKE=点赞, UNLIKE=点踩

checked

integer

反馈选项是否选中（仅 type=13 消息反馈）

action

string

操作类型（type=15 故事集：ENTER\_STORY=进入, QUIT\_STORY=退出；type=16 切换模型：对应操作动作）

message\_scene

[InteractionMessageScene](#schema-interactionmessagescene)

消息场景信息（仅 type=13 消息反馈）

authorize\_data

[AuthorizeData](#schema-authorizedata)

授权数据（仅 type=18/19 用户/群授权事件）

**InteractionMessageScene**

名称

类型

描述

ext

\[\]string

扩展信息键值对列表，如 "disable\_net\_search=1" 表示关闭联网搜索

**AuthorizeData**

名称

类型

描述

opt\_scene

string

授权操作场景。setting=资料页设置, dialog=弹窗授权

scope

string

授权范围。c2c\_push=C2C 主动消息推送, group\_push=群主动消息推送

### 事件示例

**示例1**

```
{
  "application_id": "1904842048",
  "chat_type": 2,
  "data": {
    "resolved": {
      "button_data": "confirm:once",
      "button_id": "allow-once"
    },
    "type": 11
  },
  "id": "1b13d569-4610-4ab9-bc51-feecc5def6d4",
  "scene": "c2c",
  "timestamp": "2026-07-20T21:53:54+08:00",
  "type": 11,
  "user_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "version": 1
}
```

**示例2**

```
{
  "application_id": "101984245",
  "chat_type": 1,
  "data": {
    "resolved": {
      "button_data": "eyJjb21tYW5kIjogInNhbXBsZSJ9"
    },
    "type": 11
  },
  "group_member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "id": "06915133-7aef-46ed-94f7-c50939e285ae",
  "scene": "group",
  "timestamp": "2026-07-20T21:53:54+08:00",
  "type": 11,
  "version": 1
}
```

**示例3**

```
{
  "application_id": "102057050",
  "data": {
    "resolved": {
      "authorize_data": {
        "opt_scene": "setting",
        "scope": "c2c_push"
      }
    }
  },
  "id": "c30c003e-9454-4450-8e5e-665267c088c4",
  "scene": "c2c",
  "timestamp": "2026-07-20T21:54:38+08:00",
  "type": 18,
  "user_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "version": 1
}
```

### 用户添加好友（FRIEND_ADD）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/friend_add.html

# 用户添加好友

通过传 scene\_param 中的 callback\_data 可区分不同来源的添加好友场景。

## 事件

字段

值

事件名

FRIEND\_ADD

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### 事件体

名称

类型

描述

timestamp

integer

添加时间戳（Unix 秒）

openid

string

用户 OpenID

scene

integer

加好友场景值。1000=缺省默认, 1001=网络搜索（全部tab）, 1002=网络搜索（机器人tab）, 1003=群场景, 1004=空间场景, 2001=站内分享资料页, 2002=站外分享资料页, 2003=开发者生成的分享链接（站内）, 2004=开发者生成的分享链接（站外）

scene\_param

string

开发者自定义的回调数据（callback\_data），用于区分不同来源

author

[FriendAuthor](#schema-friendauthor)

用户信息

short\_code

string

机器人分享链接的短链code

**FriendAuthor**

名称

类型

描述

union\_openid

string

用户统一 OpenID（跨应用标识）

### 事件示例

**用户添加好友（网络搜索场景）**

```
{
  "openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570523,
  "scene": 1001,
  "scene_param": "",
  "author": {
    "union_openid": "DB85A74E07BA08B5B44CD9ED332FCBD2"
  }
}
```

**用户添加好友（开发者分享链接）**

```
{
  "openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570600,
  "scene": 2003,
  "scene_param": "callback_abc123",
  "author": {
    "union_openid": "DB85A74E07BA08B5B44CD9ED332FCBD2"
  }
}
```

### 机器人加入群聊（GROUP_ADD_ROBOT）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_add_robot.html

# 机器人加入群聊

机器人被添加到群聊时触发。

## 事件

字段

值

事件名

GROUP\_ADD\_ROBOT

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### 事件体

名称

类型

描述

timestamp

integer

加入时间戳（Unix 秒）

group\_openid

string

群 OpenID

op\_member\_openid

string

操作添加机器人进群的群成员 OpenID

### 事件示例

**机器人加入群聊**

```
{
  "group_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "op_member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570534
}
```

### 单聊消息接收开启（C2C_MSG_RECEIVE）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/c2c_msg_receive.html

# 单聊消息接收开启

用户在机器人资料卡手动开启"主动消息"推送开关时触发。

用户在机器人资料卡手动开启主动消息推送开关时触发。开启后机器人可向该用户发送主动消息。

## 事件

字段

值

事件名

C2C\_MSG\_RECEIVE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### 事件体

名称

类型

描述

timestamp

integer

操作时间戳（Unix 秒）

openid

string

用户 OpenID

### 事件示例

**C2C消息接收开启**

```
{
  "openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570617
}
```

### 群聊消息接收开启（GROUP_MSG_RECEIVE）

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_msg_receive.html

# 群聊消息接收开启

群管理员在机器人资料页操作开启通知时触发。

## 事件

字段

值

事件名

GROUP\_MSG\_RECEIVE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### 事件体

名称

类型

描述

timestamp

integer

操作时间戳（Unix 秒）

group\_openid

string

群 OpenID

op\_member\_openid

string

操作群成员 OpenID

### 事件示例

**群消息接收开启**

```
{
  "timestamp": 1784276800,
  "group_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "op_member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"
}
```

## 7. 变更记录

### 变更记录

> Source: https://bot.q.qq.com/wiki/develop/api-v2/changelog.html

# 变更记录

## 20260916

### 优化

-   **生成分享链接（`/v2/generate_url_link`）** 修正请求和响应字段说明。
-   **消息事件（群 @ 消息、群消息、单聊消息）**：`ark_type` 枚举新增 `picture`（图片）取值说明。

## 20260903

### 新增

-   **群管理接口**
    -   新增**群成员管理**相关接口：
        -   获取群成员列表
        -   获取群成员信息
        -   群成员批量移除
        -   群黑名单查询
        -   群黑名单操作

### 优化

-   修改了部分接口描述。

## 20260812

### 新增

-   **自定义菜单**
    -   新增查询、修改全局自定义菜单接口。
-   **指令面板**
    -   新增指令面板管理接口，支持查询列表、创建、查询详情、修改、删除及修改关联对象。

## 20260810

### 优化

-   **接口调用域名统一**：所有接口调用域名统一为 `api.bot.qq.com`。

### 新增

-   **群消息 / C2C 消息**
    -   发送 Markdown 消息：新增可选参数 `force_verify_image_resource`。开启后，当图片资源转存失败时，将中断消息发送并返回失败（默认关闭，保持原有行为）。
-   **群管理接口**
    -   新增**群禁言管理**相关接口：
        -   查询用户禁言状态
        -   设置用户禁言
    -   新增**入群申请审批**相关接口：
        -   拉取入群申请列表
        -   审批入群请求
    -   新增**入群自动审批策略**相关接口。
-   **事件**
    -   新增用户入群申请事件。

