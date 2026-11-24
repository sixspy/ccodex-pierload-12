export const stubsViewTemplate = `
<section class="grid-2">
  <section class="panel">
    <h2>海关申报空桩</h2>
    <p class="hint">接口已挂载，回执未对接。</p>
    <div class="form-row">
      <div><label>提单</label><input v-model="customsForm.bl_code"/></div>
      <div><label>行数</label><input v-model.number="customsForm.row_count" type="number"/></div>
    </div>
    <div class="actions"><button @click="enqueueCustoms">入队</button></div>
    <table class="data-table compact">
      <tr v-for="j in customsJobs" :key="j.id"><td>{{ j.bl_code }}</td><td>{{ j.status }}</td></tr>
    </table>
  </section>
  <section class="panel">
    <h2>岸桥计划空桩</h2>
    <p class="hint">挂票即生成泊位行；本页须与放行页、对账页同源——岸桥页空而别处已放行即为偏航。</p>
    <div class="form-row">
      <div><label>泊位</label><input v-model="craneForm.berth_slot"/></div>
      <div><label>票ID(可空)</label><input v-model.number="craneForm.ticket_id" type="number"/></div>
    </div>
    <div class="actions"><button @click="enqueueCrane">入队</button></div>
    <p v-if="craneUnplanned.length" class="hint recon-warn">
      偏航 {{ craneUnplanned.length }} 条：无岸桥计划却已出正式放行（岸桥禁放第12号）。
    </p>
    <table class="data-table compact">
      <thead><tr><th>泊位</th><th>票号</th><th>状态</th></tr></thead>
      <tbody>
        <tr v-for="j in craneJobs" :key="j.id">
          <td>{{ j.berth_slot }}</td>
          <td>{{ j.ticket_code || '—' }}</td>
          <td><span class="badge" :class="j.crane_plan_ready ? 'pass' : 'muted'">{{ j.status }}</span></td>
        </tr>
      </tbody>
    </table>
    <table v-if="craneUnplanned.length" class="data-table compact" style="margin-top:10px">
      <thead><tr><th>偏航放行号</th><th>票号</th><th>车道</th><th>原因</th></tr></thead>
      <tbody>
        <tr v-for="o in craneUnplanned" :key="o.id">
          <td>{{ o.release_ref }}</td>
          <td>{{ o.ticket_code }}</td>
          <td>{{ o.lane_code }}</td>
          <td class="recon-warn">{{ o.reason }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</section>
`;
