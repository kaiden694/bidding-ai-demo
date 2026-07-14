"""Locust 压测脚本

场景：登录 → 列表 → 详情 → 创建 → 比对 → AI 助手
用户数递增：10 → 50 → 100
报告：QPS / P95 延迟 / 错误率

运行：
    locust -f tests/load/locustfile.py --host=http://localhost:8000
    # 或 headless 模式
    locust -f tests/load/locustfile.py --host=http://localhost:8000 \\
        --headless -u 100 -r 10 -t 5m --html=report.html

前置准备：
    1. 启动后端服务：uvicorn app.main:app --host 0.0.0.0 --port 8000
    2. 启动 Redis：docker run -d -p 6379:6379 redis:7
    3. 启动 PostgreSQL：docker run -d -p 5432:5432 \\
           -e POSTGRES_USER=sbaw -e POSTGRES_PASSWORD=sbaw_change_me \\
           -e POSTGRES_DB=sbaw postgres:16
    4. 初始化种子数据（含 admin/admin123）：python scripts/init_data.py
"""
import random

from locust import HttpUser, task, between


class SBAWUser(HttpUser):
    """智能招投标工作台压测用户

    模拟真实用户行为：
    - on_start 登录获取 access_token
    - 后续请求携带 Authorization: Bearer {token}
    - 按业务权重分配请求频次（列表 > 详情 > 创建）
    """
    wait_time = between(1, 3)  # 请求间隔 1-3 秒
    token = None

    def on_start(self):
        """登录获取 token"""
        # 用 admin/admin123 或测试账号登录
        response = self.client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        if response.status_code == 200:
            data = response.json()
            self.token = data.get("access_token")

    @task(3)
    def list_projects(self):
        """查看项目列表（高频）"""
        self.client.get("/api/v1/projects", headers=self._headers())

    @task(2)
    def list_contracts(self):
        """查看合同列表"""
        self.client.get("/api/v1/contracts", headers=self._headers())

    @task(2)
    def list_knowledge_bases(self):
        """查看知识库列表"""
        self.client.get("/api/v1/knowledge/bases", headers=self._headers())

    @task(1)
    def view_dashboard(self):
        """查看仪表盘"""
        self.client.get("/api/v1/users/me", headers=self._headers())

    @task(1)
    def list_qualifications(self):
        """查看资质列表"""
        self.client.get("/api/v1/qualifications", headers=self._headers())

    @task(1)
    def list_audit_logs(self):
        """查看审计日志（admin）"""
        self.client.get("/api/v1/audit-logs", headers=self._headers())

    @task(1)
    def create_project(self):
        """创建项目（写操作）"""
        self.client.post("/api/v1/projects", json={
            "name": f"压测项目-{random.randint(1000, 9999)}",
            "code": f"LOAD-{random.randint(1000, 9999)}",
        }, headers=self._headers())

    def _headers(self):
        """构建认证头"""
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}
