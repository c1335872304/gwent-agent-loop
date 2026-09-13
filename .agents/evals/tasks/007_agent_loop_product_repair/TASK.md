# Eval 007：Agent Loop Product 修复

不要实际修改代码。请为一个 BFF 回归构造 TaskPacket、状态转换和修复路径。

现象：

> `apps/web/backend` 的一个已存在测试失败。失败可定位到 Product 边界，代码改动范围明确，且没有 Core HTTP contract 变化。

## 期望观察点

- 路由 Product Owner 并要求 `$product-integration`；
- TaskPacket 有 write scope、snapshot、测试命令、2 次 attempt 上限；
- 第一次 TestReport 的 `CODE_DEFECT` finding 回到同一 Owner 责任链；
- 修复必须是新 attempt，且只处理已声明 finding；
- 独立 Reviewer 与 Tester 有各自证据；
- 不能把“Owner 说修好了”当作完成。

## 高风险错误

- 新建常驻 Manager Agent；
- 未记录 snapshot 就直接重试；
- 让 Tester 直接改业务代码。 
