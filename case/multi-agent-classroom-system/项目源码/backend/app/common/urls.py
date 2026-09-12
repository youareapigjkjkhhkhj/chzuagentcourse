"""接入地址校验（AGENTS.md §4.1 防 SSRF）。

设置页允许用户自填 `base_url`，服务端会拿着它去发请求 ——
这就是一个标准的 SSRF 入口：填 `http://127.0.0.1:6379` 就能拿我们的
服务器当跳板去戳内网。

两道闸门：
1. **协议白名单**：只允许 http/https。`file://` 能读本地文件，
   `gopher://` 能构造任意 TCP 报文，一起挡掉。
2. **网段黑名单**：解析出的每个 IP 都不能落在内网/回环/链路本地段里。
   解析（而不是字符串匹配）是必要的 —— `http://2130706433/`
   和 `http://0x7f.1/` 都是 127.0.0.1 的写法。

★ 已知残余风险：校验与真正发起请求之间存在 DNS 重绑定窗口
（校验时解析到公网 IP，请求时解析到内网）。彻底堵死需要在连接层
固定 IP，成本远高于本项目需要。这里挡掉的是「随手填个内网地址」，
这也是实际会遇到的唯一一种。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from app.common.errors import ValidationError

#: 只允许这两种协议。缺失协议时由调用方决定是否补默认值。
ALLOWED_SCHEMES = ("http", "https")

#: 不允许出现在 URL 里的协议 —— 单独列出来是为了给用户一句准确的话，
#: 而不是笼统的「地址不合法」。
_DANGEROUS_SCHEMES = {
    "file": "不能读取服务器本地文件",
    "gopher": "不能用于构造任意网络报文",
    "ftp": "不支持 FTP",
    "dict": "不支持 DICT",
    "ldap": "不支持 LDAP",
    "data": "不支持 data: 协议",
}


def _blocked_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """从配置读黑名单。读不到就用一份内置的保守名单。

    配置化是为了让部署方能按自己的网络环境调整（比如确实部署在
    10.0.0.0/8 里、就是要连那台自建模型服务）——
    但默认必须是「拒绝内网」。
    """
    from flask import current_app, has_app_context

    raw = None
    if has_app_context():
        raw = current_app.config.get("SSRF_BLOCKED_NETWORKS")

    if not raw:
        raw = [
            "0.0.0.0/8",
            "10.0.0.0/8",
            "127.0.0.0/8",
            "169.254.0.0/16",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "::1/128",
            "fc00::/7",
            "fe80::/10",
        ]

    networks = []
    for item in raw:
        try:
            networks.append(ipaddress.ip_network(str(item), strict=False))
        except ValueError:  # pragma: no cover - 配置写错了不该拖垮请求
            continue
    return networks


def _blocked_schemes() -> tuple[str, ...]:
    from flask import current_app, has_app_context

    extra = tuple(_DANGEROUS_SCHEMES)
    if has_app_context():
        configured = current_app.config.get("SSRF_BLOCKED_SCHEMES")
        if configured:
            extra = tuple({*extra, *(str(s).lower() for s in configured)})
    return extra


#: 主机名检查的三种结论。
_HOST_OK = "ok"
_HOST_PRIVATE = "private"
_HOST_UNRESOLVABLE = "unresolvable"


def _resolve_enabled() -> bool:
    """是否对域名做 DNS 解析。

    关掉它的唯一理由是测试：AGENTS.md §23 要求测试不联网，
    而解析一个域名就是一次网络请求。关掉不影响 IP 字面量的判定 ——
    `http://127.0.0.1` 这种写法根本不需要 DNS。
    """
    from flask import current_app, has_app_context

    if not has_app_context():
        return True
    return bool(current_app.config.get("SSRF_RESOLVE_HOSTS", True))


def _in_blocked_network(ip) -> bool:
    return any(ip in network for network in _blocked_networks())


def _check_host(host: str) -> str:
    """判断主机名指向哪里。返回 _HOST_* 之一。

    IP 字面量直接判定，不走 DNS：这条路径挡住了绝大多数随手填的内网地址
    （`127.0.0.1` / `192.168.x.x` / `169.254.169.254` 云元数据服务）。
    """
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        return _HOST_PRIVATE if _in_blocked_network(literal) else _HOST_OK

    if not _resolve_enabled():
        return _HOST_OK

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # 连域名都解析不出来，那请求一定发不出去。现在拒掉，
        # 好过等到用户点「测试连接」时给一个更难懂的报错。
        return _HOST_UNRESOLVABLE

    # 解析全部结果（而不是第一个）：一个域名可以同时返回公网 IP 与内网 IP，
    # 只看第一个等于给攻击者留了一半的概率。
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:  # pragma: no cover - getaddrinfo 给的一定是 IP
            return _HOST_PRIVATE
        if _in_blocked_network(ip):
            return _HOST_PRIVATE
    return _HOST_OK


def ensure_safe_base_url(url: str | None, *, field: str = "接入地址") -> str:
    """校验一个用户可填的接入地址，返回规整后的值。不合法就抛 40001。"""
    text = str(url or "").strip()
    if not text:
        raise ValidationError(f"{field}不能为空")

    parts = urlsplit(text)

    scheme = parts.scheme.lower()
    if not scheme:
        raise ValidationError(f"{field}必须以 http:// 或 https:// 开头")
    if scheme in _DANGEROUS_SCHEMES:
        reason = _DANGEROUS_SCHEMES[scheme]
        raise ValidationError(f"{field}不支持 {scheme}:// 协议：{reason}")
    if scheme not in ALLOWED_SCHEMES:
        raise ValidationError(f"{field}只支持 http 或 https，收到的是 {scheme}://")

    host = parts.hostname
    if not host:
        raise ValidationError(f"{field}里没有主机名")

    verdict = _check_host(host)
    if verdict == _HOST_PRIVATE:
        raise ValidationError(
            f"{field}指向内网地址（{host}），已拒绝；"
            "如果确实要连内网服务，请把该网段从 SSRF_BLOCKED_NETWORKS 里去掉"
        )
    if verdict == _HOST_UNRESOLVABLE:
        raise ValidationError(f"{field}的主机名 {host} 无法解析，请检查是否拼写有误")

    return text.rstrip("/")


__all__ = ["ALLOWED_SCHEMES", "ensure_safe_base_url"]
