#!/usr/bin/env python3
"""
交互输入测试脚本 - 用于测试 AgentPark ConsoleCommand 节点的交互输入功能

使用方法:
  在 ConsoleCommand 节点里执行: python scripts/test_interactive.py
  然后在右侧 Live 输出区的交互输入栏依次回答问题
"""
import sys
import time


def prompt(msg: str) -> str:
    print(msg, flush=True, end="")
    line = sys.stdin.readline()
    if not line:  # EOF
        return ""
    return line.rstrip("\r\n")


def main():
    print("=" * 50, flush=True)
    print("  交互输入测试脚本 v1.0", flush=True)
    print("=" * 50, flush=True)
    print("", flush=True)

    # 测试1: 普通文本输入
    name = prompt("[1/5] 请输入你的名字: ")
    if not name:
        print("(收到 EOF，退出)", flush=True)
        return
    print(f"    你好, {name}!", flush=True)
    print("", flush=True)

    # 测试2: YES/NO 确认
    ans = prompt("[2/5] 是否继续测试? (yes/no): ").lower().strip()
    if ans not in ("y", "yes"):
        print("    收到，测试中止。", flush=True)
        return
    print("    继续测试...", flush=True)
    print("", flush=True)

    # 测试3: 数字输入
    while True:
        num_str = prompt("[3/5] 请输入一个 1-10 的数字: ").strip()
        if not num_str:
            print("(收到 EOF，退出)", flush=True)
            return
        try:
            num = int(num_str)
            if 1 <= num <= 10:
                print(f"    你输入的数字平方是: {num ** 2}", flush=True)
                break
            else:
                print("    数字不在范围内，请重试。", flush=True)
        except ValueError:
            print(f"    '{num_str}' 不是有效数字，请重试。", flush=True)
    print("", flush=True)

    # 测试4: 多行输入（直到输入空行）
    print("[4/5] 请输入多行文本（空行结束）:", flush=True)
    lines = []
    while True:
        line = prompt("> ")
        if not line:  # 空行或EOF
            break
        lines.append(line)
    print(f"    你一共输入了 {len(lines)} 行:", flush=True)
    for i, line in enumerate(lines, 1):
        print(f"      {i}: {line}", flush=True)
    print("", flush=True)

    # 测试5: 等待后退出（模拟长任务，期间可测试 Ctrl+C）
    print("[5/5] 最后测试: 倒计时 10 秒，可以按 Ctrl+C 中断...", flush=True)
    for i in range(10, 0, -1):
        print(f"    倒计时: {i}...", flush=True)
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            print("", flush=True)
            print("    收到 Ctrl+C (KeyboardInterrupt)，正常退出。", flush=True)
            return

    print("", flush=True)
    print("=" * 50, flush=True)
    print("  所有测试通过! ✅", flush=True)
    print("=" * 50, flush=True)


if __name__ == "__main__":
    main()
