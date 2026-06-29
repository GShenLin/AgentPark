import sys
import os
import traceback

# 确保 src 目录在 python 路径中
sys.path.append(os.getcwd())

from src.providers.gemini_agent import GeminiAgent

def test_connection():
    print("=== Testing Gemini Agent Connection ===")
    try:
        # 初始化 Agent
        agent = GeminiAgent(provider_id="gemini")
        print(f"Model: {agent.config.get('model')}")
        masked_key = agent.config.get('apiKey', '')[:5] + "..." if agent.config.get('apiKey') else "None"
        print(f"API Key: {masked_key}")
        
        print("\nSending test message...")
        # 模拟一条用户消息
        agent.Message("user", "Hello, reply with 'OK' if you can hear me.")
        
        # 发送请求 (run_tools=False 表示仅测试对话，不执行工具)
        response = agent.Send(run_tools=False)
        print(f"\nResponse: {response}")
        
    except Exception as e:
        print(f"\n[!] Error occurred:")
        traceback.print_exc()

if __name__ == "__main__":
    test_connection()