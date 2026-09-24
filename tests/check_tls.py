import json, os, socket, ssl
from pathlib import Path
import httpx
host=os.environ.get("TLS_HOST","127.0.0.1")
port=int(os.environ.get("TLS_PORT","18443"))
ca=os.environ["TLS_CA_FILE"]
result={}
for version in (ssl.TLSVersion.TLSv1_2,ssl.TLSVersion.TLSv1_3):
    context=ssl.create_default_context(cafile=ca)
    context.minimum_version=context.maximum_version=version
    with socket.create_connection((host,port),timeout=5) as raw:
        with context.wrap_socket(raw,server_hostname=host) as sock:
            result[version.name]=sock.version()
context=ssl.create_default_context(cafile=ca)
context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_1
context.set_ciphers("ALL:@SECLEVEL=0")
try:
    with socket.create_connection((host,port),timeout=5) as raw:
        context.wrap_socket(raw,server_hostname=host)
except ssl.SSLError as exc:
    result["tls_1_1_rejected"]=exc.reason
else:
    raise AssertionError("TLS 1.1 unexpectedly accepted")
with httpx.Client(verify=ssl.create_default_context(cafile=ca),trust_env=False) as client:
    response=client.get(f"https://{host}:{port}/health")
    response.raise_for_status()
    assert "max-age=" in response.headers["strict-transport-security"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    result["https_health"]=response.status_code
print(json.dumps(result,indent=2))
Path(os.environ.get("TLS_REPORT","test-results/tls.json")).write_text(json.dumps(result,indent=2))
