import json
import hashlib
import numpy as np
import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import logging
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# 配置日志
logger = logging.getLogger(__name__)


class VectorCacheManager:
    """向量化缓存: 使用句子嵌入进行相似度匹配"""
    CACHE_DIR = Path(__file__).parent.parent.parent.parent / "files/vector_cache"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 预加载嵌入模型
    EMBEDDING_MODEL = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

    # 相似度阈值
    SIMILARITY_THRESHOLD = 0.85

    @classmethod
    def _get_cache_file_path(cls, query_hash: str) -> Path:
        """获取缓存文件路径"""
        return cls.CACHE_DIR / f"{query_hash}.json"

    @classmethod
    def _get_embedding_file_path(cls) -> Path:
        """获取嵌入索引文件路径"""
        return cls.CACHE_DIR / "embeddings_index.json"

    @classmethod
    def _get_query_embedding(cls, text: str) -> np.ndarray:
        """获取查询的嵌入向量"""
        return cls.EMBEDDING_MODEL.encode([text], convert_to_numpy=True)[0]

    @classmethod
    def save_params(cls, user_query: str, parsed_params: Dict[str, Any], prompt_text: str) -> str:
        """保存参数到缓存并更新嵌入索引"""
        # 创建唯一哈希标识
        query_hash = hashlib.md5(user_query.encode()).hexdigest()
        cache_file = cls._get_cache_file_path(query_hash)

        # 创建缓存数据
        cache_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "user_query": user_query,
            "parsed_params": parsed_params,
            "prompt_text": prompt_text,
            "embedding": cls._get_query_embedding(user_query).tolist()
        }

        # 保存到文件
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

        # 更新嵌入索引
        cls._update_embedding_index(query_hash, cache_data["embedding"])

        logger.info(f"保存向量缓存: {query_hash}")
        return query_hash

    @classmethod
    def _update_embedding_index(cls, query_hash: str, embedding: List[float]):
        """更新嵌入索引"""
        index_file = cls._get_embedding_file_path()
        index_data = {}

        # 加载现有索引
        if index_file.exists():
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
            except Exception as e:
                logger.error(f"加载嵌入索引失败: {str(e)}")

        # 添加新条目
        index_data[query_hash] = embedding

        # 保存更新后的索引
        try:
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存嵌入索引失败: {str(e)}")

    @classmethod
    def load_cache(cls, query_hash: str) -> Optional[Dict[str, Any]]:
        """从缓存加载数据"""
        cache_file = cls._get_cache_file_path(query_hash)
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载缓存失败: {str(e)}")
            return None

    @classmethod
    def find_similar_query(cls, current_query: str) -> Optional[Tuple[str, Dict]]:
        """使用向量相似度查找相似的历史查询"""
        # 获取当前查询的嵌入向量
        current_embedding = cls._get_query_embedding(current_query)

        # 加载嵌入索引
        index_file = cls._get_embedding_file_path()
        if not index_file.exists():
            return None

        try:
            with open(index_file, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
        except Exception as e:
            logger.error(f"加载嵌入索引失败: {str(e)}")
            return None

        # 如果没有缓存条目，直接返回
        if not index_data:
            return None

        # 准备向量和哈希列表
        embeddings = []
        hashes = []
        for query_hash, embedding in index_data.items():
            embeddings.append(embedding)
            hashes.append(query_hash)

        # 计算相似度
        similarities = cosine_similarity(
            [current_embedding],
            embeddings
        )[0]

        # 找到最相似的条目
        best_idx = np.argmax(similarities)
        best_similarity = similarities[best_idx]
        best_hash = hashes[best_idx]

        # 检查是否超过阈值
        if best_similarity < cls.SIMILARITY_THRESHOLD:
            logger.info(f"最高相似度 {best_similarity:.4f} 低于阈值 {cls.SIMILARITY_THRESHOLD}")
            return None

        # 加载完整的缓存数据
        cache_data = cls.load_cache(best_hash)
        if not cache_data:
            return None

        # 添加相似度信息
        cache_data["similarity"] = best_similarity

        logger.info(f"找到相似查询: {best_hash} (相似度: {best_similarity:.4f})")
        return best_hash, cache_data
