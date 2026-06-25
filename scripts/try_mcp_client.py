"""验证 src/agent/mcp_client.py:工具能加载 + 单例生效。

前置:8004 monitor + 8003 cls 两个 MCP 服务都起着。
运行: python scripts/try_mcp_client.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com"

from src.agent.mcp_client import get_mcp_client, load_mcp_tools_safe


async def main():
    # ① 优雅降级版加载:成功拿到工具,失败拿到错误字符串(不抛异常)
    tools, error = await load_mcp_tools_safe()
    print("=" * 60)
    if error:
        print(f"⚠️ 加载失败(已降级,未抛异常): {error}")
        return
    print(f"✅ 加载到 {len(tools)} 个工具: {[t.name for t in tools]}")

    # ② 单例验证:两次 get_mcp_client() 必须是同一个对象
    print("=" * 60)
    c1 = get_mcp_client()
    c2 = get_mcp_client()
    print(f"两次 get_mcp_client() 是同一个对象吗? {c1 is c2}")
    print(f"  id(c1)={id(c1)}")
    print(f"  id(c2)={id(c2)}")
    print("✅ 单例生效" if c1 is c2 else "❌ 不是单例,检查 if _mcp_client is None 逻辑")


if __name__ == "__main__":
    asyncio.run(main())
