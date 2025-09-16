\
import os
import shlex
import re
import subprocess
from urllib.parse import urlparse, urlunparse, quote


def _mask_secrets(s: str) -> str:
    return re.sub(r'(https?://)([^:@/\s]+):([^@/\s]+)@', r'\1***:***@', s)

def run(cmd: str, cwd: str | None = None, env: dict | None = None):
    e = os.environ.copy()
    if env:
        e.update(env)
    proc = subprocess.run(shlex.split(cmd), cwd=cwd, env=e, capture_output=True, text=True)
    if proc.returncode != 0:
        cmd_safe = _mask_secrets(cmd)
        out_safe = _mask_secrets(proc.stdout or "")
        err_safe = _mask_secrets(proc.stderr or "")
        raise RuntimeError(f"Command failed: {cmd_safe}\nSTDOUT:\n{out_safe}\nSTDERR:\n{err_safe}")
    return proc.stdout

def with_https_creds(url: str, username: str | None, password: str | None) -> str:
    if not (username and password):
        return url
    p = urlparse(url)
    host = p.hostname or ""
    if p.port:
        host += f":{p.port}"
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}"
    return urlunparse((p.scheme, netloc, p.path, "", p.query or "", p.fragment or ""))

def clone_mirror(src_url: str, dest_path: str, git_ssl_no_verify: bool = False):
    env = {"GIT_TERMINAL_PROMPT": "0"}
    if git_ssl_no_verify:
        env["GIT_SSL_NO_VERIFY"] = "true"
    run(f"git clone --mirror {shlex.quote(src_url)} {shlex.quote(dest_path)}", env=env)

def lfs_fetch_all(repo_path: str, git_ssl_no_verify: bool = False):
    env = {"GIT_TERMINAL_PROMPT": "0"}
    if git_ssl_no_verify:
        env["GIT_SSL_NO_VERIFY"] = "true"
    try:
        run("git lfs fetch --all", cwd=repo_path, env=env)
        return True
    except Exception:
        return False
    
def lfs_repo_has_content(repo_path: str) -> bool:
    """
    Возвращает True, если в bare-репозитории есть LFS-файлы/объекты.
    1) Пробуем `git lfs ls-files --all` с GIT_DIR=repo_path (bare-режим).
    2) Фоллбэк: проверяем на файловой системе наличие объектов в lfs/objects.
    """
    env = {"GIT_DIR": repo_path, "GIT_TERMINAL_PROMPT": "0"}
    try:
        out = run("git lfs ls-files --all", env=env)
        if out and out.strip():
            return True
    except Exception:
        pass
    objects_dir = os.path.join(repo_path, "lfs", "objects")
    for _root, _dirs, files in os.walk(objects_dir):
        if files:
            return True
    return False

def add_remote(repo_path: str, name: str, url: str):
    try:
        run(f"git remote remove {name}", cwd=repo_path)
    except Exception:
        pass
    run(f"git remote add {name} {shlex.quote(url)}", cwd=repo_path)

def push_mirror(repo_path: str, remote_name: str = "gitflic", git_ssl_no_verify: bool = False):
    env = {"GIT_TERMINAL_PROMPT": "0"}
    if git_ssl_no_verify:
        env["GIT_SSL_NO_VERIFY"] = "true"
    run(f"git push --mirror {remote_name}", cwd=repo_path, env=env)

def lfs_push_all(repo_path: str, remote_name: str = "gitflic", git_ssl_no_verify: bool = False):
    env = {"GIT_TERMINAL_PROMPT": "0"}
    if git_ssl_no_verify:
        env["GIT_SSL_NO_VERIFY"] = "true"
    try:
        run(f"git lfs push --all {remote_name}", cwd=repo_path, env=env)
        return True
    except Exception:
        return False
