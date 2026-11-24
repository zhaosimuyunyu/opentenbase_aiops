"""DeepSeek LLM client (OpenAI-compatible)"""
from typing import List, Dict, Any, Optional
from openai import OpenAI
from ..utils.config import Config
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class DeepSeekClient:
    """DeepSeek API client using OpenAI-compatible interface"""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()

        if not self.config.DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY is required")

        self.client = OpenAI(
            api_key=self.config.DEEPSEEK_API_KEY,
            base_url=self.config.DEEPSEEK_API_BASE
        )
        self.model = self.config.DEEPSEEK_MODEL
        logger.info(f"DeepSeek client initialized with model: {self.model}")

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ) -> str:
        """Send chat completion request"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream
            )

            if stream:
                return response  # Return generator for streaming
            else:
                return response.choices[0].message.content

        except Exception as e:
            logger.error(f"DeepSeek API error: {e}")
            raise

    def answer_question(
        self,
        question: str,
        context: Optional[str] = None,
        system_prompt: Optional[str] = None
    ) -> str:
        """Answer a question with optional context"""

        default_system = """你是 OpenTenBase 数据库专家助手。
你的任务是帮助用户诊断和解决 OpenTenBase 分布式数据库的问题。

回答要求：
1. 简洁明了，直接给出答案
2. 如果是故障诊断，按照：问题原因 → 解决方案 → 验证步骤
3. 提供具体的 SQL 或命令示例
4. 如果不确定，明确说明
"""

        messages = [
            {"role": "system", "content": system_prompt or default_system}
        ]

        if context:
            messages.append({
                "role": "user",
                "content": f"参考信息：\n{context}\n\n问题：{question}"
            })
        else:
            messages.append({"role": "user", "content": question})

        return self.chat(messages)

    def diagnose_issue(
        self,
        issue_description: str,
        cluster_data: Dict[str, Any]
    ) -> str:
        """Diagnose database issue with cluster data"""

        system_prompt = """你是 OpenTenBase 分布式数据库诊断专家。
基于用户描述和集群数据，进行根因分析并给出解决方案。

输出格式：
## 问题诊断
[分析问题原因]

## 解决方案
1. [步骤1]
2. [步骤2]

## 验证方法
[如何验证问题已解决]
"""

        context = f"""
集群信息：
- 节点数：{len(cluster_data.get('nodes', []))}
- 连接数：{cluster_data.get('connections', {}).get('total', 'unknown')}
- 复制状态：{len(cluster_data.get('replication', []))} 个复制连接

详细数据：
{str(cluster_data)[:2000]}  # 限制长度
"""

        return self.answer_question(
            question=issue_description,
            context=context,
            system_prompt=system_prompt
        )

    def generate_health_summary(
        self,
        cluster_data: Dict[str, Any],
        performance_data: Dict[str, Any]
    ) -> str:
        """Generate health check summary with AI insights"""

        prompt = f"""
请分析以下 OpenTenBase 集群的健康状况：

集群数据：
{str(cluster_data)[:1500]}

性能数据：
{str(performance_data)[:1500]}

请生成健康巡检报告，包括：
1. 整体健康评分（0-100）
2. 发现的问题（按严重程度排序）
3. 优化建议
4. 需要立即处理的项目
"""

        return self.answer_question(prompt)
