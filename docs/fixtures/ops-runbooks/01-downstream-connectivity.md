# 下游不可达与连接拒绝排查

作者：本项目编写。版本：2026-10-23。适用：Windows 本机专用测试业务。
本文是依据公开技术文档整理的排查方法，不是厂商原文，不是某次现场诊断结论。
参考：https://learn.microsoft.com/en-us/powershell/module/nettcpip/test-netconnection
参考：https://docs.python.org/3/library/socket.html

## 1. 从入口症状检查下游

入口 HTTP 503 表示暂时无法处理请求，但单凭状态码不能认定下游进程退出。
先记录请求时间、入口 URL、HTTP 状态、错误摘要，再从允许的配置或应用日志获取真实下游地址。
在允许检查的对象内运行 Test-NetConnection -ComputerName 127.0.0.1 -Port <下游端口>。
只对专用测试业务端口检查，不能把示例端口当作实际配置。
TcpTestSucceeded 为 False 仅说明该次 TCP 建连未成功，需要继续区分连接拒绝和超时。
连接拒绝通常需要核对监听端口与进程；超时还需考虑防火墙、目标地址和响应时限。
TCP 建连成功不能证明业务接口、数据库认证或下游查询一定正常。

## 2. 用进程、监听和日志核对

用 Get-NetTCPConnection -State Listen 检查目标端口，再通过 OwningProcess 与 Get-Process 核对 PID。
应用日志出现 ConnectionRefusedError、Connection refused 或 WinError 10061 时，关联同一时间窗口及目标地址。
同时记录下游健康接口、入口调用日志、进程和端口，不用单个“没找到”结果证明进程曾经崩溃。
监听缺失可能是服务未启动、绑定到其他地址或端口配置不同，缺少退出日志时不能认定崩溃原因。
若下游端口可连接、健康接口正常，而入口仍失败，应继续检查应用异常和入口实际依赖配置。
修复由人核对配置、恢复测试下游后执行；恢复后重新测入口请求与下游健康，不能只看进程存在。

结论边界：手册给出检查方法。现场证据最多支持本次可用性和故障层，深层原因需要额外日志或变更证据。
