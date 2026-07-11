# KV Cache Optimization — Decision Record

> 决策: DEFERRED (对小模型不适用，对大模型保留为未来优化)

## Analysis

KV cache optimization was tested on Shehui-LLaMA (15.7M params, 8L/320d).

Result: KV-Cache version was 10x SLOWER than standard batch TRACE.

## Root Cause

```
Standard batch TRACE (our approach):
  batch_size=16, seq_len~100 → 1 forward pass/batch
  Cost: 16 × 100 × 320^2 ≈ 16M ops in < 0.05s

KV-Cache TRACE:
  For each unique first_mask_position → separate forward
  Many small groups → loses batch advantage
  DynamicCache creation/truncation per group → overhead > savings
  Cost: overhead overwhelms compute savings

Net: 106 pairs/s vs 816 pairs/s (7.7x slower)
```

## When KV Cache WOULD Help

```
Model size:  > 100M params → forward pass dominates cost
Sequence length: > 500 tokens → prefix is large
Batch size: > 8 → cache sharing across batch members

Our case: 15M model, 100-token seq, batch=16
→ Cache manipulation overhead > recomputation cost
→ Standard batch approach is optimal
```

## Future

If TRACE moves to larger models (Qwen 0.5B+) or longer sequences (>500 tokens),
revisit KV cache with the following considerations:
- Pre-group by first_mask_position before cache creation
- Use torch.compile on the cache-optimized path
- Consider FlashAttention's built-in KV cache support
