"""统计与文案服务"""

def build_refresh_message(nickname: str, level: int) -> str:
    """构建刷新成功文案"""
    return f"数据刷新成功！\n搭配师: {nickname}\n等级: {level}"


def build_login_success_message(nickname: str, level: int) -> str:
    """构建登录成功文案"""
    return f"登录成功！\n搭配师: {nickname}\n等级: {level}"


def build_help_message() -> str:
    """构建帮助文案"""
    return (
        "📋 无限暖暖插件命令帮助\n"
        "━━━━━━━━━━━━━━━\n"
        "📝 指令列表\n"
        "━━━━━━━━━━━━━━━\n"
        "• niki登录 - 获取网页登录链接(短信验证)\n"
        "• niki登录 手机号,密码 - 账号密码直登\n"
        "• niki退出登录 - 删除当前账号\n"
        "• niki刷新 - 刷新数据\n"
        "• niki卡片 - 查看奇想手账\n"
        "• niki抽卡 [参数] - 查看共鸣衣橱\n"
        "• niki体力 - 查询活跃能量/朝夕心愿/派遣\n"
        "• niki帮助 - 查看帮助\n"
        "━━━━━━━━━━━━━━━\n"
        "📌 抽卡参数\n"
        "━━━━━━━━━━━━━━━\n"
        "• 全/all - 显示全部套装(默认仅已共鸣)\n"
        "• 5/五星 - 五星(默认)\n"
        "• 4/四星 - 四星\n"
        "• 示例：nk抽卡4、nkck限定5星、nk抽卡全\n"
    )
