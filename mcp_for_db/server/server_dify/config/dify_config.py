import os
from pathlib import Path

from dotenv import load_dotenv


class DiFyConfig:
    """DiFy服务配置类"""

    def __init__(self, config: dict = None):
        # 如果传入了配置字典，使用它；否则从环境变量加载
        if config:
            self.DIFY_BASE_URL = config.get('DIFY_BASE_URL') or config.get('base_url')
            self.DIFY_API_KEY = config.get('DIFY_API_KEY') or config.get('api_key')
            self.DIFY_DATASET_ID = config.get('DIFY_DATASET_ID') or config.get('dataset_id')
        else:
            # 从环境变量加载
            root_dir = Path(__file__).parent.parent.parent.parent.parent
            dify_env_file = os.path.join(root_dir, "envs", "dify.env")
            load_dotenv(dify_env_file, override=True)
            self.DIFY_BASE_URL = os.getenv('DIFY_BASE_URL')
            self.DIFY_API_KEY = os.getenv('DIFY_API_KEY')
            self.DIFY_DATASET_ID = os.getenv('DIFY_DATASET_ID')

    def get_headers(self) -> dict:
        """获取API请求头"""
        return {
            'Authorization': f'Bearer {self.DIFY_API_KEY}',
            'Content-Type': 'application/json'
        }


if __name__ == '__main__':
    config = DiFyConfig()
    print(config.DIFY_BASE_URL)
    print(config.DIFY_API_KEY)
    print(config.DIFY_DATASET_ID)
