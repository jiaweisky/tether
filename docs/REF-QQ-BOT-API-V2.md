# QQ Bot api-v2 Reference (Local Mirror)

> **Local, curated mirror**: This file is a locally curated mirror of the official **api-v2** documentation for the QQ Bot Open Platform, intended for offline reference only.
>
> - **Unofficial**: This file is not an official Tencent/QQ release. If there are discrepancies, refer to the official documentation.
> - **Official documentation root (canonical root)**: https://bot.q.qq.com/wiki/develop/api-v2/
> - **Crawl date**: 2026-10-16
> - **English edition**: prose, headings, table text, and example content have been translated from the original Chinese; code syntax, schemas, identifiers, and URLs are preserved. If there is any discrepancy, the official Chinese documentation is authoritative.
> - The legacy "channel / guild" management cluster is intentionally **excluded**; only the "direct chat / group / protocol / related" content collections are mirrored.

---

## 1. Getting Started Guide

### Onboarding

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/getting-started.html

# Onboarding

## Account Registration

QQ bot: A bot can be added to `group chats/channels` for interactive conversations, and QQ users can also `chat directly` with the bot.

Registration URL: [QQ Open Platform website (opens new window)](https://q.qq.com/#/)

## Integration Credentials

After registering and creating a bot, you obtain the development bot integration credentials `AppID` and `AppSecret`

Name

Description

Remarks

AppID

Bot ID

Required

AppSecret

Bot secret

Key used for request signing

Token-based authentication is deprecated; use the more secure `Access Token` authentication method.

If you encounter any problems during development, you can contact the QQ Bot feedback assistant.

## SDK DEMO

To quickly build a bot server, refer to the following SDK DEMOs. (The SDKs are provided for integration reference only; for detailed capabilities, refer to the official documentation.)

Go: [botgo (opens new window)](https://github.com/tencent-connect/botgo)

Python: [botpy (opens new window)](https://github.com/tencent-connect/botpy)

NodeJs: [bot-node-sdk (opens new window)](https://github.com/tencent-connect/bot-node-sdk)

### Obtain an Access Credential

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html

# Obtain an Access Credential

The QQ Bot Open Platform provides the following types of access credentials:

Credential type

Requires user authorization

Description

access\_token

No

Credential used when calling APIs as the bot identity; the readable and writable data scope is determined by the bot's permission scope. Suitable for scenarios such as the bot sending proactive messages and managing group chats.

## Obtain an access\_token

### Request

Basic Information

HTTP URL

https://api.bot.qq.com/app/getAppAccessToken

HTTP Method

POST

### Request Parameters

**Attribute**

**Type**

**Required**

**Description**

appId

string

Yes

Obtained from the Open Platform admin console.

clientSecret

string

Yes

Obtained from the Open Platform admin console.

### Response Parameters

**Success Response**

**Attribute**

**Type**

**Description**

access\_token

string

The obtained credential.

expires\_in

number

Credential validity period, in seconds. Currently a value within 7200 seconds.

**Failure Response**

**Attribute**

**Type**

**Description**

code

number

Error code; see "Business Error Codes" below for values.

message

string

Error message, for manual troubleshooting only; the content may change at any time.

Note

Business errors for this API are returned via the `code` field in the response body. Even if the call fails, the HTTP status code is still `200`. Prefer using `code` to determine whether the request succeeded rather than relying solely on the HTTP status code; also do not use `message` to determine the error type. See "Error Return Codes" below for details.

### Error Codes

#### Business Error Codes

**Error Code**

**Error Message**

**Troubleshooting Guide**

100001

Too many requests

Too many requests; reduce the call frequency and try again

100007

appid invalid

The AppID is invalid, or the bot status is abnormal (banned or deleted). Check whether the AppID is correct and the bot status.

100016

invalid appid or secret

The AppID or ClientSecret is incorrect. Check whether the passed appId and clientSecret match those in the Open Platform admin console.

10004

Bot does not exist

No bot exists for the AppID; confirm that the AppID is correct.

### Call Example

```
curl --location 'https://api.bot.qq.com/app/getAppAccessToken' \
--header 'Content-Type: application/json' \
--data '{
  "appId": "APPID",
  "clientSecret": "CLIENTSECRET"
}'
```

### Response Example

**Success**

```
{
  "access_token": "ACCESS_TOKEN",
  "expires_in": "7200"
}
```

**Failure**

```
{
  "code": 100007,
  "message": "appid invalid"
}
```

## Credential Validity Period and Refresh

Currently the `access_token` lifetime defaults to `7200` seconds (2 hours). Developers need to refresh the `access_token` themselves after it expires to ensure permissions remain valid throughout the call chain.

-   Each request does not refresh a new `access_token`; repeated retrieval within the validity period returns the same value
-   Within `60` seconds before the previous `access_token` expires, retrieving `access_token` returns a new `access_token`; the old `access_token` remains valid during these `60` seconds
-   Developers are advised to implement scheduled credential refresh logic on the server side to prevent expiration

## Using an Access Credential

Each time an OpenAPI endpoint is called, `access_token` must be included in the HTTP request header for call permission verification.

**Request Header**:

Name

Type

Required

Description

Authorization

string

Yes

Format value: `QQBot ACCESS_TOKEN`

**Example**:

```
curl --location 'https://api.bot.qq.com/users/@me' \
--header 'Authorization: QQBot ACCESS_TOKEN'
```

Note

For security reasons, do not use access credentials in the application frontend. Initiate API requests from the application server.

### API Call Guide

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html

# API Call Guide

The QQ Bot Open Platform provides OpenAPI endpoints based on the HTTPS protocol. Developers can use these endpoints to implement features such as sending and receiving messages, group chat management, and channel management.

## Calling Methods

### Unified Request URL

```
https://api.bot.qq.com
```

### Authentication Method

When calling APIs, place access\_token in the request header:

```
Authorization: QQBot {ACCESS_TOKEN}
```

### Request Example

Take sending a direct chat message as an example:

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

### Response Structure

When an API call succeeds, the response body returns the business data directly; when the call fails, the response body contains error information such as `err_code` and `message`:

-   **err\_code**: Error code. 0 on success
-   **message**: Error message
-   **trace\_id**: Trace ID, used for troubleshooting

**Success Response Example**:

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "timestamp": "2026-07-21T10:30:00+08:00"
}
```

**Failure Response Example**:

```
{
  "err_code": 40034005,
  "message": "Reply message msg_id has expired",
  "trace_id": "4a8a61565b909f199b1ec169fdd6f49e"
}
```

Note

Do not use `message` to determine whether a request failed; `message` may change at any time. Use `err_code` to determine whether a request failed.

## Unique Identity Mechanism

Different `bot(AppID)`s obtain different user `openid`s, group `openid`s, and channel `openid`s. If there is a need to associate user identities across businesses, once cross-`AppID` binding is provided in the future, a mechanism similar to `unionid` can be used to unify identities.

Example

-   In direct chat scenarios, different `bot`s obtain different unique user identifiers `openid`, called `user_openid`
-   In group chat scenarios, different `bot`s obtain different unique group identifiers `openid`, called `group_openid`
-   In group chat scenarios, a `bot` obtains the unique identifier of a user within the group, called `member_openid`

## End-to-End Tracing

The platform's trace `TraceID` can be obtained in two ways:

-   **HTTP response header**: the `X-Tps-trace-ID` field
-   **Response body**: the `trace_id` field in the response body

If developers encounter issues they cannot troubleshoot themselves and need platform assistance, they can extract this ID and submit it to the platform to facilitate log lookup.

## OpenAPI Error Codes

Error codes consist of two parts:

-   HTTP status code
-   `err_code` in the JSON returned in the HTTP body

### HTTP Status Codes

Value

Meaning

200

Success

204

Success, but no body; generally used for delete operations

201, 202

Asynchronous operation succeeded; although it is successful, it returns an error body and requires special handling

401

Authentication failed

404

API not found

405

HTTP method not allowed

429

Rate limited

500

Processing failed

504

Processing failed

### Common Error Codes

> The following are common error codes applicable to all APIs. For error codes specific to each API, refer to the "Error Codes" section in the corresponding API documentation.

Value

Meaning

10001

UnknownAccount Account abnormal

10003

UnknownChannel Sub-channel abnormal

10004

UnknownGuild Channel abnormal

11281

ErrorCheckAdminFailed Failed to check whether the user is an administrator; system error, usually resolves after one retry; retry at most once

11282

ErrorCheckAdminNotPass Administrator check failed; this API requires administrator permission, but the user did not grant this permission when adding the bot. This is a logic error; prompt the user to authorize.

11251

ErrorWrongAppid The appid in the parameters is wrong; the token filled in by the developer is wrong, and the appid cannot be recognized

11252

ErrorCheckAppPrivilegeFailed Failed to check application permissions; system error, usually resolves after one retry; retry at most once

11253

ErrorCheckAppPrivilegeNotPass Application permission check failed; this bot application has not been granted permission to call this API and must apply to the platform

11254

ErrorInterfaceForbidden The application API is banned; although this bot has been granted permission for this API, it has been banned

11261

ErrorWrongAppid appid is missing from the parameters; same as 11251

11262

ErrorCheckRobot This API does not support being called with a bot Bot Token

11263

ErrorCheckGuildAuth Failed to check channel permissions; system error, usually resolves after one retry; retry at most once

11264

ErrorGuildAuthNotPass Guild permission check failed; the administrator did not grant this API permission when adding the bot. This is a logic error; you can prompt the user to authorize. If authorization has already been granted, check whether the passed guild id is correct.

11265

ErrorRobotHasBaned The bot has been banned

11241

ErrorWrongToken token is missing from the parameters

11242

ErrorCheckTokenFailed Failed to verify token; system error, usually resolves after one retry; retry at most once

11243

ErrorCheckTokenNotPass Token verification failed; the token filled in by the user is wrong and the developer needs to check it

11273

ErrorCheckUserAuth Failed to check user permissions; this API does not support being called with a Bearer Token

11274

ErrorUserAuthNotPass User permission check failed; the user did not grant this API permission during OAuth authorization. You can prompt the user to authorize again.

11275

ErrorWrongAppid No appid; same as 11251

11301

ErrorGetHTTPHeader Invalid HTTP header

11302

ErrorGetHeaderUIN Invalid HTTP header

11303

ErrorGetNick Failed to get nickname

11304

ErrorGetAvatar Failed to get avatar

11305

ErrorGetGuildID Failed to get channel ID

11306

ErrorGetGuildInfo Failed to get channel information

12001

ReplaceIDFailed Failed to replace id

12002

RequestInvalid Invalid request body

12003

ResponseInvalid Invalid response packet

20028

ChannelHitWriteRateLimit Sub-channel message rate limit triggered

50006

CannotSendEmptyMessage Message is empty

50035

InvalidFormBody Abnormal form-data content

50037

Messages with markdown only support markdown or keyboard combinations

50038

Not the same channel and sub-channel

50039

Failed to get message

50040

Message template type error

50041

markdown contains empty values

50042

markdown list reached the maximum length

50043

guild\_id conversion failed

50045

Cannot reply to messages generated by the bot itself

50046

Message does not @ the bot

50047

Message not generated by a bot, or a message @ing the bot

50048

message id cannot be empty

50049

Only messages containing keyboard elements can be modified

50050

When modifying a message, the keyboard element cannot be empty

50051

Only messages sent by the bot itself can be modified

50053

Error modifying message

50054

markdown template parameter error

50055

Invalid markdown content

50056

Sending markdown content is not allowed

50057

The markdown parameter supports either native syntax or a template, not both

301000~301099

Sub-channel permission error

301000

Parameter error

301001

Error querying channel information

301002

Error querying sub-channel permissions

301003

Error modifying sub-channel permissions

301004

The number of people associated with the private sub-channel has reached the limit

301005

Failed to call RPC service

301006

Non-group members do not have query permission

301007

Parameters exceed the quantity limit

302000

Parameter error

302001

Error querying channel information

302002

Failed to query schedule list

302003

Failed to query schedule

302004

Failed to modify schedule

302005

Failed to delete schedule

302006

Failed to create schedule

302007

Failed to get creator information

302008

Sub-channel ID cannot be empty

302009

Channel system error; please contact customer service

302010

No permission to modify schedule

302011

The schedule event has been deleted

302012

You can only create 10 schedules per day; come back tomorrow!

302013

Schedule creation triggered a security block

302014

The schedule duration exceeds 7 days; please select again

302015

The start time cannot be earlier than the current time

302016

The end time cannot be earlier than the start time

302017

The Schedule object is empty

302018

Parameter type conversion failed

302019

Failed to call downstream; please contact customer service

302020

Schedule content violates rules; account violates rules

302021

The number of new events in the channel for the day has reached the limit

302022

Cannot bind a sub-channel that does not belong to the current channel

302023

Cannot bind a schedule sub-channel when redirecting at start time

302024

The bound sub-channel does not exist

304003

URL\_NOT\_ALLOWED url is not registered

304004

ARK\_NOT\_ALLOWED No permission to send ARK messages

304005

EMBED\_LIMIT embed length exceeds limit

304006

SERVER\_CONFIG backend configuration error

304007

GET\_GUILD error querying channel

304008

GET\_BOT error querying bot

304009

GET\_CHENNAL error querying sub-channel

304010

CHANGE\_IMAGE\_URL image transfer error

304011

NO\_TEMPLATE template does not exist

304012

GET\_TEMPLATE error retrieving template

304014

TEMPLATE\_PRIVILEGE no template permission

304016

SEND\_ERROR error sending message

304017

UPLOAD\_IMAGE image upload error

304018

SESSION\_NOT\_EXIST bot is not connected to gateway

304019

AT\_EVERYONE\_TIMES @all members count limit exceeded

304020

FILE\_SIZE file size exceeds limit

304021

GET\_FILE error downloading file

304022

PUSH\_TIME push message time limit

304023

PUSH\_MSG\_ASYNC\_OK push message async call succeeded, awaiting manual review

304024

REPLY\_MSG\_ASYNC\_OK reply message async call succeeded, awaiting manual review

304025

BEAT message was blocked by security

304026

MSG\_ID reply message id error

304027

MSG\_EXPIRE replied message expired

304028

MSG\_PROTECT replying to a message that does not @ the current user is not allowed

304029

CORPUS\_ERROR error calling corpus service

304030

CORPUS\_NOT\_MATCH corpus mismatch

304031

Direct message is closed

304032

Direct message does not exist

304033

Error retrieving direct message

304034

Not a member of the direct message

304035

Push message exceeds the sub-channel count limit

304036

No permission for markdown template

304037

No permission to send message button component

304038

Message button component does not exist

304039

Message button component parsing error

304040

Message button component message content error

304044

Error retrieving message settings

304045

Rate limit on the number of proactive messages in a sub-channel

304046

Proactive messages are not allowed in this sub-channel

304047

Proactive message push exceeds the limit of sub-channels

304048

Proactive messages are not allowed in this channel

304049

Rate limit on the number of proactive direct messages

304050

Rate limit on the total number of proactive direct messages

304051

Error constructing message settings guide request

304052

Sending message settings guide exceeded rate limit

306001

param invalid invalid parameters for recalling message

306002

msgid error message id error

306003

fail to get message error getting message (retryable)

306004

no permission to delete message no permission to recall this message

306005

retract message error failed to recall message (retryable)

306006

fail to get channel failed to get sub-channel (retryable)

501000~501999

Announcement error

501001

Parameter validation failed

501002

Failed to create sub-channel announcement (retryable)

501003

Failed to delete sub-channel announcement (retryable)

501004

Failed to get channel information (retryable)

501005

MessageID error

501006

Failed to create channel global announcement (retryable)

501007

Failed to delete channel global announcement (retryable)

501008

MessageID does not exist

501009

MessageID parsing failed

501010

This message is not a message within a sub-channel

501011

Failed to create featured message (retryable)

501012

Failed to delete featured message (retryable)

501013

Featured messages exceed the maximum count

501014

Blocked by security

501015

This message cannot be set

501016

Channel announcement sub-channel recommendations exceed the maximum count

501017

Not a channel owner or administrator

501018

Invalid recommended sub-channel ID

501019

Announcement type error

501020

Failed to create recommended sub-channel type channel announcement

502000~502099

Mute-related error

502001

Invalid channel id

502002

Channel id is empty

502003

Invalid user id

502004

User id is empty

502005

Invalid timestamp

502006

Timestamp is invalid

502007

Parameter conversion error

502008

rpc call failed

502009

Blocked by security

502010

Request header error

503001

Invalid channel id

503002

Channel id is empty

503003

Failed to get sub-channel information

503004

Exceeded the rate limit for publishing posts

503005

Post title is empty

503006

Post content is empty

503007

Post ID is empty

503008

Failed to get X-Uin

503009

Post ID is invalid or illegal

503010

Failed to get TinyID via Uin

503011

The timestamp in the post ID is invalid or illegal

503012

Post does not exist or has been deleted

503013

Internal server error

503014

Failed to parse post JSON content

503015

Failed to convert post content

503016

Number of links exceeds limit

503017

Character count exceeds limit

503018

Number of images exceeds limit

503019

Number of videos exceeds limit

503020

Title length exceeds limit

504000~504999

Message rate-related error

504001

Invalid request parameter error

504002

Failed to get HTTP header

504003

Error getting BOT UIN

504004

Error getting message rate settings

610000-619999

Channel permission error

610001

Failed to get channel ID

610002

Failed to get HTTP header

610003

Failed to get bot number

610004

Failed to get bot role

610005

Internal error getting bot role

610006

Failed to fetch bot permission list

610007

Bot is not in the channel

610008

Invalid parameter

610009

Failed to get API endpoint details

610010

API endpoint already authorized

610011

Failed to get bot information

610012

Rate limiting failed

610013

Rate limited

610014

Failed to send api authorization link

620001-629999

Emoji reaction error

620001

Invalid parameter for emoji reaction

620002

The maximum number of emoji reaction types has been reached

620003

This emoji reaction has already been set

620004

This emoji reaction has not been set

620005

No permission to set emoji reaction

620006

Operation rate limited

620007

Emoji reaction operation failed, please retry

630001-639999

Interaction callback data update

630001

Invalid parameter for interaction callback data update

630002

Failed to get AppID for interaction callback data update

630003

AppID mismatch for interaction callback data

630004

Internal storage error for interaction callback data update

630005

Internal storage read error for interaction callback data update

630006

Failed to read AppID from request for interaction callback data update

630007

Interaction callback data is too large

1000000~2999999

Error sending message

1100100

Security block: message rate-limited

1100101

Security block: content involves sensitive material, please modify and resubmit

1100102

Security block: sorry, you have not yet obtained eligibility to try the new feature

1100103

Blocked by security

1100104

Security block: this group is no longer valid or no longer exists

1100300

Internal system error

1100301

Caller is not a group member

1100302

Failed to get specified channel name

1100303

Non-administrators are not allowed to send messages in the homepage channel

1100304

@ count authentication failed

1100305

TinyId to Uin conversion failed

1100306

Not a member of the private channel

1100307

Non-whitelisted application sub-channel

1100308

Rate limit triggered within the channel

1100499

Other error

3000000~3999999

Error editing message

3300006

Blocked by security

### Common Data Structures

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html

# Common Data Structures

`payload` refers to the data transmitted over a `webhook` or `websocket` connection. The uplink and downlink messages of the gateway use the same structure, as follows:

```
{
  "id":"event_id",
  "op": 0,
  "d": {},
  "s": 42,
  "t": "GATEWAY_EVENT_NAME"
}
```

Field

Description

id

Event id

op

Refers to the opcode; see connection maintenance

s

Every downlink message has a sequence number that identifies the uniqueness of the message. When the client sends a heartbeat, it needs to carry the latest s received by the client.

t

Represents the event type. Mainly used when op is 0 Dispatch.

d

Represents the event content. The content format differs for each event type, so please identify it carefully. Mainly used when op is 0 Dispatch.

## OpCode Meaning

The list of all `opcode` values is as follows:

**CODE**

**Name**

**Access Method**

**Client Behavior**

**Description**

0

Dispatch

webhook/websocket

Receive

Server pushes messages

1

Heartbeat

websocket

Send/Receive

Client or server sends heartbeat

2

Identify

websocket

Send

Client sends authentication

6

Resume

websocket

Send

Client resumes connection

7

Reconnect

websocket

Receive

Server notifies client to reconnect

9

Invalid Session

websocket

Receive

When identify or resume is used, if any parameter is incorrect, the server returns this message

10

Hello

websocket

Receive

The first message sent by the gateway after the client establishes a ws connection with the gateway

11

Heartbeat ACK

websocket

Receive/Reply

Received after a heartbeat is sent successfully

12

HTTP Callback ACK

webhook

Reply

Used only for the response packet in http callback mode, indicating that the bot has received the data pushed by the platform

13

Callback address verification

webhook

Receive

The Open Platform verifies the bot server

The meanings of client behaviors are as follows:

-   `Receive` The client receives a message `push`ed by the server
-   `Send` The client sends a message
-   `Reply` The response packet after the client receives a message sent by the server (HTTP callback mode)

## Event Subscription Intents

The `intents` of an event is a bitmask, where each bit represents a different event. If you need to receive a certain type of event, set that bit to `1`.

Each `intents` bit represents a type of event, which can be distinguished by the value of the `t` field in the data transmitted over `websocket`.

The relationship between events and bit shifts is as follows:

```
GUILDS (1 << 0)
  - GUILD_CREATE           // When the bot joins a new guild
  - GUILD_UPDATE           // When guild information changes
  - GUILD_DELETE           // When the bot leaves a guild
  - CHANNEL_CREATE         // When a channel is created
  - CHANNEL_UPDATE         // When a channel is updated
  - CHANNEL_DELETE         // When a channel is deleted

GUILD_MEMBERS (1 << 1)
  - GUILD_MEMBER_ADD       // When a member joins
  - GUILD_MEMBER_UPDATE    // When member information changes
  - GUILD_MEMBER_REMOVE    // When a member is removed

GUILD_MESSAGES (1 << 9)    // Message events; only *private domain* bots can set this intents.
  - MESSAGE_CREATE         // Message send event, representing all messages in the channel, not just messages that @ the bot. Content is the same as AT_MESSAGE_CREATE
  - MESSAGE_DELETE         // Message delete (recall) event

GUILD_MESSAGE_REACTIONS (1 << 10)
  - MESSAGE_REACTION_ADD    // Add an emoji reaction to a message
  - MESSAGE_REACTION_REMOVE // Remove an emoji reaction from a message

DIRECT_MESSAGE (1 << 12)
  - DIRECT_MESSAGE_CREATE   // When a direct message sent by a user to the bot is received
  - DIRECT_MESSAGE_DELETE   // Message delete (recall) event

GROUP_AND_C2C_EVENT (1 << 25)
  - C2C_MESSAGE_CREATE      // When a user sends a direct chat message to the bot
  - FRIEND_ADD              // User adds and uses the bot
  - FRIEND_DEL              // User removes the bot
  - C2C_MSG_REJECT          // User manually turns off "proactive message" push on the bot profile card
  - C2C_MSG_RECEIVE         // User manually turns on the "proactive message" push switch on the bot profile card
  - GROUP_AT_MESSAGE_CREATE // Message received when a user @s the bot in a group
  - GROUP_ADD_ROBOT         // Bot is added to a group chat
  - GROUP_DEL_ROBOT         // Bot is removed from a group chat
  - GROUP_MSG_REJECT        // Group administrator manually turns off notifications on the bot profile page
  - GROUP_MSG_RECEIVE       // Group administrator manually turns on notifications on the bot profile page

INTERACTION (1 << 26)
  - INTERACTION_CREATE     // When an interaction event is created

MESSAGE_AUDIT (1 << 27)
  - MESSAGE_AUDIT_PASS     // Message audit passed
  - MESSAGE_AUDIT_REJECT   // Message audit failed

FORUMS_EVENT (1 << 28)  // Forum event; only *private-domain* bots can set this intents.
  - FORUM_THREAD_CREATE     // When a user creates a thread
  - FORUM_THREAD_UPDATE     // When a user updates a thread
  - FORUM_THREAD_DELETE     // When a user deletes a thread
  - FORUM_POST_CREATE       // When a user creates a post
  - FORUM_POST_DELETE       // When a user deletes a post
  - FORUM_REPLY_CREATE      // When a user replies to a comment
  - FORUM_REPLY_DELETE      // When a user replies to a comment
  - FORUM_PUBLISH_AUDIT_RESULT      // When a user's post passes audit

AUDIO_ACTION (1 << 29)
  - AUDIO_START             // When audio starts playing
  - AUDIO_FINISH            // When audio finishes playing
  - AUDIO_ON_MIC            // When going on mic
  - AUDIO_OFF_MIC           // When going off mic

PUBLIC_GUILD_MESSAGES (1 << 30) // Message event; this is a public-domain message event
  - AT_MESSAGE_CREATE       // When a message @mentioning the bot is received
  - PUBLIC_MESSAGE_DELETE   // When a channel message is deleted
```

### Example

If a developer needs to receive messages in which users at-mention the bot, `PUBLIC_GUILD_MESSAGES` must be enabled in `intents`. First calculate the value of `1 << 30`, then perform a bitwise OR with `0` to obtain the final `intents` to pass.

If multiple event types need to be received, perform a bitwise OR on the multiple results. For example, `0|1<<30|1<<1` means subscribing to both the `PUBLIC_GUILD_MESSAGES` and `GUILD_MEMBERS` event types.

### Permissions

Event type subscriptions are subject to permission control. Apart from `GUILDS`, `PUBLIC_GUILD_MESSAGES`, and `GUILD_MEMBERS`, which are basic events that are subscribed to by default, all other special events require an application before use. If `intents` without permission are passed during authentication, `websocket` returns an error and closes the connection directly. Developers should keep the scope of event subscriptions within what they actually need.

If permission for a special event type you have is revoked, no error occurs on the current connection, but the corresponding event type will no longer be received. On reconnection, an error occurs. Therefore, if a developer's event type permission is revoked, adjust the event listening code promptly to avoid being unable to connect due to the error.

### WebSocket Method

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/websocket.html

# WebSocket Method

## Connecting to the Gateway

First, call the [Get General WSS Access Point](/wiki/develop/api-v2/openapi/wss/url_get.html) or [Get Sharded WSS Access Point](/wiki/develop/api-v2/openapi/wss/shard_url_get.html) API to obtain the gateway address.

You will get an address similar to the following:

```
wss://api.bot.qq.com/websocket/
```

Then establish a persistent `websocket` connection. Once the connection succeeds, an OpCode 10 Hello message is returned. Its main content is the heartbeat interval in milliseconds, as follows:

```
{
  "op": 10,
  "d": {
    "heartbeat_interval": 45000
  }
}
```

## Login Authentication to Obtain a Session

After the persistent `websocket` connection is established, login authentication is required. Once authentication succeeds, a session ID is obtained; only after a successful login does the QQ backend deliver event notifications.

Send an OpCode 2 Identify message with the following `payload`:

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

**Field**

**Description**

token

Format: "QQBot {AccessToken}"

intents

The events to receive on this connection. For details, see [Event Subscription Intents](/wiki/develop/api-v2/dev-prepare/event-emit/payload.html#%E4%BA%8B%E4%BB%B6%E8%AE%A2%E9%98%85-intents)

shard

To enable load balancing when receiving events, QQ provides sharding logic: event notifications fall on different shards. This parameter is an array with two elements. For example, `[0,4]` means the connection is divided into four shards and the current connection is shard 0; the business should subsequently establish connections with `shard` set to `[1,4]`, `[2,4]`, and `[3,4]` to receive all events. For more details, see [Shard mechanism](#%E5%88%86%E7%89%87%E8%BF%9E%E6%8E%A5-loadbalance). If sharding is not needed, use `[0, 1]`.

properties

Currently has no practical effect; fill it in according to your own situation or leave it empty.

After successful authentication, the QQ backend delivers a Ready Event with the following `payload`:

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
      "username": "Group Pro Test Bot",
      "bot": true
    },
    "shard": [0, 0]
  }
}
```

## Sending Heartbeat Ack

After successful authentication, heartbeats must be sent periodically. d is the s of the latest message received by the client; on the first connection, pass null for d. The `payload` is as follows:

```
{
  "op": 1,
  "d": 251
}
```

After a heartbeat is sent successfully, an OpCode 11 Heartbeat ACK message is received with the following `payload`:

```
{
  "op": 11
}
```

## Resuming the Login Session

Many reasons can cause the persistent `websocket` connection to disconnect. Reconnecting shortly after a disconnect re-delivers events missed in between, ensuring business logic correctness. After disconnecting and reconnecting to the gateway, there is no need to send a new OpCode 2 Identify login request. After connecting to the `Gateway`, send an OpCode 6 Resume message with the following `payload`:

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

Here `seq` refers to the `s` field when receiving events. We recommend that developers record `s` after processing an event so that it can be passed to `websocket` during `resume`; `websocket` will automatically re-deliver events after this seq.

After a successful resume, missed events begin to be redelivered. Once all events have been redelivered, a `Resumed Event` is delivered with the following `payload`:

```
{
  "op": 0,
  "s": 2002,
  "t": "RESUMED",
  "d": ""
}
```

## Sharded Connection Load Balancing

As a bot grows and is added to more and more channels, events increase, and the business needs to split events horizontally to achieve load balancing. The bot gateway implements a user-controllable sharding method that allows events to be split across multiple gateway connections. Sharding is entirely controlled by the user and does not require state sharing between separate connections.

To enable sharding on a connection, specify the shard parameter when establishing the connection. For details, see [gateway](/wiki/develop/api-v2/dev-prepare/interface-framework/reference.html)

### Determining the Appropriate Number of Shards

When using the [/gateway/bot](/wiki/develop/api-v2/openapi/wss/shard_url_get.html) API to obtain the gateway address, a recommended `shard` count and the maximum concurrency limit are also returned.

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

### Sharding Rules

Shards are hashed by channel id, so information for the same channel is always pushed over the same connection. The specific hash calculation rules are as follows:

```
shard_id = (guild_id >> 22) % num_shards
```

### Maximum Number of Connections

The number of connections created by each bot cannot exceed the remaining connection count `remaining`.

## WebSocket Error Codes

Value

Meaning

Whether RESUME Can Be Retried

Whether IDENTIFY Can Be Retried

4001

Invalid opcode

No

No

4002

Invalid payload

No

No

4007

Invalid seq

No

**Yes**

4006

Invalid session id; cannot continue resume, please identify

No

**Yes**

4008

Payloads sent too quickly. Please reconnect and follow the rate-limit information returned after connecting

**Yes**

**Yes**

4009

Connection expired. Please reconnect and perform resume to re-establish the connection

**Yes**

**Yes**

4010

Invalid shard

No

No

4011

The connection has too many guilds to handle. Please shard appropriately

No

No

4012

Invalid version

No

No

4013

Invalid intent

No

No

4014

Intent not authorized

No

No

4900~4913

Internal error. Please reconnect

No

**Yes**

4914

The bot has been delisted and may only connect to the sandbox environment. Please disconnect and check the current connection environment

No

No

4915

The bot has been banned and is not allowed to connect. Please disconnect and reconnect after requesting an unban

No

No

Simple handling logic for WebSocket error codes:

-   4009: resume can be initiated again
-   4914, 4915: cannot connect; please contact the official team to request an unban
-   For other errors, initiate identify again

### Webhook Method

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html

# Webhook Method

The QQ Bot Open Platform supports receiving events through HTTP APIs. Developers can configure a callback address and subscribe to events via the [Admin Console (opens new window)](https://q.qq.com/qqbot/#/developer/webhook-setting).

The ports currently allowed for callback addresses are: 80, 443, 8080, and 8443.

## Signature Verification

The bot server needs to verify the signature of callback requests to ensure the data has not been tampered with. [Signature Algorithm](/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html)

## Callback Address and Event Subscription Configuration

Developers need to provide an HTTPS callback address and select the event types to listen for. The Open Platform pushes events to the bot via callbacks.

![event_subscription](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/webhook_new.b24ed4d6.png)

After the callback address is configured, the Open Platform verifies it:

-   Request structure (Payload.d)

**Field**

**Description**

plain\_token

String used to calculate the signature

event\_ts

Timestamp used to calculate the signature

-   Return result

**Field**

**Description**

plain\_token

String used to calculate the signature

signature

Signature

The calculation process is as follows (golang):

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
	// The GenerateKey method returns a public key and a private key; only the private key is needed here to generate the signature, so the public key does not need to be returned
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

For example, bot account

```
appid: 11111111
secret: DG5g3B4j9X2KOErG
```

Callback verification request:

```
headers: User-Agent:[QQBot-Callback] X-Bot-Appid:[11111111]
body: {"d":{"plain_token":"Arq0D5A61EgUu4OxUvOp","event_ts":"1725442341"},"op":13},
```

The bot should return:

```
body: {"plain_token": "Arq0D5A61EgUu4OxUvOp","signature": "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"}
```

### opcode

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html

# opcode

The full list of opcodes is as follows:

CODE

Name

Client Operation

Description

0

Dispatch

Receive

Server pushes messages

1

Heartbeat

Send/Receive

Client or server sends heartbeat

2

Identify

Send

Client sends authentication

6

Resume

Send

Client resumes connection

7

Reconnect

Receive

Server notifies client to reconnect

9

Invalid Session

Receive

Returned by the server when a parameter is incorrect during identify or resume

10

Hello

Receive

The first message sent by the gateway after the client establishes a WebSocket connection with the gateway

11

Heartbeat ACK

Receive/Reply

Received after a heartbeat is sent successfully

12

HTTP Callback ACK

Reply

Used only as the reply in HTTP callback mode, indicating that the bot has received the data pushed by the platform ()

13

Callback address verification

Receive

The Open Platform verifies the bot server

The meanings of client operations are as follows:

-   `Receive`: the client receives a message pushed by the server
-   `Send` The client sends a message
-   `Reply` The response packet after the client receives a message sent by the server (HTTP callback mode)

### Event Subscription and Notification

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html

# Event Subscription and Notification

Description

When users perform certain actions within the QQ platform, or when some APIs have an asynchronous return notification confirmation mechanism, QQ notifies the developer's server through "events", and developers can respond accordingly based on the specific event notification. Examples include a user messaging the bot, a user adding the bot as a friend, or the bot being added to a group chat.

## Common Data Structure Payload

`payload` refers to the data transmitted over a `webhook` or `websocket` connection. The gateway uses the same structure for both upstream and downstream messages, as follows:

```
{
  "id":"event_id",
  "op": 0,
  "d": {},
  "s": 42,
  "t": "GATEWAY_EVENT_NAME"
}
```

Field

Description

id

Event id

op

Refers to the opcode; see connection maintenance

s

Every downstream message has a sequence number that identifies it uniquely. When sending a heartbeat, the client must carry the latest s it has received.

t

Represents the event type. Mainly used when op is 0 Dispatch

d

Represents the event content. The content format differs for each event type, so identify it carefully. Mainly used when op is 0 Dispatch

### OpCode Meanings

The list of all `opcode` values is as follows:

**CODE**

**Name**

Connection Method

**Client Behavior**

**Description**

0

Dispatch

webhook/websocket

Receive

Server pushes messages

1

Heartbeat

websocket

Send/Receive

Client or server sends heartbeat

2

Identify

websocket

Send

Client sends authentication

6

Resume

websocket

Send

Client resumes connection

7

Reconnect

websocket

Receive

Server notifies client to reconnect

9

Invalid Session

websocket

Receive

When identify or resume is used, if any parameter is incorrect, the server returns this message

10

Hello

websocket

Receive

The first message sent by the gateway after the client establishes a ws connection with the gateway

11

Heartbeat ACK

websocket

Receive/Reply

Received after a heartbeat is sent successfully

12

HTTP Callback ACK

webhook

Reply

Used only for the response packet in http callback mode, indicating that the bot has received the data pushed by the platform

13

Callback address verification

webhook

Receive

The Open Platform verifies the bot server

The meanings of client behaviors are as follows:

`Receive`: the client receives a message `push`ed by the server

`Send`: the client sends a message

`Reply`: the client's response after receiving a message sent by the server (HTTP callback mode)

## Webhook Method

The QQ Bot Open Platform supports receiving events through HTTP APIs. Developers can configure a callback address and subscribe to events via the [Admin Console (opens new window)](https://q.qq.com/qqbot/#/developer/webhook-setting).

The ports currently allowed for callback addresses are: 80, 443, 8080, and 8443.

### Signature Verification

The bot server needs to verify the signature of callback requests to ensure the data has not been tampered with. [Signature Algorithm](/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html)

### Callback Address and Event Subscription Configuration

Developers need to provide an HTTPS callback address and select the event types to listen for. The Open Platform pushes events to the bot via callbacks.

![event_subscription](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/webhook_new.b24ed4d6.png)

After the callback address is configured, the Open Platform verifies it:

-   Request structure (Payload.d)

**Field**

**Description**

plain\_token

String used to calculate the signature

event\_ts

Timestamp used to calculate the signature

-   Return result

**Field**

**Description**

plain\_token

String used to calculate the signature

signature

Signature

The calculation process is as follows (golang):

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
	// The GenerateKey method returns a public key and a private key; only the private key is needed here to generate the signature, so the public key does not need to be returned
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

For example, bot account

```
appid: 11111111
secret: DG5g3B4j9X2KOErG
```

Callback verification request:

```
headers: User-Agent:[QQBot-Callback] X-Bot-Appid:[11111111]
body: {"d":{"plain_token":"Arq0D5A61EgUu4OxUvOp","event_ts":"1725442341"},"op":13},
```

The bot should return:

```
body: {"plain_token": "Arq0D5A61EgUu4OxUvOp","signature": "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"}
```

## WebSocket Method

### Connecting to the Gateway

First, call the [Get General WSS Access Point | QQ Bot Documentation](/wiki/develop/api-v2/openapi/wss/url_get.html) or [Get Sharded WSS Access Point | QQ Bot Documentation](/wiki/develop/api-v2/openapi/wss/shard_url_get.html) API to obtain the gateway address.

You will get an address similar to the following:

```
wss://api.bot.qq.com/websocket/
```

Then establish a persistent `websocket` connection. Once the connection succeeds, an [OpCode 10 Hello](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) message is returned. Its main content is the heartbeat interval in milliseconds, as follows:

```
{
  "op": 10,
  "d": {
    "heartbeat_interval": 45000
  }
}
```

### Login Authentication to Obtain a Session

After the persistent `websocket` connection is established, login authentication is required. Once authentication succeeds, a session ID is obtained; only after a successful login does the QQ backend deliver event notifications,

Send an OpCode 2 Identify message with the following `payload`:

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

**Field**

**Description**

token

Format: "QQBot {AccessToken}"

intents

The events to receive on this connection. For details, see **Intents** \[event subscription intents\\

shard

To enable load balancing when receiving events, QQ provides sharding logic: event notifications fall on different shards. This parameter is an array with two elements.  
For example: \[0,4\] means four shards; the current connection is shard 0, and the business should subsequently establish connections with `shard` set to \[1,4\],\[2,4\],\[3,4\] to receive all events. For more details, see **Shard** \[Shard mechanism\\

properties

Currently has no practical effect; fill it in according to your own situation or leave it empty.

After successful authentication, the QQ backend delivers a Ready Event with the following `payload`:

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
      "username": "Group Pro Test Bot",
      "bot": true
    },
    "shard": [0, 0]
  }
}
```

### Sending Heartbeat Ack

After successful authentication, heartbeats must be sent periodically. d is the s of the latest message received by the client; on the first connection, pass null for d. The `payload` is as follows:

```
{
  "op": 1,
  "d": 251
}
```

After a heartbeat is sent successfully, an [OpCode 11 Heartbeat ACK](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) message is received with the following `payload`:

```
{
  "op": 11
}
```

### Resuming the Login Session

Many reasons can cause the persistent `websocket` connection to disconnect. Reconnecting shortly after a disconnect re-delivers events missed in between, ensuring business logic correctness. After disconnecting and reconnecting to the gateway, there is no need to send a new [Opcode 2 Identify](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) login request. After connecting to the `Gateway`, send an [Opcode 6 Resume](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) message with the following `payload`:

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

Here `seq` refers to the `s` field when receiving events. We recommend that developers record `s` after processing an event so that it can be passed to `websocket` during `resume`; `websocket` will automatically re-deliver events after this seq.

After a successful resume, missed events begin to be redelivered. Once all events have been redelivered, a `Resumed Event` is delivered with the following `payload`:

```
{
  "op": 0,
  "s": 2002,
  "t": "RESUMED",
  "d": ""
}
```

### Event Subscription Intents

The `intents` of an event is a bitmask, where each bit represents a different event. If you need to receive a certain type of event, set that bit to `1`.

Each `intents` bit represents a category of events and can be distinguished by the value of the `t` field in data transmitted over `websocket`.

The relationship between events and bit shifts is as follows:

```
GUILDS (1 << 0)
  - GUILD_CREATE           // When the bot joins a new guild
  - GUILD_UPDATE           // When guild information changes
  - GUILD_DELETE           // When the bot leaves a guild
  - CHANNEL_CREATE         // When a channel is created
  - CHANNEL_UPDATE         // When a channel is updated
  - CHANNEL_DELETE         // When a channel is deleted

GUILD_MEMBERS (1 << 1)
  - GUILD_MEMBER_ADD       // When a member joins
  - GUILD_MEMBER_UPDATE    // When member information changes
  - GUILD_MEMBER_REMOVE    // When a member is removed

GUILD_MESSAGES (1 << 9)    // Message events; only *private domain* bots can set this intents.
  - MESSAGE_CREATE         // Message send event, representing all messages in the channel, not just messages that @ the bot. Content is the same as AT_MESSAGE_CREATE
  - MESSAGE_DELETE         // Message delete (recall) event

GUILD_MESSAGE_REACTIONS (1 << 10)
  - MESSAGE_REACTION_ADD    // Add an emoji reaction to a message
  - MESSAGE_REACTION_REMOVE // Remove an emoji reaction from a message

DIRECT_MESSAGE (1 << 12)
  - DIRECT_MESSAGE_CREATE   // When a direct message sent by a user to the bot is received
  - DIRECT_MESSAGE_DELETE   // Message delete (recall) event


GROUP_AND_C2C_EVENT (1 << 25)
  - C2C_MESSAGE_CREATE      // When a user sends a direct chat message to the bot
  - FRIEND_ADD              // User adds and uses the bot
  - FRIEND_DEL              // User removes the bot
  - C2C_MSG_REJECT          // User manually turns off "proactive message" push on the bot profile card
  - C2C_MSG_RECEIVE         // User manually turns on the "proactive message" push switch on the bot profile card
  - GROUP_AT_MESSAGE_CREATE // Message received when a user @s the bot in a group
  - GROUP_ADD_ROBOT         // Bot is added to a group chat
  - GROUP_DEL_ROBOT         // Bot is removed from a group chat
  - GROUP_MSG_REJECT        // Group administrator manually turns off notifications on the bot profile page
  - GROUP_MSG_RECEIVE       // Group administrator manually turns on notifications on the bot profile page

INTERACTION (1 << 26)
  - INTERACTION_CREATE     // When an interaction event is created

MESSAGE_AUDIT (1 << 27)
  - MESSAGE_AUDIT_PASS     // Message audit passed
  - MESSAGE_AUDIT_REJECT   // Message audit failed

FORUMS_EVENT (1 << 28)  // Forum event; only *private-domain* bots can set this intents.
  - FORUM_THREAD_CREATE     // When a user creates a thread
  - FORUM_THREAD_UPDATE     // When a user updates a thread
  - FORUM_THREAD_DELETE     // When a user deletes a thread
  - FORUM_POST_CREATE       // When a user creates a post
  - FORUM_POST_DELETE       // When a user deletes a post
  - FORUM_REPLY_CREATE      // When a user replies to a comment
  - FORUM_REPLY_DELETE      // When a user replies to a comment
  - FORUM_PUBLISH_AUDIT_RESULT      // When a user's post passes audit

AUDIO_ACTION (1 << 29)
  - AUDIO_START             // When audio starts playing
  - AUDIO_FINISH            // When audio finishes playing
  - AUDIO_ON_MIC            // When going on mic
  - AUDIO_OFF_MIC           // When going off mic

PUBLIC_GUILD_MESSAGES (1 << 30) // Message event; this is a public-domain message event
  - AT_MESSAGE_CREATE       // When a message @mentioning the bot is received
  - PUBLIC_MESSAGE_DELETE   // When a channel message is deleted
```

#### Example

If a developer needs to receive messages in which users at-mention the bot, `PUBLIC_GUILD_MESSAGES` must be enabled in `intents`. First calculate the value of `1 << 30`, then perform a bitwise OR with `0` to obtain the final `intents` to pass.

If multiple event types need to be received, perform a bitwise OR on the multiple results. For example, `0|1<<30|1<<1` means subscribing to both the `PUBLIC_GUILD_MESSAGES` and `GUILD_MEMBERS` event types.

#### Permissions

Event type subscriptions are subject to permission control. Apart from `GUILDS`, `PUBLIC_GUILD_MESSAGES`, and `GUILD_MEMBERS`, which are basic events that are subscribed to by default, all other special events require an application before use. If `intents` without permission are passed during authentication, `websocket` returns an error and closes the connection directly. Developers should keep the scope of event subscriptions within what they actually need.

If permission for a special event type you have is revoked, no error occurs on the current connection, but the corresponding event type will no longer be received. On reconnection, an error occurs. Therefore, if a developer's event type permission is revoked, adjust the event listening code promptly to avoid being unable to connect due to the error.

### Sharded Connection Load Balancing

As a `bot` grows and is added to more and more channels, events increase, and the business needs to split events horizontally to achieve load balancing. The bot gateway implements a user-controllable sharding method that allows events to be split across multiple gateway connections. Sharding is entirely controlled by the user and does not require state sharing between separate connections.

To enable sharding on a connection, specify the shard parameter when establishing the connection. For details, see [gateway](/wiki/develop/api-v2/dev-prepare/interface-framework/reference.html)

#### Determining the Appropriate Number of Shards

When using the [/gateway/bot](/wiki/develop/api-v2/openapi/wss/shard_url_get.html) API to obtain the gateway address, a recommended `shard` count and the maximum concurrency limit are also returned.

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

#### Sharding Rules

Shards are hashed by channel id, so information for the same channel is always pushed over the same connection. The specific hash calculation rules are as follows:

```
shard_id = (guild_id >> 22) % num_shards
```

#### Maximum Number of Connections

The number of connections created by each bot cannot exceed the remaining connection count `remaining`

### API Calls and Authentication

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/api-use.html

# API Calls and Authentication

Description

The `openapi` APIs exposed by the `QQ Bot` server are all called over `https`, and authentication for `openapi` API calls is implemented through the `AccessToken` mechanism.

## Obtaining the Call Credential

-   **Request**

Basic Information

HTTP URL

https://api.bot.qq.com/app/getAppAccessToken

HTTP Method

POST

-   **Request Parameters**

**Attribute**

**Type**

**Required**

**Description**

appId

string

Yes

Obtained from the Open Platform admin console.

clientSecret

string

Yes

Obtained from the Open Platform admin console.

-   **Response Parameters**

**Attribute**

**Type**

**Description**

access\_token

string

The obtained credential.

expires\_in

number

Credential validity period in seconds. Currently a value within 7200 seconds.

-   **Error Codes**

**Error Code**

**Error Code Values**

0

ok

-   **Call Example**

```
curl --location 'https://api.bot.qq.com/app/getAppAccessToken' \
--header 'Content-Type: application/json' \
--data '{
  "appId": "APPID",
  "clientSecret": "CLIENTSECRET"
}'
```

-   **Response Example**

```
{
  "access_token": "ACCESS_TOKEN",
  "expires_in": "7200"
}
```

-   **Additional Notes**

Currently the default `access_token` lifetime is `7200` seconds. Each request does not refresh the `access_token`; developers need to refresh the `access_token` themselves after it expires to ensure the call chain has normal permissions.

When obtaining an `access_token` within `60` seconds of the previous `access_token`'s expiration, a new `access_token` is obtained, and the old `access_token` remains valid during these `60` seconds.

## Authentication Method

For each HTTPS request to an openapi API, include `access_token` in the header to verify call permission.

**Unified Address**

```
https://api.bot.qq.com
```

**Request Header**

Name

Type

Required

Description

Authorization

string

Yes

Format: "QQBot ACCESS\_TOKEN"

**Example**

```
{
  "headers": {
    "Authorization": "QQBot {ACCESS_TOKEN}"
  }
}
```

### Security and Authorization

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html

# Security and Authorization

Developers need to verify the requester's identity for every callback request based on the signature and other information in the callback to avoid security risks. The signature algorithm currently used is Ed25519.

## Security Credential

The Bot Secret on the Developer Platform is used to encrypt the signature string and as the key for server-side signature verification. Users must keep security credentials strictly confidential to avoid leaks.

## Verifying the Signature

### 1. Signature Verification Parameters

Field Name

Description

Reference Value

X-Signature-Ed25519

Signature passed through in the HTTP header

3ecd\*\*\* (64 bytes)

X-Signature-Timestamp

Signature timestamp passed through in the HTTP header

1636373772

HTTP Body

Body value in the HTTP request

{"msg":"hello"}

### 2. Signature Verification Process

The following code uses Go as an example, referencing the `crypto/ed25519` package to implement the `Ed25519` algorithm

-   Repeat the Bot Secret value from the Developer Platform to obtain a 32-byte signing seed, then call the Ed25519 algorithm with the seed to generate a 32-byte public key

```
  // Obtain the seed value by repeating botSecret, then calculate the public key
  seed := botSecret
  for len(seed) < ed25519.SeedSize {
    seed = strings.Repeat(seed, 2)
  }
  rand := strings.NewReader(seed[:ed25519.SeedSize])
  publicKey, privateKey, err := ed25519.GenerateKey(rand)
```

DEMO

```
[Input]
secret: naOC0ocQE3shWLAfffVLB1rhYPG7
seed: naOC0ocQE3shWLAfffVLB1rhYPG7naOC
[Output]
publicKey: [215 195 98 254 120 174 248 31 242 50 135 180 147 98 139 93 176 42 60 79 227 11 33 94 77 25 96 155 93 118 103 58]
privateKey: [110 97 79 67 48 111 99 81 69 51 115 104 87 76 65 102 102 102 86 76 66 49 114 104 89 80 71 55 110 97 79 67 215 195 98 254 120 174 248 31 242 50 135 180 147 98 139 93 176 42 60 79 227 11 33 94 77 25 96 155 93 118 103 58]
```

-   Get the value of X-Signature-Ed25519 from the HTTP header, perform hex decoding to obtain the Signature, and verify it

```
  // Get X-Signature-Ed25519 from the HTTP header (hex-decode it) and verify 
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

-   Get the values of X-Signature-Timestamp from the HTTP header and the HTTP body, and combine them in timestamp+body order to form the signature body msg

```
    // Get X-Signature-Timestamp from the HTTP header and verify it
  timestamp := req.Header.Get("X-Signature-Timestamp")
  if timestamp == "" {
    return false
  }
  httpBody, err := io.ReadAll(req.Body)
  if err != nil {
    return false
  }
  // Form the signature body in timestamp+Body order
  var msg bytes.Buffer
  msg.WriteString(timestamp)
  msg.Write(httpBody)
  if err != nil {
    return false
  }
```

-   Call the Ed25519 algorithm with the public key, Signature, and signature body to verify

```
  ed25519.Verify(publicKey, msg.Bytes(), sig)
```

DEMO

```
[Input]
secret: naOC0ocQE3shWLAfffVLB1rhYPG7
body: { "op": 0,"d": {}, "t": "GATEWAY_EVENT_NAME"}
timestamp: 1725442341

[Output]
sig: 865ad13a61752ca65e26bde6676459cd36cf1be609375b37bd62af366e1dc25a8dc789ba7f14e017ada3d554c671a911bfdf075ba54835b23391d509579ed002

```

### Using WebSocket

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/reference.html

# Using WebSocket

### payload

payload refers to the data transmitted over a websocket connection. The gateway uses the same structure for both upstream and downstream messages, as follows:

```
{
  "op": 0,
  "d": {},
  "s": 42,
  "t": "GATEWAY_EVENT_NAME"
}
```

`op` refers to the opcode. For the full opcode list, see [opcode](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html).

`s` Every downstream message has a sequence number that identifies it uniquely. When sending a heartbeat, the client must include the latest `s` it has received.

`t` and `d` are mainly used when `op` is `0 Dispatch`: `t` represents the event type and `d` represents the event content. The content format differs for each event type, so identify it carefully.

### 1. Connecting to the Gateway

First, call the [/gateway](/wiki/develop/api-v2/openapi/wss/url_get.html) or [/gateway/bot](/wiki/develop/api-v2/openapi/wss/shard_url_get.html) API to obtain the gateway address. You will get an address similar to the following:

```
wss://api.bot.qq.com/websocket/
```

Then establish a websocket connection. Once the connection succeeds, an [OpCode 10 Hello](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) message is returned. The main content of this message is the heartbeat interval in milliseconds, as follows:

```
{
  "op": 10,
  "d": {
    "heartbeat_interval": 45000
  }
}
```

### 2. Authentication Connection

After establishing the websocket connection, you need to authenticate by sending an [OpCode 2 Identify](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) message, as follows:

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

`token` is assigned when the bot is created, in the format `Bot {appid}.{app_token}`

`intents` specifies the events to receive for this connection; see [Intents](/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html#%E4%BA%8B%E4%BB%B6%E7%B1%BB%E5%9E%8BIntents) for details

`shard` is used for horizontal sharding. This parameter is an array with two elements. For example: `[0,4]` means four shards total and the current connection is shard 0; the service should subsequently establish connections with shard `[1,4]`, `[2,4]`, and `[3,4]` to receive all events. For more details, refer to [Shard](/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html#%E5%88%86%E7%89%87%E8%BF%9E%E6%8E%A5LoadBalance).

`properties` currently has no practical effect; you can fill it in according to your actual situation or leave it empty

After successful authentication, the backend sends a `Ready Event` with the following structure:

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
      "username": "Group Pro Test Bot",
      "bot": true
    },
    "shard": [0, 0]
  }
}
```

### 3. Sending Heartbeats

After successful authentication, you need to send heartbeats periodically. `d` is the `s` of the latest message received by the client; for the first connection, pass `null`.

```
{
  "op": 1,
  "d": 251
}
```

After a heartbeat is sent successfully, you will receive an [OpCode 11 Heartbeat ACK](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) message, as follows:

```
{
  "op": 11
}
```

### 4. Resuming the Connection

Many reasons can cause the connection to drop. Reconnecting shortly after disconnection will resend events missed in between, ensuring business logic correctness. Reconnecting does not require sending an `Identify` request. After connecting to the Gateway, send an [Opcode 6 Resume](/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html) message with the following structure:

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

Here `seq` refers to the `s` field received with events. We recommend developers record `s` after processing an event so it can be passed to the websocket during resume; the websocket will automatically resend events after this seq.

After a successful resume, missed events start being resent. Once all events have been resent, a `Resumed Event` is sent with the following structure:

```
{
  "op": 0,
  "s": 2002,
  "t": "RESUMED",
  "d": ""
}
```

### WebSocket (Error Codes)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/error-trace/websocket.html

# WebSocket

### Error Code

Value

Meaning

Whether RESUME Can Be Retried

Whether IDENTIFY Can Be Retried

4001

Invalid opcode

No

No

4002

Invalid payload

No

No

4007

Invalid seq

No

**Yes**

4006

Invalid session id; cannot continue resume, please identify

No

**Yes**

4008

Payloads sent too quickly. Please reconnect and follow the rate-limit information returned after connecting

**Yes**

**Yes**

4009

Connection expired. Please reconnect and perform resume to re-establish the connection

**Yes**

**Yes**

4010

Invalid shard

No

No

4011

The connection has too many guilds to handle. Please shard appropriately

No

No

4012

Invalid version

No

No

4013

Invalid intent

No

No

4014

Intent not authorized

No

No

4014

Intent not authorized

No

No

4900~4913

Internal error. Please reconnect

No

**Yes**

4914

The bot has been delisted. Only sandbox environment connections are allowed. Please disconnect and verify the current connection environment

No

No

4915

The bot has been banned and connections are not allowed. Please disconnect and reconnect after applying for unbanning

No

No

### Simple Handling Logic for WebSocket Error Codes

-   4009: resume can be initiated again
-   4914, 4915: cannot connect; please contact the official team to request an unban
-   For other errors, initiate identify again

## 2. Gateway and Authentication

### Get the General WSS Access Point (autogen/api gateway.get)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/gateway.get.html

# Get the General WSS Access Point

Get the WSS access address; a WebSocket long connection can be established through this address.

## Request

### Basic Information

Field

Value

HTTP URL

/gateway

HTTP Method

GET

API Rate Limit

2 QPM / 10 QPM burst

### Request Example

**Get General WSS Access Point**

```
GET /gateway
```

## Response

### Response Body

Name

Type

Description

url

string

WebSocket connection address

## Response Example

**Successfully obtained the WSS gateway address**

```
{
  "url": "wss://qqbot-api.example.com/websocket"
}
```

### Get the General WSS Access Point (openapi/wss/url_get)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/url_get.html

# Get the General WSS Access Point

### Endpoint

```
GET /gateway
```

### Description

Used to obtain the WSS access address; a `websocket` long connection can be established through this address.

### Content-Type

```
application/json
```

### Response

Returns an address for connecting to `websocket`.

### Error Codes

See [error codes](/wiki/develop/api-v2/openapi/error/error.html) for details.

### Example

Response data packet

```
{
  "url": "wss://api.bot.qq.com/websocket/"
}
```

### Get the Sharded WSS Access Point

> Source: https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/shard_url_get.html

# Get the Sharded WSS Access Point

### Endpoint

```
GET /gateway/bot
```

### Description

Used to obtain the WSS access address and related information; a `websocket` long connection can be established through this address. The related information includes:

-   Recommended number of shards.
-   Current connection usage.

### Content-Type

```
application/json
```

### Response

Field Name

Type

Description

url

string

WebSocket connection address

shards

int

Recommended number of shards

session\_start\_limit

[SessionStartLimit](#sessionstartlimit)

Session creation limit information

### SessionStartLimit

Field Name

Type

Description

total

int

Number of sessions that can be created per 24 hours

remaining

int

Number of sessions that can still be created

reset\_after

int

Remaining time until the count resets (ms)

max\_concurrency

int

Number of sessions that can be created per 5s

### Error Codes

See [error codes](/wiki/develop/api-v2/openapi/error/error.html) for details.

### Example

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

### Get User Details

> Source: https://bot.q.qq.com/wiki/develop/api-v2/openapi/user/me.html

# Get User Details

### Endpoint

```
GET /users/@me
```

### Description

Used to get details of the current user (bot).

### Content-Type

```
application/json
```

### Response

Returns a [User](/wiki/develop/api-v2/openapi/user/model.html#user) object.

### Error Codes

See [error codes](/wiki/develop/api-v2/openapi/error/error.html) for details.

### Example

Response data packet

```
{
  "id": "11586990140073229091",
  "username": "gitsub",
  "avatar": "https://thirdqq.qlogo.cn/g?b=oidb&k=M5TibpXicS7Jt4z89BZxiamAA&s=100&t=1641802698",
  "union_openid": "74F138F7F3AF68C4B8E8325013FCA295",
  "union_user_account": ""
}
```

### User Object (User)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/openapi/user/model.html

# User Object (User)

ID-type data in the user object is only circulated in the bot context and is unrelated to real IDs. Do not interpret it as a real ID

### User

Field Name

Type

Description

id

string

User ID

username

string

Username

avatar

string

User avatar URL

bot

bool

Whether the user is a bot

union\_openid

string

The openid of a specially associated application; returned only after special application and configuration. To apply, please contact platform operations staff.

union\_user\_account

string

User information of the interconnected application associated with the bot; it is the same application associated with union\_openid. To apply, please contact platform operations staff.

### Note

`union_openid` and `union_user_account` are provided only when fetching member information separately; the user object carried in other events does not contain these two fields.

### WebSocket Errors

> Source: https://bot.q.qq.com/wiki/develop/api-v2/gateway/error/error.html

# WebSocket Errors

### code

Value

Meaning

Whether RESUME Can Be Retried

Whether IDENTIFY Can Be Retried

4001

Invalid opcode

No

No

4002

Invalid payload

No

No

4007

Invalid seq

No

**Yes**

4006

Invalid session id; cannot continue resume, please identify

No

**Yes**

4008

Payloads sent too quickly. Please reconnect and follow the rate-limit information returned after connecting

**Yes**

**Yes**

4009

Connection expired. Please reconnect and perform resume to re-establish the connection

**Yes**

**Yes**

4010

Invalid shard

No

No

4011

The connection has too many guilds to handle. Please shard appropriately

No

No

4012

Invalid version

No

No

4013

Invalid intent

No

No

4014

Intent not authorized

No

No

4014

Intent not authorized

No

No

4900~4913

Internal error. Please reconnect

No

**Yes**

4914

The bot has been delisted. Only sandbox environment connections are allowed. Please disconnect and verify the current connection environment

No

No

4915

The bot has been banned and connections are not allowed. Please disconnect and reconnect after applying for unbanning

No

No

### Simple Handling Logic for WebSocket Error Codes

-   4009: resume can be initiated again
-   4914, 4915: cannot connect; please contact the official team to request an unban
-   For other errors, initiate identify again

### Data Returned on Business Errors (Data)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/gateway/error/data/model.html

# Data Returned on Business Errors (Data)

### Data

Field Name

Type

Description

message\_audit

[MessageAudited](/wiki/develop/api-v2/gateway/message/model.html#messageaudited) object

Message audit information; only the audit\_id field of this object is populated

## 3. Sending and Receiving Messages (Direct Chat/Group)

### Message Sending and Receiving Overview

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html

# Message Sending and Receiving Overview

Bots can send and receive messages in three scenarios: QQ direct chat, group chat, and channel. This page introduces basic concepts and general rules; refer to the corresponding subcategories for specific APIs and events.

## Scenarios

Scenario

Send Message

Receive Event

QQ Direct Chat

[Send Direct Chat Message](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html) / [Streaming Message](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_stream_messages.post.html)

[C2C\_MESSAGE\_CREATE](/wiki/develop/api-v2/autogen/event/c2c_message_create.html)

QQ Group Chat

[Send Group Message](/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html)

[GROUP\_AT\_MESSAGE\_CREATE](/wiki/develop/api-v2/autogen/event/group_at_message_create.html) / [GROUP\_MESSAGE\_CREATE](/wiki/develop/api-v2/autogen/event/group_message_create.html)

Channel

[Send Sub-channel Message](/wiki/develop/api-v2/server-inter/channel/message/send.html) / [Channel Direct Message](/wiki/develop/api-v2/server-inter/channel/message/dms.html)

[Channel Message Event](/wiki/develop/api-v2/server-inter/channel/message/event.html)

### Conversation Scenario Diagram

Description

Bots can be added to various chat scenarios

Direct Chat

Group Chat

Text Sub-channel

Channel Direct Message

![Direct Chat](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/chat-single.c4f33531.jpg)

![Group Chat](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/chat-group.d5318db5.jpg)

![Text Sub-channel](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/chat-text-channel.6dfae006.jpg)

![Channel Direct Message](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/chat-c2c.33e2820c.jpg)

## Proactive and Passive Messages

Type

Feature

Description

Proactive Message

No conditions

The bot proactively reaches out to the user. Users can turn off the "Allow Proactive Sending" switch in the client; once disabled, proactive messages will fail to send

Interaction recall message

`is_wakeup=true`

After the user proactively converses with the bot, 1 recall message can be sent per period

Passive message (replying to user)

Carries `msg_id`

Reply to a user message

Passive message (responding to event)

Carries `event_id`

Reply to an event

## Message Types

Specify the message content format via `msg_type`:

msg\_type

Type

Content Field

Send

Receive

0

Text

`content`

✅

✅

2

Markdown

`markdown`

✅

\-

7

Rich Media

`media` (upload the file first to obtain `file_info`)

✅

✅

In addition to the above, responses may also contain types such as images, videos, voice, emoji, and cards; see [Message Types](/wiki/develop/api-v2/server-inter/message/type/overview.html) for details.

## Rich Media Messages

Rich media such as images, videos, voice, and files must first be uploaded to obtain `file_info`, then sent via the send message API (`msg_type=7`) with `media.file_info`.

Upload methods:

-   **Multipart upload**: recommended; developers do not need to provide a public CDN address. See [Multipart Upload Process](/wiki/develop/api-v2/server-inter/message/rich-media.html#%E5%88%86%E7%89%87%E4%B8%8A%E4%BC%A0%EF%BC%88%E6%8E%A8%E8%8D%90%EF%BC%89)
-   **Whole-file upload**: [Direct Chat Upload](/wiki/develop/api-v2/server-inter/message/rich-media.html#url-%E4%B8%8A%E4%BC%A0) / [Group Chat Upload](/wiki/develop/api-v2/server-inter/message/rich-media.html#url-%E4%B8%8A%E4%BC%A0)

> -   `file_info` has a validity period (`ttl`); re-upload after it expires.
> -   The file upload APIs for direct chat and group chat are not interoperable.

## Rate and Validity Rules

### Passive Messages

Scenario

Validity Period

Replies allowed per message

Direct Chat

60 minutes

4 times

Group Chat

5 minutes

5 times

Channel

5 minutes

\-

### Proactive Messages

Notes on proactive and passive messages: QQ users can choose in the QQ client whether to receive proactive messages sent by bots. If disabled, all proactive messages will fail to send.

#### Direct Chat

-   Proactive message sending rate limits (HTTP API)

Authentication Type

Scenario

Bot-level rate limit

Per-relationship rate limit

Daily limit

Enterprise verification

Direct Chat

10/qps

20/qpm

1000 messages/user

Personal verification

Direct Chat

10/qps

20/qpm

1000 messages/user

Unverified

Direct Chat

5/qps & 30/qpm

20/qpm

1000 messages/user

-   Interaction recall messages: After the user proactively converses with the bot, the bot can send interaction recall messages to the user within the next 30 days (the message type is subject to the message type permissions the bot currently has), with one message allowed per period. The periods are: same day, 1-3 days, 3-7 days, and 7-30 days, for a total of 4 periods. Use the is\_wakeup field in the send message API to declare use of this capability.

#### Group Chat

-   Proactive message sending rate limits (HTTP API)

Authentication Type

Scenario

Bot-level rate limit

Per-relationship rate limit

Daily limit

Enterprise verification

Group

60/qpm

20/qpm

1000 messages/group

Personal verification

Group

60/qpm

20/qpm

1000 messages/group

Unverified

Group

30/qpm

20/qpm

1000 messages/group

#### Text Sub-channel

-   If the channel owner or administrators have configured proactive messages, rate limiting follows the configured quantity. If not configured, the following limits apply:
    -   For proactive push messages, by default up to 20 messages can be pushed to each sub-channel per day; exceeding this limit is restricted.
    -   For proactive push messages, each channel can push messages to 2 sub-channels per day. Exceeding this is restricted.
-   Regardless of whether proactive or passive, at most 5 messages can be sent per second in a sub-channel.
-   Passive reply messages have a validity period of 5 minutes; sending after timeout will fail.
-   The send message API requires the bot to maintain an online WebSocket connection
-   For proactive message auditing, you can obtain results via the MessageAudited object returned by the MESSAGE\_AUDIT audit event in event subscription Intents.

#### Channel Direct Message

-   In the direct message scenario, each bot can send 2 proactive messages to a user per day.
-   In the direct message scenario, each bot can send a cumulative total of 200 proactive messages per day.
-   Passive reply messages have a validity period of 5 minutes; sending after timeout will fail.

## Message Deduplication

The same `msg_id` may be pushed multiple times; use `msg_seq` for deduplication. For passive replies, sending the same `msg_id + msg_seq` repeatedly will fail; increment `msg_seq` to reply to the same message multiple times.

## Recalling Messages

A bot can recall messages it has sent (messages sent more than **2 minutes** ago cannot be recalled):

-   [Recall Direct Chat Message](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages_message_id.delete.html)
-   [Recall Group Chat Message](/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages_message_id.delete.html)
-   [Recall Channel Message](/wiki/develop/api-v2/server-inter/channel/message/recall.html) / [Recall Channel Direct Message](/wiki/develop/api-v2/server-inter/channel/message/dms.html#%E6%92%A4%E5%9B%9E%E7%A7%81%E4%BF%A1)

### Get Bot Details (users/@me)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/users_me.get.html

# Get Bot Details

Get detailed information about the current user (bot).

-   union\_openid and union\_user\_account are returned only after special application and configuration
-   These two fields are provided only when fetching member information separately

## Request

### Basic Information

Field

Value

HTTP URL

/users/@me

HTTP Method

GET

API Rate Limit

50 QPS

### Request Example

**Get Current User Information**

```
GET /users/@me
```

## Response

### Response Body

Name

Type

Description

id

string

User ID

username

string

Username

avatar

string

Avatar URL

bot

boolean

Whether it is a bot

union\_openid

string

Cross-application unified user OpenID (special application required)

union\_user\_account

string

Cross-application unified user account (special application required)

## Response Example

**Successfully obtained current user information**

```
{
  "id": "5777414462219517083",
  "username": "Sunshine Assistant",
  "avatar": "https://thirdqq.qlogo.cn/g?b=oidb&k=AbCdEfGhIjKlMnOpQrStUv&kti=xyzABC&s=0&t=1781676795",
  "bot": true,
  "union_openid": "9F2E872045CCCC5948BEAF5B5FCCDF22",
  "union_user_account": "",
  "share_url": "https://qun.qq.com/qunpro/robot/qunshare?robot_uin=3889007780&robot_appid=102083127&biz_type=0",
  "welcome_msg": "Welcome to our group chat"
}
```

### Send Direct Chat Message

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html

# Send Direct Chat Message

Send a direct chat message to the specified user.

-   Passive messages are valid for **60 minutes**, with up to **4 replies** per message
-   Proactive message rate limit rules:
    -   Bot level (sender): enterprise verification/personal ID verification **10/qps**; unverified **5/qps** and **30/qpm**
    -   Per-relationship level (receiver): **20/qpm**; each friend can receive at most **1000** messages per day
-   Interaction recall messages: After the user proactively converses with the bot, the bot can send interaction recall messages to the user within the next 30 days (the message type is subject to the message type permissions the bot currently has), with one message allowed per period. The periods are: same day, 1-3 days, 3-7 days, and 7-30 days, for a total of 4 periods. Use the is\_wakeup field in the send message API to declare use of this capability.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/users/{user\_openid}/messages

HTTP Method

POST

API Rate Limit

100 QPS, including all message types such as proactive and passive

## Path Parameters

Name

Type

Required

Description

user\_openid

string

Yes

User OpenID

## Request Body

Name

Type

Required

Description

msg\_type

integer

No

Message type. Determines which content field takes effect: 0=plain text (content), 2=Markdown (markdown), 6=typing status (input\_notify), 7=rich media (media)

content

string

No

Text content. Full text when msg\_type=0. Note: if markdown is provided, this field must be empty

markdown

[MessageMarkdown](#schema-messagemarkdown)

No

Markdown message. Required when msg\_type=2. Note: if this field is provided, content/ark must both be empty

keyboard

[Keyboard](#schema-keyboard)

No

Inline keyboard. The short form passes only id; the long form passes content.rows

msg\_id

string

No

Message ID for passive reply. Obtained from d.id of events such as C2C\_MESSAGE\_CREATE; valid for 5 minutes

event\_id

string

No

Event ID for passive reply. Obtained from the outermost id of the event. Choose either this or msg\_id. Supported events: "INTERACTION\_CREATE", "C2C\_MSG\_RECEIVE", "FRIEND\_ADD"

msg\_seq

integer

No

Sequence number of the reply message, used together with msg\_id to avoid sending duplicate replies for the same message ID. Defaults to 1 if omitted. Sending the same msg\_id + msg\_seq repeatedly will fail.

media

[MediaInfo](#schema-mediainfo)

No

Rich media message. Fill in when msg\_type=7; file\_info comes from /v2/users/{user\_openid}/files

message\_reference

[MessageReference](#schema-messagereference)

No

Quoted reply. When provided, it is displayed as a quote and links the context

is\_wakeup

boolean

No

Indicates that the message being sent is an interaction recall message; mutually exclusive with msg\_id and event\_id

input\_notify

[InputNotify](#schema-inputnotify)

No

Typing status, used when msg\_type=6

**MessageMarkdown**

Name

Type

Required

Description

template\_id

integer

No

[Deprecated] Platform Markdown template ID. Fill in when using a template; omit when not using a template

content

string

No

Markdown content. For supported formats, refer to the documentation: [Markdown (opens new window)](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html)

custom\_template\_id

string

No

[Deprecated] Custom template ID. Choose either this or template\_id

force\_verify\_image\_resource

boolean

No

Whether to verify the image storage result. When true, if image storage fails, an error is returned and the message is not sent. Defaults to false

**Keyboard**

Name

Type

Required

Description

id

string

No

Inline keyboard template ID. Fill in this field when using a platform preset template

content

[KeyboardContent](#schema-keyboardcontent)

No

Custom keyboard layout. Mutually exclusive with id; used for custom buttons

**KeyboardContent**

Name

Type

Required

Description

rows

\[\][Row](#schema-row)

No

List of button rows

**Row**

Name

Type

Required

Description

buttons

\[\][Button](#schema-button)

No

Buttons in the row, arranged from left to right

**Button**

Name

Type

Required

Description

id

string

No

Button ID. Unique within the same keyboard

render\_data

[RenderData](#schema-renderdata)

No

Button rendering

action

[Action](#schema-action)

No

Button click behavior

group\_id

string

No

Group ID. After a button in the same group is operated, the other buttons become gray and cannot be clicked. Note: only effective when action.type = 1

**RenderData**

Name

Type

Required

Description

label

string

No

Button text, up to 10 characters

visited\_label

string

No

Text after clicking; stays unchanged if not provided

style

integer

No

0: gray outline, 1: blue outline, 3: white background + red text, 4: blue background + white text

**Action**

Name

Type

Required

Description

type

integer

No

0: link button: http or mini program; 1: callback button: calls back the backend API, data is passed to the backend; 2: command button: automatically inserts @bot data into the input box

permission

[Permission](#schema-permission)

No

Operation permission

data

string

No

Callback data. Required when type=1/2

click\_limit

integer

No

[Deprecated] Click limit. 0=unlimited

unsupport\_tips

string

No

Prompt text when the version is too low

enter

boolean

No

Available for command buttons. After clicking the button, data is automatically sent directly. Only available in direct chat. Defaults to false. Supported since version 8983

reply

boolean

No

Available for command buttons. Whether the command includes a quoted reply to this message. Defaults to false. Supported since version 8983

anchor

integer

No

This field is only valid for command buttons. Once set, the action.enter configuration is ignored. When set to 1, clicking the button automatically opens the mobile QQ image picker; other values currently have no effect. (Only supported in direct chat on mobile version 8983+; not supported on desktop)

modal

[Modal](#schema-modal)

No

Secondary confirmation action when the user clicks

**Permission**

Name

Type

Required

Description

type

integer

No

0=specified users, 1=administrators, 2=everyone

specify\_user\_ids

\[\]string

No

List of user IDs with permission

specify\_role\_ids

\[\]string

No

List of identity group IDs with permission (channel only)

**Modal**

Name

Type

Required

Description

content

string

No

Prompt text for secondary confirmation. If not empty, secondary confirmation is performed. Note: up to 40 characters, must not contain a URL

confirm\_text

string

No

Text displayed in the confirm button of the secondary confirmation prompt. Can be empty; defaults to "Confirm". Note: up to 4 characters

cancel\_text

string

No

Text in the cancel button of the secondary confirmation prompt. Can be empty; defaults to "Cancel". Note: up to 4 characters

**MediaInfo**

Name

Type

Required

Description

file\_info

string

No

File data. From the return value of the file upload API

**MessageReference**

Name

Type

Required

Description

message\_id

string

No

Quoted message ID, e.g. REFIDX\_xxxxxx  
\- For messages not sent by the bot, obtain from the `msg_idx` field of the `ext` array of `MessageScene` in the message event  
\- For messages sent by the bot itself, obtain from `ext_info.ref_idx` in the message sending response

**InputNotify**

Name

Type

Required

Description

input\_type

integer

No

Set to 1

input\_second

integer

No

Status duration, up to 60s

### Request Example

**Text message (msg\_type=0)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages
{
  "content": "Hello, welcome to the bot assistant!",
  "msg_type": 0,
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**Markdown message (msg\_type=2)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages
{
  "msg_type": 2,
  "markdown": {
    "content": "# Today's Picks\n\n**Featured Articles**\n> Knowledge is power, and learning never ends\n\n[Click to view details](https://example.com)"
  },
  "keyboard": {
    "id": "1070001"
  },
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**Input status notification (msg\_type=6)**

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

**Rich media message (msg\_type=7)**

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

## Response

### Response Body

Name

Type

Description

id

string

Message ID, can be used for later recall

timestamp

string

Send time, RFC3339 UTC+8

ext\_info

[MessageExtInfo](#schema-messageextinfo)

Extended information

**MessageExtInfo**

Name

Type

Description

ref\_idx

string

Quoted message index. Corresponds to msg\_idx and ref\_msg\_idx in the message event ext

## Response Example

**Message sent successfully**

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "timestamp": "2026-07-21T10:30:00+08:00"
}
```

**Message sent successfully (with extended information)**

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "timestamp": "2026-07-21T10:30:00+08:00",
  "ext_info": {
    "ref_idx": "REFIDX_xxxxxxxxxxxxxxxxxxxx=="
  }
}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

22006

Message type does not match content

Check whether msg\_type corresponds to content

50059

Invalid input type

Check the input type

304004

No permission to use this ARK template

Apply for ARK template permission first

304061

Invalid message content

Check whether the message format meets the requirements

304062

Subscription button count has reached the limit

Reduce the number of buttons

304064

Subscription message not authorized

Guide the user to authorize subscription messages first

304080

Invalid file information

Check whether the file information format is correct

304103

Message ID has expired and cannot be replied to

Reply as soon as possible after receiving the message

340067

Failed to get bot information

Check the bot status

40034004

Failed to store rich media information

Try again

40034005

The msg\_id for the reply message has expired

Reply as soon as possible after receiving the message

40034006

Message content violates the rules

Modify the message content and try again

40034008

markdown parameter has an empty value

Ensure all Markdown parameters have values

40034009

markdown parameter contains a newline

Remove newlines from the Markdown parameters

40034010

Template parameters must not contain Markdown syntax

Use plain text parameters without Markdown syntax

40034011

Invalid markdown content

Check whether the Markdown syntax is correct

40034024

Request parameter msg\_id is invalid or unauthorized

Check whether msg\_id is correct

40034025

Request parameter event\_id is invalid

Check whether event\_id is correct

40034026

Request parameter event\_id has expired

Reply as soon as possible after receiving the event

40034027

This event does not support replying to messages

Confirm whether the event type supports replies

40034029

Inline keyboard rows/columns exceed the limit

Reduce the number of keyboard buttons

40034100

Proactive message sending exceeds the rate limit

Lower the sending frequency or wait for the quota to recover

40034105

Proactive message sending failed: no permission

Check the bot permission settings

40034106

The message does not support this command type

Check the message command type

40034108

Command parameter length exceeds the limit

Shorten the command parameters

40034109

Failed to parse command parameters

Check the command parameter format

40034122

Message recall has reached the interval limit

Message recall has reached the limit; cannot recall further

40034123

Message recall not supported

This message does not support recall

40034124

markdown message parameter error

Check the Markdown parameter format

40034127

No markdown template permission

Apply for Markdown template permission first

40034128

Passive reply time or count exceeds the limit

Reply as soon as possible after receiving the event

40054004

No friend relationship

Add the user as a friend before sending a direct message

40054005

Message deduplicated

Ensure each request uses a different msgseq value

40054006

Failed to verify friend relationship

Try again

40054007

Message length exceeds the limit

Shorten the message content

40054013

User rejected the message

The user has rejected messages; cannot send

40054016

The bot is offline

Check the bot status

40054018

Message is too long or abnormal

Shorten the message content

50055002

Message sending error; try again later

Try again later

### Send direct chat message in streaming mode

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_stream_messages.post.html

# Send direct chat message in streaming mode

Send a direct chat message in batches in streaming mode. Each chunk uses the same stream\_msg\_id, and index increases from 0. Supports the markdown content format.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/users/{user\_openid}/stream\_messages

HTTP Method

POST

API Rate Limit

50 QPS

## Path Parameters

Name

Type

Required

Description

user\_openid

string

Yes

## Request Body

Name

Type

Required

Description

input\_mode

string

No

Input mode. append (default): ContentRaw is appended to Pending. replace: ContentRaw is the current full body and must start with the prefix SentContent already delivered upstream; after merging, Pending holds only the undelivered suffix.

input\_state

integer

No

Input status. 1=generating, 10=generation finished

index

integer

No

Chunk index, increasing from 0

content\_type

string

No

Content format type. text: text message; markdown: Markdown message

content\_raw

string

No

Text content in Markdown format

event\_id

string

No

Event ID for passive reply (choose either this or msg\_id)

msg\_id

string

No

Message ID for passive reply (choose either this or event\_id)

stream\_msg\_id

string

No

Streaming message ID. The first one is generated and returned by the server; subsequent chunks must carry the id returned by the previous chunk

msg\_seq

integer

No

Message sequence number, used for deduplication

is\_wakeup

boolean

No

Whether this is a recall message. When true, the validity period of msg\_id/event\_id is not verified

### Request Example

**First chunk message (input\_state=1, index=0)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/stream_messages
{
  "input_mode": "replace",
  "input_state": 1,
  "index": 0,
  "content_type": "markdown",
  "content_raw": "Generating the answer, please wait",
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**Continuation chunk message (input\_state=1, index=1)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/stream_messages
{
  "input_mode": "replace",
  "input_state": 1,
  "index": 1,
  "content_type": "markdown",
  "content_raw": "Generating the answer, please wait. Most of the content is now complete",
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "stream_msg_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "msg_seq": 1
}
```

**Final chunk message (input\_state=10)**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/stream_messages
{
  "input_mode": "replace",
  "input_state": 10,
  "index": 2,
  "content_type": "markdown",
  "content_raw": "Generating the answer, please wait. All content is now complete; the final result follows.",
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "stream_msg_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "msg_seq": 1
}
```

## Response

### Response Body

Name

Type

Description

id

string

Message ID. The first response returns stream\_msg\_id for subsequent chunks

timestamp

string

Message send time, RFC3339 format

ext\_info

[MessageExtInfo](#schema-messageextinfo)

Extended information. ref\_idx: quoted message index. Extended information

remain\_msg\_len

integer

Remaining length of the streaming message (in characters)

**MessageExtInfo**

Name

Type

Description

ref\_idx

string

Quoted message index. Corresponds to msg\_idx and ref\_msg\_idx in the message event ext

## Response Example

**First chunk response (returns stream\_msg\_id)**

```
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2026-07-21T10:00:00+08:00",
  "ext_info": {
    "ref_idx": "REFIDX_xxxxxxxxxxxxxxx=="
  }
}
```

**Continuation/final chunk response**

```
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2026-07-21T10:00:01+08:00",
  "ext_info": {
    "ref_idx": "REFIDX_xxxxxxxxxxxxxxx=="
  }
}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

40007

The prefix of delivered content cannot be modified

Keep the prefix of the delivered content consistent

50001

Internal server error

Try again later

50002

Rate limited

Reduce the call frequency

### Recall direct chat message

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages_message_id.delete.html

# Recall direct chat message

Recall a message sent by the bot to the current user. Messages sent more than 2 minutes ago cannot be recalled. Returns HTTP 200 on success with no response body.

-   Messages sent more than **2 minutes** ago cannot be recalled

## Request

### Basic Information

Field

Value

HTTP URL

/v2/users/{user\_openid}/messages/{message\_id}

HTTP Method

DELETE

API Rate Limit

10 QPS

## Path Parameters

Name

Type

Required

Description

user\_openid

string

Yes

User OpenID

message\_id

string

Yes

Message ID

### Request Example

**Example 1**

```
DELETE /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages/0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF
```

## Response

None

## Response Example

**Example 1**

```
{}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

306009

Invalid user openid

Check whether user\_openid is correct

40061001

Invalid request parameter

Check the request parameter format

40061002

Request parameter msgid is invalid

Check whether the msgid format is correct

40064004

The message recall time limit has been exceeded

Messages cannot be recalled more than 2 minutes after being sent

### Send group chat message

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html

# Send group chat message

Send a message to the specified group. Supports text/Markdown/rich media and other types, and can include an inline keyboard. Note: group messages do not support streaming parameters

-   Passive messages are valid for **5 minutes**, and each message can be replied to at most **5 times**
-   Proactive message rate limit rules
    -   Bot dimension (sender): enterprise verification/personal ID verification **60/qpm**; unverified **30/qpm**
    -   Per-relationship dimension (receiver): **20/qpm**; each group can receive at most **1000** messages per day

## Request

### Basic Information

Field

Value

HTTP URL

/v2/groups/{group\_openid}/messages

HTTP Method

POST

API Rate Limit

100 QPS

## Path Parameters

Name

Type

Required

Description

group\_openid

string

Yes

Group OpenID

## Request Body

Name

Type

Required

Description

msg\_type

integer

No

Message type. Determines which content field takes effect: 0=plain text (content), 2=Markdown (markdown), 7=rich media (media)

content

string

No

Text content. Full text when msg\_type=0. Note: if markdown is provided, this field must be empty

markdown

[MessageMarkdown](#schema-messagemarkdown)

No

Markdown message. Required when msg\_type=2. Note: if this field is provided, content/ark must both be empty

keyboard

[Keyboard](#schema-keyboard)

No

Inline keyboard. The short form passes only id; the long form passes content.rows

msg\_id

string

No

Message ID for passive reply. Obtained from d.id of events such as GROUP\_AT\_MESSAGE\_CREATE; valid for 5 minutes

event\_id

string

No

Event ID for passive reply. Obtained from the outermost id of the event. Choose either this or msg\_id. Supported events: "INTERACTION\_CREATE", "GROUP\_ADD\_ROBOT", "GROUP\_MSG\_RECEIVE"

msg\_seq

integer

No

Sequence number of the reply message, used together with msg\_id to avoid sending duplicate replies for the same message ID. Defaults to 1 if omitted. Sending the same msg\_id + msg\_seq repeatedly will fail.

media

[MediaInfo](#schema-mediainfo)

No

Rich media message. Fill in when msg\_type=7; file\_info comes from /v2/groups/{group\_openid}/files

message\_reference

[MessageReference](#schema-messagereference)

No

Quoted reply. When provided, it is displayed as a quote and links the context

**MessageMarkdown**

Name

Type

Required

Description

template\_id

integer

No

[Deprecated] Platform Markdown template ID. Fill in when using a template; omit when not using a template

content

string

No

Markdown content. For supported formats, refer to the documentation: [Markdown (opens new window)](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html)

custom\_template\_id

string

No

[Deprecated] Custom template ID. Choose either this or template\_id

force\_verify\_image\_resource

boolean

No

Whether to verify the image storage result. When true, if image storage fails, an error is returned and the message is not sent. Defaults to false

**Keyboard**

Name

Type

Required

Description

id

string

No

Inline keyboard template ID. Fill in this field when using a platform preset template

content

[KeyboardContent](#schema-keyboardcontent)

No

Custom keyboard layout. Mutually exclusive with id; used for custom buttons

**KeyboardContent**

Name

Type

Required

Description

rows

\[\][Row](#schema-row)

No

List of button rows

**Row**

Name

Type

Required

Description

buttons

\[\][Button](#schema-button)

No

Buttons in the row, arranged from left to right

**Button**

Name

Type

Required

Description

id

string

No

Button ID. Unique within the same keyboard

render\_data

[RenderData](#schema-renderdata)

No

Button rendering

action

[Action](#schema-action)

No

Button click behavior

group\_id

string

No

Group ID. After a button in the same group is operated, the other buttons become gray and cannot be clicked. Note: only effective when action.type = 1

**RenderData**

Name

Type

Required

Description

label

string

No

Button text, up to 10 characters

visited\_label

string

No

Text after clicking; stays unchanged if not provided

style

integer

No

0: gray outline, 1: blue outline, 3: white background + red text, 4: blue background + white text

**Action**

Name

Type

Required

Description

type

integer

No

0: link button: http or mini program; 1: callback button: calls back the backend API, data is passed to the backend; 2: command button: automatically inserts @bot data into the input box

permission

[Permission](#schema-permission)

No

Operation permission

data

string

No

Callback data. Required when type=1/2

click\_limit

integer

No

[Deprecated] Click limit. 0=unlimited

unsupport\_tips

string

No

Prompt text when the version is too low

enter

boolean

No

Available for command buttons. After clicking the button, data is automatically sent directly. Only available in direct chat. Defaults to false. Supported since version 8983

reply

boolean

No

Available for command buttons. Whether the command includes a quoted reply to this message. Defaults to false. Supported since version 8983

anchor

integer

No

This field is only valid for command buttons. Once set, the action.enter configuration is ignored. When set to 1, clicking the button automatically opens the mobile QQ image picker; other values currently have no effect. (Only supported in direct chat on mobile version 8983+; not supported on desktop)

modal

[Modal](#schema-modal)

No

Secondary confirmation action when the user clicks

**Permission**

Name

Type

Required

Description

type

integer

No

0=specified users, 1=administrators, 2=everyone

specify\_user\_ids

\[\]string

No

List of user IDs with permission

specify\_role\_ids

\[\]string

No

List of identity group IDs with permission (channel only)

**Modal**

Name

Type

Required

Description

content

string

No

Prompt text for secondary confirmation. If not empty, secondary confirmation is performed. Note: up to 40 characters, must not contain a URL

confirm\_text

string

No

Text displayed in the confirm button of the secondary confirmation prompt. Can be empty; defaults to "Confirm". Note: up to 4 characters

cancel\_text

string

No

Text in the cancel button of the secondary confirmation prompt. Can be empty; defaults to "Cancel". Note: up to 4 characters

**MediaInfo**

Name

Type

Required

Description

file\_info

string

No

File data. From the return value of the file upload API

**MessageReference**

Name

Type

Required

Description

message\_id

string

No

Quoted message ID, e.g. REFIDX\_xxxxxx  
\- For messages not sent by the bot, obtain from the `msg_idx` field of the `ext` array of `MessageScene` in the message event  
\- For messages sent by the bot itself, obtain from `ext_info.ref_idx` in the message sending response

### Request Example

**Text message (msg\_type=0)**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages
{
  "msg_type": 0,
  "content": "Welcome to this group assistant. How can I help you?",
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**Markdown + keyboard message (msg\_type=2)**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages
{
  "msg_type": 2,
  "markdown": {
    "content": "## Daily Check-in\n\nCheck-in successful today! You earned **50** points\n**7** consecutive check-in days"
  },
  "keyboard": {
    "content": {
      "rows": [
        {
          "buttons": [
            {
              "id": "btn_signin",
              "render_data": {
                "label": "Check in",
                "style": 1
              },
              "action": {
                "type": 2,
                "permission": {
                  "type": 2
                },
                "data": "/checkin",
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

**Rich media message (msg\_type=7)**

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

## Response

### Response Body

Name

Type

Description

id

string

Message ID, can be used for later recall

timestamp

string

Send time, RFC3339 UTC+8

ext\_info

[MessageExtInfo](#schema-messageextinfo)

Extended information

**MessageExtInfo**

Name

Type

Description

ref\_idx

string

Quoted message index. Corresponds to msg\_idx and ref\_msg\_idx in the message event ext

## Response Example

**Sent successfully**

```
{
  "id": "ROBOT1.0_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
  "timestamp": "2026-07-21T10:00:00+08:00",
  "ext_info": {
    "ref_idx": "REFIDX_xxxxxxxxxxxxxxx=="
  }
}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

22006

Message type does not match content

Check whether msg\_type corresponds to content

304004

No permission to use this ARK template

Apply for ARK template permission first

304036

No Markdown template permission

Apply for Markdown template permission first

304061

Invalid message content

Check whether the message format meets the requirements

304064

Subscription message not authorized

Guide the user to authorize subscription messages first

304080

Invalid file information

Check whether the file information format is correct

304103

Message ID has expired and cannot be replied to

Reply as soon as possible after receiving the message

305007

Invalid keyboard style parameter

Check the keyboard parameter

340069

Invalid message type

Check the msg\_type value

40034004

Failed to store rich media information

Try again

40034005

The msg\_id for the reply message has expired

Reply as soon as possible after receiving the message

40034006

Message content violates the rules

Modify the message content and try again

40034008

markdown parameter has an empty value

Ensure all Markdown parameters have values

40034009

markdown parameter contains a newline

Remove newlines from the Markdown parameters

40034010

Template parameters must not contain Markdown syntax

Use plain text parameters without Markdown syntax

40034011

Invalid markdown content

Check whether the Markdown syntax is correct

40034024

Request parameter msg\_id is invalid or unauthorized

Check whether msg\_id is correct

40034025

Request parameter event\_id is invalid

Check whether event\_id is correct

40034026

Request parameter event\_id has expired

Reply as soon as possible after receiving the event

40034027

This event does not support replying to messages

Confirm whether the event type supports replies

40034029

Inline keyboard rows/columns exceed the limit

Reduce the number of keyboard buttons

40034100

Proactive message sending exceeds the rate limit

Lower the sending frequency or wait for the quota to recover

40034101

The bot is not a group member

Add the bot to the group chat first

40034105

Proactive message sending failed: no permission

Check the bot permission settings

40034106

The message does not support this command type

Check the message command type

40034108

Command parameter length exceeds the limit

Shorten the command parameters

40034109

Failed to parse command parameters

Check the command parameter format

40034124

markdown message parameter error

Check the Markdown parameter format

40034127

No markdown template permission

Apply for Markdown template permission first

40034128

Passive reply time or count exceeds the limit

Reply as soon as possible after receiving the event

40054002

The bot is muted

Wait until the mute is lifted before sending

40054003

The bot is not a group member

Add the bot to the group chat first

40054005

Message deduplicated

Ensure each request uses a different msgseq value

40054007

Message length exceeds the limit

Shorten the message content

40054010

Sending URLs is not allowed

Remove the URL from the message

40054016

The bot is offline

Check the bot status

50055001

Message sending error; try again later

Try again later

50055006

ARK message sending error; try again later

Try again later

### Recall group chat message

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages_message_id.delete.html

# Recall group chat message

Recall a group message. Messages sent more than 2 minutes ago cannot be recalled. Returns HTTP 200 on success with no response body.

-   Messages sent more than **2 minutes** ago cannot be recalled.
-   If the bot is a group administrator, it can recall its own messages and those of ordinary group members. The message ID of a group member is obtained from the `d.id` field in the group message event `GROUP_AT_MESSAGE_CREATE` or `GROUP_MESSAGE_CREATE`.
-   If the bot is an ordinary member, it can only recall messages sent by the bot itself. The message ID can be obtained from the response of the message sending API.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/groups/{group\_openid}/messages/{message\_id}

HTTP Method

DELETE

API Rate Limit

10 QPS

## Path Parameters

Name

Type

Required

Description

group\_openid

string

Yes

Group OpenID

message\_id

string

Yes

Message ID

### Request Example

**Recall group message**

```
DELETE /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages/0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF
```

## Response

None

## Response Example

**Response example**

```
{}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

40061001

Invalid request parameter

Check the request parameter format

40062003

No operation permission

Check whether the bot has operation permission, whether the bot is a group administrator, or whether the user who sent the message is an ordinary user

40064004

The message recall time limit has been exceeded

Messages cannot be recalled more than 2 minutes after being sent

50065001

Message recall failed; try again later

Try again later

### Generate share link

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_generate_url_link.post.html

# Generate share link

Generate a bot share link for inviting users to add the bot as a friend.

Generate a bot share link with custom parameters, used to invite users to add the bot as a friend. When a user adds the bot via this link, the callback\_data parameter is passed through to the developer. callback\_data is at most 32 characters.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/generate\_url\_link

HTTP Method

POST

API Rate Limit

50 QPS

## Request Body

Name

Type

Required

Description

callback\_data

string

No

Data passed back to the bot backend

### Request Example

**Generate share link**

```
POST /v2/generate_url_link
{
  "callback_data": "custom_data_123"
}
```

## Response

### Response Body

Name

Type

Description

data

[Data](#schema-data)

**Data**

Name

Type

Description

url

string

Generated share link

## Response Example

**Share link generated successfully**

```
{
  "data": {
    "url": "https://qun.qq.com/qunpro/robot/qunshare?robot_appid=1234567890&robot_uin=12345678&data=xxx"
  }
}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

10001

Invalid request parameters

Please check whether the request parameters are correct

10002

Invalid request header

Please check whether the request header is correct

10003

Failed to query bot information

Please confirm whether the bot exists

10044

Failed to get uin from protocol header

Please check whether the Authorization Header is correct

11004

Failed to generate share ARK

Try again later

### Interaction event response

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/interactions_interaction_id.put.html

# Interaction event response

After receiving an INTERACTION\_CREATE event, you must call this API to respond, notifying the QQ backend that the event has been received. Otherwise, the client remains in the loading state until it times out.

Only interaction events with type=11 (message button) and type=12 (quick menu) need to be responded to via this API; other types do not require a response (calling it will not return an error). The response must be made within the validity period of the event trigger; after timeout, interaction\_id becomes invalid. The same interaction\_id can only be responded to once. When code=0, for type=14 (clear conversation), the backend sends a gray bar indicating that the conversation has been cleared to prompt the user.

## Request

### Basic Information

Field

Value

HTTP URL

/interactions/{interaction\_id}

HTTP Method

PUT

API Rate Limit

50 QPS

## Path Parameters

Name

Type

Required

Description

interaction\_id

string

Yes

Interaction event ID, obtained from the d.id field of the INTERACTION\_CREATE event. Note that this ID does not include the "INTERACTION\_CREATE:" prefix

## Request Body

Name

Type

Required

Description

code

integer

No

Callback result. 0=success, 1=operation failed, 2=operation too frequent, 3=duplicate operation, 4=no permission, 5=administrators only

### Request Example

**Interaction event response**

```
PUT /interactions/a1b2c3d4-e5f6-7890-abcd-ef1234567890
{
  "code": 0
}
```

## Response

None

## Response Example

**Success**

```
{}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

630001

param invalid

Please check whether the request parameters are correct

630002

get appid failed

Please check whether the Authorization Header is correct

630003

appid invalid

AppID does not match interaction\_id. Please confirm that you are using the correct Bot Token

630004

set interaction data failed

Try again later

630005

get interaction data failed

Try again later

630006

get header appid failed

Please check the request Header

630007

data too large

Please reduce the request body size

630008

interaction preprocess failed

Please check the request parameters

## 4. Rich Media

### Rich Media Message Overview

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/rich-media.html

# Rich media message overview

Rich media messages support sending images, videos, voice, files, and other types. You must first upload the file to obtain `file_info`, then send it via the send message API (`msg_type=7`) with `media.file_info`.

## Supported message types

Image

Voice

Video

File

![Image message](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/image-send.35813305.jpg)

![Voice message](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/voice-send.21dce8bf.jpg)

![Video message](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/video-send.9416079c.jpg)

![File message](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/large-file-transfer.f49ff1e2.jpg)

Supports jpg/png/gif/webp/bmp formats; the image is displayed directly after sending

Supports silk/mp3/wav/ogg formats; a voice bar is displayed after sending

Supports mp4 format; a playable video cover is displayed after sending

Supports any format; a downloadable file card is displayed after sending

## File types and limits

file\_type

Type

Format

Soft limit

Hard limit

1

Image

png / jpg

20 MB

200 MB

2

Video

mp4

30 MB

200 MB

3

Voice

silk

20 MB

200 MB

4

File

\-

200 MB

200 MB

Exceeding the soft limit downgrades the upload to the file type; exceeding the hard limit returns an error.

## Upload methods

For whole-file upload, use the [direct chat upload](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_files.post.html) / [group chat upload](/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_files.post.html) APIs and pass the file URL directly; for larger files, use multipart upload. See [direct chat pre-upload](/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_prepare.post.html) to start the multipart process.

### Multipart upload (recommended)

Suitable for large or local files. Completed in four steps:

```
1. Pre-upload
   Call upload_prepare, passing the file information and checksum
   → Obtain upload_id + block_size + presigned URL for each part

2. Part PUT
   Split the file by block_size and HTTP PUT each part to its corresponding presigned URL

3. Confirm parts
   After each part is PUT successfully, call upload_part_finish to notify the server that the part is complete

4. Complete merge
   After all parts are complete, call the upload API with upload_id
   → Return file_info
```

Flowchart:

```
 upload_prepare         part PUT + part_finish        upload API (merge)
┌──────────────┐    ┌─────────────────────────┐    ┌──────────────────┐
│ Get         │    │  for each chunk:        │    │ POST .../files   │
│ upload_id   │───▶│  PUT → presigned_url    │───▶│ { upload_id }   │
│ block_size  │    │  POST → part_finish     │    │ → file_info      │
│ presigned   │    └─────────────────────────┘    └──────────────────┘
│ URLs        │
└──────────────┘
```

### URL upload

Suitable when the file is already publicly accessible; pass the file URL directly and the platform downloads and stores it automatically.

```
POST /v2/users/{user_openid}/files
{
  "file_type": 1,
  "url": "https://example.com/image.png"
}
```

Returns `file_info`, which can then be used to send messages.

## Send using file\_info

After obtaining `file_info`, set `msg_type=7` in the send message API and put `file_info` in the `media` field:

```
POST /v2/users/{user_openid}/messages
{
  "msg_type": 7,
  "media": {
    "file_info": "{file_info returned in the previous step}"
  }
}
```

> `srv_send_msg=true` allows sending directly during upload, skipping the separate call to the send message API, but it consumes proactive message quota.

## Direct chat and group chat isolation

The file upload APIs for direct chat and group chat are independent, and uploaded files cannot be used across scenarios:

Scenario

Upload API

Direct Chat

`/v2/users/{user_openid}/files`

Group Chat

`/v2/groups/{group_openid}/files`

The corresponding pre-upload and part APIs must also use endpoints for the same scenario.

## Notes

-   `file_info` has a validity period (`ttl`); after it expires, you must re-upload.
-   `md5_10m` (MD5 of the first 10002432 bytes of the file, about 9.54 MB) can be used for instant upload detection to avoid duplicate uploads.
-   The default part size is 5MB; the concurrency and retry policy are issued by the server in `upload_config`.
-   It is recommended to set the upload API timeout to ≥ 5 seconds.

### Direct Chat Rich Media Upload

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_files.post.html

# Direct chat rich media upload

Upload images/videos/voice to a direct chat and return file\_info for the media field of the send message API. Files uploaded via the direct chat API can only be sent to direct chats. File type and size limits:

-   1=Image (png/jpg): soft limit 20MB, hard limit 200MB
-   2=Video (mp4): soft limit 30MB, hard limit 200MB
-   3=Voice (silk): soft limit 20MB, hard limit 200MB
-   4=File: soft limit 200MB, hard limit 200MB. Exceeding the soft limit downgrades the upload to the file type; exceeding the hard limit returns an error.

Three upload methods are supported; choose based on the actual file size and resource source.

## I. Supported upload methods

Method

Description

Limits / Notes

URL upload

Pass `url`, and the platform downloads and stores it

The server may fail to download the resource due to network or other reasons

Multipart upload merge

First complete the multipart upload via `upload_prepare` + `upload_part_finish`, then call this API with `upload_id` to complete the merge

**Recommended**

Direct binary data upload

Pass the file's binary content directly

The data size must not exceed 5M; for larger data, multipart upload is recommended

## II. Recommended flow: multipart upload

1.  Call `upload_prepare` to obtain `upload_id`, `block_size`, and the presigned URL for each part.
2.  Split the file into multiple parts by `block_size`, and upload each part to its corresponding presigned URL via HTTP `PUT`.
3.  After each part is `PUT` successfully, call `upload_part_finish` to notify the server that the part upload is complete.
4.  After all parts are uploaded, call this API with `upload_id` to complete the merge and return `file_info`.

## III. Notes

-   URL upload may fail on the server side. If a download failure occurs, download the resource locally first, then upload it via **direct binary data upload**.
-   Direct binary upload has a 5M size limit; for larger files, use multipart upload instead.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/users/{user\_openid}/files

HTTP Method

POST

API Rate Limit

50 QPS

## Path Parameters

Name

Type

Required

Description

user\_openid

string

Yes

User OpenID

## Request Body

Name

Type

Required

Description

file\_type

integer

No

Media type. 1=Image, 2=Video, 3=Voice, 4=File. Images support png/jpg, videos support mp4, voice supports silk

url

string

No

URL of the media resource, which must start with http; the platform downloads and stores it. Can be empty when merging a multipart upload

srv\_send\_msg

boolean

No

true=send the message directly and consume proactive message quota; the response includes the message ID. false=only return file\_info for the media field of a later send message API call

upload\_id

string

No

Multipart upload task ID. From the upload\_id in the UploadPrepare response. When passed, the multipart upload merge path is used and url can be empty

file\_name

string

No

File name (required for multipart upload or binary upload)

file\_data

string

No

Upload binary data directly. Direct binary upload has a size limit and must be within 5M; if it exceeds this, use URL upload or multipart upload.

### Request Example

**URL image upload**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/files
{
  "file_type": 1,
  "url": "https://example.com/image.png",
  "srv_send_msg": false
}
```

**Multipart upload merge**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/files
{
  "file_type": 2,
  "srv_send_msg": false,
  "file_name": "video.mp4",
  "upload_id": "upload_a1b2c3d4e5f6"
}
```

**Binary upload**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/files

{
  "file_type": 1,
  "file_name": "111.png",
  "file_data": "xxxx binary data of the image"
}
```

## Response

### Response Body

Name

Type

Description

file\_uuid

string

Unique file ID

file\_info

string

File information, used for the media.file\_info field of the send message API. It is serialized binary data internally; developers do not need to parse it and can pass it through directly

ttl

integer

file\_info validity period (seconds). Re-upload is required after expiry. 0 means it can be used long-term

id

string

Unique ID of the sent message. Returned only when srv\_send\_msg=true

raw\_url

string

File download link (COS presigned GET URL), with the same validity period as ttl. Returned only for multipart upload merge (upload\_id path) when file\_type is image/video/voice; not returned for direct URL upload or the file type (file\_type=4)

## Response Example

**Upload successful**

```
{
  "file_uuid": "uuid_a1b2c3d4e5f6",
  "file_info": "AE86C5D3F0E14B238C656C0F6DD1D0479C",
  "ttl": 300
}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

850018

The group is muted or the bot is muted

Please check whether the bot is muted

850019

Unsupported file format

Please check whether file\_type is correct

850026

Failed to download the original file

Please check whether the URL is accessible or try again

850031

The uploaded file exceeds the size limit

Please reduce the file size

850027

Timed out sending data

Try again later

10000

Unsupported operation

Please check the request parameters

40093001

File upload failed, please try again

BDH channel exception during large file multipart upload, please try again

40093002

Exceeded today's file sending capacity limit

Please try again tomorrow or reduce the file size

### Direct Chat Rich Media Pre-upload

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_prepare.post.html

# Direct Chat Rich Media Pre-upload

Preparation before multipart upload of large files in a direct chat. Returns upload\_id, presigned URLs for the parts, and the upload configuration. Next, split the file by block\_size, PUT each part to its presigned URL, and after each part is complete, call the part completion API.

The first step of large file multipart upload. Pass the file size and MD5/SHA1 checksums, and the server returns upload\_id and the presigned URL for each part.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/users/{user\_id}/upload\_prepare

HTTP Method

POST

API Rate Limit

10 QPS

## Path Parameters

Name

Type

Required

Description

user\_id

string

Yes

User OpenID

## Request Body

Name

Type

Required

Description

file\_type

integer

Yes

Business type. 1=Image, 2=Video, 3=Voice, 4=File

file\_size

string

Yes

File size (bytes)

file\_name

string

Yes

File name

md5

string

Yes

MD5 of the entire file

sha1

string

Yes

SHA1 of the entire file

md5\_10m

string

Yes

MD5 checksum of the first 10002432 bytes (about 10MB) of the file

### Request Example

**Pre-upload a video file**

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

## Response

### Response Body

Name

Type

Description

upload\_id

string

Upload task ID, required for subsequent multipart upload and completion merge

block\_size

string

Block size (bytes), default 5MB. The client splits the file according to this size

parts

\[\][UploadPart](#schema-uploadpart)

Part list; each part contains a presigned upload URL

upload\_config

[UploadConfig](#schema-uploadconfig)

Upload configuration, issued by the backend to control client upload behavior

**UploadPart**

Name

Type

Description

index

integer

Part index, starting from 0

presigned\_url

string

Presigned upload URL; the client uploads part data to this URL via HTTP PUT

block\_size

string

Size of this block (bytes)

**UploadConfig**

Name

Type

Description

concurrency

integer

Upload concurrency, default 1

retry\_timeout

integer

Retry timeout (seconds), default 300 (5 minutes)

retry\_delay

integer

Retry delay (seconds), default 1

## Response Example

**Pre-upload successful (3 parts)**

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

### Error Codes

Error code

Description

Troubleshooting suggestion

850018

The group is muted or the bot is muted

Please check whether the bot is muted

850019

Unsupported file format

Please check whether file\_type is correct

850026

Failed to download the original file

Please check whether the URL is accessible or try again

850031

The uploaded file exceeds the size limit

Please reduce the file size

850027

Timed out sending data

Try again later

10000

Unsupported operation

Please check the request parameters

40093001

File upload failed, please try again

Failed to request upload, please try again

### Direct Chat Multipart Upload Completion

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_part_finish.post.html

# Direct chat multipart upload completion

Notify the server that a part has been uploaded. After all parts are complete, use upload\_id as the upload\_id field of MediaUpload to call the upload API once to complete the merge

The second step of multipart upload. Called after each part is successfully PUT to its presigned URL to notify the server that the part upload is complete. After all parts are complete, call /v2/users/{user\_openid}/files with upload\_id to complete the merge.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/users/{user\_id}/upload\_part\_finish

HTTP Method

POST

API Rate Limit

10 QPS

## Path Parameters

Name

Type

Required

Description

user\_id

string

Yes

User OpenID

## Request Body

Name

Type

Required

Description

upload\_id

string

No

Upload task ID

part\_index

integer

No

Part index

block\_size

string

No

Block size (bytes)

md5

string

No

Part MD5

### Request Example

**Notify that part 0 upload is complete**

```
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/upload_part_finish
{
  "upload_id": "upload_a1b2c3d4e5f6",
  "part_index": 0,
  "block_size": "10485760",
  "md5": "c4d8c5f3a2b1e0f9a8b7c6d5e4f3a2b1"
}
```

## Response

None

## Response Example

**Part completion confirmation**

```
{}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

850018

The group is muted or the bot is muted

Please check whether the bot is muted

850019

Unsupported file format

Please check whether file\_type is correct

850026

Failed to download the original file

Please check whether the URL is accessible or try again

850031

The uploaded file exceeds the size limit

Please reduce the file size

850027

Timed out sending data

Try again later

10000

Unsupported operation

Please check the request parameters

40093001

File upload failed, please try again

BDH channel exception while storing the part, please try again

40093002

Exceeded today's file sending capacity limit

Please try again tomorrow or reduce the file size

### Group Chat Rich Media Upload

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_files.post.html

# Group chat rich media upload

Upload images/videos/voice to a group chat and return file\_info for the media field of the send message API. When srv\_send\_msg=true, the message is sent directly and proactive message quota is consumed; when false, only file\_info is returned. Files uploaded via the group API can only be sent to group chats. File type and size limits:

-   1=Image (png/jpg): soft limit 20MB, hard limit 200MB
-   2=Video (mp4): soft limit 30MB, hard limit 200MB
-   3=Voice (silk): soft limit 20MB, hard limit 200MB
-   4=File: soft limit 200MB, hard limit 200MB. Exceeding the soft limit downgrades the upload to the file type; exceeding the hard limit returns an error.

Three upload methods are supported; choose based on the actual file size and resource source.

## I. Supported upload methods

Method

Description

Limits / Notes

URL upload

Pass `url`, and the platform downloads and stores it

The server may fail to download the resource due to network or other reasons

Multipart upload merge

First complete the multipart upload via `upload_prepare` + `upload_part_finish`, then call this API with `upload_id` to complete the merge

**Recommended**

Direct binary data upload

Pass the file's binary content directly

The data size must not exceed 5M; for larger data, multipart upload is recommended

## II. Recommended flow: multipart upload

1.  Call `upload_prepare` to obtain `upload_id`, `block_size`, and the presigned URL for each part.
2.  Split the file into multiple parts by `block_size`, and upload each part to its corresponding presigned URL via HTTP `PUT`.
3.  After each part is `PUT` successfully, call `upload_part_finish` to notify the server that the part upload is complete.
4.  After all parts are uploaded, call this API with `upload_id` to complete the merge and return `file_info`.

## III. Notes

-   URL upload may fail on the server side. If a download failure occurs, download the resource locally first, then upload it via **direct binary data upload**.
-   Direct binary upload has a 5M size limit; for larger files, use multipart upload instead.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/groups/{group\_openid}/files

HTTP Method

POST

API Rate Limit

50 QPS

## Path Parameters

Name

Type

Required

Description

group\_openid

string

Yes

Group OpenID

## Request Body

Name

Type

Required

Description

file\_type

integer

No

Media type. 1=Image, 2=Video, 3=Voice, 4=File. Images support png/jpg, videos support mp4, voice supports silk,mp3,wav

url

string

No

URL of the media resource, which must start with http; the platform downloads and stores it. Can be empty when merging a multipart upload

srv\_send\_msg

boolean

No

true=send the message directly and consume proactive message quota; the response includes the message ID. false=only return file\_info for the media field of a later send message API call

upload\_id

string

No

Multipart upload task ID. From the upload\_id in the UploadPrepare response. When passed, the multipart upload merge path is used and url can be empty

file\_name

string

No

File name (required for multipart upload or binary upload)

file\_data

string

No

Upload binary data directly. Direct binary upload has a size limit and must be within 5M; if it exceeds this, use URL upload or multipart upload.

### Request Example

**URL image upload**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/files
{
  "file_type": 1,
  "url": "https://example.com/image.png",
  "srv_send_msg": false
}
```

**Multipart upload merge**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/files
{
  "file_type": 2,
  "srv_send_msg": false,
  "file_name": "video.mp4",
  "upload_id": "upload_a1b2c3d4e5f6"
}
```

**Binary upload**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/files
{
  "file_type": 1,
  "file_name": "video.mp4",
  "file_data": "xxxx binary data of the image"
}
```

## Response

### Response Body

Name

Type

Description

file\_uuid

string

Unique file ID

file\_info

string

File information, used for the media.file\_info field of the send message API. It is serialized binary data internally; developers do not need to parse it and can pass it through directly

ttl

integer

file\_info validity period (seconds). Re-upload is required after expiry. 0 means it can be used long-term

id

string

Unique ID of the sent message. Returned only when srv\_send\_msg=true

raw\_url

string

File download link (COS presigned GET URL), with the same validity period as ttl. Returned only for multipart upload merge (upload\_id path) when file\_type is image/video/voice; not returned for direct URL upload or the file type (file\_type=4)

## Response Example

**Upload successful**

```
{
  "file_uuid": "uuid_a1b2c3d4e5f6",
  "file_info": "AE86C5D3F0E14B238C656C0F6DD1D0479C",
  "ttl": 300
}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

850018

The group is muted or the bot is muted

Please check whether the bot is muted

850019

Unsupported file format

Please check whether file\_type is correct

850026

Failed to download the original file

Please check whether the URL is accessible or try again

850031

The uploaded file exceeds the size limit

Please reduce the file size

850027

Timed out sending data

Try again later

10000

Unsupported operation

Please check the request parameters

40093001

File upload failed, please try again

BDH channel exception during large file multipart upload, please try again

40093002

Exceeded today's file sending capacity limit

Please try again tomorrow or reduce the file size

### Group Chat Rich Media Pre-upload

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_id_upload_prepare.post.html

# Group Chat Rich Media Pre-upload

Preparation before multipart upload of large files. Returns upload\_id, presigned URLs for the parts, and the upload configuration. Next, split the file by block\_size, PUT each part to its presigned URL, and after each part is complete, call the part completion API.

The first step of large file multipart upload. Pass the file size and MD5/SHA1 checksums, and the server returns upload\_id and the presigned URL for each part.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/groups/{group\_id}/upload\_prepare

HTTP Method

POST

API Rate Limit

10 QPS

## Path Parameters

Name

Type

Required

Description

group\_id

string

Yes

Group OpenID

## Request Body

Name

Type

Required

Description

file\_type

integer

Yes

Business type. 1=Image, 2=Video, 3=Voice, 4=File. Image soft limit 20MB, video soft limit 30MB, voice soft limit 20MB, file soft limit 200MB. Exceeding the soft limit downgrades to the file type; exceeding the 200MB hard limit returns an error

file\_size

string

Yes

File size (bytes)

file\_name

string

Yes

File name

md5

string

Yes

MD5 checksum of the entire file

sha1

string

Yes

SHA1 checksum of the entire file

md5\_10m

string

Yes

MD5 checksum of the first 10002432 bytes (about 10MB) of the file

### Request Example

**Pre-upload a video file**

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

## Response

### Response Body

Name

Type

Description

upload\_id

string

Upload task ID, required for subsequent multipart upload and completion merge

block\_size

string

Block size (bytes), default 5MB. The client splits the file according to this size

parts

\[\][UploadPart](#schema-uploadpart)

Part list; each part contains a presigned upload URL

upload\_config

[UploadConfig](#schema-uploadconfig)

Upload configuration, issued by the backend to control client upload behavior

**UploadPart**

Name

Type

Description

index

integer

Part index, starting from 0

presigned\_url

string

Presigned upload URL; the client uploads part data to this URL via HTTP PUT

block\_size

string

Size of this block (bytes)

**UploadConfig**

Name

Type

Description

concurrency

integer

Upload concurrency, default 1

retry\_timeout

integer

Retry timeout (seconds), default 300 (5 minutes)

retry\_delay

integer

Retry delay (seconds), default 1

## Response Example

**Pre-upload successful (3 parts)**

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

### Error Codes

Error code

Description

Troubleshooting suggestion

850018

The group is muted or the bot is muted

Please check whether the bot is muted

850019

Unsupported file format

Please check whether file\_type is correct

850026

Failed to download the original file

Please check whether the URL is accessible or try again

850031

The uploaded file exceeds the size limit

Please reduce the file size

850027

Timed out sending data

Try again later

10000

Unsupported operation

Please check the request parameters

40093001

File upload failed, please try again

Failed to request upload, please try again

### Group Chat Multipart Upload Completion

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_id_upload_part_finish.post.html

# Group chat multipart upload completion

Notify the server that a part has been uploaded. Must be called after each part is PUT successfully. After all parts are complete, use upload\_id as the upload\_id field of MediaUpload to call the upload API once to complete the merge

The second step of multipart upload. Called after each part is successfully PUT to its presigned URL to notify the server that the part upload is complete. After all parts are complete, call /v2/groups/{group\_openid}/files with upload\_id to complete the merge.

## Request

### Basic Information

Field

Value

HTTP URL

/v2/groups/{group\_id}/upload\_part\_finish

HTTP Method

POST

API Rate Limit

10 QPS

## Path Parameters

Name

Type

Required

Description

group\_id

string

Yes

Group OpenID

## Request Body

Name

Type

Required

Description

upload\_id

string

No

Upload task ID, from the pre-upload response

part\_index

integer

No

Part index, corresponding to UploadPart.index

block\_size

string

No

Actual size of this block (bytes)

md5

string

No

MD5 checksum of this part

### Request Example

**Notify that part 0 upload is complete**

```
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/upload_part_finish
{
  "upload_id": "upload_a1b2c3d4e5f6",
  "part_index": 0,
  "block_size": "10485760",
  "md5": "c4d8c5f3a2b1e0f9a8b7c6d5e4f3a2b1"
}
```

## Response

None

## Response Example

**Part completion confirmation**

```
{}
```

### Error Codes

Error code

Description

Troubleshooting suggestion

850018

The group is muted or the bot is muted

Please check whether the bot is muted

850019

Unsupported file format

Please check whether file\_type is correct

850026

Failed to download the original file

Please check whether the URL is accessible or try again

850031

The uploaded file exceeds the size limit

Please reduce the file size

850027

Timed out sending data

Try again later

10000

Unsupported operation

Please check the request parameters

40093001

File upload failed, please try again

BDH channel exception while storing the part, please try again

40093002

Exceeded today's file sending capacity limit

Please try again tomorrow or reduce the file size

## 5. Message types

### Message types (overview)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/overview.html

# Message types

Specify the message format via `msg_type`; different types correspond to different content fields and send/receive capabilities.

## Sending: msg\_type

When sending a message, specify the format via `msg_type`:

msg\_type

Type

Content Field

Description

0

Text

`content`

Plain text message

2

Markdown

`markdown`

Supports Markdown syntax; see [Markdown message](/wiki/develop/api-v2/server-inter/message/type/markdown.html)

7

Rich Media

`media`

Image/video/voice/file; you must upload first to obtain `file_info`

## Receiving: message\_type

When a user message is received, the `message_type` in the event body indicates the message content type:

message\_type

Meaning

Description

0

Plain text

The `content` field carries the text content

3

Structured card

The `ark_data` field carries the card data

103

Quoted message

The `msg_elements` field carries nested content

> Additional content such as images, videos, voice, and files is carried in the `attachments` field (`content_type` distinguishes the specific type), rather than being represented separately by `message_type`.

## Support by scenario

Type

Direct Chat

Group Chat

Channel

**Text**

Send/receive ✅

Send/receive ✅

Send/receive ✅

**Markdown**

Send ✅ / Receive ❌

Send/receive ✅

Send ✅ / Receive ❌

**Image**

Send/receive ✅

Send/receive ✅

Send/receive ✅

**Video**

Send/receive ✅

Send/receive ✅

Send/receive ✅

**Voice**

Send/receive ✅

Send/receive ✅

Send/receive ✅

**File**

Send/receive ✅

Send/receive ✅

❌

**Structured card**

Send ❌ / Receive ✅

Send ❌ / Receive ✅

Send ❌ / Receive ❌

**Embed**

❌

❌

Send ✅ / Receive ❌

**Emoji reaction**

❌

❌

Send/receive ✅

**Quoted message**

Receive ✅

Receive ✅

Receive ✅

> -   The sending side supports only four types: msg\_type=0/2/3/7 (see the table above)
> -   For the rich media upload process, see [Rich Media Usage Instructions](/wiki/develop/api-v2/server-inter/message/rich-media.html)
> -   Emoji reactions are supported only in channels; see [Emoji Reactions](/wiki/develop/api-v2/server-inter/message/trans/emoji.html) for details

### Markdown Message

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html

# Markdown Message

2026/04/23 Capability Update Notice

Custom Markdown message capability in direct chat and group chat scenarios is now available to all bots, with no separate Markdown template application required. The channel scenario currently requires an invitation for activation.

## Supported Formats

### Heading

```
# Heading 1
## Heading 2
Body text
```

### Text Styles

```
**Bold**
__Underline bold__
_Italic_
*Asterisk italic*
***Bold italic***
~~Strikethrough~~

```

### Links

```
Welcome to: [🔗Tencent](https://www.qq.com)  
Documentation available at <https://doc.qq.com>
```

### Images

For image resources in Markdown messages, use a resource URL that is publicly accessible; the Open Platform will download and re-host the resource.

```
![text #208px #320px](https://resource5-1255303497.cos.ap-guangzhou.myqcloud.com/abcmouse_word_watch/markdown/building.png)
```

### Ordered List

```
# Ordered List
1. Welcome ceremony for newcomers landing on Peach Blossom Spring Island
2. The Sunshine Guidelines help build a warmer channel
3. Islanders share stories and chat while cooling off
```

### Unordered List

```
# Unordered List
- Welcome ceremony for newcomers landing on Peach Blossom Spring Island
- The Sunshine Guidelines help build a warmer channel
- Islanders share stories and chat while cooling off
```

### Nested Lists

```
# Ordered List Heading
1. First nesting level
    - If ordinary text precedes the list, you need to separate it with a blank line; otherwise it will not be recognized
    - If it is a paragraph tag such as a heading, no blank line is needed
2. Second nesting level
    1. I am an ordered list; second-level lists need 4 leading spaces
    2. Unordered and ordered lists can be nested within each other, but unlimited nesting is not recommended.
```

### Blockquote

```
> Green, green is your collar; deep, deep is my longing. It is all for you, my lord, that I ponder to this day
> In the fourth month summer begins; in the sixth month the heat passes. Our forebears were not strangers—how could they bear to treat me so?
> Autumn days are bleak and chill; all the plants have withered. Amid the misery of upheaval, where can I find refuge?
The Book of Songs, "Minor Odes"
```

### Horizontal Rule

```
This is paragraph 1
***
This is paragraph 2
```

### Multiple Lines

```
First line

Second line

\u200B
\u200B
Third line
```

## Sending Methods

Example of using a custom Markdown message:

```
{
  "markdown": {
    "content": "# Title \n## Intro is very happy \nContent[🔗Tencent](https://www.qq.com)"
  }
}
```

Example of using a Markdown template message:

```
// Template example

#{{.title}}

![img#618px #249px]({{.image}})

*{{.para1}}
*{{.para2}}

## {{.desc}}

{{.content}}[{{.link_introduction}}]({{.link}})

// Send case
{
	"markdown": {
		"custom_template_id": "101993071_1658748972",
		"params": [{
				"key": "title",
				"values": ["Title"]
			},
			{
				"key": "image",
				"values": [
					"https://resource5-1255303497.cos.ap-guangzhou.myqcloud.com/abcmouse_word_watch/other/mkd_img.png"
				]
			},
			{
				"key": "para1",
				"values": ["Paragraph 1"]
			},
			{
				"key": "para2",
				"values": ["Paragraph 2"]
			},
			{
				"key": "desc",
				"values": ["Introduction"]
			},
			{
				"key": "content",
				"values": ["I am very happy in this sub-channel"]
			},
			{
				"key": "link_introduction",
				"values": ["Link description"]
			},
			{
				"key": "link",
				"values": ["https://www.qq.com"]
			}
		]
	}
}
```

## Data Structures and Protocols

The markdown field value in a message send is a JSON object; the fields are as follows:

**Attribute**

**Type**

**Required**

**Description**

content

string

No

Custom Markdown text content

custom\_template\_id

string

No

Markdown template ID, obtained after applying for the template

params

Array

No

{key: xxx, values: xxx}, a kv mapping of template variables to fill values

### Structured Card Message

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/ark.html

# Structured Card Message

Description

Developers who meet the eligibility requirements can obtain permission by applying to platform operations.

## Sending Methods

Choose an appropriate Structured Card Message (ARK) template, fill in the template variables as key-value pairs, and send it. Each template defines its own variables (`#XXX#`), whose types can be strings, arrays, URLs, etc.

### Data Structure

Structure of the `ark` field in the message sending API:

Property

Type

Required

Description

template\_id

int

Yes

Template ID; can be 23 / 24 / 37

kv

kv array

Yes

`[{key: "#variable#", value: "fill value"}]`, the mapping of template variables to fill values

When the variable type is an array, kv elements use the `obj` nested array structure:

```
{
  "key": "#LIST#",
  "obj": [
    {
      "obj_kv": [
        { "key": "desc", "value": "Text" },
        { "key": "link", "value": "https://..." }
      ]
    }
  ]
}
```

### Request Example

```
{
  "ark": {
    "template_id": 23,
    "kv": [
      { "key": "#DESC#", "value": "Bot subscription message" },
      { "key": "#PROMPT#", "value": "XX Bot" },
      { "key": "#TITLE#", "value": "XX Bot message" },
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

## Template 23 — Link + Text List

![23](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/23.dcdba41f.png)

Template ID = 23.

### Template Format

```
{
  "app": "com.tencent.channel.robot",
  "view": "albumAddPic",
  "ver": "0.0.0.1",
  "desc": "#DESC#",
  "prompt": "[QQ Mini Program]#PROMPT#",
  "meta": {
    "detail": {
      "list": "#LIST#"
    }
  }
}
```

### Field Description

Variable

Type

Description

#DESC#

string

Description

#PROMPT#

string

Prompt message

#LIST#

array

Text list, where each element is `{desc, link}`

**#LIST# Element Structure**:

Field

Type

Description

desc

string

Text content

link

string

Redirect link (must be registered in advance); if omitted, only the text is displayed

### Request Example

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
          { "obj_kv": [{ "key": "desc", "value": "Requirement title: UI issue resolution" }] },
          { "obj_kv": [{ "key": "desc", "value": "Current status \"In trial\" Click the action below to change the status directly to:" }] },
          {
            "obj_kv": [
              { "key": "desc", "value": "Reviewed" },
              { "key": "link", "value": "https://qun.qq.com" }
            ]
          },
          {
            "obj_kv": [
              { "key": "desc", "value": "Scheduled" },
              { "key": "link", "value": "https://qun.qq.com" }
            ]
          },
          {
            "obj_kv": [
              { "key": "desc", "value": "In development" },
              { "key": "link", "value": "https://qun.qq.com" }
            ]
          },
          {
            "obj_kv": [
              { "key": "desc", "value": "In incremental testing" },
              { "key": "link", "value": "https://qun.qq.com" }
            ]
          },
          { "obj_kv": [{ "key": "desc", "value": "Please follow up" }] }
        ]
      }
    ]
  }
}
```

## Template 24 — Text + Thumbnail

![24](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/24.4656049a.png)

Template ID = 24.

### Template Format

```
{
  "app": "com.tencent.channelrobot.smallpic",
  "view": "albumAddPic",
  "ver": "0.0.0.1",
  "desc": "#DESC#",
  "prompt": "[QQ Mini Program]#PROMPT#",
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

### Field Description

Variable

Type

Description

#DESC#

string

Description

#PROMPT#

string

Prompt text

#TITLE#

string

Title

#METADESC#

string

Detail description

#IMG#

string

Image link

#LINK#

string

Redirect link

#SUBTITLE#

string

Source

### Request Example

```
{
  "ark": {
    "template_id": 24,
    "kv": [
      { "key": "#DESC#", "value": "..." },
      { "key": "#PROMPT#", "value": "Notification" },
      { "key": "#TITLE#", "value": "Title" },
      { "key": "#METADESC#", "value": "Meta description" },
      { "key": "#IMG#", "value": "https://pub.idqqimg.com/pc/misc/files/20190820/2f4e70ae3355ece23d161cf5334d4fc1jzjfmtep.png" },
      { "key": "#LINK#", "value": "https://qq.com" },
      { "key": "#SUBTITLE#", "value": "Subtitle" }
    ]
  }
}
```

## Template 37 — Large Image

![37](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/37.2955062b.png)

Template ID = 37.

### Template Format

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

### Field Description

Variable

Type

Description

#PROMPT#

string

Prompt message

#METATITLE#

string

Title

#METASUBTITLE#

string

Subtitle

#METACOVER#

string

Large image, size 975×540

#METAURL#

string

Redirect link

### Request Example

```
{
  "ark": {
    "template_id": 37,
    "kv": [
      { "key": "#PROMPT#", "value": "Notification alert" },
      { "key": "#METATITLE#", "value": "Title" },
      { "key": "#METASUBTITLE#", "value": "Subtitle" },
      { "key": "#METACOVER#", "value": "https://vfiles.gtimg.cn/vupload/20211029/bf0ed01635493790634.jpg" },
      { "key": "#METAURL#", "value": "https://qq.com" }
    ]
  }
}
```

### Embed Message

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/embed.html

# Embed Message

**Direct Chat**

**Group Chat**

**Text Sub-channel**

**Channel Direct Message**

Bot receives

\-

\-

\-

\-

Bot sends

Not supported

Not supported

Supported

Supported

## Style

![embed](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/message-embed.18d8bc6d.jpg)

## Data Structures and Protocols

### Content-Type

```
application/json
```

### Parameters

Field Name

Type

Description

embed

[MessageEmbed](/wiki/develop/api-v2/server-inter/message/template/model.html#messageembed)

Embed message details

-   embed.thumbnail is optional; leave it empty if there is no thumbnail.
-   embed.fields.name is text.

### Response

Returns a [Message](/wiki/develop/api-v2/server-inter/message/template/model.html#message) object.

### Error Codes

See [error codes](/wiki/develop/api-v2/openapi/error/error.html) for details.

### Example

Request payload

```
{
  "embed": {
    "title": "Title",
    "prompt": "Message notification",
    "thumbnail": {
      "url": "xxxxxx"
    },
    "fields": [
      {
        "name": "Current level: Gold"
      },
      {
        "name": "Previous level: Silver"
      },
      {
        "name": "😁Keep it up"
      }
    ]
  }
}
```

Response payload

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
      "title": "Title",
      "prompt": "xxxx",
      "description": "",
      "thumbnail": {
        "url": "xxxxxx"
      },
      "fields": [
        {
          "name": "Current level: Gold"
        },
        {
          "name": "Previous level: Silver"
        },
        {
          "name": "😁Keep it up"
        }
      ]
    }
  ],
  "pinned": false,
  "type": 0,
  "flags": 0
}
```

### Message Interaction Overview

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/overview.html

# Message Interaction Overview

Description

In various message scenarios, developers can implement custom interaction methods with users on the message body.

Message button

Text link

![Message button](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/message-btn.94002609.jpg)

![Text link](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.36.0/assets/img/text-chain.b2f9b0fb.jpg)

## Message Button Interaction Flow

The overall flow of message button interaction is as follows:

1.  **Send a message with buttons**: The bot sends a message containing the `keyboard` field, and the user sees the buttons attached at the bottom of the message
2.  **The user clicks a button**: The platform pushes the [`INTERACTION_CREATE`](/wiki/develop/api-v2/autogen/event/interaction_create.html) event to the bot
3.  **The bot responds to the interaction**: The bot calls [PUT /interactions/{interaction\_id}](/wiki/develop/api-v2/autogen/api/interactions_interaction_id.put.html) to reply to the user

### Carrying a Keyboard When Sending a Message

Pass the button configuration in the message's `keyboard` field; both template buttons and custom buttons are supported.

-   Sending a direct chat message: [keyboard field reference](/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html#schema-keyboard)
-   Sending a group chat message: [keyboard field reference](/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html#schema-keyboard)

**Button data example** (configure and cache a batch of buttons in one place, then dynamically extract them to generate action buttons):

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
                "label": "Confirm",
                "visited_label": "Confirmed",
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

### Responding to Interactions

After receiving the `INTERACTION_CREATE` event, you must call [PUT /interactions/{interaction\_id}](/wiki/develop/api-v2/autogen/api/interactions_interaction_id.put.html) to respond within the specified time; otherwise it will time out.

**Response timeout**: 3 seconds for command callback scenarios. Respond as soon as possible after receiving the event to avoid no feedback on the user side due to a timeout.

### Text Interaction

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/text-chain.html

# Text Interaction

Description

QQBot provides interactive capabilities for text messages. When developers send messages in the specified format, users can perform click interactions on the message body, such as mentioning someone or following a link.

## Using @ Mentions

Description

Group chats & text sub-channels support message types that contain text, such as text messages, image-text messages, and Markdown messages.

1.  @Mention a user | Available in group chats and text sub-channels

Embedded text format: `<qqbot-at-user id="" />`. Protocol: `<@userid>` will be deprecated; please use the latest format above.

Displayed on the client as: @User label

2.  @All members | Available only in text sub-channels

Embedded text format: `<qqbot-at-everyone />`. Protocol: `@everyone` will be deprecated; please use the latest format above.

Displayed on the client as: @All members label. The bot must have permission to send @All members messages,

## Command Operations

Currently supported only in Markdown.

**1\. Enter command format (text is sent directly after clicking)**

Embedded text format:

`<qqbot-cmd-enter text="xxx" />`

Displayed on the client as: /Enter command clickable label. Group chats and text sub-channels do not support this capability.

-   `text` The text sent directly after the user clicks; required; maximum 100 characters; URL-encode the value when passing it.

**2\. Parameter command format (after clicking, the text is inserted into the input box for the user to edit and send)**

Embedded text format:

`<qqbot-cmd-input text="xxx" show="xxx" reference="false" />`

Displayed on the client as: /Parameter command clickable label

-   `text` The text inserted into the input box after the user clicks; required; maximum 100 characters; URL-encode the value when passing it.
-   `show` The text the user sees in the message; optional; defaults to the text value; maximum 100 characters; URL-encode the value when passing it.
-   `reference` Whether to include a quote reply to the original message when inserting into the input box; optional; defaults to `false`; when set to `true`, the inserted text includes a quote reply.

## Jumping to a Sub-channel

Available only in channels.

Embedded text format: `<#channel_id>`

Displayed on the client as: #XXX text sub-channel label; clicking it jumps to the sub-channel. Only sub-channels within the current channel are supported.

## Emoji

Available only in channels; parsed as a system emoji. For specific emoji IDs, see [Emoji List](/wiki/develop/api-v2/openapi/emoji/model.html#Emoji List).

Embedded text format: `<emoji:id>`

-   Only system emojis with `type = 1` are supported.
-   Emoji with `type = 2` can be filled in directly as a string.

### Message Button

> Source: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/msg-btn.html

# Message Button

Description

In addition to Markdown messages, buttons can be attached at the bottom of a message.

## Sending Methods

[Apply for use] Button template. Button templates do not currently support variable substitution.

```
{
    "keyboard": {
        "id": "123" // obtained after applying for the template
    }
}
```

[Internal invitation activation] Custom button

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
            ] // custom button content; up to 5 rows of buttons, with up to 5 buttons per row.
        }
    }
}
```

## Data Structures and Protocols

The value of the keyboard field in the message sending API is a JSON object {}. Each element in the rows array represents a row of buttons.

Each button is a JSON object with the following fields:

**Attribute**

**Type**

**Required**

**Description**

id

string

No

Button ID: must be unique within a keyboard message

render\_data.label

string

Yes

Text on the button

render\_data.visited\_label

string

Yes

Text on the button after it is clicked

render\_data.style

int

Yes

Button style: 0 gray outline, 1 blue outline

action.type

int

Yes

Set to 0 for a link button: http or mini program scheme recognized by the client; set to 1 for a callback button: calls the backend API and passes data to the backend; set to 2 for a command button: automatically inserts @bot data into the input box

action.permission.type

int

Yes

0: only specified users can operate; 1: only administrators can operate; 2: everyone can operate; 3: specified identity groups can operate (channels only)

action.permission.specify\_user\_ids

array

No

List of user IDs with permission

action.permission.specify\_role\_ids

array

No

List of identity group IDs with permission (channel only)

action.data

string

Yes

Operation-related data

action.reply

bool

No

Available for command buttons. Whether the command includes a quoted reply to this message. Defaults to false. Supported since version 8983

action.enter

bool

No

Available for command buttons; clicking the button automatically sends data directly. Defaults to false. Supported since version 8983.

action.anchor

int

No

This field is valid only for command buttons. Once set, the action.enter configuration is ignored.  
When set to 1, clicking the button automatically opens the Mobile QQ image picker; other values currently have no effect.  
(Supported only in the direct chat scenario on mobile version 8983+; not supported on desktop)

action.click\_limit

int

No

[Deprecated] Number of times the button can be clicked. Unlimited by default.

action.at\_bot\_show\_channel\_list

bool

No

[Deprecated] Available for command buttons; opens the sub-channel selector. Defaults to false.

action.unsupport\_tips

string

Yes

Toast text displayed when the client does not support this action

Example

```
{
  "rows": [
    {
      "buttons": [
        {
          "id": "1",
          "render_data": {
            "label": "⬅️Previous Page",
            "visited_label": "⬅️Previous Page"
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
            "unsupport_tips": "Compatibility text",
            "data": "data",
            "at_bot_show_channel_list": true
          }
        },
        {
          "id": "2",
          "render_data": {
            "label": "➡️Next Page",
            "visited_label": "➡️Next Page"
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
            "unsupport_tips": "Compatibility text",
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
            "label": "📅 Check-in (5)",
            "visited_label": "📅 Check-in (5)"
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
            "unsupport_tips": "Compatibility text",
            "data": "data",
            "at_bot_show_channel_list": true
          }
        }
      ]
    }
  ]
}
```

## Related Events and APIs

When a user clicks a callback button, an `INTERACTION_CREATE` event is triggered. After receiving the event, the bot must call `PUT /interactions/{interaction_id}` to respond; otherwise, the client remains in a loading state until it times out.

-   Event details: [INTERACTION\_CREATE](/wiki/develop/api-v2/autogen/event/interaction_create.html)
-   Response API: [PUT /interactions/{interaction\_id}](/wiki/develop/api-v2/autogen/api/interactions_interaction_id.put.html)

## 6. Events

### Direct Chat Message Event (C2C_MESSAGE_CREATE)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/c2c_message_create.html

# Direct Chat Message Event

Triggered when a user sends a direct chat message to the bot. To ensure message delivery, the same msg\_id may be pushed repeatedly; developers must deduplicate using msg\_seq.

To ensure message delivery, the same msg\_id may be pushed repeatedly; deduplicate using msg\_idx in message\_scene.ext. message\_type determines the message structure: 0=plain text, 3=ARK card (ark\_data has a value), 103=quoted message (msg\_elements has a value; message\_scene.ext contains ref\_msg\_idx).

## Event

Field

Value

Event name

C2C\_MESSAGE\_CREATE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### Event Body

Name

Type

Description

id

string

Message ID, which can be used for passive replies and recall

author

[User](#schema-user)

Sender (user\_openid has a value)

content

string

Message text content

timestamp

string

Message send time, RFC3339 format

message\_type

integer

Message content type: 0=plain text, 3=structured card, 101=parallel message, 102=chat history, 103=quoted message

message\_scene

[MessageScene](#schema-messagescene)

Message scene context (including message index, authentication token, etc.)

attachments

\[\][MessageAttachment](#schema-messageattachment)

Message attachments (images, files, voice, etc.)

ark\_data

[ARKData](#schema-arkdata)

Structured card message data (has a value when message\_type=3)

msg\_elements

\[\][MsgElement](#schema-msgelement)

List of message elements (contains the quoted content when message\_type=103 is a quoted message)

**User**

Name

Type

Description

id

string

Unique user identifier (OpenID format)

username

string

User nickname

bot

boolean

Whether it is a bot

union\_openid

string

Cross-application unified user OpenID (may be empty)

union\_user\_account

string

Cross-application unified user account (may be empty)

user\_openid

string

User OpenID (used in direct chat scenarios)

member\_openid

string

Group member OpenID (used in group chat scenarios)

member\_role

string

Role in the group. member=regular member, admin=administrator, owner=group owner

**MessageScene**

Name

Type

Description

source

string

Scene source. default=default chat window

ext

\[\]string

List of extended data in key=value format: msg\_idx=message index, used in quoted scenarios; ref\_msg\_idx=index of the quoted message; auth\_token=authentication token

**MessageAttachment**

Name

Type

Description

url

string

Attachment download URL

filename

string

File name

width

integer

Image width (pixels); this field is absent for non-image attachments

height

integer

Image height (pixels); this field is absent for non-image attachments

size

integer

File size (bytes)

content\_type

string

Attachment content type (MIME type): voice=voice message, image/jpeg=JPEG image, image/png=PNG image, image/gif=GIF image, video/mp4=MP4 video, file=group file

voice\_wav\_url

string

URL of the WAV file converted from SILK and other formats for voice messages

asr\_refer\_text

string

ASR reference result for voice messages

**ARKData**

Name

Type

Description

prompt

string

User action prompt text in card messages

ark\_type

string

Card message type identifier: tuwen = image-text H5 (e.g., Kuaishou share link) feed = image-text card (group album, channel post, share card) miniapp = mini program (WeChat mini program, QQ mini program, Bilibili, etc.) map = location card contact\_card = friend contact card video\_share = video share music\_together = listen to music together picture = image

ark\_name

string

Localized name of the card message type, such as "Image-Text H5", "Mini Program", and "Image-Text Card"

fields

object

Card message fields; common keys: tag/tags=source tag, title=title, desc=description, jump\_url=jump link, preview=preview image, source=source name, source\_logo=source icon, tag\_icon=tag icon, nickname=nickname, avatar=avatar, address=address

**MsgElement**

Name

Type

Description

msg\_idx

string

Reference message index of the message element in the list

author

[User](#schema-user)

Message sender corresponding to this element

message\_type

integer

Message content type: 0=plain text, 3=structured card, 101=parallel message, 102=chat history, 103=quoted message

content

string

Message body content

attachments

\[\][MessageAttachment](#schema-messageattachment)

Attachments carried by this element

ark\_data

[ARKData](#schema-arkdata)

Structured card message data (has a value when message\_type=3)

msg\_elements

\[\][MsgElement](#schema-msgelement)

Nested message element list (recursive structure)

### Event Example

**Example 1**

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
  "content": "Hello, any recommended activities today?",
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

**Example 2**

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
  "content": "[Card message] Mini program\nSummary: [Daily check-in] Complete today's study check-in now",
  "message_type": 3,
  "ark_data": {
    "ark_type": "miniapp",
    "ark_name": "Mini Program",
    "prompt": "[Daily check-in] Complete today's study check-in now",
    "fields": {
      "title": "Complete today's study check-in now",
      "source": "Study Assistant",
      "tag": "WeChat Mini Program",
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

**Example 3**

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
  "content": "That suggestion is very helpful, thank you!",
  "message_type": 103,
  "msg_elements": [
    {
      "msg_idx": "REFIDX_aaaaaaaaaaaaaaa==",
      "message_type": 103,
      "content": "Keep reading for half an hour every day, and you'll notice a change in yourself after a month"
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

### Group @Bot Message (GROUP_AT_MESSAGE_CREATE)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_at_message_create.html

# Group @Bot Message

Triggered when a user sends a message mentioning the bot in a group. This is the event most commonly received by bots. The @bot prefix is automatically removed from the content field. To ensure message delivery, the same msg\_id may be pushed repeatedly; developers must deduplicate using msg\_seq.

## Event

Field

Value

Event name

GROUP\_AT\_MESSAGE\_CREATE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### Event Body

Name

Type

Description

id

string

Message ID, which can be used for passive replies and recall

author

[User](#schema-user)

Sender (member\_openid has a value)

content

string

Message text content (the @bot prefix has been removed)

group\_openid

string

Group OpenID

timestamp

string

Message send time, RFC3339 format

message\_type

integer

Message content type (same as C2C\_MESSAGE\_CREATE)

message\_scene

[MessageScene](#schema-messagescene)

Message scene context

attachments

\[\][MessageAttachment](#schema-messageattachment)

Message attachments

mentions

\[\][User](#schema-user)

List of users mentioned in the message (excluding the bot itself)

ark\_data

[ARKData](#schema-arkdata)

Structured card message data

msg\_elements

\[\][MsgElement](#schema-msgelement)

Message element list

**User**

Name

Type

Description

id

string

Unique user identifier (OpenID format)

username

string

User nickname

bot

boolean

Whether it is a bot

union\_openid

string

Cross-application unified user OpenID (may be empty)

union\_user\_account

string

Cross-application unified user account (may be empty)

user\_openid

string

User OpenID (used in direct chat scenarios)

member\_openid

string

Group member OpenID (used in group chat scenarios)

member\_role

string

Role in the group. member=regular member, admin=administrator, owner=group owner

**MessageScene**

Name

Type

Description

source

string

Scene source. default=default chat window

ext

\[\]string

List of extended data in key=value format: msg\_idx=message index, used in quoted scenarios; ref\_msg\_idx=index of the quoted message; auth\_token=authentication token

**MessageAttachment**

Name

Type

Description

url

string

Attachment download URL

filename

string

File name

width

integer

Image width (pixels); this field is absent for non-image attachments

height

integer

Image height (pixels); this field is absent for non-image attachments

size

integer

File size (bytes)

content\_type

string

Attachment content type (MIME type): voice=voice message, image/jpeg=JPEG image, image/png=PNG image, image/gif=GIF image, video/mp4=MP4 video, file=group file

voice\_wav\_url

string

URL of the WAV file converted from SILK and other formats for voice messages

asr\_refer\_text

string

ASR reference result for voice messages

**ARKData**

Name

Type

Description

prompt

string

User action prompt text in card messages

ark\_type

string

Card message type identifier: tuwen = image-text H5 (e.g., Kuaishou share link) feed = image-text card (group album, channel post, share card) miniapp = mini program (WeChat mini program, QQ mini program, Bilibili, etc.) map = location card contact\_card = friend contact card video\_share = video share music\_together = listen to music together picture = image

ark\_name

string

Localized name of the card message type, such as "Image-Text H5", "Mini Program", and "Image-Text Card"

fields

object

Card message fields; common keys: tag/tags=source tag, title=title, desc=description, jump\_url=jump link, preview=preview image, source=source name, source\_logo=source icon, tag\_icon=tag icon, nickname=nickname, avatar=avatar, address=address

**MsgElement**

Name

Type

Description

msg\_idx

string

Reference message index of the message element in the list

author

[User](#schema-user)

Message sender corresponding to this element

message\_type

integer

Message content type: 0=plain text, 3=structured card, 101=parallel message, 102=chat history, 103=quoted message

content

string

Message body content

attachments

\[\][MessageAttachment](#schema-messageattachment)

Attachments carried by this element

ark\_data

[ARKData](#schema-arkdata)

Structured card message data (has a value when message\_type=3)

msg\_elements

\[\][MsgElement](#schema-msgelement)

Nested message element list (recursive structure)

### Event Example

**Example 1**

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "author": {
    "id": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "member_role": "member",
    "username": "Xiaoming",
    "bot": false
  },
  "content": " /today's weather ",
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

**Example 2**

```
{
  "id": "ROBOT1.0_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
  "author": {
    "id": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "member_openid": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "member_role": "member",
    "username": "Xiaohong",
    "bot": false
  },
  "content": " Look at this landscape photo ",
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

**Example 3**

```
{
  "id": "ROBOT1.0_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
  "author": {
    "id": "D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1",
    "member_openid": "D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1",
    "member_role": "owner",
    "username": "Xiaohua",
    "bot": false
  },
  "content": " ",
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "message_type": 103,
  "timestamp": "2026-07-21T10:10:00+08:00",
  "msg_elements": [
    {
      "content": "=== Message 1 ===\n[Message content] Today's study plan has been completed\n\n=== Message 2 ===\n[Message content] Great! Keep it up, and keep going tomorrow\n\n=== Message 3 ===\n[Message content] Okay, let's make progress together!"
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

### Group Message (Full Mode) (GROUP_MESSAGE_CREATE)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_message_create.html

# Group Message (Full Mode)

After the bot enables the "receive all messages" feature, every message in the group (not limited to those mentioning the bot) triggers this event. The meaning of each field is exactly the same as in GROUP\_AT\_MESSAGE\_CREATE.

## Event

Field

Value

Event name

GROUP\_MESSAGE\_CREATE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### Event Body

Name

Type

Description

id

string

Message ID, which can be used for passive replies and recall

author

[User](#schema-user)

Sender

content

string

Message text content (the @bot prefix has been removed)

group\_openid

string

Group OpenID

timestamp

string

Message send time, RFC3339 format

message\_type

integer

Message content type

message\_scene

[MessageScene](#schema-messagescene)

Message scene context

attachments

\[\][MessageAttachment](#schema-messageattachment)

Message attachments

mentions

\[\][User](#schema-user)

List of users mentioned in the message

ark\_data

[ARKData](#schema-arkdata)

Structured card message data

msg\_elements

\[\][MsgElement](#schema-msgelement)

Message element list

**User**

Name

Type

Description

id

string

Unique user identifier (OpenID format)

username

string

User nickname

bot

boolean

Whether it is a bot

union\_openid

string

Cross-application unified user OpenID (may be empty)

union\_user\_account

string

Cross-application unified user account (may be empty)

user\_openid

string

User OpenID (used in direct chat scenarios)

member\_openid

string

Group member OpenID (used in group chat scenarios)

member\_role

string

Role in the group. member=regular member, admin=administrator, owner=group owner

**MessageScene**

Name

Type

Description

source

string

Scene source. default=default chat window

ext

\[\]string

List of extended data in key=value format: msg\_idx=message index, used in quoted scenarios; ref\_msg\_idx=index of the quoted message; auth\_token=authentication token

**MessageAttachment**

Name

Type

Description

url

string

Attachment download URL

filename

string

File name

width

integer

Image width (pixels); this field is absent for non-image attachments

height

integer

Image height (pixels); this field is absent for non-image attachments

size

integer

File size (bytes)

content\_type

string

Attachment content type (MIME type): voice=voice message, image/jpeg=JPEG image, image/png=PNG image, image/gif=GIF image, video/mp4=MP4 video, file=group file

voice\_wav\_url

string

URL of the WAV file converted from SILK and other formats for voice messages

asr\_refer\_text

string

ASR reference result for voice messages

**ARKData**

Name

Type

Description

prompt

string

User action prompt text in card messages

ark\_type

string

Card message type identifier: tuwen = image-text H5 (e.g., Kuaishou share link) feed = image-text card (group album, channel post, share card) miniapp = mini program (WeChat mini program, QQ mini program, Bilibili, etc.) map = location card contact\_card = friend contact card video\_share = video share music\_together = listen to music together picture = image

ark\_name

string

Localized name of the card message type, such as "Image-Text H5", "Mini Program", and "Image-Text Card"

fields

object

Card message fields; common keys: tag/tags=source tag, title=title, desc=description, jump\_url=jump link, preview=preview image, source=source name, source\_logo=source icon, tag\_icon=tag icon, nickname=nickname, avatar=avatar, address=address

**MsgElement**

Name

Type

Description

msg\_idx

string

Reference message index of the message element in the list

author

[User](#schema-user)

Message sender corresponding to this element

message\_type

integer

Message content type: 0=plain text, 3=structured card, 101=parallel message, 102=chat history, 103=quoted message

content

string

Message body content

attachments

\[\][MessageAttachment](#schema-messageattachment)

Attachments carried by this element

ark\_data

[ARKData](#schema-arkdata)

Structured card message data (has a value when message\_type=3)

msg\_elements

\[\][MsgElement](#schema-msgelement)

Nested message element list (recursive structure)

### Event Example

**Example 1**

```
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "author": {
    "id": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "member_role": "member",
    "username": "Xiaoming",
    "bot": false
  },
  "content": "Good morning, everyone!",
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

**Example 2**

```
{
  "id": "ROBOT1.0_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
  "author": {
    "id": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "member_openid": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "member_role": "owner",
    "username": "Xiaohong",
    "bot": false
  },
  "content": "Sharing a landscape photo from today",
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

**Example 3**

```
{
  "id": "ROBOT1.0_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
  "author": {
    "id": "D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1",
    "member_openid": "D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1",
    "member_role": "admin",
    "username": "Xiaohua",
    "bot": false
  },
  "content": " ",
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "message_type": 103,
  "timestamp": "2026-07-21T10:10:00+08:00",
  "msg_elements": [
    {
      "content": "=== Message 1 ===\n[Message content] Today's study plan has been completed\n\n=== Message 2 ===\n[Message content] Great! Keep it up, and keep going tomorrow\n\n=== Message 3 ===\n[Message content] Okay, let's make progress together!"
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

### Interaction Event (INTERACTION_CREATE)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/interaction_create.html

# Interaction Event

This event is triggered by user interactions with the bot, including message button clicks, quick menu callbacks, message feedback, clearing conversations, entering/leaving story collections, switching models, and user/group authorization. After receiving the event, call the PUT /interactions/{interaction\_id} API to respond; otherwise, the client remains loading until it times out.

Only type=11 (message button) and type=12 (quick menu) require calling PUT /interactions/{interaction\_id} to respond; other types (message feedback, clearing conversations, entering/leaving story collections, switching models, authorization, etc.) do not require a response. The same interaction\_id can be responded to only once and becomes invalid after timeout.

## Event

Field

Value

Event name

INTERACTION\_CREATE

Intent

INTERACTION (1<<26)

### Event Body

Name

Type

Description

id

string

Event ID, used for passive message sending and interaction callbacks

type

integer

Interaction type 11 - message button callback (INLINE\_KEYBOARD): the user clicks an inline keyboard button in a message 12 - direct chat quick menu callback (CALLBACK\_COMMAND): the user clicks a custom menu in the direct chat scenario 13 - message feedback (MESSAGE\_FEEDBACK): the user likes/dislikes a bot message 14 - clear conversation (CLEAR\_SESSION): the user clears the bot conversation history 15 - enter/leave story collection (IN\_OUT\_STORY): the user enters or exits a story collection 16 - switch model (SWITCH\_MODEL): the user switches the bot model 18 - user authorization (USER\_AUTHORIZE): user authorization event 19 - group authorization (GROUP\_AUTHORIZE): group authorization event 20 - group authorization status change (GROUP\_AUTHORIZE\_STATUS)

scene

string

Event scene. c2c=direct chat, group=group chat, guild=channel

chat\_type

integer

Chat scenario. 0=channel, 1=group chat, 2=direct chat

timestamp

string

Trigger time, in RFC3339 format

guild\_id

string

Channel OpenID (has a value only in channel scenarios)

channel\_id

string

Sub-channel OpenID (has a value only in channel scenarios)

user\_openid

string

User OpenID (has a value only in direct chat scenarios)

group\_openid

string

Group OpenID (has a value only in group chat scenarios)

group\_member\_openid

string

Group member OpenID (has a value only in group chat scenarios)

data

[InteractionData](#schema-interactiondata)

Interaction data

version

integer

Version number, defaults to 1

application\_id

string

Bot AppID

**InteractionData**

Name

Type

Description

type

integer

Interaction data type, with the same meaning as the outer type. 11=message button click, 12=quick menu click, 13=message feedback click, 14=clear conversation click, 15=story collection click, 16=switch model click

resolved

[InteractionResolved](#schema-interactionresolved)

Resolved interaction data

**InteractionResolved**

Name

Type

Description

button\_data

string

The value of the button's data field (set when sending a message button); in the message feedback scenario, this is the callback data

button\_id

string

The value of the button's id field (set when sending a message button)

user\_id

string

Operating user ID (has a value only in channel scenarios)

feature\_id

string

Feature ID (has a value only for the quick menu; set on the admin side)

message\_id

string

ID of the operated message (in channel scenarios, the message OpenID; in message feedback scenarios, the bot message ID)

feedback\_opt

string

Feedback option (only for type=13 message feedback). LIKE=like, UNLIKE=dislike

checked

integer

Whether the feedback option is selected (only for type=13 message feedback)

action

string

Operation type (type=15 story collection: ENTER\_STORY=enter, QUIT\_STORY=exit; type=16 switch model: the corresponding operation action)

message\_scene

[InteractionMessageScene](#schema-interactionmessagescene)

Message scene information (only for type=13 message feedback)

authorize\_data

[AuthorizeData](#schema-authorizedata)

Authorization data (only for type=18/19 user/group authorization events)

**InteractionMessageScene**

Name

Type

Description

ext

\[\]string

List of extended information key-value pairs, e.g. "disable\_net\_search=1" means disable web search

**AuthorizeData**

Name

Type

Description

opt\_scene

string

Authorization operation scenario. setting=profile page setting, dialog=popup authorization

scope

string

Authorization scope. c2c\_push=C2C proactive message push, group\_push=group proactive message push

### Event Example

**Example 1**

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

**Example 2**

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

**Example 3**

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

### User Adds Friend (FRIEND_ADD)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/friend_add.html

# User Adds Friend

Different friend-add sources can be distinguished by passing callback\_data in scene\_param.

## Event

Field

Value

Event name

FRIEND\_ADD

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### Event Body

Name

Type

Description

timestamp

integer

Add timestamp (Unix seconds)

openid

string

User OpenID

scene

integer

Friend-add scene value. 1000=default, 1001=web search (all tab), 1002=web search (bot tab), 1003=group scenario, 1004=space scenario, 2001=on-platform profile page sharing, 2002=off-platform profile page sharing, 2003=developer-generated share link (on-platform), 2004=developer-generated share link (off-platform)

scene\_param

string

Developer-defined callback data (callback\_data), used to distinguish different sources

author

[FriendAuthor](#schema-friendauthor)

User information

short\_code

string

Short link code of the bot share link

**FriendAuthor**

Name

Type

Description

union\_openid

string

Unified user OpenID (cross-application identifier)

### Event Example

**User Adds Friend (Web Search Scenario)**

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

**User Adds Friend (Developer Share Link)**

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

### Bot Joins Group Chat (GROUP_ADD_ROBOT)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_add_robot.html

# Bot Joins Group Chat

Triggered when the bot is added to a group chat.

## Event

Field

Value

Event name

GROUP\_ADD\_ROBOT

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### Event Body

Name

Type

Description

timestamp

integer

Join timestamp (Unix seconds)

group\_openid

string

Group OpenID

op\_member\_openid

string

OpenID of the group member who added the bot to the group

### Event Example

**Bot Joins Group Chat**

```
{
  "group_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "op_member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570534
}
```

### Direct Chat Message Receiving Enabled (C2C_MSG_RECEIVE)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/c2c_msg_receive.html

# Direct Chat Message Receiving Enabled

Triggered when the user manually enables the "proactive message" push switch on the bot profile card.

Triggered when the user manually enables the proactive message push switch on the bot profile card. Once enabled, the bot can send proactive messages to this user.

## Event

Field

Value

Event name

C2C\_MSG\_RECEIVE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### Event Body

Name

Type

Description

timestamp

integer

Operation timestamp (Unix seconds)

openid

string

User OpenID

### Event Example

**C2C Message Receiving Enabled**

```
{
  "openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570617
}
```

### Group Chat Message Receiving Enabled (GROUP_MSG_RECEIVE)

> Source: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_msg_receive.html

# Group Chat Message Receiving Enabled

Triggered when a group administrator enables notifications on the bot profile page.

## Event

Field

Value

Event name

GROUP\_MSG\_RECEIVE

Intent

GROUP\_AND\_C2C\_EVENT (1<<25)

### Event Body

Name

Type

Description

timestamp

integer

Operation timestamp (Unix seconds)

group\_openid

string

Group OpenID

op\_member\_openid

string

Operating group member OpenID

### Event Example

**Group Message Receiving Enabled**

```
{
  "timestamp": 1784276800,
  "group_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "op_member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"
}
```

## 7. Changelog

### Changelog

> Source: https://bot.q.qq.com/wiki/develop/api-v2/changelog.html

# Changelog

## 20260916

### Improvements

-   **Generate Share Link (`/v2/generate_url_link`)**: fixed the descriptions of the request and response fields.
-   **Message events (group @ message, group message, direct chat message)**: added documentation for the new `picture` (image) value in the `ark_type` enum.

## 20260903

### New

-   **Group management APIs**
    -   Added APIs related to **group member management**:
        -   Get group member list
        -   Get group member information
        -   Bulk remove group members
        -   Query group blacklist
        -   Group blacklist operations

### Improvements

-   Modified some API descriptions.

## 20260812

### New

-   **Custom menu**
    -   Added APIs to query and modify the global custom menu.
-   **Command panel**
    -   Added command panel management APIs, supporting listing, creating, retrieving details, modifying, deleting, and modifying associated objects.

## 20260810

### Improvements

-   **Unified API call domain**: all API call domains are unified as `api.bot.qq.com`.

### New

-   **Group messages / C2C messages**
    -   Sending Markdown messages: added the optional parameter `force_verify_image_resource`. When enabled, if image resource saving fails, message sending is aborted and a failure is returned (disabled by default, preserving existing behavior).
-   **Group management APIs**
    -   Added APIs related to **group mute management**:
        -   Query user mute status
        -   Set user mute
    -   Added APIs related to **group join request approval**:
        -   Fetch group join request list
        -   Approve group join requests
    -   Added APIs related to **automatic group join approval policies**.
-   **Events**
    -   Added the user group join request event.

