from openai import OpenAI


class OpenAICompatibleClient:
    """
    通用大语言模型客户端。
    可以连接 OpenAI、阿里云、智谱、Ollama 等任何兼容 OpenAI 接口的服务。
    """

    def __init__(self, model: str, api_key: str, base_url: str):
        """
        初始化客户端。

        参数:
            model: 模型名称，如 "gpt-3.5-turbo"、"qwen-turbo"
            api_key: 你的 API 密钥
            base_url: API 地址，如 "https://api.openai.com/v1"
        """
        self.model = model
        # 创建 OpenAI 客户端实例
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, prompt: str, system_prompt: str) -> str:
        """
        调用大模型生成回复。

        参数:
            prompt: 用户的问题（包含历史记录）
            system_prompt: 给模型的"角色说明书"
        返回: 模型生成的文本
        """
        print("  → 正在调用大语言模型...")

        try:
            # 构造消息列表：先告诉它角色，再告诉它具体问题
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]

            # 发送请求
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False  # 非流式，等完整结果返回
            )

            # 提取回复内容
            answer = response.choices[0].message.content
            print("  → 大语言模型响应成功")
            return answer

        except Exception as e:
            print(f"  → 调用LLM API时发生错误: {e}")
            return "错误:调用语言模型服务时出错。"
