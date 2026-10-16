"""Single-origin web container; no seeding, migration or inference on startup."""
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path


def configure(environ):
    domain=environ.get("RAILWAY_PUBLIC_DOMAIN","")
    if domain:
        if not re.fullmatch(r"[a-zA-Z0-9.-]+",domain):
            raise ValueError("Invalid public domain")
        environ.setdefault("ALLOWED_HOSTS",f"{domain},localhost,127.0.0.1,healthcheck.railway.app")
        environ.setdefault("CORS_ORIGINS",f"https://{domain}")
    environ.setdefault("ENVIRONMENT","production")
    environ.setdefault("SECURE_COOKIES","true")
    environ.setdefault("ALLOW_MOCK_INGESTION","false")
    commit=environ.get("RAILWAY_GIT_COMMIT_SHA","")
    if re.fullmatch(r"[a-fA-F0-9]{40}",commit) and environ.get("APP_COMMIT","unknown")=="unknown":
        environ["APP_COMMIT"]=commit
    port=int(environ.get("PORT","8080"))
    if not 1024<=port<=65535 or port==8000:
        raise ValueError("PORT must be 1024..65535 and differ from the private API port 8000")
    workers=int(environ.get("WEB_CONCURRENCY","2"))
    if not 1<=workers<=16:
        raise ValueError("WEB_CONCURRENCY must be 1..16")
    return port,workers


def main():
    port,workers=configure(os.environ)
    # Validate production settings before starting either child.
    from app.core.config import get_settings
    get_settings()
    config=Path("/app/cloud.nginx.conf").read_text().replace("__PORT__",str(port))
    Path("/tmp/cloud.nginx.conf").write_text(config)
    children=[]
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
        for child in children:
            if child.poll() is None:child.terminate()
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    try:
        children.append(subprocess.Popen([sys.executable,"-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000","--workers",str(workers),"--no-proxy-headers"]))
        children.append(subprocess.Popen(["nginx","-c","/tmp/cloud.nginx.conf","-g","daemon off;"]))
        while not stopping and all(child.poll() is None for child in children):time.sleep(.5)
        if not stopping:raise SystemExit("A serving process stopped")
    finally:
        stop()
        for child in children:
            try:child.wait(timeout=15)
            except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__=="__main__":main()
