import { api } from "../api/workbench.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { status } from "../components/common/status.js";
import { table } from "../components/common/table.js";
import { poll } from "../hooks/poll.js";
import { el } from "../utils/dom.js";
import { time } from "../utils/format.js";

function retryControl(run, onRetry) {
  const issue = el("p", {role: "alert"});
  const button = el("button", {
    type: "button",
    class: "quiet",
    "data-testid": "retry-run",
    onclick: async () => {
      button.disabled = true;
      button.textContent = "正在重新入队…";
      issue.textContent = "";
      try {
        await api.retryRun(run.id);
        await onRetry?.();
      } catch (error) {
        issue.textContent = error.message;
        button.disabled = false;
        button.textContent = "失败重试（沿用同一批次）";
      }
    },
  }, "失败重试（沿用同一批次）");
  return el("div", {class: "retry-control"}, button, issue);
}

function reportState(run, user, onRetry) {
  const canRetry = user?.role === "operator" && run.status === "failed";
  return el("div", {class: "stack", id: "run-state", "data-run-state": run.status}, status(run.status),
    el("p", {}, run.status === "queued" ? "后台正在处理，页面会自动更新。" : run.failure || run.result?.summary),
    canRetry ? retryControl(run, onRetry) : null,
    run.status === "done"
      ? el("div", {class: "button-row"},
          el("a", {class: "button", href: `#evidence/${run.id}`}, "查看业务证据"),
          el("a", {class: "button quiet", href: `#evidence/${run.id}`, "data-testid": "continue-next"}, "续演下一场"))
      : null);
}

export async function runsPage(config, user, route, signal) {
  const items = await api.runs();
  const latest = route.id ? await api.run(route.id, signal) : items[0];
  let detail;
  if (!latest) {
    detail = empty("进入资料页，选用一个业务样本并提交执行。");
  } else {
    detail = reportState(latest, user, async () => {
      const next = await refresh();
      if (next) poll(refresh, signal);
    });
  }

  async function refresh() {
    if (!latest) return false;
    try {
      const next = await api.run(latest.id, signal);
      if (!signal.aborted) {
        detail.replaceChildren(...reportState(next, user, async () => {
          const queued = await refresh();
          if (queued) poll(refresh, signal);
        }).childNodes);
        const badge = document.querySelector(`[data-run="${next.id}"] .status`);
        if (badge) badge.replaceWith(status(next.status));
      }
      return next.status === "queued";
    } catch (error) {
      if (!signal.aborted) detail.append(el("p", {role: "alert"}, error.message));
      return false;
    }
  }
  if (latest?.status === "queued") poll(refresh, signal);
  return el("div", {class: "page"},
    pageHeading(config.modules[2], config.parameter_label),
    latest ? section(latest.case_title, detail) : detail,
    section("执行批次", items.length ? table(["资料", "编号", "参数", "状态", "提交时间"],
      items.map(run => [el("a", {"data-run": run.id, href: `#runs/${run.id}`}, run.case_title), run.id,
        run.parameter, el("span", {"data-run": run.id}, status(run.status)), time(run.created_at)]), "执行批次") :
      empty("暂无执行记录。")));
}
