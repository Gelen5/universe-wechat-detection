"""抖音 Web 端签名算法（纯 Python，无浏览器、无网络、无状态）。

为什么这个包存在
----------------
抖音的数据接口不是「带上 Cookie 就给你数据」的普通接口。它的前端会给每个
``/aweme/v1/`` 请求挂两层签名，缺任何一层，服务端都回 403：

``a_bogus``
    由 ``bdms.js`` 生成的查询串签名，挂在 URL 的 ``a_bogus`` 参数上。

``x-secsdk-web-signature``
    由 ``secsdk`` 生成的请求头签名，``md5(f"{uifid}_{ts}_{SALT}_{query}")``。
    少了它，响应体是 ``Blocked by ArgusSecurityPlugin Uifid Not Found`` —— 这个
    错误信息指的是**签名**里的访客 ID，不是 Cookie 里的。

把这两层算对，一次作品详情请求就变成一个普通的 HTTP GET：几十毫秒、几 KB
内存。这是本站能在 1.6 GB 内存的机器上做抖音解析、而别人要一台 8 GB 机器跑
整套浏览器的原因 —— 签名在进程内算，不需要 Chromium。

来源与许可
----------
``sm3.py``、``abogus.py``、``websign.py`` 三个文件原样取自
`Douyin_TikTok_Download_API <https://github.com/Evil0ctal/Douyin_TikTok_Download_API>`_
（Apache License 2.0，Copyright 2021-2026 Evil0ctal and contributors）的
``src/dtk/signing/native/``。改动只有一处：``abogus.py`` 的
``from dtk.signing.native.sm3 import ...`` 改为包内相对导入。许可全文见同目录
``LICENSE``，署名见 ``NOTICE``。

上游把这三个模块单独挑出来是有原因的：它们是纯函数，没有配置、没有 IO，
因此可以整块搬进别的项目而不带进一整套采集框架。
"""

from __future__ import annotations

from .abogus import ABogus
from .websign import (
    SIGNATURE_PARAM,
    UIFID_COOKIE_NAMES,
    UIFID_PARAM,
    encode_pairs,
    pick_uifid,
    sign as websign,
)

__all__ = [
    "ABogus",
    "SIGNATURE_PARAM",
    "UIFID_COOKIE_NAMES",
    "UIFID_PARAM",
    "encode_pairs",
    "pick_uifid",
    "websign",
]
