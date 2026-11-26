# AI Game Playtester

用真实浏览器画面驱动网页游戏试玩。玩家有可配置的目标、耐心和退出意愿。每次决策保留预期、情绪、操作、前后截图与费用。仓库自带原创 Canvas 游戏 **Lantern Coast**，可以在没有模型密钥时验证整条浏览器链路。

[云端验收记录与并发测量](云端验收记录.md)

## 快速开始

Python 3.12+。在仓库根目录运行：

```sh
python -m pip install -e '.[test]'
python -m pytest -q
python -m playtester.cli dry-run --run-id first --pause-at 10
python -m playtester.cli resume --resume artifacts/first/memory_checkpoint.json
python -m playtester.acceptance artifacts/first --mode offline
```

dry-run 使用合成截图和模拟 Responses，验证 50 步、费用账本、网格证据、自然退出、二次进入和完整报告。本地只需做离线测试。**Actions → Browser integration** 在标准 ubuntu-latest 上启动真实 Chromium 和回环演示服务器，识别屏幕上的信号灯、操作游戏、关闭浏览器、读取检查点，重新登录后验证服务器 revision。演示识别器只读像素，产生的延时和费用与真实模型分列。

## 并发与费用

调度 Browser integration 时选择 single、local-2、local-5、matrix-2 或 matrix-5。local 在同一个 Runner 启动独立进程与 Chromium，matrix 将玩家分到独立 Runner。下载 numeric-demo-metrics 可查看进程起止、步数、浏览器重开次数、实际重叠时间和操作 P50/P95。各测试运行 4 步，无模型费用。

自有游戏的同机多账号运行使用 `python -m playtester.parallel examples/parallel.yaml --budget 1 --output artifacts/batch`。每人独立账号、进程和账本，均分整批预算。跨机器时使用相同的账户分配原则，为每个 Matrix job 注入独立账号，并预分总预算。单角色使用 `python -m playtester.cli run --game custom --persona explorer --steps 50`。正式模型试玩入口限 GitHub Actions Linux；标准托管机适合仓库开发验证。独立私有 Linux self-hosted Runner 也可接入私有仓库中的同一工作流。

## 多模态模型

config/models.yaml 保存模型 ID、提供商、上下文上限和百万 Token 美元价格。OpenAI 使用 Responses 严格结构化输出和官方输入计数。GLM 使用国际站视觉 Chat Completions 和 JSON 输出，以配置的完整上下文窗口作为最大输入预留。Gemini 使用原生 generateContent、图片 inlineData、countTokens 与 thinkingBudget。三条路线都由 Pydantic 校验；缺少价格会在请求前停止。GLM 的 low 关闭思考，medium、高档开启。Gemini 的输出费用包含 thoughtsTokenCount。显式付费缓存存储未启用。调整价格前请核对账号所用地区和服务档位。[Z.AI 单价](https://docs.z.ai/guides/overview/pricing) · [Gemini 单价](https://ai.google.dev/gemini-api/docs/pricing) · [OpenAI 单价](https://openai.com/api/pricing/)

设置 PLAYTEST_MODEL、PLAYTEST_REASONING_EFFORT、PLAYTEST_MAX_OUTPUT_TOKENS、PLAYTEST_MAX_BUDGET_USD，或使用同名 CLI 参数（如 --max-budget-usd）。每次调用前先原子预留最高费用，响应后按实际用量结算。缓存写细分缺失时记录 0 及来源。超时后的未知费用留在预留余额，后续尝试使用剩余额度。每步最多三次尝试。实际收费以供应商账单为准。

**付费演示**在 model-validation 环境中配置所选供应商的 OPENAI_API_KEY、GLM_API_KEY 或 GEMINI_API_KEY，限制部署分支为 main，再由个人仓库所有者手动调度 Maintainer model validation。该工作流只允许从 main 运行内置游戏，最多两步、0.05 美元。组织仓库需由管理员将所有者检查替换为经审核的维护者身份白名单。普通 PR、fork、评论、定时任务不会触发付费验证。

## 私有多账号执行与加密归档

在独立私有部署仓库保留 Private deployment validation 工作流，配置 private-validation 环境并限制 main 分支。个人仓库由所有者触发。在该仓库中安装受信任的游戏适配器、角色卡和价格表。环境 Secret PLAYTEST_SEATS_JSON 为账号数组，每项提供 game、persona、username、password、url。每个角色卡的测试身份须与分配的账号一致。ARCHIVE_CERT_PEM 为接收方公钥证书的 PEM 内容，解密私钥留在接收端。

选择 local 或 matrix 和 1、2、5 个席位。所有机器按总席位数预分同一批美元预算。每次调度只运行一批，多个私有调度串行。每个分片先在临时私有目录生成证据，再用 OpenSSL CMS 和 AES-256-GCM 加密归档。工作流只上传 evidence.cms。解密示例：

```sh
openssl cms -decrypt -binary -inform DER -in evidence.cms -recip recipient.pem -inkey recipient-key.pem -out evidence.tar.gz
```

私有工作流可以选择自己的独占临时 Linux self-hosted Runner，公开演示固定使用 ubuntu-latest。真实模型验证请在供应商允许的地区、配额与数据处理条件下运行。

## 接入自己的游戏

1. 在私有运行项目建立 games/custom，参考 games/demo 的 game.yaml、adapter.py 与 personas/explorer.yaml。适配器从正常登录界面建立会话，通过只读版本指纹和 revision 检查连续性，按路径和方法限定允许产生副作用的动作，给截图标出需遮盖的身份信息区域。角色卡只供模型读取公开画像字段。
2. 用受信任的私有 checkout 或加密配置包提供适配器。令 PLAYTEST_GAMES_DIR 指向私有 games 目录、PYTHONPATH 指向可导入适配器的包，必要时用 PLAYTEST_MODELS_FILE 指向私有价格表。通过 PLAYTEST_GAME_URL、PLAYTEST_USERNAME、PLAYTEST_PASSWORD 注入目标和测试凭据。仅可信 HTTPS 域名可访问，随仓库演示仅在回环地址提供 HTTP。
3. 使用独立测试号。游戏可见内容属于不可信输入。模型仅接收实际截图、角色记忆和反馈；游戏状态和凭据留在适配器。疑似点空两次或明确请求辅助才生成 10×20 网格，先保存原图、落点与困惑理由。
4. 检查点在每步原子替换。恢复请保留整个运行目录并使用 --resume。发生云档回退、冲突、未知动作结果或篡改错误时暂停写入。自然退出节点保留原始心理记录和截图。
5. 打开《试玩结论》《问题与证据》《玩家体验日记》，沿相对链接回看截图。CSV 与 JSONL 支持复核缓存费用、操作耗时、反馈分类、阶段和存档衔接。准确率统计需要同时检查玩家的下一步观察，以排除无关动画。

## 运行数据与 Actions 使用范围

公开工作流只验证本仓库的实现及原创演示游戏。付费步骤关闭应用日志输出，临时目录随 Runner 销毁。上传白名单仅包含数值型演示测量和固定状态，不上传截图、配置、提示词、角色记忆、原始账本或私有游戏日志。两个工作流均关闭依赖缓存。个人或公司的私人试玩应把完整产物送到独立私有存储，或先用接收方公钥加密，再上传密文。请将第三方游戏代码和资产留在其原项目。

GitHub-hosted Actions 任务必须与关联仓库软件的生产、测试、部署或发布相关，且资源负担须相称。仓库公开本身不授予持续运行私人业务的资格。做长期或大规模私人测试前应向 GitHub 确认具体用法，或改在自己管理的私有运行器执行。[GitHub Actions 附加条款](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#actions)

框架和内置演示采用 [MIT 许可证](LICENSE)。
