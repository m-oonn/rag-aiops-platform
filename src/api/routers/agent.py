from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from datetime import datetime

from src.database.sql_session import get_db
from src.database.models import Agent, User
from src.api.dependencies import get_current_user
from src.services.agent_tool_service import execute_agent_query
from src.settings import settings

router = APIRouter()


class MCPServerConfig(BaseModel):
    """单个 MCP 服务器的配置。

    安全最佳实践:
    - 禁用 stdio transport 防止 RCE(用户可配置任意 command 执行命令)
    - 禁止 extra 字段防止注入未验证的配置项
    - URL 校验防止 SSRF(阻止内网地址)
    """

    model_config = ConfigDict(extra="forbid")

    transport: Literal["streamable_http", "sse"] = "streamable_http"
    url: Optional[str] = None

    @model_validator(mode="after")
    def url_required_and_safe(self):
        # transport 必须提供 url
        if self.transport in ("streamable_http", "sse") and not self.url:
            raise ValueError(f"transport '{self.transport}' requires url")
        # SSRF 防护: 阻止内网地址
        if self.url:
            self._validate_url_safe(self.url)
        return self

    @staticmethod
    def _validate_url_safe(url: str) -> None:
        """校验 URL 不指向内网地址，防止 SSRF。

        阻止的地址段:
        - 127.0.0.0/8 (回环)
        - 10.0.0.0/8 (内网 A 类)
        - 172.16.0.0/12 (内网 B 类)
        - 192.168.0.0/16 (内网 C 类)
        - 169.254.0.0/16 (链路本地，含云元数据 169.254.169.254)
        - 0.0.0.0/8
        - ::1 (IPv6 回环)
        - fc00::/7 (IPv6 唯一本地)
        """
        from urllib.parse import urlparse
        import ipaddress
        import socket

        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            raise ValueError(f"Invalid URL: cannot parse hostname from {url}")

        # 只允许 http/https
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Only http/https schemes allowed, got: {parsed.scheme}")

        # 如果是 IP 地址，直接检查是否为内网
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
                # 开发环境允许回环地址(127.0.0.1/::1)用于本地 MCP 服务器
                # 与项目统一用 APP_ENV 判定环境
                if ip.is_loopback and settings.APP_ENV != "production":
                    pass
                else:
                    raise ValueError(
                        f"SSRF protection: internal/private IP not allowed: {hostname}"
                    )
        except ValueError:
            # 不是 IP 地址(是域名)，解析 DNS 后检查所有解析结果
            # 安全最佳实践: 防止 DNS 重绑定攻击，域名解析的 IP 也不能是内网
            # 例外: localhost 在开发环境中允许通过(与项目统一用 APP_ENV 判定环境)
            if hostname == "localhost" and settings.APP_ENV != "production":
                pass  # 开发环境允许 localhost
            else:
                try:
                    addrs = socket.getaddrinfo(hostname, None)
                    for addr_info in addrs:
                        resolved_ip = ipaddress.ip_address(addr_info[4][0])
                        if resolved_ip.is_private or resolved_ip.is_loopback or resolved_ip.is_link_local or resolved_ip.is_unspecified:
                            raise ValueError(
                                f"SSRF protection: domain {hostname} resolves to internal IP: {resolved_ip}"
                            )
                except socket.gaierror:
                    # DNS 解析失败，允许通过(后续连接时自然失败)
                    pass


class LLMConfig(BaseModel):
    """Agent 专用 LLM 配置。"""

    model_config = ConfigDict(extra="forbid")  # 安全最佳实践: 拒绝未定义字段

    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, gt=0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)


class ExecutionConfig(BaseModel):
    """Agent 执行策略配置。"""

    model_config = ConfigDict(extra="forbid")  # 安全最佳实践: 拒绝未定义字段

    max_iterations: Optional[int] = Field(None, gt=0, le=20)
    llm_timeout: Optional[float] = Field(None, gt=0.0)
    tool_timeout: Optional[float] = Field(None, gt=0.0)
    mcp_load_timeout: Optional[float] = Field(None, gt=0.0)


class AgentConfigMixin(BaseModel):
    """Agent 配置字段复用：Create 和 Update 共用同一套 schema。"""

    system_prompt: Optional[str] = None
    tools_config: Optional[dict[str, MCPServerConfig]] = None
    knowledge_config: Optional[dict] = None
    memory_config: Optional[dict] = None
    reasoning_config: Optional[dict] = None
    security_config: Optional[dict] = None
    interaction_config: Optional[dict] = None
    llm_config: Optional[LLMConfig] = None
    execution_config: Optional[ExecutionConfig] = None


class AgentCreate(AgentConfigMixin):
    name: str
    description: Optional[str] = None
    type: str = "function_call"
    config: Optional[dict] = {}


class AgentUpdate(AgentConfigMixin):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    config: Optional[dict] = None


class AgentOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    type: str

    system_prompt: Optional[str]
    tools_config: Optional[dict]
    knowledge_config: Optional[dict]
    memory_config: Optional[dict]
    reasoning_config: Optional[dict]
    security_config: Optional[dict]
    interaction_config: Optional[dict]
    llm_config: Optional[dict]
    execution_config: Optional[dict]

    config: Optional[dict]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentExecute(BaseModel):
    query: str


@router.post("/", response_model=AgentOut)
def create_agent(
    agent_in: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = Agent(
        name=agent_in.name,
        description=agent_in.description,
        type=agent_in.type,
        user_id=current_user.id,

        system_prompt=agent_in.system_prompt,
        tools_config={k: v.model_dump(exclude_none=True) for k, v in agent_in.tools_config.items()} if agent_in.tools_config else None,
        knowledge_config=agent_in.knowledge_config,
        memory_config=agent_in.memory_config,
        reasoning_config=agent_in.reasoning_config,
        security_config=agent_in.security_config,
        interaction_config=agent_in.interaction_config,
        llm_config=agent_in.llm_config.model_dump(exclude_none=True) if agent_in.llm_config else None,
        execution_config=agent_in.execution_config.model_dump(exclude_none=True) if agent_in.execution_config else None,

        config=agent_in.config
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/", response_model=List[AgentOut])
def list_agents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Agent).filter(Agent.user_id == current_user.id).all()


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return agent


@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: int,
    agent_in: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_data = agent_in.model_dump(exclude_unset=True)
    # Pydantic 子模型需要再转一层 dict，方便 SQLAlchemy JSON 字段存储
    if "tools_config" in update_data and update_data["tools_config"] is not None:
        update_data["tools_config"] = {k: v.model_dump(exclude_none=True) if hasattr(v, "model_dump") else v for k, v in update_data["tools_config"].items()}
    if "llm_config" in update_data and update_data["llm_config"] is not None:
        update_data["llm_config"] = update_data["llm_config"].model_dump(exclude_none=True) if hasattr(update_data["llm_config"], "model_dump") else update_data["llm_config"]
    if "execution_config" in update_data and update_data["execution_config"] is not None:
        update_data["execution_config"] = update_data["execution_config"].model_dump(exclude_none=True) if hasattr(update_data["execution_config"], "model_dump") else update_data["execution_config"]

    for field, value in update_data.items():
        setattr(agent, field, value)

    db.commit()
    db.refresh(agent)
    return agent


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    db.delete(agent)
    db.commit()
    return {"message": "Agent deleted"}


@router.post("/{agent_id}/execute")
async def execute_agent(
    agent_id: int,
    payload: AgentExecute,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """执行 Agent 的 MCP 工具查询。Agent 的 tools_config 将用于连接 MCP 服务器并加载工具。"""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await execute_agent_query(agent, payload.query)
    return result
