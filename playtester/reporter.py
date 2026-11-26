import csv
from io import StringIO

from .security import atomic, dump, now

SESSIONS = "run_id phase persona account start_time end_time active_seconds steps start_revision end_revision pause_reason end_status".split()
COSTS = ("step timestamp model reasoning_effort status uncached_input_tokens cache_write_tokens cache_read_tokens "
         "output_tokens reasoning_tokens cache_hit_rate est_max_usd actual_usd cumulative_usd cache_write_source").split()


class Reporter:
    def __init__(self, folder, state, persona, privacy):
        self.folder, self.state, self.persona, self.privacy = folder, state, persona, privacy
        for sub in ("screenshots/raw", "screenshots/assist", "logs"):
            (folder / sub).mkdir(parents=True, exist_ok=True)

    def log(self, message):
        with (self.folder / "logs/run.log").open("a", encoding="utf-8") as out:
            print(now(), self.privacy.clean(message), file=out)

    def write(self, name, content):
        atomic(self.folder / name, self.privacy.clean(content))

    def csv(self, name, fields, rows):
        out = StringIO(newline="")
        writer = csv.DictWriter(out, fields)
        writer.writeheader()
        writer.writerows(rows)
        self.write(name, out.getvalue())

    def finish(self):
        s = self.state
        self.csv("实玩时段与角色记录.csv", SESSIONS, s.sessions)
        self.csv("usage_and_cost.csv", COSTS, s.usage)
        self.write("action_trace.jsonl", "".join(dump(r.model_dump()) + "\n" for r in s.steps))
        title = "离线模拟" if s.offline else "正式云端试玩"
        summary = [f"# {self.persona.name} · {title}", f"状态 {s.status}　{s.detail}",
                   self.persona.profile, f"实载版本 {dump(s.version_fingerprint) if s.version_fingerprint else '尚未核实'}",
                   f"自主决策 {s.step_index} 步，实际用时 {s.active_play_seconds:.1f} 秒。"]
        clicks = [r for r in s.steps if r.executed in {"click", "double_click", "drag", "swipe", "type_text", "scroll"}
                  and r.decision.action.target_description.strip()]
        hits = sum(r.detector_status in {"major_transition", "modal_or_panel_change", "subtle_feedback"} for r in clicks)
        summary.append(f"明确目标操作获得可见或业务反馈 {hits}/{len(clicks)}"
                       + (f"（{hits/len(clicks):.1%}）。" if clicks else "（尚无样本）。"))
        summary.append("该指标统计操作反馈。动画未稳定计入分母，目标是否符合玩家预期可从下一步观察复核。")
        reads = sum(row["cache_read_tokens"] or 0 for row in s.usage)
        inputs = sum(sum(row[key] or 0 for key in ("uncached_input_tokens","cache_write_tokens","cache_read_tokens"))
                     for row in s.usage)
        summary.append(f"已核算费用 ${s.spent_usd}，待核实费用预留 ${s.reserved_usd}。缓存读取 {reads}/{inputs} Token"
                       + (f"（{reads/inputs:.1%}）。" if inputs else "（无用量）。"))
        diary = [f"# {self.persona.name}的玩家体验日记 · {title}"]
        issues = ["# 问题与证据"]
        for phase, label in (("initial_play", "首次自然游玩"), ("return_after_quit", "退出后回流复验")):
            records = [r for r in s.steps if r.phase == phase]
            summary.append(f"## {label}\n\n{len(records)} 步，{sum(r.elapsed_seconds for r in records):.1f} 秒。")
            if phase == "return_after_quit" and records:
                first = records[0]
                summary.append(f"回城第一念头：{first.decision.goal_update}。[画面]({first.before})")
            diary.append(f"## {label}")
            for r in records:
                d = r.decision
                diary.append(f"### 第 {r.step} 步 · {d.emotion.mood} · 耐心 {r.patience}/10\n\n"
                             f"{d.observation}　{d.action.reason}　我原以为{d.expectation_before_action}。"
                             f"　{d.experience_reflection.notable_good}　{d.experience_reflection.friction_or_issue}"
                             f"　{d.emotion.quit_reason}　我想{d.goal_update}。\n\n"
                             f"操作 {r.executed}，可见反馈 {r.detector_status}。[操作前]({r.before}) · [操作后]({r.after})")
        first_urge = next((r for r in s.steps if r.decision.emotion.quit_reason or r.executed == "natural_quit"), None)
        if first_urge:
            summary.append(f"首次明确表达退出意愿在第 {first_urge.step} 步。"
                           f"{first_urge.decision.emotion.quit_reason or first_urge.decision.action.reason}。[画面]({first_urge.before})")
        for event in s.natural_quit_events:
            summary.append(f"第 {event['step']} 步自然退出，累计 {event['seconds']:.1f} 秒。{event['reason']}。[画面]({event['screen']})")
        summary.append("## 体验亮点")
        good = [r for r in s.steps if r.decision.experience_reflection.notable_good]
        summary.extend([f"- {r.decision.experience_reflection.notable_good}。[第 {r.step} 步]({r.before})" for r in good[:5]]
                       or ["尚无玩家明确记录的亮点。"])
        summary.append("## 优先整改")
        ordered = sorted(s.discovered_issues, key=lambda i: i.severity)
        summary.extend([f"- {i.severity} · {i.observed}。{i.suggestion}。[证据]({i.before})" for i in ordered[:5]]
                       or ["尚无已记录问题。"])
        summary.append("## 角色关注维度")
        for dim in self.persona.dimensions:
            matching = [r for r in s.steps if r.decision.experience_reflection.issue_category == dim]
            summary.append(f"- {dim}：" + ("、".join(f"[第 {r.step} 步]({r.before})" for r in matching)
                                           or "尚无明确归入此维度的观察。"))
        for i in s.discovered_issues:
            issues.append(f"## {i.number:03} · {i.severity} · {i.category}\n\n复现：沿操作轨迹至第 {i.step} 步，"
                          f"{i.target}。预期：{i.expected}。实际：{i.observed}。影响：{i.impact}。建议：{i.suggestion}。"
                          f"　[操作前]({i.before}) · [操作后]({i.after})")
        if s.fault_screenshot:
            issues.append(f"故障现场 [{s.status}]({s.fault_screenshot})。{s.detail}")
        elif s.detail:
            issues.append(f"运行状态 {s.status}。{s.detail}。[运行日志](logs/run.log)")
        if s.status in {"SAVE_CONFLICT", "SAVE_TAMPERED", "SAVE_ROLLBACK", "API_HTTP_ERROR", "RUNTIME_ERROR",
                        "CONSOLE_ERROR", "NETWORK_ERROR", "ACCOUNT_CHANGED"}:
            issues.append(f"## {len(s.discovered_issues)+1:03} · P0 · 异常\n\n"
                          f"复现：载入该角色检查点，沿已有轨迹至第 {s.step_index} 步。"
                          f"预期：账号、存档连续，页面正常响应。实际：{s.detail}。影响：试玩已暂停。"
                          f"建议：核对同一时刻的服务端日志和最后确认的 revision {s.last_confirmed_server_revision}。"
                          "　[操作轨迹](action_trace.jsonl) · [运行日志](logs/run.log)")
        for name, parts in (("试玩结论.md", summary), ("玩家体验日记.md", diary), ("问题与证据.md", issues)):
            self.write(name, "\n\n".join(parts) + "\n")
        self.write("screenshots/assist/说明.md", "带 raw、point 的文件记录升级前证据。grid 文件为实际发送的网格副本。\n")
        if not any((self.folder / "screenshots/raw").glob("*.png")):
            self.write("screenshots/raw/说明.md", "本次运行尚未取得通过安全检查的游戏画面。\n")
