\
from typing import List, Dict, Optional
import requests
from tenacity import retry, wait_exponential, stop_after_attempt

class BitbucketServerClient:
    def __init__(
        self,
        base_url: str,
        auth_type: str = "BASIC",
        username: str = "",
        password: str = "",
        token: str = "",
        verify: bool = True,
        ca_cert: Optional[str] = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.api = f"{self.base}/rest/api/1.0"
        self.session = requests.Session()
        self.verify = ca_cert or verify  
        self.auth_type = auth_type.upper()
        if self.auth_type == "BASIC":
            self.session.auth = (username, password)
        elif self.auth_type == "TOKEN":
            self.session.headers["Authorization"] = f"Bearer {token}"
        else:
            raise ValueError("Unsupported BITBUCKET_AUTH_TYPE; use BASIC or TOKEN")

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(5))
    def _get(self, url: str, params: dict = None) -> requests.Response:
        r = self.session.get(url, params=params or {}, timeout=30, verify=self.verify)
        r.raise_for_status()
        return r

    def list_repositories(self, project_key: str) -> List[Dict]:
        """Return a list of repositories with fields: name, slug, clone_http, clone_ssh, description"""
        results: List[Dict] = []
        start = 0
        while True:
            url = f"{self.api}/projects/{project_key}/repos"
            resp = self._get(url, params={"limit": 100, "start": start}).json()
            for it in resp.get("values", []):
                name = it.get("name") or it.get("slug")
                slug = it.get("slug")
                desc = it.get("description") or ""
                clone_http, clone_ssh = None, None
                for link in it.get("links", {}).get("clone", []):
                    if link.get("name") == "http":
                        clone_http = link.get("href")
                    elif link.get("name") == "ssh":
                        clone_ssh = link.get("href")
                results.append({
                    "name": name,
                    "slug": slug,
                    "description": desc,
                    "clone_http": clone_http,
                    "clone_ssh": clone_ssh,
                    "project_key": project_key,
                })
            if resp.get("isLastPage", True):
                break
            start = resp.get("nextPageStart", 0)
        return results
