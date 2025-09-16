\
import os
import json
from urllib.parse import urlparse
import typer
from dotenv import load_dotenv
from rich import print
from rich import box
from rich.table import Table
from rich.console import Console
from rich.panel import Panel

from src.clients.bitbucket_server import BitbucketServerClient
from src.clients.gitflic import GitFlicClient
from src.core.migrator import migrate_repositories
from src.core.utils import load_yaml

app = typer.Typer(
    help="Bitbucket Server/DC → GitFlic migrator",
    no_args_is_help=False,        
    add_completion=False,         
    rich_markup_mode=None,        
)
console = Console()

@app.callback(invoke_without_command=True)
def root(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        typer.echo("Укажите подкоманду. Например: bb2gf migrate")
        raise typer.Exit(2)

def split_env_list(val: str | None) -> list[str]:
    if not val:
        return []
    raw = val.replace(",", "\n")
    return [x.strip() for x in raw.splitlines() if x.strip()]

def build_targets(env, cli_urls: list[str], cli_keys: list[str]) -> list[tuple[str, str]]:
    """
    Возвращает список (bb_base, project_key).
    Приоритет:
      1) CLI --project-url (можно несколько)
      2) .env: BITBUCKET_PROJECT_URLS (можно несколько)
      3) CLI --project-key (требует BITBUCKET_BASE_URL)
      4) .env: BITBUCKET_PROJECT_URL
      5) .env: BITBUCKET_BASE_URL + BITBUCKET_PROJECT_KEYS
      6) .env: BITBUCKET_BASE_URL + BITBUCKET_PROJECT_KEY
    """
    targets: list[tuple[str, str]] = []

    if cli_urls:
        for u in cli_urls:
            base, key = parse_project_url(u)
            targets.append((base, key))

    elif split_env_list(env.get("BITBUCKET_PROJECT_URLS")):
        for u in split_env_list(env.get("BITBUCKET_PROJECT_URLS")):
            base, key = parse_project_url(u)
            targets.append((base, key))

    elif cli_keys:
        base = (env.get("BITBUCKET_BASE_URL") or "").rstrip("/")
        if not base:
            raise ValueError("Для --project-key требуется BITBUCKET_BASE_URL в .env")
        for k in cli_keys:
            targets.append((base, k))

    elif env.get("BITBUCKET_PROJECT_URL"):
        base, key = parse_project_url(env.get("BITBUCKET_PROJECT_URL"))
        targets.append((base, key))

    else:
        base = (env.get("BITBUCKET_BASE_URL") or "").rstrip("/")
        keys = split_env_list(env.get("BITBUCKET_PROJECT_KEYS")) or (
            [env.get("BITBUCKET_PROJECT_KEY")] if env.get("BITBUCKET_PROJECT_KEY") else []
        )
        if base and keys:
            for k in keys:
                targets.append((base, k))

    # дедупликация
    uniq = []
    seen = set()
    for base, key in targets:
        t = (base, key)
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq

def parse_project_url(project_url: str):
    """
    Expects: https://bitbucket/projects/PROJECT1
    Returns: (base_url, project_key)
    """
    p = urlparse(project_url)
    base = f"{p.scheme}://{p.netloc}"
    parts = [part for part in p.path.split("/") if part]
    # .../projects/<KEY>
    try:
        idx = parts.index("projects")
        project_key = parts[idx + 1]
    except Exception:
        raise ValueError(f"Не удалось извлечь PROJECT_KEY из URL: {project_url}")
    return base, project_key

@app.command()
def migrate(
    project_url: list[str] = typer.Option(
        None, "--project-url", "-u", help="URL проекта Bitbucket (можно несколько)"
    ),
    project_key: list[str] = typer.Option(
        None, "--project-key", "-k", help="Ключ проекта (можно несколько, используется с BITBUCKET_BASE_URL)"
    ),
    dry_run: bool = typer.Option(None, help="Сухой прогон (переопределяет DRY_RUN из .env)"),
):
    load_dotenv()

    env = os.environ
    cfg = load_yaml("config.yml") if os.path.exists("config.yml") else {}

    targets = build_targets(env, list(project_url or []), list(project_key or []))
    
    if not targets:
        typer.echo(
            "Укажите один или несколько --project-url / --project-key, "
            "или задайте BITBUCKET_PROJECT_URL(S) / BITBUCKET_PROJECT_KEY(S) в .env",
            err=True
        )
        raise typer.Exit(2)

    owner_type = (env.get("GITFLIC_OWNER_ALIAS_TYPE") or "TEAM").upper()
    if owner_type not in ("TEAM", "COMPANY"):
        typer.echo("GITFLIC_OWNER_ALIAS_TYPE должен быть TEAM или COMPANY", err=True)
        raise typer.Exit(2)
    
    global_owner_alias = (env.get("GITFLIC_OWNER_ALIAS") or "").strip().lower()
    if len(targets) > 1 and global_owner_alias:
        console.print("[yellow]GITFLIC_OWNER_ALIAS задан, но проектов больше одного — игнорирую и использую project_key в lower[/yellow]")
        global_owner_alias = ""

    bb_clients: dict[str, BitbucketServerClient] = {}
    def get_bb_client(base_url: str) -> BitbucketServerClient:
        if base_url not in bb_clients:
            bb_clients[base_url] = BitbucketServerClient(
                base_url=base_url,
                auth_type=auth_type,
                username=bb_username,
                password=bb_password,
                token=bb_token,
                verify=verify_tls,
                ca_cert=ca_cert,
            )
        return bb_clients[base_url]


    # Bitbucket auth
    auth_type = (env.get("BITBUCKET_AUTH_TYPE") or "BASIC").upper()
    bb_username = env.get("BITBUCKET_USERNAME") or ""
    bb_password = env.get("BITBUCKET_PASSWORD") or ""
    bb_token = env.get("BITBUCKET_TOKEN") or ""
    bb_git_user = env.get("BITBUCKET_GIT_USERNAME") or bb_username
    bb_git_pass = bb_password if auth_type == "BASIC" else (env.get("BITBUCKET_GIT_PASSWORD") or bb_token)
    verify_tls = env.get("BITBUCKET_VERIFY_TLS", "true").lower() == "true"
    ca_cert = env.get("BITBUCKET_CA_CERT") or None

    # GitFlic API
    gf_base = (env.get("GITFLIC_API_BASE_URL") or "http://localhost:8080/rest-api").rstrip("/")
    gf_token = env.get("GITFLIC_API_TOKEN")
    if not gf_token:
        typer.echo("Не задан GITFLIC_API_TOKEN", err=True)
        raise typer.Exit(2)

    # Git push credentials
    use_ssh = (env.get("USE_SSH", "false").lower() == "true")
    gf_git_user = env.get("GITFLIC_GIT_USERNAME")
    gf_git_pass = env.get("GITFLIC_GIT_PASSWORD")

    # Options
    visibility_private = (env.get("VISIBILITY_PRIVATE", "true").lower() == "true")
    raw_lang = (env.get("LANGUAGE_DEFAULT") or "").strip()
    language_default = raw_lang or None  # None = не передавать поле language
    env_dry_run = (env.get("DRY_RUN", "false").lower() == "true")
    if dry_run is None:
        dry_run = env_dry_run

    workdir = env.get("WORKDIR", "/tmp/migrate-bb-to-gf")
    keep_clones = (env.get("KEEP_CLONES", "false").lower() == "true")

    gf = GitFlicClient(base_url=gf_base, api_token=gf_token)

    # Init clients
    global_report = {
        "projects": [],
        "totals": {"total": 0, "created": 0, "exists": 0, "lfs_pushed": 0, "skipped": 0, "errors": 0}
    }

    for bb_base, key in targets:
        owner_alias = (global_owner_alias or str(key)).strip().lower()

        console.rule(f"[bold]Bitbucket → GitFlic: проект {key}[/bold]")
        info_tbl = Table(show_header=False, box=None)
        info_tbl.add_row("Bitbucket", f"{bb_base} (project={key})")
        info_tbl.add_row("GitFlic API", gf_base)
        info_tbl.add_row("ownerAlias / type", f"{owner_alias} / {owner_type}")
        info_tbl.add_row("Visibility", "private" if visibility_private else "public")
        info_tbl.add_row("Language", language_default or "")
        info_tbl.add_row("Dry run", str(dry_run))
        info_tbl.add_row("Workdir", workdir)
        info_tbl.add_row("Use SSH", str(use_ssh))
        console.print(info_tbl)

        bb = get_bb_client(bb_base)
        repos = bb.list_repositories(project_key=key)
        if not repos:
            console.print(f"[yellow]Репозитории не найдены для проекта {key}[/yellow]")
            proj_report = {"project_key": key, "base_url": bb_base, "summary": {"total": 0}}
            global_report["projects"].append(proj_report)
            continue

        report = migrate_repositories(
            repos=repos,
            owner_alias=owner_alias,
            owner_type=owner_type,
            visibility_private=visibility_private,
            language_default=language_default,
            use_ssh=use_ssh,
            dry_run=dry_run,
            workdir=workdir,
            keep_clones=keep_clones,
            bb_client=bb,
            gf_client=gf,
            gf_git_user=gf_git_user,
            gf_git_pass=gf_git_pass,
            bb_git_user=bb_git_user,
            bb_git_pass=bb_git_pass,
        )

        try:
            with open(f"report_{key.lower()}.json", "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        for ksum in global_report["totals"].keys():
            global_report["totals"][ksum] += int(report.get(ksum, 0))
        global_report["projects"].append({"project_key": key, "base_url": bb_base, "summary": report})

    console.rule("[bold]Итоги по проектам[/bold]")

    proj_tbl = Table(box=box.SIMPLE_HEAVY)
    proj_tbl.add_column("Проект", style="bold")
    proj_tbl.add_column("Всего")
    proj_tbl.add_column("Создано")
    proj_tbl.add_column("LFS")
    proj_tbl.add_column("Пропущено")
    proj_tbl.add_column("Ошибок")
    for p in global_report["projects"]:
        s = p.get("summary", {})
        proj_tbl.add_row(
            p.get("project_key", ""),
            str(s.get("total", 0)),
            str(s.get("created", 0)),
            str(s.get("lfs_pushed", 0)),
            str(s.get("skipped", 0)),
            str(s.get("errors", 0)),
        )
    console.print(proj_tbl)

    totals = global_report["totals"]
    all_line = (
        f"[bold]Всего:[/bold] {totals['total']}    "
        f"[green]Создано:[/green] {totals['created']}    "
        f"[cyan]LFS загружено:[/cyan] {totals['lfs_pushed']}    "
        f"[yellow]Пропущено:[/yellow] {totals['skipped']}    "
        f"[red]Ошибок:[/red] {totals['errors']}"
    )
    console.print(Panel(all_line, title="Сводка по всем проектам", border_style="blue"))

    try:
        with open("report_all.json", "w", encoding="utf-8") as f:
            json.dump(global_report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

@app.command("help")
def help_cmd():
    """Краткая справка по командам."""
    typer.echo(
        "Использование:\n"
        "  bb2gf migrate [ОПЦИИ]\n\n"
        "Опции migrate:\n"
        "  -u, --project-url TEXT   URL проекта Bitbucket (можно несколько)\n"
        "  -k, --project-key TEXT   Ключ проекта (можно несколько; требует BITBUCKET_BASE_URL в .env)\n"
        "  --dry-run / --no-dry-run Сухой прогон (переопределяет DRY_RUN из .env)\n\n"
        "Примеры:\n"
        "  bb2gf migrate -u https://bitbucket/projects/SUP -u https://bitbucket/projects/MG\n"
        "  bb2gf migrate -k SUP -k MG   (при заданном BITBUCKET_BASE_URL в .env)\n"
        "  bb2gf migrate                (берёт BITBUCKET_PROJECT_URL(S) или KEYS из .env)\n"
    )

if __name__ == "__main__":
    app()
