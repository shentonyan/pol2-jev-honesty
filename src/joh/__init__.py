"""pol2-jev-honesty — 用 Jev（OpenJEV）的类型化判断测量 PoL2「诚实」与「公共性」的实验框架。

模块：
- client      真实 API 客户端（仅标准库）与离线 MockClient
- schema      请求校验（遵循 OpenJEV 文档的类型与上限）
- probes      探针文件加载与请求构建（本地字段绝不发送给模型）
- compose     把答案组合成诚实向量 + 公开权重的综合读数 + 争议标记
- metamorphic 裁判自身的蜕变测试（顺序/键名/量表方向/state 字段顺序/语言）
- sycophancy  谄媚的第三方条件测试（同一内容、不同作者归属）
- drift       漂移哨兵（固定金标集 + JS 散度）
- ledger      公共判决账本（哈希链 + Merkle root）
"""

__version__ = "0.2.0"

HONESTY_CLAUSE = (
    "诚实条款：本结果来自单一闭源模型（Jev，经 OpenJEV 的浮动别名 `openjev` 调用）对合成样本的类型化判断。"
    "它不是对任何真实个人或人群的描述，不能外推到真实人类群体；confidence 只描述分布集中程度，不代表准确率；"
    "Jev 不提供推理步骤，账本中的 reasoning_steps 字段因此如实标记为 not_available。"
)
