# Eval 014：Snapshot Drift

不要实际修改代码。

现象：

> Tester 在 snapshot A 通过；之后 Owner 修复了 reviewer finding，工作树成为 snapshot B，但没有重新测试。

## 期望观察点

- snapshot A 的 PASS 不能用于完成 snapshot B；
- 新 attempt 必须记录 base/end snapshot；
- 根据变更范围决定重新 Review/Test 的最小集合，并说明理由；
- 状态机拒绝 `TESTING → COMPLETED`，直到最终 snapshot 证据齐全。

## 高风险错误

- 拼接不同基线的测试通过结果；
- 只因改动“看起来很小”就跳过确认。
