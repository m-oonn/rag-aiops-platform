"""Real Linux sandbox/SSH checks, without MCP transport or paid model calls.

Uses a disposable locally prepared image with Python, OpenSSH and bubblewrap.
The image is a test prerequisite; this does not substitute for production image build.
"""

import argparse
import json
import subprocess
from uuid import uuid4
from pathlib import Path


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


SETUP = '''
import json, pathlib, subprocess
subprocess.run(["adduser", "-D", "-s", "/bin/sh", "collector"], check=True)
subprocess.run(["sh", "-c", "echo collector:unused-test-password | chpasswd"], check=True)
subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", "/verification/key"], check=True)
os = __import__('os')
os.chown('/verification/key',1000,1000)
os.chmod('/verification',0o777)
home=pathlib.Path("/home/collector/.ssh"); home.mkdir(mode=0o700)
home.joinpath("authorized_keys").write_text('restrict,command="/usr/bin/python3 /opt/collector.py" '+pathlib.Path("/verification/key.pub").read_text())
subprocess.run(["chown", "-R", "collector:collector", str(home)], check=True)
home.joinpath("authorized_keys").chmod(0o600)
pathlib.Path("/etc/aiops-diagnostic.json").write_text(json.dumps({"target_id":"test-target", "services":{"api":{"process_name":"sshd","logs":["/tmp/service.log"],"dependencies":["closed"]}},"dependencies":{"closed":{"host":"127.0.0.1","port":1}}}))
pathlib.Path("/tmp/service.log").write_text("worker healthy\\nconnection refused\\n")
pathlib.Path("/etc/ssh/sshd_config").write_text("Port 22\\nHostKey /etc/ssh/ssh_host_ed25519_key\\nPasswordAuthentication no\\nPermitRootLogin no\\nAllowUsers collector\\nAllowTcpForwarding no\\nPermitTunnel no\\nX11Forwarding no\\n")
subprocess.run(["ssh-keygen", "-A"], check=True)
'''


CHECK = r'''
import ast, json, pathlib, subprocess, os, time, socket
# Load production stdlib execution/query helpers. MCP decorators are omitted
# because this check tests the real boundary, not tool discovery/transport.
tree=ast.parse(pathlib.Path("/opt/diagnostic_server.py").read_text())
nodes=[]
for node in tree.body:
    if isinstance(node, ast.ImportFrom) and node.module.startswith("fastmcp"): continue
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "mcp" for t in node.targets): continue
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef)):
        if isinstance(node, ast.FunctionDef): node.decorator_list=[]
        nodes.append(node)
exec(compile(ast.Module(body=nodes,type_ignores=[]),"production_helpers","exec"))
os.environ.update(DIAGNOSTIC_EXEC_ENABLED="true", DIAGNOSTIC_EVIDENCE_DIR="/verification/evidence", DIAGNOSTIC_SSH_CONFIG="/verification/target.json")
pathlib.Path("/verification/evidence").mkdir(exist_ok=True)
scan=subprocess.run(["ssh-keyscan","-t","ed25519","test-target"],capture_output=True,text=True,timeout=5)
assert scan.returncode==0 and scan.stdout
pathlib.Path("/verification/known_hosts").write_text(scan.stdout)
pathlib.Path("/verification/target.json").write_text(json.dumps({"host":"test-target","user":"collector","target_id":"test-target","known_hosts":"/verification/known_hosts","identity_file":"/verification/key"}))
catalog=_diagnostic_query("catalog"); assert catalog.get("target_id")=="test-target",catalog
logs=_diagnostic_query("logs","api"); assert "connection refused" in logs["logs"][0]["content"],logs
assert _diagnostic_query("logs","unknown")["data_source"]=="unavailable"
ports=_diagnostic_query("ports"); assert "0016" in ports["tcp"],ports
dep=_diagnostic_query("dependency",dependency="closed"); assert dep["reachable"] is False,dep
assert _diagnostic_query("dependency",dependency="unknown")["data_source"]=="unavailable"
result=_diagnostic_exec("cat /evidence/"+logs["evidence_file"]); assert "connection refused" in result.get("stdout", ""),result
assert _diagnostic_exec("cat /verification/key /connection/key /etc/shadow")["exit_code"]!=0
write=_diagnostic_exec("echo changed > /evidence/blocked"); assert write["exit_code"]!=0,write
assert not pathlib.Path("/verification/evidence/blocked").exists()
network=_diagnostic_exec("python3 -c 'import socket; socket.create_connection((\"test-target\",22),timeout=1)'")
assert network["exit_code"]!=0,network
output=_diagnostic_exec("yes x",timeout=0.2,max_output=64); assert output["timed_out"] and len(output["stdout"])<=64,output
assert output["output_truncated"]
background=_diagnostic_exec("setsid sh -c 'sleep 1; touch /tmp/escaped' & sleep 5",timeout=0.2)
assert background["timed_out"],background
assert _diagnostic_exec("test ! -e /tmp/escaped")["exit_code"]==0
assert _diagnostic_exec("test ! -S /var/run/docker.sock")["exit_code"]==0
print(json.dumps({"real_ssh_collector":"passed","sandbox":"passed","target_id":catalog["target_id"],"model_calls":0,"mcp_transport":"not run"}))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="aiops-diagnostic-verification-base:local")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "data" / "diagnostic-verification" / uuid4().hex
    output.mkdir(parents=True, exist_ok=False)
    (output / "setup_target.py").write_text(SETUP)
    (output / "check.py").write_text(CHECK)
    network = "aiops-diagnostic-boundary-test"
    target = "aiops-diagnostic-boundary-target"
    docker("network", "create", network)
    try:
        docker("run", "-d", "--name", target, "--network", network,
               "--network-alias", "test-target", "-v", f"{output}:/verification",
               "-v", f"{root / 'mcp_servers/diagnostic_collector.py'}:/opt/collector.py:ro",
               "--entrypoint", "sh", args.image, "-c",
               "python3 /verification/setup_target.py && exec /usr/sbin/sshd -D -e")
        # Ready check has a finite deadline; no credentials or target output is printed.
        import time
        for _ in range(30):
            if (output / "key.pub").exists():
                break
            time.sleep(0.2)
        result = docker("run", "--rm", "--network", network, "--read-only",
            "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--security-opt", f"seccomp={root / 'docker/diagnostic/seccomp.json'}",
            "--pids-limit", "64", "--memory", "256m", "--tmpfs", "/tmp:size=16m",
            "-v", f"{output}:/verification", "-v",
            f"{root / 'mcp_servers/diagnostic_server.py'}:/opt/diagnostic_server.py:ro",
            "--entrypoint", "python3", args.image, "/verification/check.py")
        (output / "result.json").write_text(result)
        print(result)
    finally:
        docker("rm", "-f", target)
        docker("network", "rm", network)


if __name__ == "__main__":
    main()
