\
import os
import re
import yaml
from slugify import slugify as _slugify

def load_yaml(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def coalesce(*args):
    for a in args:
        if a is not None and a != "":
            return a
    return None

def apply_replace_map(s: str, replace_map: dict) -> str:
    out = s
    for k, v in (replace_map or {}).items():
        out = out.replace(k, v)
    return out

def make_alias(name: str, cfg_naming: dict) -> str:
    s = name or ""
    s = apply_replace_map(s, cfg_naming.get("replace_map", {}))
    if cfg_naming.get("slugify", True):
        s = _slugify(s, allow_unicode=cfg_naming.get("transliterate_ru", True))
    if cfg_naming.get("lowercase", True):
        s = s.lower()
    return s

def match_any(patterns, text: str) -> bool:
    for p in patterns or []:
        if re.search(p, text):
            return True
    return False
