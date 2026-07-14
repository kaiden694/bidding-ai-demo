#!/usr/bin/env python3
"""端到端样例验证脚本（T7，Phase 1 MVP）

覆盖完整业务闭环：上传 → 解析 → 比对 / 审查 → 导出

执行流程：
  1.  健康检查 + 登录（Phase 1 占位：无认证端点时匿名放行）
  2.  上传招标文件（doc_type=tender）
  3.  上传规格书（doc_type=spec）
  4.  解析招标文件 → 等待完成
  5.  解析规格书 → 等待完成
  6.  创建参数偏离比对任务 → 等待完成
  7.  获取比对结果
  8.  导出偏离报告（Docx）
  9.  （可选）上传合同文件 → 解析 → 审查 → 导出风险报告

用法：
  python scripts/e2e_demo.py \
      --tender path/to/tender.pdf \
      --spec   path/to/spec.docx \
      --contract path/to/contract.docx

可配置项见 --help（BASE_URL / 用户名密码 / 超时 均可环境变量覆盖）。
"""
from __future__ import annotations

import argparse
import asyncio
import mimetypes
import os
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

# 允许直接 `python scripts/e2e_demo.py` 运行时导入后端模块（合同创建兜底用）
_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import httpx  # noqa: E402

# ---------------------------------------------------------------------------
# 默认配置（环境变量优先）
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
DEFAULT_USERNAME = os.getenv("E2E_USERNAME", "")
DEFAULT_PASSWORD = os.getenv("E2E_PASSWORD", "")
DEFAULT_TIMEOUT = float(os.getenv("E2E_TIMEOUT", "600"))

API_PREFIX = "/api/v1"

# Phase 1 解析/比对为同步执行；以下轮询参数仅作异步场景兜底
PARSE_POLL_INTERVAL = 2.0
PARSE_POLL_TIMEOUT = 300.0
TASK_POLL_INTERVAL = 2.0
TASK_POLL_TIMEOUT = 300.0

# 文档类型枚举（与 app.models.document.DocumentType 对齐）
DOC_TYPE_TENDER = "tender"
DOC_TYPE_SPEC = "spec"
DOC_TYPE_CONTRACT = "contract"

# 终端状态
PARSE_DONE = "done"
PARSE_FAILED = "failed"
TASK_DONE = "done"
TASK_FAILED = "failed"


# ---------------------------------------------------------------------------
# 工具：步骤计时与状态打印
# ---------------------------------------------------------------------------
@contextmanager
def step(name: str):
    """步骤计时上下文：开始/成功/失败均打印状态与耗时"""
    start = time.perf_counter()
    print(f"\n>>> [{name}] 开始 ...")
    try:
        yield
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - start
        print(f"!!! [{name}] 失败（{elapsed:.2f}s）：{exc}")
        raise
    else:
        elapsed = time.perf_counter() - start
        print(f"<<< [{name}] 完成（{elapsed:.2f}s）")


def fail(msg: str, code: int = 1) -> None:
    print(f"\n[FATAL] {msg}", file=sys.stderr)
    raise SystemExit(code)


def _short(obj: Any, limit: int = 120) -> str:
    """截断长文本用于日志打印"""
    s = str(obj).replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "…"


# ---------------------------------------------------------------------------
# E2E 运行器
# ---------------------------------------------------------------------------
class E2ERunner:
    """端到端流程运行器：封装 HTTP 调用与状态轮询"""

    def __init__(self, base_url: str, username: str, password: str,
                 timeout: float, verbose: bool):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.verbose = verbose
        self.token: Optional[str] = None
        self.client = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, follow_redirects=True
        )
        # 结果汇总
        self.summary: list[dict] = []

    # ---- HTTP 基础 ----
    def _headers(self) -> dict:
        h: dict = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = self._headers()
        # 合并调用方传入的 headers
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        resp = await self.client.request(method, url, headers=headers, **kwargs)
        if self.verbose:
            print(f"    {method} {url} -> {resp.status_code}")
        if resp.status_code >= 400:
            body = _short(resp.text, 300)
            raise RuntimeError(f"{method} {url} 失败：HTTP {resp.status_code} {body}")
        return resp

    def _record(self, step_name: str, detail: str, ok: bool = True) -> None:
        self.summary.append({"step": step_name, "detail": detail, "ok": ok})

    # ---- 步骤 0：健康检查 ----
    async def health_check(self) -> None:
        with step("健康检查"):
            resp = await self._request("GET", "/health")
            data = resp.json()
            print(f"    服务：{data.get('app')} env={data.get('env')} "
                  f"version={data.get('version')}")
        self._record("健康检查", f"{data.get('app')} {data.get('version')}")

    # ---- 步骤 1：登录 ----
    async def login(self) -> None:
        """登录获取 JWT token

        Phase 1 占位：后端 deps.get_current_user 在无 token 时返回匿名管理员放行，
        且当前尚未提供 /auth/login 端点。此处尝试登录，失败则匿名放行。
        """
        with step("登录获取 Token"):
            if not self.username:
                print("    未提供用户名，Phase 1 匿名放行")
                self._record("登录", "匿名放行（Phase 1 占位）")
                return
            # 尝试常见登录路径；不存在则回退匿名
            for path in (f"{API_PREFIX}/auth/login", f"{API_PREFIX}/login"):
                try:
                    resp = await self.client.post(
                        path,
                        json={"username": self.username, "password": self.password},
                        headers={"Accept": "application/json"},
                    )
                    if resp.status_code == 404:
                        continue
                    if resp.status_code >= 400:
                        raise RuntimeError(
                            f"登录失败：HTTP {resp.status_code} {_short(resp.text, 200)}"
                        )
                    data = resp.json()
                    token = data.get("access_token") or data.get("token")
                    if token:
                        self.token = token
                        print(f"    登录成功，已获取 token（{path}）")
                        self._record("登录", f"{path} 成功")
                        return
                except httpx.HTTPError as exc:
                    print(f"    登录端点 {path} 不可用：{exc}")
                    continue
            print("    未找到可用登录端点，Phase 1 匿名放行")
            self._record("登录", "匿名放行（未找到登录端点）")

    # ---- 上传文档 ----
    async def upload_document(self, file_path: str, doc_type: str) -> str:
        name = Path(file_path).name
        with step(f"上传文档 [{doc_type}] {name}"):
            if not Path(file_path).is_file():
                raise FileNotFoundError(f"文件不存在：{file_path}")
            mime, _ = mimetypes.guess_type(file_path)
            with open(file_path, "rb") as f:
                files = {"file": (name, f, mime or "application/octet-stream")}
                data = {"doc_type": doc_type}
                resp = await self._request(
                    "POST", f"{API_PREFIX}/documents/upload", files=files, data=data
                )
            doc = resp.json()
            doc_id = doc["id"]
            print(f"    doc_id={doc_id} 解析状态={doc.get('parse_status')} "
                  f"大小={doc.get('file_size')}")
            self._record(f"上传[{doc_type}]", f"id={doc_id}")
            return doc_id

    # ---- 解析文档（含轮询兜底） ----
    async def parse_document(self, doc_id: str, label: str) -> None:
        with step(f"解析文档 [{label}] {doc_id}"):
            resp = await self._request("POST", f"{API_PREFIX}/documents/{doc_id}/parse")
            doc = resp.json()
            status = doc.get("parse_status")
            # Phase 1 同步返回 DONE；若仍 PARSING 则轮询列表兜底
            if status not in (PARSE_DONE, PARSE_FAILED):
                status = await self._wait_parse_done(doc_id)
            if status != PARSE_DONE:
                raise RuntimeError(f"解析未完成，状态={status}")
            page_count = doc.get("page_count")
            meta = doc.get("metadata_json") or {}
            print(f"    解析完成：页数={page_count} 切块数={meta.get('chunk_count')}")
            self._record(f"解析[{label}]", f"页数={page_count} 块数={meta.get('chunk_count')}")

    async def _wait_parse_done(self, doc_id: str) -> str:
        """轮询文档列表直到解析终态"""
        deadline = time.perf_counter() + PARSE_POLL_TIMEOUT
        while time.perf_counter() < deadline:
            await asyncio.sleep(PARSE_POLL_INTERVAL)
            resp = await self._request("GET", f"{API_PREFIX}/documents")
            for d in resp.json():
                if d["id"] == doc_id:
                    st = d.get("parse_status")
                    if st in (PARSE_DONE, PARSE_FAILED):
                        return st
        raise TimeoutError(f"解析轮询超时（{PARSE_POLL_TIMEOUT}s）doc_id={doc_id}")

    # ---- 步骤 6：创建比对任务 ----
    async def create_comparison(self, tender_doc_id: str, spec_doc_id: str) -> str:
        with step("创建参数偏离比对任务"):
            resp = await self._request(
                "POST",
                f"{API_PREFIX}/comparison",
                json={"tender_doc_id": tender_doc_id, "spec_doc_id": spec_doc_id},
            )
            task = resp.json()
            task_id = task["id"]
            status = task.get("status")
            print(f"    task_id={task_id} 初始状态={status}")
            # Phase 1 同步完成；若仍进行中则轮询兜底
            if status not in (TASK_DONE, TASK_FAILED):
                status = await self._wait_task_done(task_id)
            if status != TASK_DONE:
                raise RuntimeError(f"比对任务未完成，状态={status}")
            self._record("创建比对", f"task_id={task_id}")
            return task_id

    async def _wait_task_done(self, task_id: str) -> str:
        deadline = time.perf_counter() + TASK_POLL_TIMEOUT
        while time.perf_counter() < deadline:
            await asyncio.sleep(TASK_POLL_INTERVAL)
            resp = await self._request("GET", f"{API_PREFIX}/comparison/{task_id}")
            st = resp.json().get("status")
            if st in (TASK_DONE, TASK_FAILED):
                return st
        raise TimeoutError(f"比对任务轮询超时（{TASK_POLL_TIMEOUT}s）task_id={task_id}")

    # ---- 步骤 7：获取比对结果 ----
    async def get_comparison_results(self, task_id: str) -> list[dict]:
        with step("获取比对结果"):
            resp = await self._request(
                "GET", f"{API_PREFIX}/comparison/{task_id}/results"
            )
            results = resp.json()
            # 统计判定分布
            counter: dict[str, int] = {}
            for r in results:
                v = r.get("verdict", "?")
                counter[v] = counter.get(v, 0) + 1
            print(f"    参数条目数={len(results)} 判定分布={counter}")
            for r in results[:5]:
                print(f"    - {r.get('param_name')}: "
                      f"招标={_short(r.get('tender_value'), 40)} "
                      f"规格={_short(r.get('spec_value'), 40)} "
                      f"判定={r.get('verdict')} 置信={r.get('confidence')}")
            if len(results) > 5:
                print(f"    ...（共 {len(results)} 条，仅展示前 5 条）")
            self._record("比对结果", f"共{len(results)}条 分布={counter}")
            return results

    # ---- 步骤 8：导出偏离报告 ----
    async def export_comparison(self, task_id: str) -> dict:
        with step("导出偏离报告（Docx）"):
            resp = await self._request(
                "GET", f"{API_PREFIX}/comparison/{task_id}/export"
            )
            data = resp.json()
            print(f"    file_key={data.get('file_key')}")
            print(f"    download_url={_short(data.get('download_url'), 100)}")
            self._record("导出偏离报告", f"file_key={data.get('file_key')}")
            return data

    # ---- 步骤 9a：合同创建 ----
    async def ensure_contract_record(self, document_id: str, title: str) -> str:
        """创建合同审查所需的 Contract 记录（通过 HTTP POST /api/v1/contracts）"""
        with step("创建合同记录"):
            resp = await self.client.post(
                f"{self.base_url}/api/v1/contracts",
                json={
                    "title": title,
                    "document_id": document_id,
                },
                headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()
            contract_id = data["id"]
            print(f"    contract_id={contract_id}")
            self._record("创建合同记录", f"contract_id={contract_id}")
            return contract_id

    # ---- 步骤 9b：合同风险审查 ----
    async def review_contract(self, contract_id: str) -> list[dict]:
        with step("合同风险扫描"):
            resp = await self._request(
                "POST", f"{API_PREFIX}/contracts/{contract_id}/review"
            )
            risks = resp.json()
            counter: dict[str, int] = {}
            for r in risks:
                lv = r.get("level", "?")
                counter[lv] = counter.get(lv, 0) + 1
            print(f"    风险条目数={len(risks)} 等级分布={counter}")
            for r in risks[:5]:
                print(f"    - [{r.get('level')}] {r.get('title')} "
                      f"类别={r.get('category')} 置信={r.get('confidence')}")
            if len(risks) > 5:
                print(f"    ...（共 {len(risks)} 条，仅展示前 5 条）")
            self._record("合同审查", f"共{len(risks)}条 分布={counter}")
            return risks

    # ---- 步骤 10：导出风险报告 ----
    async def export_contract_risk(self, contract_id: str) -> dict:
        with step("导出风险报告（Docx）"):
            resp = await self._request(
                "GET", f"{API_PREFIX}/contracts/{contract_id}/export"
            )
            data = resp.json()
            print(f"    file_key={data.get('file_key')}")
            print(f"    download_url={_short(data.get('download_url'), 100)}")
            self._record("导出风险报告", f"file_key={data.get('file_key')}")
            return data

    async def close(self) -> None:
        await self.client.aclose()

    # ---- 汇总 ----
    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("端到端验证汇总")
        print("=" * 60)
        for item in self.summary:
            mark = "✔" if item["ok"] else "✘"
            print(f"  {mark} {item['step']:<14} {item['detail']}")
        print("=" * 60)
        print(f"共 {len(self.summary)} 步，全部通过 ✓")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
async def run(args: argparse.Namespace) -> None:
    runner = E2ERunner(
        base_url=args.base_url,
        username=args.username,
        password=args.password,
        timeout=args.timeout,
        verbose=args.verbose,
    )
    try:
        # 0. 健康检查
        await runner.health_check()
        # 1. 登录
        await runner.login()

        # 2-5. 上传 + 解析招标文件 / 规格书
        tender_doc_id = await runner.upload_document(args.tender, DOC_TYPE_TENDER)
        spec_doc_id = await runner.upload_document(args.spec, DOC_TYPE_SPEC)
        await runner.parse_document(tender_doc_id, "招标文件")
        await runner.parse_document(spec_doc_id, "规格书")

        # 6-8. 比对 / 结果 / 导出
        task_id = await runner.create_comparison(tender_doc_id, spec_doc_id)
        await runner.get_comparison_results(task_id)
        await runner.export_comparison(task_id)

        # 9-10. 合同审查 / 导出（可选）
        if args.contract:
            contract_doc_id = await runner.upload_document(
                args.contract, DOC_TYPE_CONTRACT
            )
            await runner.parse_document(contract_doc_id, "合同文件")
            contract_title = Path(args.contract).stem
            contract_id = await runner.ensure_contract_record(
                contract_doc_id, contract_title
            )
            await runner.review_contract(contract_id)
            await runner.export_contract_risk(contract_id)

        runner.print_summary()
    finally:
        await runner.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="端到端样例验证脚本（Phase 1 MVP）：上传→解析→比对/审查→导出",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--tender", required=True, help="招标文件路径（PDF/DOCX）")
    p.add_argument("--spec", required=True, help="规格书文件路径（PDF/DOCX/TXT）")
    p.add_argument("--contract", default=None, help="合同文件路径（可选，PDF/DOCX）")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="后端服务地址")
    p.add_argument("--username", default=DEFAULT_USERNAME, help="登录用户名（留空则匿名）")
    p.add_argument("--password", default=DEFAULT_PASSWORD, help="登录密码")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP 超时（秒）")
    p.add_argument("-v", "--verbose", action="store_true", help="打印请求日志")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run(args))
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n[中断] 用户取消", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:  # noqa: BLE001
        fail(f"端到端验证未通过：{exc}")


if __name__ == "__main__":
    main()
