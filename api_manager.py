# api_manager.py
import requests
import logging
import time
import json
import os


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


class YS7APIManager:
    """
    处理与萤石云(YS7)开放平台API所有交互的类。
    """

    def __init__(self, api_config, token_file):
        """
        初始化API管理器。

        :param api_config: API配置字典
        :param token_file: 用于存储和读取token的本地文件名
        """
        self.config = api_config
        self.base_url = self.config['api_base_url']
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/x-www-form-urlencoded'})

        self.token_file = token_file
        self.access_token = None
        self.token_expires_at = 0

        # 尝试从文件加载现有的token
        self._load_token_from_file()

    def _make_request(self, endpoint, data):
        """统一的请求发送方法"""
        url = f"{self.base_url}/{endpoint}"
        try:
            response = self.session.post(url, data=data)
            response.raise_for_status()
            res_json = response.json()
            if res_json.get('code') == '200':
                return res_json.get('data')
            else:
                logging.error(f"API请求失败 at {endpoint}: Code: {res_json.get('code')}, Msg: {res_json.get('msg')}")
                # 处理token失效的特定错误码
                if res_json.get('code') in ['10002', '10017']:  # 10002: accessToken异常或过期, 10017: accessToken不存在
                    logging.info("AccessToken已失效，将强制刷新。")
                    self.get_access_token(force_refresh=True)
                return None
        except requests.exceptions.RequestException as e:
            logging.error(f"API请求异常 at {endpoint}: {e}")
            return None

    def _load_token_from_file(self):
        """从文件中加载token和过期时间"""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    token_data = json.load(f)
                    # 检查token是否仍然有效 (增加60秒的缓冲时间)
                    if token_data.get('expires_at', 0) > time.time() + 60:
                        self.access_token = token_data['access_token']
                        self.token_expires_at = token_data['expires_at']
                        logging.info(f"成功从 {self.token_file} 加载有效的AccessToken。")
                    else:
                        logging.info("文件中的AccessToken已过期。")
            except (IOError, json.JSONDecodeError) as e:
                logging.error(f"从 {self.token_file} 加载token失败: {e}")

    def _save_token_to_file(self):
        """将当前的token和过期时间保存到文件"""
        token_data = {
            'access_token': self.access_token,
            'expires_at': self.token_expires_at
        }
        try:
            with open(self.token_file, 'w') as f:
                json.dump(token_data, f)
            logging.info(f"已将新的AccessToken保存至 {self.token_file}")
        except IOError as e:
            logging.error(f"保存token到 {self.token_file} 失败: {e}")

    def get_access_token(self, force_refresh=False):
        """
        获取accessToken。
        优先从内存和本地文件缓存中读取，过期或强制刷新时才重新请求。
        """
        # 如果不是强制刷新，且内存中的token有效，则直接返回
        if not force_refresh and self.access_token and time.time() < self.token_expires_at:
            return self.access_token

        # 如果需要刷新或token无效，则发起API请求
        logging.info("正在从萤石云API获取新的AccessToken...")
        data = {
            'appKey': self.config['appKey'],
            'appSecret': self.config['appSecret']
        }
        # 直接调用requests.post，避免在_make_request中因token失效产生循环调用
        try:
            response = self.session.post(f"{self.base_url}/token/get", data=data)
            response.raise_for_status()
            res_json = response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"请求AccessToken时发生网络异常: {e}")
            return None

        if res_json.get('code') == '200' and 'data' in res_json:
            token_data = res_json['data']
            self.access_token = token_data['accessToken']
            # token有效期单位是毫秒，转换为秒级时间戳
            expire_seconds = token_data.get('expireTime', 7 * 24 * 3600 * 1000) / 1000
            # 设置本地过期时间，比实际过期时间提前1小时，防止边界问题
            self.token_expires_at = time.time() + expire_seconds - 3600

            logging.info("成功获取新的AccessToken")
            self._save_token_to_file()  # 持久化保存
            return self.access_token
        else:
            logging.error(f"获取AccessToken失败: Code: {res_json.get('code')}, Msg: {res_json.get('msg')}")
            # 获取失败时，清空无效的token信息
            self.access_token = None
            self.token_expires_at = 0
            return None

    def list_temp_passwords(self, device_serial):
        """获取门锁的临时密码列表"""
        token = self.get_access_token()
        if not token: return None
        data = {'accessToken': token, 'deviceSerial': device_serial}
        return self._make_request('keylock/temporary/list', data)

    def delete_temp_password(self, device_serial, temp_index):
        """删除指定的临时密码"""
        token = self.get_access_token()
        if not token: return False
        data = {
            'accessToken': token,
            'deviceSerial': device_serial,
            'tempIndex': str(temp_index)
        }
        result = self._make_request('keylock/temporary/delete', data)
        return result is not None

    def add_temp_password(self, device_serial, begin_time, end_time):
        """添加一个新的临时密码"""
        token = self.get_access_token()
        if not token: return None
        data = {
            'accessToken': token,
            'deviceSerial': device_serial,
            'lockUserName': 'temp',
            'beginTime': str(begin_time),
            'endTime': str(end_time),
            'limitTime': -1
        }
        return self._make_request('keylock/temporary/add', data)
