# main.py
import logging
import os
from config import DB_CONFIG, YS7_API_CONFIG
from database_manager import DatabaseManager
from api_manager import YS7APIManager
from task_manager import TaskManager


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, 'password_manager.log')
TOKEN_FILE_PATH = os.path.join(BASE_DIR, 'ys7_token.json')

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler()
    ]
)



def run_daily_task():
    """
    执行每日密码管理和预约更新的主函数
    """
    logging.info("==============================================")
    logging.info("====== 每日门锁密码管理任务启动 ======")
    logging.info("==============================================")

    try:
        # 初始化管理器
        db_manager = DatabaseManager(DB_CONFIG)
        api_manager = YS7APIManager(YS7_API_CONFIG, token_file=TOKEN_FILE_PATH)
        task_manager = TaskManager(db_manager, api_manager)

        task_manager.process_locks_and_reservations()

    except Exception as e:
        logging.critical(f"任务执行过程中发生未捕获的严重错误: {e}", exc_info=True)

    logging.info("==============================================")
    logging.info("====== 每日门锁密码管理任务结束 ======")
    logging.info("==============================================")


if __name__ == '__main__':
    run_daily_task()