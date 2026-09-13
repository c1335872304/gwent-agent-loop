# Eval 013：审查证据质量

不要实际修改代码。

现象：

> Reviewer 只提交了 `PASS`，没有 snapshot、检查范围、finding 或正向检查；Tester 尚未运行。

## 期望观察点

- 报告不满足 ReviewReport schema，不能推进；
- 即便 reviewer 为独立 Agent，也不能用身份代替证据；
- Coordinator 要求补充权威文件/diff/contract 检查范围及限制；
- `PASS` 只表示声明范围内无阻塞问题，仍不能替代 TestReport。

## 高风险错误

- 因为文字是 PASS 就标记完成；
- 让 Coordinator 自己编造审查证据。
