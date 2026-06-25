"""Phase 0 网络诊断: 挖出 APIConnectionError 背后的真实根因。

上一版探针只打印笼统的 "Connection error.",真正的原因(代理/DNS/SSL)
被包在异常链里层。这一版:
1. 打印当前代理环境变量(VPN/代理是最常见元凶)。
2. 用 httpx 直连 base_url,暴露最底层的网络错误。
3. 调 openai SDK 时把完整异常链(__cause__)全打印出来。

运行: $env:PYTHONPATH="."; python scripts/diag_net.py
"""

import os
import traceback

import httpx

from src.settings import settings


def show_proxy_env() -> None:
    print("=" * 60, "\n[1] 代理环境变量检查(VPN/代理是最常见元凶)\n" + "=" * 60)
    keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
            "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy"]
    found = False
    for k in keys:
        v = os.environ.get(k)
        if v:
            print(f"  ⚠️  {k} = {v}")
            found = True
    if not found:
        print("  (没有设置任何代理环境变量)")


def raw_httpx_test() -> None:
    print("\n" + "=" * 60, "\n[2] httpx 直连测试(绕过 openai SDK,看最底层)\n" + "=" * 60)
    # /compatible-mode/v1/models 是个轻量端点,能连通就会返回 401(没带完整鉴权头也算"连上了")
    url = settings.DASHSCOPE_API_BASE.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"}
    try:
        # trust_env=True: 让 httpx 读系统代理设置(和 openai SDK 行为一致)
        with httpx.Client(timeout=15, trust_env=True) as client:
            r = client.get(url, headers=headers)
        print(f"  ✅ 连上了! HTTP {r.status_code}")
        print(f"  响应前 200 字: {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ 直连失败,真实根因如下:")
        traceback.print_exc()


def raw_httpx_test_no_proxy() -> None:
    print("\n" + "=" * 60, "\n[3] httpx 直连(强制不走代理)\n" + "=" * 60)
    url = settings.DASHSCOPE_API_BASE.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"}
    try:
        # trust_env=False: 忽略系统代理,直连。若这个成功而 [2] 失败 => 就是代理的锅
        with httpx.Client(timeout=15, trust_env=False) as client:
            r = client.get(url, headers=headers)
        print(f"  ✅ 不走代理连上了! HTTP {r.status_code}")
        print(f"  响应前 200 字: {r.text[:200]}")
        print("  >>> 结论: 问题就是代理/VPN。解决见脚本末尾提示。")
    except Exception as e:
        print(f"  ❌ 不走代理也失败:")
        traceback.print_exc()


if __name__ == "__main__":
    print("base_url =", settings.DASHSCOPE_API_BASE)
    print("api_key 长度 =", len(settings.DASHSCOPE_API_KEY or ""),
          "| 前缀 =", (settings.DASHSCOPE_API_KEY or "")[:6])
    show_proxy_env()
    raw_httpx_test()
    raw_httpx_test_no_proxy()
    print("\n" + "=" * 60)
    print("解读:")
    print("  - [3]成功但[2]失败  -> 代理/VPN 的锅,关掉代理或设 NO_PROXY 即可")
    print("  - [2][3]都失败      -> DNS/防火墙/SSL,看 traceback 最后一行错误类型")
    print("  - 都返回 401        -> 网络通! key 需要检查(但连接没问题,可继续)")
    print("=" * 60)
