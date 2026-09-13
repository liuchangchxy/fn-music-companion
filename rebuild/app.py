#!/usr/bin/env python3
"""LAN dashboard for the bounded two-directory music pipeline."""
from __future__ import annotations

import html
import json
import os
import shutil
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    os.umask(0)
except Exception:
    pass

STATE = Path(os.environ.get("MUSIC_STATE", os.environ.get("MUSIC_DATA", "/state")))
CONFIG, STATUS, LOCK, LOG = STATE / "config.json", STATE / "status.json", STATE / "pipeline.lock", STATE / "last-run.log"
PORT = int(os.environ.get("MUSIC_UI_PORT", "8091"))
DEFAULT_SOURCE = os.environ.get("MUSIC_MOUNT_SOURCE", "")
DEFAULT_OUTPUT = os.environ.get("MUSIC_MOUNT_OUTPUT", "")
if Path("/appdata").is_dir():
    os.environ.setdefault("MUSIC_CACHE_DIR", "/appdata/cache")


def read_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def accessible_paths() -> list[Path]:
    values = os.environ.get("TRIM_DATA_ACCESSIBLE_PATHS", "").split(":")
    values.extend([os.environ.get("MUSIC_MOUNT_SOURCE", ""), os.environ.get("MUSIC_MOUNT_OUTPUT", "")])
    result: list[Path] = []
    for value in values:
        if not value.strip().startswith("/vol"):
            continue
        path = Path(value.strip()).resolve(strict=False)
        if path not in result:
            result.append(path)
    return result


def authorized(path: Path) -> bool:
    candidate = path.resolve(strict=False)
    return any(candidate == root or root in candidate.parents for root in accessible_paths())


def nested(first: Path, second: Path) -> bool:
    first, second = first.resolve(strict=False), second.resolve(strict=False)
    return first == second or first in second.parents or second in first.parents


def config_valid(config: dict) -> tuple[bool, str]:
    allowed_keys = {"source_dir", "output_dir", "sample_verified", "initialized", "proxy", "offline_mode", "admin_password"}
    if set(config) - allowed_keys:
        return False, "配置只能包含受支持的应用设置字段"
    source_raw, output_raw = config.get("source_dir"), config.get("output_dir")
    if not all(isinstance(value, str) and value.startswith("/vol") for value in (source_raw, output_raw)):
        return False, "只能使用飞牛授权返回的真实 /volN/... 路径"
    source, output = Path(source_raw), Path(output_raw)
    if not authorized(source) or not authorized(output):
        return False, "两个目录必须先在飞牛应用权限中授权"
    if not source.is_dir() or not output.is_dir():
        return False, "原始文件夹和整理后文件夹都必须存在"
    if not os.access(source, os.R_OK):
        return False, "原始文件夹不可读"
    if not os.access(output, os.R_OK | os.W_OK | os.X_OK):
        return False, "整理后文件夹不可读写"
    if nested(source, output):
        return False, "两个文件夹不能相同，也不能互相包含"
    return True, ""


def connection() -> sqlite3.Connection:
    database = sqlite3.connect(STATE / "ledger-v6.sqlite", timeout=60)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA journal_mode=WAL;")
    database.execute("PRAGMA busy_timeout=60000;")
    database.execute("PRAGMA synchronous=NORMAL;")
    return database


def latest_runs(limit: int = 20) -> list[dict]:
    database: sqlite3.Connection | None = None
    try:
        database = connection()
        rows = database.execute("SELECT id,mode,status,phase,phase_done,phase_total,started_at,finished_at,summary_json FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["summary"] = json.loads(item.pop("summary_json") or "{}")
            result.append(item)
        return result
    except (OSError, sqlite3.Error, json.JSONDecodeError):
        return []
    finally:
        if database is not None:
            database.close()


def report(run_id: str | None = None) -> dict:
    db_conn: sqlite3.Connection | None = None
    try:
        db_conn = connection()
        if run_id:
            run = db_conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        else:
            run = db_conn.execute("SELECT * FROM runs WHERE status='running' ORDER BY started_at DESC LIMIT 1").fetchone()
            if not run:
                run = db_conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if not run:
            return {}

        target_run_id = run["id"]
        if run["status"] == "done" and run["summary_json"] and run["summary_json"] != "{}":
            try:
                cached = json.loads(run["summary_json"])
                if isinstance(cached, dict) and cached.get("metrics"):
                    return cached
            except json.JSONDecodeError:
                pass

        def counts(column: str) -> dict[str, int]:
            return {str(r["key"]): int(r["value"]) for r in db_conn.execute(f"SELECT {column} AS key,count(*) AS value FROM items WHERE run_id=? GROUP BY {column}", (target_run_id,))}

        dispositions = counts("disposition")
        metadata = counts("metadata_state")
        lyrics = counts("lyrics_state")
        covers = counts("cover_state")
        groups = {str(r["key"]): int(r["value"]) for r in db_conn.execute("SELECT decision AS key,count(*) AS value FROM groups WHERE run_id=? GROUP BY decision", (target_run_id,))}

        lyrics_already_present = lyrics.get("lyrics_already_present", 0)
        lyrics_embedded = lyrics.get("lyrics_embedded", 0)
        cover_already_present = covers.get("cover_already_present", 0)
        cover_embedded = covers.get("cover_embedded", 0)

        metrics = {
            "scanned_total": sum(dispositions.values()),
            "published": dispositions.get("published", 0),
            "exact_duplicate": dispositions.get("duplicate_exact", 0),
            "same_recording_duplicate": dispositions.get("duplicate_same_recording", 0),
            "possible_version_groups": groups.get("keep_all_ambiguous", 0),
            "quality_upgraded": groups.get("quality_upgrade", 0),
            "failed": dispositions.get("failed", 0),
            "metadata_matched": metadata.get("metadata_matched", 0),
            "lyrics_embedded": lyrics_embedded,
            "lyrics_already_present": lyrics_already_present,
            "lyrics_total_with": lyrics_already_present + lyrics_embedded,
            "lyrics_not_found": lyrics.get("lyrics_not_found", 0),
            "cover_embedded": cover_embedded,
            "cover_already_present": cover_already_present,
            "cover_total_with": cover_already_present + cover_embedded,
            "cover_not_found": covers.get("cover_not_found", 0),
            "state_bytes": state_size(),
            "temporary_audio_bytes": 0,
        }
        return {
            "run_id": target_run_id,
            "status": run["status"],
            "phase": {"name": run["phase"], "done": run["phase_done"], "total": run["phase_total"]},
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "dispositions": dispositions,
            "metadata": metadata,
            "lyrics": lyrics,
            "covers": covers,
            "groups": groups,
            "metrics": metrics,
        }
    except Exception:
        return {}
    finally:
        if db_conn is not None:
            db_conn.close()


def sample_ready(config: dict) -> bool:
    marker = config.get("sample_verified") or {}
    run_id = marker.get("run_id") if isinstance(marker, dict) else None
    if not run_id:
        return False
    try:
        with connection() as db_conn:
            return bool(db_conn.execute("SELECT 1 FROM runs WHERE id=? AND mode='sample' AND status='done'", (run_id,)).fetchone())
    except Exception:
        return any(run["id"] == run_id and run["status"] == "done" for run in latest_runs(100))


def state_size() -> int:
    total = 0
    if STATE.exists():
        for path in STATE.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                pass
    return total


def take_lock() -> bool:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        if LOCK.exists():
            try:
                os.kill(int(LOCK.read_text(encoding="ascii")), 0)
                return False
            except (OSError, ValueError):
                try:
                    LOCK.unlink(missing_ok=True)
                except OSError:
                    pass
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except (FileExistsError, OSError):
        return False


GLOBAL_PIPELINE_PROC: subprocess.Popen | None = None


def stop_pipeline() -> None:
    global GLOBAL_PIPELINE_PROC
    proc = GLOBAL_PIPELINE_PROC
    if proc and proc.poll() is None:
        try:
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                try:
                    os.killpg(os.getpgid(proc.pid), 15)
                except OSError:
                    proc.terminate()
            else:
                proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                    try:
                        os.killpg(os.getpgid(proc.pid), 9)
                    except OSError:
                        proc.kill()
                else:
                    proc.kill()
            except Exception:
                pass
    GLOBAL_PIPELINE_PROC = None
    try:
        LOCK.unlink(missing_ok=True)
    except OSError:
        pass

    # Clean up any stale temporary run roots on output disk
    try:
        cfg_val = read_json(CONFIG, {})
        out_str = cfg_val.get("output_dir")
        if out_str and Path(out_str).is_dir():
            for p in Path(out_str).iterdir():
                if p.is_dir() and p.name.startswith(".music-rebuild-run-"):
                    shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[{now_str}] 任务已手动停止。\n")
    except Exception:
        pass
    write_json(STATUS, {"state": "idle", "message": "任务已手动停止"})
    try:
        with connection() as db_conn:
            db_conn.execute("UPDATE runs SET status='stopped',finished_at=CURRENT_TIMESTAMP WHERE status='running'")
            db_conn.commit()
    except Exception:
        pass


def reset_system(clear_history: bool = True, clear_inventory: bool = True, clear_kb: bool = False, clear_ncm: bool = False) -> dict:
    if read_json(STATUS, {}).get("state") == "running":
        raise RuntimeError("任务运行中，禁止执行重置操作")

    # 1. Clear database tables
    db_path = STATE / "ledger-v6.sqlite"
    if db_path.is_file():
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            if clear_history:
                for tbl in ("runs", "items", "groups", "events"):
                    try:
                        conn.execute(f"DELETE FROM {tbl}")
                    except sqlite3.OperationalError:
                        pass
            if clear_inventory:
                try:
                    conn.execute("DELETE FROM source_inventory")
                except sqlite3.OperationalError:
                    pass
            if clear_kb:
                try:
                    conn.execute("DELETE FROM knowledge_base")
                except sqlite3.OperationalError:
                    pass
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()

    # 2. Reset Dupsonic if exists
    dup_db = STATE / "dupsonic-v6.sqlite"
    if clear_history and dup_db.is_file():
        try:
            conn = sqlite3.connect(dup_db, timeout=10)
            conn.execute("DELETE FROM files")
            conn.commit()
            conn.execute("VACUUM")
            conn.close()
        except Exception:
            pass

    # 3. Clear NCM cache directory if requested
    # 3. Clear NCM cache directory and legacy work dirs if requested
    ncm_count = 0
    if clear_ncm:
        cache_dir = Path(os.environ.get("MUSIC_CACHE_DIR", "/appdata/cache"))
        if cache_dir.is_dir():
            for p in list(cache_dir.rglob("*")):
                try:
                    if p.is_file():
                        p.unlink()
                        ncm_count += 1
                except OSError:
                    pass
            shutil.rmtree(cache_dir, ignore_errors=True)
        legacy_work = Path("/appdata/work")
        if legacy_work.is_dir():
            shutil.rmtree(legacy_work, ignore_errors=True)

    # 4. Clear Log & Reset Status
    if clear_history:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            LOG.write_text("", encoding="utf-8")
        except OSError:
            pass
        write_json(STATUS, {
            "state": "idle",
            "message": "系统状态与历史记录已重置，已回到从头开始状态"
        })

    # 5. Reset config flags if inventory cleared
    cfg_val = read_json(CONFIG, {})
    if clear_inventory:
        cfg_val.pop("sample_verified", None)
        cfg_val.pop("initialized", None)
        write_json(CONFIG, cfg_val)

    return {
        "success": True,
        "cleared_history": clear_history,
        "cleared_inventory": clear_inventory,
        "cleared_knowledge_base": clear_kb,
        "cleared_ncm_cache_files": ncm_count,
        "message": "已成功重置，可从头开始执行整理！"
    }


def run_pipeline(mode: str) -> None:
    global GLOBAL_PIPELINE_PROC
    try:
        cfg_val = read_json(CONFIG, {})
        proxy = str(cfg_val.get("proxy", "")).strip()
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        if proxy:
            env["HTTP_PROXY"] = proxy
            env["HTTPS_PROXY"] = proxy
            env["ALL_PROXY"] = proxy
            env["http_proxy"] = proxy
            env["https_proxy"] = proxy
            env["all_proxy"] = proxy
        with LOG.open("a", encoding="utf-8") as handle:
            proc = subprocess.Popen(
                ["python3", "/opt/music-rebuild/pipeline.py", mode],
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                start_new_session=(os.name != "nt")
            )
            GLOBAL_PIPELINE_PROC = proc
            returncode = proc.wait()
        GLOBAL_PIPELINE_PROC = None
        if returncode:
            current = read_json(STATUS, {})
            if current.get("state") != "idle":
                write_json(STATUS, {"state": "failed", "message": "整理失败；查看日志", "mode": mode})
    finally:
        GLOBAL_PIPELINE_PROC = None
        try:
            LOCK.unlink(missing_ok=True)
        except OSError:
            pass


def start_mode(mode: str) -> tuple[int, str]:
    config = read_json(CONFIG, {})
    valid, message = config_valid(config)
    if not valid:
        return 400, message
    allowed = (
        mode == "sample"
        or (mode == "full" and (sample_ready(config) or bool(config.get("initialized"))))
        or (mode == "incremental" and bool(config.get("initialized")))
    )
    if not allowed:
        return 409, "当前阶段不能执行此操作"
    if not take_lock():
        return 409, "已有任务在运行"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text(f"[{now_str}] 正在初始化并启动 [{mode}] 整理流水线...\n", encoding="utf-8")
    except Exception:
        pass
    write_json(STATUS, {"state": "running", "message": f"正在启动 {mode} 整理...", "mode": mode, "phase": "starting", "phase_done": 0, "phase_total": 0})
    threading.Thread(target=run_pipeline, args=(mode,), daemon=True).start()
    return 202, json.dumps({"accepted": True, "mode": mode}, ensure_ascii=False)


DASHBOARD_HTML = Path(__file__).with_name("dashboard.html")

def render_dashboard() -> str:
    if DASHBOARD_HTML.is_file():
        return DASHBOARD_HTML.read_text(encoding="utf-8")
    config = read_json(CONFIG, {})
    state = read_json(STATUS, {"state": "idle", "message": "请先保存目录"})
    latest = report()
    metrics = latest.get("metrics", {}) if isinstance(latest, dict) else {}
    running, initialized, sampled = state.get("state") == "running", bool(config.get("initialized")), sample_ready(config)
    if running:
        action = "<p>正在运行；页面每 5 秒刷新。</p>"
    elif initialized:
        action = '<button data-mode="incremental">增量整理</button>'
    elif sampled:
        action = '<button data-mode="full">全量整理</button><p class="warn">全量前必须由你清空整理后目录；程序不会自动删除旧文件。</p>'
    else:
        action = '<button data-mode="sample">验证样本</button>'
    choices = "".join(f'<option value="{html.escape(str(path), quote=True)}">{html.escape(str(path))}</option>' for path in accessible_paths())
    labels = (("scanned_total", "扫描"), ("published", "发布"), ("exact_duplicate", "精确重复"), ("same_recording_duplicate", "同录音重复"), ("possible_version_groups", "疑似版本组"), ("lyrics_embedded", "歌词写入"), ("cover_embedded", "封面嵌入"), ("failed", "失败"))
    cards = "".join(f'<div class="card"><b>{int(metrics.get(key, 0))}</b><span>{label}</span></div>' for key, label in labels)
    rows = "".join(f'<tr><td>{html.escape(run["id"])}</td><td>{html.escape(run["mode"])}</td><td>{html.escape(run["status"])}</td><td>{html.escape(run["phase"])}</td></tr>' for run in latest_runs(8)) or '<tr><td colspan="4">暂无记录</td></tr>'
    source = html.escape(config.get("source_dir", DEFAULT_SOURCE), quote=True)
    output = html.escape(config.get("output_dir", DEFAULT_OUTPUT), quote=True)
    refresh = "setTimeout(()=>location.reload(),5000)" if running else ""
    return f'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{{font:16px system-ui;max-width:960px;margin:30px auto;padding:0 16px;color:#202124}}label,input,select,button{{display:block;width:100%;box-sizing:border-box;margin:8px 0}}button{{width:auto;padding:9px 14px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.card{{padding:12px;background:#f4f5f7;border-radius:8px}}.card b,.card span{{display:block}}.card b{{font-size:24px}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #ddd;padding:7px;text-align:left}}.warn{{color:#9b4700}}</style><h1>音乐整理</h1><p>{html.escape(str(state.get("message", "")))}</p><form id="cfg"><label>原始文件夹（只读）</label><input id="source" value="{source}" required><select onchange="document.getElementById('source').value=this.value"><option value="">选择已授权目录</option>{choices}</select><label>整理后文件夹（读写）</label><input id="output" value="{output}" required><select onchange="document.getElementById('output').value=this.value"><option value="">选择已授权目录</option>{choices}</select><button>保存两个目录</button></form><h2>操作</h2>{action}<h2>运行摘要</h2><div class="grid">{cards}</div><p>应用状态：{state_size()/1024**2:.1f} MiB / 512 MiB。音频临时文件仅在整理后目录的本次运行期间存在，结束即清理。</p><h2>最近运行</h2><table><tr><th>ID</th><th>模式</th><th>状态</th><th>阶段</th></tr>{rows}</table><p><a href="/api/report">报告 JSON</a> · <a href="/api/log">运行日志</a></p><script>async function post(url,data){{let r=await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}});if(!r.ok)alert(await r.text());else location.reload()}}document.getElementById('cfg').onsubmit=e=>{{e.preventDefault();post('/api/config',{{source_dir:source.value.trim(),output_dir:output.value.trim()}})}};document.querySelectorAll('[data-mode]').forEach(x=>x.onclick=()=>post('/api/run',{{mode:x.dataset.mode}}));{refresh}</script>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass
    def send(self, code: int, body: str, kind: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self.send(200, json.dumps(read_json(CONFIG, {}), ensure_ascii=False), "application/json")
        elif parsed.path == "/api/status":
            self.send(200, json.dumps(read_json(STATUS, {"state": "idle"}), ensure_ascii=False), "application/json")
        elif parsed.path == "/api/report":
            self.send(200, json.dumps(report(parse_qs(parsed.query).get("run_id", [None])[0]), ensure_ascii=False), "application/json")
        elif parsed.path == "/api/runs":
            self.send(200, json.dumps(latest_runs(), ensure_ascii=False), "application/json")
        elif parsed.path == "/api/accessible-paths":
            paths = [str(p) for p in accessible_paths()]
            self.send(200, json.dumps(paths, ensure_ascii=False), "application/json")
        elif parsed.path in ("/favicon.ico", "/favicon.png", "/icon.png"):
            icon_file = Path(__file__).with_name("favicon.ico" if parsed.path == "/favicon.ico" else "favicon.png")
            if not icon_file.is_file():
                icon_file = Path(__file__).with_name("favicon.png")
            if icon_file.is_file():
                ctype = "image/x-icon" if icon_file.suffix == ".ico" else "image/png"
                data = icon_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
                return
            self.send(404, "Icon not found", "text/plain")
        elif parsed.path == "/api/sponsor-qr":
            qr_type = parse_qs(parsed.query).get("type", ["wechat"])[0]
            filename = "wechat_pay.png" if qr_type == "wechat" else "alipay_pay.png"
            qr_file = STATE / filename
            if not qr_file.is_file():
                alt = STATE / (filename.rsplit(".", 1)[0] + ".jpg")
                if alt.is_file():
                    qr_file = alt
            if not qr_file.is_file():
                app_dir = Path(__file__).parent
                qr_file = app_dir / filename
                if not qr_file.is_file():
                    alt = app_dir / (filename.rsplit(".", 1)[0] + ".jpg")
                    if alt.is_file():
                        qr_file = alt
            if qr_file.is_file():
                content_type = "image/png" if qr_file.suffix.lower() == ".png" else "image/jpeg"
                data = qr_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(data)
                return
            self.send(404, "QR not found", "text/plain; charset=utf-8")
        elif parsed.path == "/api/log":
            if not LOG.exists():
                self.send(200, "尚无日志\n", "text/plain; charset=utf-8")
                return
            try:
                content = LOG.read_text(encoding="utf-8")
                qs = parse_qs(parsed.query)
                tail_param = qs.get("tail", [None])[0]
                if tail_param:
                    try:
                        count = int(tail_param)
                        lines = content.splitlines()
                        if len(lines) > count:
                            content = f"... (已隐藏较早日志，仅展示最新 {count} 行；可点击「下载完整日志」导出全量记录)\n\n" + "\n".join(lines[-count:]) + "\n"
                    except ValueError:
                        pass
                self.send(200, content, "text/plain; charset=utf-8")
            except Exception as exc:
                self.send(500, f"读取日志异常: {exc}", "text/plain; charset=utf-8")
        elif parsed.path == "/api/log/download":
            if LOG.exists():
                try:
                    data = LOG.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream; charset=utf-8")
                    self.send_header("Content-Disposition", 'attachment; filename="musicflow-runtime.log"')
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception as exc:
                    self.send(500, f"下载日志异常: {exc}", "text/plain; charset=utf-8")
                    return
            self.send(404, "日志文件尚不存在", "text/plain; charset=utf-8")
        else:
            self.send(200, render_dashboard())

    def do_POST(self) -> None:
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send(400, "请求格式错误")
            return

        cfg_val = read_json(CONFIG, {})
        req_pwd = cfg_val.get("admin_password")
        if req_pwd and self.path in ("/api/config", "/api/run", "/api/stop", "/api/reset", "/api/log/clear"):
            given_pwd = self.headers.get("X-Admin-Password") or body.get("admin_password")
            if given_pwd != req_pwd:
                self.send(401, json.dumps({"error": "控制台访问受限：管理密码不匹配", "require_password": True}, ensure_ascii=False), "application/json")
                return

        if self.path == "/api/config":
            if read_json(STATUS, {}).get("state") == "running":
                self.send(409, "任务运行中，不能更改目录")
                return
            new = {
                "source_dir": str(body.get("source_dir", "")).strip(),
                "output_dir": str(body.get("output_dir", "")).strip(),
            }
            proxy_val = str(body.get("proxy", "")).strip()
            if proxy_val:
                new["proxy"] = proxy_val
            if "offline_mode" in body:
                new["offline_mode"] = bool(body.get("offline_mode"))
            if "admin_password" in body:
                p_val = str(body.get("admin_password", "")).strip()
                if p_val:
                    new["admin_password"] = p_val
            valid, message = config_valid(new)
            if not valid:
                self.send(400, message)
                return
            old = read_json(CONFIG, {})
            if old.get("source_dir") == new["source_dir"] and old.get("output_dir") == new["output_dir"]:
                for key in ("sample_verified", "initialized"):
                    if key in old:
                        new[key] = old[key]
            write_json(CONFIG, new)
            msg = "配置已保存，随时可以开始整理" if sample_ready(new) else "配置已保存；请先验证样本"
            write_json(STATUS, {"state": "idle", "message": msg})
            self.send(200, json.dumps(new, ensure_ascii=False), "application/json")
            return
        if self.path == "/api/run":
            code, message = start_mode(str(body.get("mode", "")))
            self.send(code, message, "application/json" if code == 202 else "text/plain; charset=utf-8")
            return
        if self.path == "/api/stop":
            stop_pipeline()
            self.send(200, json.dumps({"stopped": True, "message": "任务已停止"}, ensure_ascii=False), "application/json")
            return
        if self.path == "/api/log/clear":
            try:
                LOG.parent.mkdir(parents=True, exist_ok=True)
                LOG.write_text("", encoding="utf-8")
            except OSError:
                pass
            self.send(200, json.dumps({"cleared": True}, ensure_ascii=False), "application/json")
            return
        if self.path == "/api/reset":
            try:
                res = reset_system(
                    clear_history=bool(body.get("clear_history", True)),
                    clear_inventory=bool(body.get("clear_inventory", True)),
                    clear_kb=bool(body.get("clear_knowledge_base", False)),
                    clear_ncm=bool(body.get("clear_ncm_cache", False))
                )
                self.send(200, json.dumps(res, ensure_ascii=False), "application/json")
            except Exception as exc:
                self.send(400, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json")
            return
        self.send(404, "不存在")


if __name__ == "__main__":
    STATE.mkdir(parents=True, exist_ok=True)
    if not LOCK.exists():
        curr_status = read_json(STATUS, {})
        if curr_status.get("state") == "running":
            write_json(STATUS, {"state": "idle", "message": "服务已就绪，随时可以开始整理"})
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
