# LJHskill 两句话工具箱

LJHskill（李解瀚森 skill），俗称「两句话」：第一句说清你卡在哪，第二句它带你跑对的工具。

内容电商打品工具箱。从《内容电商从 0 到 1 打品》约 20 万字方法论中，把可执行的部分（诊断表、判断标准、SOP、填空模板）提炼成 13 个 Agent skill，覆盖选品、定位、卖点、场景、内容、验证、投放、算账全链路。

课程正文不在本仓库。这里只有拿来就能跑的工具。

## 安装

### Claude Code

```bash
claude plugin marketplace add handsomeng/LJHskill
claude plugin install ljh@ljhskill
```

装 `ljh@ljhskill` 即获得全部 13 个 skill。只想单独装某一个工具时，才用类似 `claude plugin install ljh-xuanpin@ljhskill` 的命令。

### 通用安装（Codex / Claude Code）

```bash
npx -y skills add handsomeng/LJHskill -g --all
```

## 工具箱

按打品链路排序。不知道从哪开始，直接输入 `/ljh`。

| Skill | 做什么 |
|---|---|
| `/ljh` | 主入口。任务前根据你的问题路由到对的工具，任务后读结论推荐下一步 |
| `/ljh-xuanpin` | 选品五步判断。这个品值不值得下场打 |
| `/ljh-dingwei` | 新品定位一页纸。价值四象限 + 心智句，全队照一张纸打，不许各编各的 |
| `/ljh-maidian` | 卖点体检。盖住成分自检 + 双重校验，判断卖点是独一份还是公共卖点 |
| `/ljh-changjing` | 场景机会地图。扒竞品素材拆成能算账的表，四象限定性 |
| `/ljh-duiqi` | 品·人群·内容对齐表。卖点翻译四列表，新品认知钉在同一点 |
| `/ljh-jiaoben` | 带货脚本评审。七步说服链逐段核对，指出缺哪步、哪句没配画面 |
| `/ljh-yinzi` | 内容因子拆解。爆款拆到因子级，专攻课题按 EV 排序 |
| `/ljh-koc` | KOC 验证。低成本卖点验证方案设计 + 验证报告 |
| `/ljh-qianchuan` | 千川掉量诊断。决策树 + 秒查表，两分钟定位第一动作 |
| `/ljh-suanzhang` | 单元经济算账。月度总账 + 盈亏平衡 ROI + LTV 实算 |
| `/ljh-daren` | 达人选号。六维决策表 + 假数据识别，花钱前别被假热闹坑 |
| `/ljh-liangye` | 见主播的两页材料。第一页给对方记住，第二页给对方开口 |

## 典型主线

```text
xuanpin（这个品值不值得打）
    ↓
dingwei / maidian（定位和卖点立不立得住）
    ↓
changjing（往哪个场景发力）
    ↓
koc（小成本验证卖点）
    ↓
duiqi → jiaoben → yinzi（内容怎么做、怎么放大）
    ↓
daren / liangye / qianchuan（投放怎么花钱）
    ↓
suanzhang（这盘账到底赚不赚）
```

## 许可证

本项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 许可证。

- 个人使用、学习、研究、非商业项目：随便用，不需要申请
- 公开发布衍生作品：请注明来源
- 商业用途：需要单独授权，请联系作者
