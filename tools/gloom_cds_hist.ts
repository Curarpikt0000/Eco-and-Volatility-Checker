// 只读取数: 经 gloomberb 自带 api-client 的 getCloudCdsHistory(与其 CDS 图同一接口)。不登录, 不写除 stdout 外任何东西。
// 由 tools/gloom_cds_fetch.py 调用; 需 bun(隔离前缀 ~/.local/gloom-env) 且 HOME 指向隔离目录。
import { apiClient } from "/home/user/.local/gloom-env/node_modules/gloomberb/src/api-client";
const issuers: Record<string, string> = { Oracle: "Oracle Corporation", CoreWeave: "CoreWeave, Inc.", SoftBank: "SoftBank Group Corp." };
const out: any = {};
for (const [k, name] of Object.entries(issuers)) {
  try {
    const r: any = await apiClient.getCloudCdsHistory({ issuer: name, days: 730 });
    out[k] = { issuer: r.issuer, points: (r.points ?? []).map((p: any) => [p.date, p.spreadBp, p.prints, p.maturity]) };
  } catch (e: any) { out[k] = { error: String(e?.message ?? e).slice(0, 160), points: [] }; }
  await new Promise((res) => setTimeout(res, 1500));
}
console.log(JSON.stringify(out));
