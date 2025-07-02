# database_manager.py
import mysql.connector
from mysql.connector import Error
import logging
import os
from contextlib import contextmanager


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, 'password_manager.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler()
    ]
)


class DatabaseManager:
    """处理所有数据库交互的类"""

    def __init__(self, db_config):
        self.db_config = db_config

    @contextmanager
    def get_connection(self):
        """提供一个数据库连接的上下文管理器"""
        connection = None
        try:
            connection = mysql.connector.connect(**self.db_config)
            yield connection
        except Error as e:
            logging.error(f"连接MySQL时出错: {e}")
            raise
        finally:
            if connection and connection.is_connected():
                connection.close()

    def get_all_lock_serials(self):
        """从locks表获取所有门锁的序列号和描述"""
        query = "SELECT id, description FROM locks WHERE band = 'ezviz'"
        with self.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query)
            rows = cursor.fetchall()
            return {row['id']: row['description'] for row in rows}

    def save_temp_password(self, lock_id, password_id, password, effective_date):
        """
        将生成的临时密码存入passwords表。
        如果记录已存在，则更新；否则，插入新记录。
        """
        check_query = "SELECT id FROM passwords WHERE lock_id = %s AND id = %s"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(check_query, (lock_id, password_id))
                result = cursor.fetchone()

                if result:
                    # 记录存在，执行更新操作
                    update_query = """
                                   UPDATE passwords
                                   SET password   = %s, \
                                       updated_at = %s
                                   WHERE lock_id = %s \
                                     AND id = %s \
                                   """
                    cursor.execute(update_query, (password, effective_date, lock_id, password_id))
                else:
                    # 记录不存在，执行插入操作
                    insert_query = """
                                   INSERT INTO passwords (id, lock_id, password, updated_at)
                                   VALUES (%s, %s, %s, %s) \
                                   """
                    cursor.execute(insert_query, (password_id, lock_id, password, effective_date))

                conn.commit()
            except Error as e:
                logging.error(f"为门锁 {lock_id} 保存/更新密码失败: {e}")
                conn.rollback()

    def clear_passwords_for_lock_on_date(self, lock_id, date):
        """删除指定门锁在特定日期的所有密码记录"""
        query = "DELETE FROM passwords WHERE lock_id = %s AND updated_at = %s"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, (lock_id, date))
                conn.commit()
            except Error as e:
                logging.error(f"清除门锁 {lock_id} 旧密码失败: {e}")
                conn.rollback()

    def get_password(self, lock_id, password_id, date):
        """获取指定门锁、日期和序号的密码"""
        query = "SELECT password FROM passwords WHERE lock_id = %s AND id = %s AND updated_at = %s"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (lock_id, password_id, date))
            result = cursor.fetchone()
            return result[0] if result else None

    def get_active_reservations_for_date(self, start_of_day, end_of_day):
        """获取在今天范围内的有效预约"""
        query = """
                SELECT id, lock_id, start_time, end_time
                FROM reservations
                WHERE status = 'active' \
                  AND start_time >= %s \
                  AND start_time < %s \
                """
        with self.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, (start_of_day, end_of_day))
            return cursor.fetchall()

    def get_active_reservations_for_lock_on_date(self, lock_id, start_of_day, end_of_day):
        """获取指定门锁在今天范围内的有效预约"""
        query = """
                SELECT id, lock_id, start_time, end_time
                FROM reservations
                WHERE lock_id = %s \
                  AND status = 'active' \
                  AND start_time >= %s \
                  AND start_time < %s
                ORDER BY start_time \
                """
        with self.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, (lock_id, start_of_day, end_of_day))
            return cursor.fetchall()

    def update_reservation_password(self, reservation_id, password):
        """更新预约记录的密码字段"""
        query = "UPDATE reservations SET password = %s WHERE id = %s"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, (password, reservation_id))
                conn.commit()
                logging.info(f"成功更新预约 {reservation_id} 的密码: {password}")
            except Error as e:
                logging.error(f"更新预约 {reservation_id} 密码失败: {e}")
                conn.rollback()

    def complete_past_reservations(self, current_timestamp):
        """将已结束的有效预约状态更新为 'completed'"""
        query = "UPDATE reservations SET status = 'completed' WHERE end_time < %s AND status = 'active'"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, (current_timestamp,))
                conn.commit()
                logging.info(f"已完成 {cursor.rowcount} 个过期预约的状态更新")
            except Error as e:
                logging.error(f"更新过期预约状态失败: {e}")
                conn.rollback()