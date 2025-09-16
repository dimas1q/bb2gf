\
import os
import json
import time
from typing import List, Dict
from rich.console import Console
from rich.json import JSON
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from src.core.utils import load_yaml, make_alias, match_any
from src.core.git_ops import (
    with_https_creds,
    clone_mirror,
    lfs_fetch_all,
    add_remote,
    push_mirror,
    lfs_push_all,
    lfs_repo_has_content,
)

console = Console()

def migrate_repositories(
    repos: List[Dict],
    owner_alias: str,
    owner_type: str,
    visibility_private: bool,
    language_default: str,
    use_ssh: bool,
    dry_run: bool,
    workdir: str,
    keep_clones: bool,
    bb_client,
    gf_client,
    gf_git_user: str | None,
    gf_git_pass: str | None,
    bb_git_user: str | None,
    bb_git_pass: str | None,
):
    cfg = load_yaml("config.yml") if os.path.exists("config.yml") else {}
    naming = cfg.get("naming", {})
    filters = cfg.get("filters", {})
    report_path = cfg.get("report", {}).get("path", "report.json")

    os.makedirs(workdir, exist_ok=True)
    summary = {
        "total": 0,
        "created": 0,
        "exists": 0,
        "lfs_pushed": 0,
        "skipped": 0,
        "errors": 0,
        "items": [],
    }

    include_patterns = filters.get("include_patterns", [])
    exclude_patterns = filters.get("exclude_patterns", [])

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),            # N/N (xx%)
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:
        overall = progress.add_task("[bold]Миграция репозиториев[/bold]", total=len(repos))

        for r in repos:
            started = time.perf_counter()
            summary["total"] += 1
            name = r.get("name") or r.get("slug")
            alias = make_alias(r.get("slug") or name, naming)
            description = (r.get("description") or "")[:500]

            repo_task = progress.add_task(f"[white]{name}[/white]", total=5)

            item = {
                "repo": name,
                "alias": alias,
                "created": False,
                "lfs": False,
                "duration_s": None,
                "status": "PENDING",
                "message": "",
            }

            if include_patterns and not match_any(include_patterns, name):
                summary["skipped"] += 1
                item["status"] = "SKIPPED"
                item["message"] = "Не прошёл include-фильтр"
                item["duration_s"] = round(time.perf_counter() - started, 2)
                summary["items"].append(item)
                continue
            if exclude_patterns and match_any(exclude_patterns, name):
                summary["skipped"] += 1
                item["status"] = "SKIPPED"
                item["message"] = "Исключён exclude-фильтром"
                item["duration_s"] = round(time.perf_counter() - started, 2)
                summary["items"].append(item)   
                continue

            progress.console.rule(f"[bold]Репозиторий: {name} → alias={alias}")
            src_url = r.get("clone_ssh") if use_ssh and r.get("clone_ssh") else r.get("clone_http")
            if not src_url:
                console.print(f"[red]Нет clone URL в Bitbucket для {name}[/red]")
                summary["errors"] += 1
                item["status"] = "FAILED"
                item["message"] = "Нет clone URL в Bitbucket"
                item["duration_s"] = round(time.perf_counter() - started, 2)
                summary["items"].append(item)
                continue

            if (not use_ssh) and src_url.startswith("http"):
                src_url = with_https_creds(src_url, bb_git_user, bb_git_pass)

            payload = {
                "title": name,
                "isPrivate": visibility_private,
                "alias": alias,
                "ownerAlias": owner_alias,
                "ownerAliasType": owner_type,
                "description": description,
            }
            
            if language_default:
                payload["language"] = language_default

            if dry_run:
                progress.console.print("[yellow]DRY-RUN[/yellow] Создание проекта в GitFlic:", payload)
                created_ok, created_json = True, {
                    "httpTransportUrl": "<dry-run>",
                    "sshTransportUrl": "<dry-run>"
                }
                summary["created"] += 1
                item["created"] = True
                progress.advance(repo_task)
            else:
                ok, code, data = gf_client.create_project(payload)
                if ok:
                    progress.console.print(f"[green]Создан проект в GitFlic[/green]")
                    created_ok, created_json = True, data
                    summary["created"] += 1
                    item["created"] = True
                    progress.advance(repo_task)
                else:
                    progress.console.print(f"[red]Ошибка создания проекта GitFlic [{code}][/red]: {data}")
                    summary["errors"] += 1
                    item["status"] = "FAILED"
                    item["message"] = f"Ошибка создания проекта: {code}"
                    item["duration_s"] = round(time.perf_counter() - started, 2)
                    summary["items"].append(item)
                    progress.update(repo_task, completed=5)
                    progress.advance(overall)
                    continue

            dst_url = None
            if use_ssh:
                dst_url = created_json.get("sshTransportUrl")
            else:
                dst_url = created_json.get("httpTransportUrl")
                dst_url = with_https_creds(dst_url, gf_git_user, gf_git_pass)

            repo_path = os.path.join(workdir, f"{alias}.git")
            try:
                if dry_run:
                    progress.console.print(f"[yellow]DRY-RUN[/yellow] git clone --mirror {src_url} {repo_path}")
                else:
                    progress.console.print(f"[green]MIGRATING[/green] git clone --mirror {src_url} {repo_path}")
                    clone_mirror(src_url, repo_path, git_ssl_no_verify=False)
                
                progress.advance(repo_task)

                lfs_fetched = False
                has_lfs = False

                if dry_run:
                    progress.console.print("[yellow]DRY-RUN[/yellow] git lfs fetch --all")
                else:
                    progress.console.print("[green]MIGRATING[/green] git lfs fetch --all")
                    lfs_fetched = lfs_fetch_all(repo_path)
                try:
                    has_lfs = lfs_repo_has_content(repo_path)
                except Exception:
                    has_lfs = False

                progress.advance(repo_task)

                if dry_run:
                    progress.console.print(f"[yellow]DRY-RUN[/yellow] git remote add gitflic {dst_url}")
                    progress.console.print(f"[yellow]DRY-RUN[/yellow] git push --mirror gitflic")
                    progress.advance(repo_task)
                    if has_lfs:
                        progress.console.print(f"[yellow]DRY-RUN[/yellow] git lfs push --all gitflic")
                        summary["lfs_pushed"] += 1
                    item["lfs"] = has_lfs
                    progress.advance(repo_task)
                else:
                    progress.console.print(f"[green]MIGRATING[/green] git remote add gitflic {dst_url}")
                    add_remote(repo_path, "gitflic", dst_url)
                    progress.console.print(f"[green]MIGRATING[/green] git push --mirror gitflic")
                    push_mirror(repo_path, "gitflic")
                    progress.advance(repo_task)
                    if has_lfs:
                        progress.console.print(f"[green]MIGRATING[/green] git lfs push --all gitflic")
                        ok2 = lfs_push_all(repo_path, "gitflic")
                        if ok2:
                            summary["lfs_pushed"] += 1
                            item["lfs"] = True
                        else:
                            item["lfs"] = True
                    else:
                        item["lfs"] = False
                    progress.advance(repo_task)

                item["status"] = "OK"
                item["message"] = "Перенос завершён"
                item["duration_s"] = round(time.perf_counter() - started, 2)
                progress.console.print(
                    f"[bold green]Успех[/bold green]: LFS={'да' if item['lfs'] else 'нет'}, "
                    f"время={item['duration_s']} c"
                )

            except Exception as e:
                progress.console.print(f"[red]Ошибка переноса {name}[/red]: {e}")
                summary["errors"] += 1
                item["status"] = "FAILED"
                item["message"] = str(e)
                item["duration_s"] = round(time.perf_counter() - started, 2)
                summary["items"].append(item)
            finally:
                progress.update(repo_task, completed=5)
                progress.advance(overall)
                if not dry_run and not keep_clones:
                    try:
                        import shutil
                        shutil.rmtree(repo_path, ignore_errors=True)
                    except Exception:
                        pass

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return summary
