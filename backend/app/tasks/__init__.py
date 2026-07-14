"""Celery 异步任务

导入子模块以确保任务被 Celery worker 注册。
worker 启动时通过 celery_app.conf 的 include 列表自动加载：
- parsing: 文档解析 + 向量化
- comparison_task: 参数偏离比对
- contract_review_task: 合同风险扫描
- qualification_alert: 资质预警定时扫描（每日 09:00 由 Celery Beat 触发）
"""
