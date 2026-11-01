"""NIKIUID 抽卡页面模块。

- nk抽卡页面 / nkck页面 - 生成 10 分钟内有效的临时网页链接
- 网页展示全部套装(五星+四星, 限定+常驻)的抽取数据, 支持筛选/单件明细/分享图
- 命令入口挂在 niki_card 的统一分发里(避免 on_command 双响应), 本模块只提供:
  - page_router.py: FastAPI 路由 + token 缓存 + payload 构建
"""
