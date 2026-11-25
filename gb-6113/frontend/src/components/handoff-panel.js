import { api } from "../api/workbench.js";
import { errorText, field } from "./common/fields.js";
import { empty, section } from "./common/panel.js";
import { table } from "./common/table.js";
import { submit } from "../hooks/submit.js";
import { navigate } from "../router/router.js";
import { el } from "../utils/dom.js";

function lossRows(losses) {
  return (losses || []).map(item => [
    el("span", {"data-testid": "handoff-loss-code"}, item.code || item["写入号"]),
    el("span", {"data-testid": "handoff-loss-scenario"},
      item["丢失场次标签"] || (item.lost_in_run_id ? `第 ${item.lost_in_run_id} 场` : "未知场次")),
    item.replica || item["副本"] || "—",
    item.ack_at_ms ?? item["答复 ms"] ?? "—",
  ]);
}

export function lossTable(losses) {
  if (!losses?.length) return empty("交班清单上暂无未结的已答复丢失凭条。");
  return el("div", {"data-testid": "handoff-list"},
    table(["凭条号", "丢失场次", "丢失副本", "原答复 ms"], lossRows(losses), "交班清单：已答复但丢失的凭条"));
}

function inheritedLine(codes) {
  if (!codes?.length) return empty("选定副本在故障时没有已落盘凭条，下一场从空继承队列开始。");
  return el("div", {class: "chip-list", "data-testid": "inherited-list"},
    codes.map(code => el("span", {class: "chip"}, code)));
}

function continuationLedger(run) {
  const continuation = run.result?.continuation;
  if (!continuation) return null;
  return el("div", {class: "handoff-ledger", "data-testid": "incoming-handoff"},
    el("h3", {}, "本场继承与交班清单"),
    el("p", {}, `来源正式交班：第 ${continuation.source_run_id ?? "—"} 场；先按原顺序补齐以下凭条，再复制新写入。`),
    el("h4", {}, "继承凭条（原顺序）"),
    inheritedLine(continuation.inherited_codes),
    el("h4", {}, "交班清单：前序已答复但丢失"),
    el("p", {class: "hint"}, "这些记录标明丢在哪一场；即使同号重写，旧记录也不会消失。"),
    lossTable(continuation.losses));
}

function continueForm(run, sourceCase, replicas, onFormalCreated) {
  const payload = sourceCase?.payload || {};
  const names = replicas?.length ? replicas : (payload.standbys || []).map(item => item.name);
  const selected = payload.promotion && names.includes(payload.promotion) ? payload.promotion : names[0];
  const replicaField = names.length
    ? field("选定交班副本", el("select", {name: "replica", "data-testid": "continue-replica"},
        names.map(name => el("option", {value: name, selected: name === selected}, name))))
    : null;
  const parameter = field("可降级写入的等待时限（毫秒）", el("input", {
    name: "parameter", type: "number", min: 1, max: 500, required: true, value: 25,
    "data-testid": "continue-parameter",
  }));
  const jsonField = field("下一场维护剧本 JSON", el("textarea", {
    name: "payload", spellcheck: "false", required: true, rows: 16,
    "data-testid": "continue-payload",
  }, JSON.stringify(payload, null, 2)), "继承凭条由正式交班自动前置；同号重写不会抹掉交班清单中的旧丢失记录。");

  const feedback = errorText();
  const formalButton = el("button", {
    type: "button", class: "quiet", "data-testid": "create-handoff",
    onclick: async event => {
      const button = event.currentTarget;
      button.disabled = true;
      feedback.textContent = "";
      try {
        await api.createRunHandoff(run.id, {replica: form.elements.replica?.value || selected});
        await onFormalCreated?.();
      } catch (error) {
        feedback.textContent = error.message;
        button.disabled = false;
      }
    },
  }, "仅生成正式交班");

  const form = el("form", {
    id: "handoff-form", class: "continue-form", "data-testid": "continue-form",
    "data-continuation-form": "true",
  }, replicaField, parameter, jsonField, feedback,
    el("div", {class: "button-row"},
      formalButton,
      el("button", {type: "submit", "data-testid": "continue-submit"}, "提交续演")));

  submit(form, async values => {
    let nextPayload;
    try {
      nextPayload = JSON.parse(values.get("payload"));
    } catch {
      throw new Error("续演剧本 JSON 无法解析，请检查括号、引号和逗号");
    }
    const created = await api.continueRun(run.id, {
      parameter: Number(values.get("parameter")),
      replica: values.get("replica") || undefined,
      payload: nextPayload,
    });
    navigate(`runs/${created.id}`);
  });
  return form;
}

function officialPanel(handoff, continuationRun) {
  const manifest = handoff.manifest || {};
  return el("div", {class: "official-handoff", "data-testid": "official-handoff"},
    el("p", {}, el("strong", {}, "已有一份正式交班。"), `交班副本：${handoff.replica}；提交人：${handoff.actor}`),
    el("h4", {}, "继承凭条（原顺序）"),
    inheritedLine(manifest.inherited_codes || manifest.receipts),
    el("h4", {}, "交班清单：已答复但丢失，同号重写也保留"),
    el("p", {class: "hint"}, "每条旧记录都标明丢在哪一场，不按凭条号去重。"),
    lossTable(manifest.losses),
    handoff.continuation_run_id
      ? el("p", {}, "正式续演批次：",
          el("a", {href: `#runs/${handoff.continuation_run_id}`}, `#${handoff.continuation_run_id}`),
          continuationRun ? `（${continuationRun.status}）` : "",
          continuationRun?.status === "failed"
            ? el("button", {
                type: "button", class: "quiet", "data-testid": "official-retry",
                onclick: async event => {
                  event.currentTarget.disabled = true;
                  await api.retryRun(handoff.continuation_run_id);
                  navigate(`runs/${handoff.continuation_run_id}`);
                },
              }, "失败重试（不新增批次）")
            : null)
      : empty("正式交班已生成，尚未提交续演批次。"));
}

export async function handoffSection(run, user) {
  const root = el("div", {"data-testid": "formal-handoff", "data-handoff": "official"});

  async function render() {
    let sourceCase = null;
    try {
      sourceCase = await api.case(run.case_id);
    } catch {
      // The run remains usable if case lookup is forbidden/unavailable.
    }

    let handoff = null;
    try {
      handoff = await api.runHandoff(run.id);
    } catch (error) {
      if (error.status !== 404) throw error;
    }

    let continuationRun = null;
    if (handoff?.continuation_run_id) {
      try {
        continuationRun = await api.run(handoff.continuation_run_id);
      } catch {
        continuationRun = null;
      }
    }

    const canOperate = user?.role === "operator";
    const ledger = continuationLedger(run);
    const official = handoff ? officialPanel(handoff, continuationRun) : null;
    const canContinue = canOperate && (!handoff || !handoff.continuation_run_id);
    const form = canContinue
      ? continueForm(run, sourceCase, null, async () => { await render(); })
      : null;
    const readOnly = !canOperate && !handoff
      ? empty("操作员可从这个已完成故障批次提交续演并生成正式交班。")
      : null;

    root.replaceChildren(section("正式交班与续演",
      el("div", {id: "handoff", "data-testid": "handoff-section"}, ledger, official, form, readOnly)));
  }

  await render();
  return root;
}
