\
from typing import Dict, Tuple
import requests
from tenacity import retry, wait_exponential, stop_after_attempt

class GitFlicClient:
    def __init__(self, base_url: str, api_token: str) -> None:
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {api_token}",
            "Content-Type": "application/json",
        })

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(5))
    def create_project(self, payload: Dict) -> Tuple[bool, int, dict | str]:
        """POST /project -> returns (ok, status_code, data or text)"""
        url = f"{self.base}/project"
        r = self.session.post(url, json=payload, timeout=60)
        if r.status_code == 200:
            return True, r.status_code, r.json()
        else:
            # return both status code and text for diagnostics
            try:
                data = r.json()
            except Exception:
                data = r.text
            return False, r.status_code, data
