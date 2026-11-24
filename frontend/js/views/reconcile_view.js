export const reconcileViewTemplate = `
<section class="grid-2">
  <section class="panel">
    <h2>提单对账</h2>
    <p class="hint">汇总过磅毛重与提单申报吨比对；放行口径取岸桥计划晋升结果，偏航行不得计为已放行。</p>
    <div class="form-row">
      <div><label>提单号</label><input v-model="reconCode"/></div>
    </div>
    <div class="actions">
      <button @click="loadReconcile">对账</button>
      <button class="secondary" @click="loadAllReconcile">全量</button>
    </div>
    <div v-if="reconOne" class="detail-box">
      <p>申报 {{ reconOne.declared_gross_t }}t · 过磅合计 {{ reconOne.ticket_sum_t }}t</p>
      <p :class="reconOne.balanced ? 'ok' : 'bad'">{{ reconOne.balanced ? '账实平衡' : '偏差待查' }}</p>
      <p>快照数 {{ reconOne.seal_count }} · 有据放行 {{ reconOne.released_count ?? 0 }} · 偏航 {{ reconOne.unpromoted_count ?? 0 }}</p>
      <p>可出证明 {{ reconOne.proof_ready ? '是' : '否' }}</p>
      <table class="data-table compact" style="margin-top:8px">
        <thead><tr><th>票号</th><th>岸桥泊位</th><th>放行口径</th></tr></thead>
        <tbody>
          <tr v-for="t in reconOne.tickets" :key="t.ticket_code">
            <td>{{ t.ticket_code }}</td>
            <td>{{ t.crane_plan_ready ? (t.crane_berth_slot || '有') : '无计划' }}</td>
            <td>
              <span class="badge" :class="t.released ? 'pass' : (t.release_ref ? 'fail' : 'muted')">
                {{ t.release_state || (t.crane_plan_ready ? '待放行' : '禁放') }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <ul v-if="reconAllItems.length">
      <li v-for="r in reconAllItems" :key="r.bl_code">{{ r.bl_code }} · {{ r.balanced ? '平' : '偏' }}<span v-if="r.unpromoted_count" class="recon-warn"> · 偏航 {{ r.unpromoted_count }}</span></li>
    </ul>
  </section>
  <section class="panel">
    <h2>单票证明</h2>
    <div class="form-row"><div><label>票号</label><input v-model="proofCode"/></div></div>
    <div class="actions"><button @click="loadProof">拉证明</button></div>
    <div v-if="proofOne" class="detail-box">
      <p>提单匹配 {{ proofOne.manifest_matches_bl ? '是' : '否' }}</p>
      <p>超重闭环 {{ proofOne.overload_closed ? '是' : '否' }}</p>
      <p>岸桥计划 {{ proofOne.crane_plan_ready ? ('齐套 · ' + (proofOne.crane_berth_slot || '')) : '无泊位行' }}</p>
      <p :class="proofOne.release_register === '偏航' ? 'recon-warn' : ''">
        已放行 {{ proofOne.released ? '是' : '否' }} · {{ proofOne.release_state }}
        <span v-if="proofOne.release_ref">（{{ proofOne.release_ref }}）</span>
      </p>
      <p>一致 {{ proofOne.coherent ? '是' : '否' }}</p>
    </div>
  </section>
</section>
`;
