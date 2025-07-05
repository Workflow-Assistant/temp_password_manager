# task_manager.py
import logging
import os
from datetime import datetime, time, timedelta
import time as time_module


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


class TaskManager:
    """
    编排密码管理和预约更新任务的类。
    采用“边界调整”策略：基于3个固定时段，根据预约动态调整分界线。
    """

    def __init__(self, db_manager, api_manager):
        self.db = db_manager
        self.api = api_manager

    def _get_fixed_slots_and_midpoints(self, dt_today):
        """获取固定的基础时段和用于计算的中点"""
        slots = {
            1: (
                int(dt_today.replace(hour=0, minute=0, second=0).timestamp()),
                int(dt_today.replace(hour=12, minute=0, second=0).timestamp()) - 1
            ),
            2: (
                int(dt_today.replace(hour=12, minute=0, second=0).timestamp()),
                int(dt_today.replace(hour=18, minute=0, second=0).timestamp()) - 1
            ),
            3: (
                int(dt_today.replace(hour=18, minute=0, second=0).timestamp()),
                int(dt_today.replace(hour=23, minute=59, second=59).timestamp())
            )
        }
        # 注意：第一个时段的中点计算忽略了0-6点
        midpoints = {
            1: int(dt_today.replace(hour=9, minute=0, second=0).timestamp()),
            2: int(dt_today.replace(hour=15, minute=0, second=0).timestamp())
        }
        return slots, midpoints

    def _calculate_slots_by_adjustment(self, appointments, start_of_day, end_of_day):
        """
        根据预约动态调整3个时段的边界。
        """
        dt_today = datetime.fromtimestamp(start_of_day)
        initial_slots, midpoints = self._get_fixed_slots_and_midpoints(dt_today)

        # 将slots转为列表以方便修改
        final_slots = [
            list(initial_slots[1]),
            list(initial_slots[2]),
            list(initial_slots[3])
        ]

        #检查是否存在跨三个时段的预约
        for appointment in appointments:
            if appointment['start_time'] < initial_slots[1][1] and appointment['end_time'] > initial_slots[3][0]:
                # 第一时段结束时间调整为预约的开始时间
                final_slots[0][1] = appointment['start_time'] - 1
                # 第二时段开始时间调整为预约的开始时间
                final_slots[1][0] = appointment['start_time']
                # 第二时段结束时间调整为预约的结束时间
                final_slots[1][1] = appointment['end_time'] - 1
                # 第三时段开始时间调整为预约的结束时间
                final_slots[2][0] = appointment['end_time']
                logging.info(
                    f"跨时段预约调整：时段 1 结束时间调整为 {datetime.fromtimestamp(final_slots[0][1]).strftime('%H:%M:%S')}, "
                    f"时段 2 开始时间调整为 {datetime.fromtimestamp(final_slots[1][0]).strftime('%H:%M:%S')}, "
                    f"时段 2 结束时间调整为 {datetime.fromtimestamp(final_slots[1][1]).strftime('%H:%M:%S')}, "
                    f"时段 3 开始时间调整为 {datetime.fromtimestamp(final_slots[2][0]).strftime('%H:%M:%S')}")
                return [tuple(s) for s in final_slots]


        # 调整 Slot 1 和 Slot 2 的边界
        for i in range(2):  # i=0 for Slot 1, i=1 for Slot 2
            slot_id = i + 1
            midpoint = midpoints[slot_id]

            # 找到落在当前原始时段内的所有预约
            # 特别注意：slot 1的判断范围是0-12点
            slot_start_boundary = initial_slots[slot_id][0]
            slot_end_boundary = initial_slots[slot_id][1]

            relevant_apps = [
                app for app in appointments
                if slot_start_boundary <= app['start_time'] <= slot_end_boundary
            ]

            if not relevant_apps:
                continue

            # --- 应用延长逻辑 ---
            # 查找所有满足延长条件的预约
            extending_apps = [
                app for app in relevant_apps
                if app['start_time'] < midpoint and app['end_time'] > slot_end_boundary
            ]
            if extending_apps:
                # 如果有多个，取那个延伸得最远的预约
                max_end_time = max(app['end_time'] for app in extending_apps)

                # 调整当前时段的结束时间和下一个时段的开始时间
                final_slots[i][1] = max_end_time - 1 # -1 是为了确保结束时间是闭区间
                final_slots[i + 1][0] = max_end_time
                logging.info(
                    f"时段 {slot_id} 因预约被延长至 {datetime.fromtimestamp(max_end_time).strftime('%H:%M:%S')}")
                continue  # 延长逻辑优先，如果执行了延长，则不再执行缩短

            # --- 应用缩短/前提逻辑 ---
            # 查找所有满足缩短/前提条件的预约
            splitting_apps = [
                app for app in relevant_apps
                if app['start_time'] > midpoint and app['end_time'] > slot_end_boundary
            ]
            if splitting_apps:
                # 如果有多个，取那个开始时间最早的预约来作为新的边界
                min_start_time = min(app['start_time'] for app in splitting_apps)

                # 调整当前时段的结束时间和下一个时段的开始时间
                final_slots[i][1] = min_start_time - 1
                final_slots[i + 1][0] = min_start_time
                logging.info(
                    f"时段 {slot_id} 因预约被缩短至 {datetime.fromtimestamp(min_start_time - 1).strftime('%H:%M:%S')}")

        # 最后，进行一次清理，确保时段连续且没有无效区间
        for i in range(len(final_slots)):
            # 确保结束时间不早于开始时间
            if final_slots[i][1] < final_slots[i][0]:
                final_slots[i][1] = final_slots[i][0]  # 设为一个空区间

            # 确保与前一个时段连续
            #if i > 0:
            #    final_slots[i][0] = final_slots[i - 1][1] + 1
            #    if final_slots[i][1] < final_slots[i][0]:
            #        final_slots[i][1] = final_slots[i][0]

        return [tuple(s) for s in final_slots]

    def process_locks_and_reservations(self):
        """主任务流程"""
        logging.info("开始执行(边界调整)密码生成任务...")

        today_start_dt = datetime.combine(datetime.today(), time.min)
        today_date = today_start_dt.date()
        start_of_day_ts = int(today_start_dt.timestamp())
        end_of_day_ts = int((today_start_dt + timedelta(days=1)).timestamp()) - 1

        locks = self.db.get_all_lock_serials()
        if not locks: return

        for serial, des in locks.items():
            logging.info(f"--- 开始处理门锁 {des} 序列号: {serial}---")

            self._clear_existing_passwords(serial, today_date)
            reservations = self.db.get_active_reservations_for_lock_on_date(serial, start_of_day_ts, end_of_day_ts)

            final_slots = self._calculate_slots_by_adjustment(reservations, start_of_day_ts, end_of_day_ts)
            logging.info(f"为门锁 {des} 序列号: {serial} 规划了最终的3个密码时段: {final_slots}")

            # 4. 为这3个时段生成3个密码，并直接按顺序存入数据库
            generated_passwords_info = self._create_and_save_final_passwords(serial, final_slots, today_date)
            if not generated_passwords_info:
                logging.error(f"门锁 {des} 序列号: {serial} 未能生成任何密码，跳过此锁的预约更新。")
                continue

            # 5. 为预约分配密码
            self._assign_passwords_to_reservations(reservations, generated_passwords_info)
            logging.info(f"--- 门锁 {des} 序列号: {serial} 处理完毕 ---")

        current_ts = int(time_module.time())
        self.db.complete_past_reservations(current_ts)
        logging.info("边界调整密码生成任务完成。")

    def _clear_existing_passwords(self, serial, date):
        """清理物理设备和数据库中的密码"""
        logging.info(f"清理门锁 {serial} 在 {date} 的密码...")
        temp_passwords = self.api.list_temp_passwords(serial)
        if temp_passwords:
            for pwd in temp_passwords:
                self.api.delete_temp_password(serial, pwd['tempIndex'])
        self.db.clear_passwords_for_lock_on_date(serial, date)

    def _create_and_save_final_passwords(self, serial, final_slots, date):
        """为最终的3个时段生成密码，并按顺序用ID 1,2,3 保存。"""
        generated_info = []
        for i, (start, end) in enumerate(final_slots, 1):
            password_id = i
            start = start - 1800
            # 确保即使是空区间也生成一个密码，以满足3个密码的要求
            # API可能不允许开始时间大于结束时间，所以需要处理
            if start > end:
                logging.warning(f"时段 {password_id} ({datetime.fromtimestamp(start)}-{datetime.fromtimestamp(end)}) 是无效区间，跳过密码生成。")
                continue

            new_pass_data = self.api.add_temp_password(serial, start, end)
            if new_pass_data and 'pwd' in new_pass_data:
                password = new_pass_data['pwd']
                self.db.save_temp_password(serial, password_id, password, date)
                logging.info(
                    f"为门锁 {serial} 的第 {password_id} 个时段 "
                    f"({datetime.fromtimestamp(start).strftime('%H:%M:%S')}-{datetime.fromtimestamp(end).strftime('%H:%M:%S')}) "
                    f"申请得到密码: {password}")
                generated_info.append({'password': password, 'start_time': start, 'end_time': end})
            else:
                logging.error(f"!! API调用失败：无法为时段 ({datetime.fromtimestamp(start)}-{datetime.fromtimestamp(end)}) 创建密码。")
        return generated_info

    def _assign_passwords_to_reservations(self, reservations, passwords_info):
        """为预约列表分配正确的密码"""
        if not reservations or not passwords_info: return
        logging.info(f"开始为 {len(reservations)} 个预约分配密码...")
        for res in reservations:
            assigned = False
            for pwd_info in passwords_info:
                if res['start_time'] >= pwd_info['start_time'] and res['end_time'] - 1 <= pwd_info['end_time']:
                    self.db.update_reservation_password(res['id'], pwd_info['password'])
                    assigned = True
                    break
            if not assigned:
                logging.warning(
                    f"警告：未能为预约 {res['id']} (时间: {res['start_time']}-{res['end_time']}) 找到匹配的密码时段。")
