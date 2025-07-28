import json
import hashlib
import numpy as np
import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import logging
from sentence_transformers import SentenceTransformer
from server.utils.logger import get_logger, configure_logger
from sklearn.metrics.pairwise import cosine_similarity
import os
import threading

# 配置日志
logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(logging.WARNING)


class VectorCacheManager:
    """高性能向量缓存管理器 - 集成优化逻辑"""
    CACHE_DIR = Path(__file__).parent.parent.parent.parent / "files/vector_cache"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 使用更轻量级的模型
    MODEL_NAME = "sentence-transformers/paraphrase-MiniLM-L6-v2"

    # 嵌入维度
    EMBEDDING_DIM = 384  # MiniLM-L6模型的维度

    # 相似度阈值
    SIMILARITY_THRESHOLD = 0.85

    # 模型实例
    _embedding_model = None
    _model_lock = threading.Lock()

    # 预热缓存
    _warm_embeddings = {}

    @classmethod
    def _get_embedding_model(cls):
        """线程安全的模型加载"""
        if cls._embedding_model is None:
            with cls._model_lock:
                if cls._embedding_model is None:
                    logger.info("正在加载嵌入模型...")
                    cls._embedding_model = SentenceTransformer(cls.MODEL_NAME)
                    logger.info("嵌入模型加载完成")
        return cls._embedding_model

    @classmethod
    def preload_model(cls):
        """预加载模型（可选）"""
        cls._get_embedding_model()

    @classmethod
    def warmup_cache(cls, common_queries: List[str]):
        """预热缓存 - 预先计算常见查询的嵌入向量"""
        logger.info("开始预热向量缓存")
        model = cls._get_embedding_model()

        # 批量获取嵌入向量
        embeddings = model.encode(
            common_queries,
            batch_size=32,
            convert_to_numpy=True
        )

        # 存储预热的嵌入向量
        cls._warm_embeddings = dict(zip(common_queries, embeddings))
        logger.info(f"预热完成，缓存了 {len(common_queries)} 个查询的嵌入向量")

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
        # 优先使用预热缓存
        if text in cls._warm_embeddings:
            return cls._warm_embeddings[text]

        model = cls._get_embedding_model()
        return model.encode([text], convert_to_numpy=True)[0]

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
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存缓存文件失败: {str(e)}")
            return ""

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
            # 使用临时文件确保原子写入
            temp_file = index_file.with_suffix(".tmp")
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)

            # 原子替换文件
            os.replace(temp_file, index_file)
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
        try:
            # 获取当前查询的嵌入向量
            current_embedding = cls._get_query_embedding(current_query)

            # 加载嵌入索引
            index_data = cls._load_embedding_index()

            if not index_data:
                return None

            # 准备向量和哈希列表
            embeddings = []
            hashes = []
            for query_hash, embedding in index_data.items():
                embeddings.append(embedding)
                hashes.append(query_hash)

            # 检查嵌入维度是否一致
            if len(embeddings) > 0 and len(embeddings[0]) != cls.EMBEDDING_DIM:
                logger.warning(f"嵌入维度不匹配: 预期 {cls.EMBEDDING_DIM}, 实际 {len(embeddings[0])}")
                return None

            # 计算相似度
            similarities = cls._calculate_similarities(current_embedding, embeddings)

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
        except Exception as e:
            logger.error(f"查找相似查询失败: {str(e)}")
            return None

    @classmethod
    def _load_embedding_index(cls) -> Dict[str, List[float]]:
        """加载嵌入索引"""
        index_file = cls._get_embedding_file_path()
        if not index_file.exists():
            return {}

        try:
            with open(index_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载嵌入索引失败: {str(e)}")
            return {}

    @classmethod
    def _calculate_similarities(cls, current_embedding: np.ndarray, embeddings: List[List[float]]) -> np.ndarray:
        """计算相似度"""
        # 转换列表为NumPy数组
        embeddings_array = np.array(embeddings, dtype=np.float32)
        current_embedding_array = np.array([current_embedding], dtype=np.float32)

        # 计算相似度
        return cosine_similarity(current_embedding_array, embeddings_array)[0]
