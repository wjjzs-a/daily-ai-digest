# 自检：验证 Markdown 转换与 Telegram 字节切分，不联网、不发送
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_ai as D

SAMPLE = """## AI 热点

- **OpenAI 再融 110 亿美元**：估值 1.25 万亿，头部两家资本竞赛还在加速。
- **某国产模型登顶**：99.4% 刷新纪录，漏洞挖掘从演示进实战。

## GitHub 热门

- `NVIDIA/auto-ontology` — 语义图谱推理层，Python，8.0k★

## 今天可以点开的那个

**NVIDIA/auto-ontology**。先看 README 的 quickstart。
"""

out = D.md_for_telegram(SAMPLE)
print("=== 转换后 ===")
print(out)
print()
assert "**" not in out, "仍有双星号，Telegram 会显示成字面量"
assert "##" not in out, "仍有 ## 标题"
assert "*OpenAI 再融 110 亿美元*" in out

# 字节切分：造一条超长中文，确认每段 <= 3900 字节且不切坏字符
long_text = ("这是中文测试行，用来验证按 UTF-8 字节切分不会把多字节字符打断。\n" * 400)
chunks = D.tg_split(long_text, 3900)
print(f"=== 切分：{len(long_text)} 字 → {len(chunks)} 段 ===")
for i, c in enumerate(chunks, 1):
    b = len(c.encode("utf-8"))
    print(f"  chunk {i}: {len(c)} 字 / {b} 字节")
    assert b <= 3900, f"chunk {i} 超字节上限: {b}"
    assert "\ufffd" not in c, f"chunk {i} 出现替换符，字符被切断"
print("自检通过")
