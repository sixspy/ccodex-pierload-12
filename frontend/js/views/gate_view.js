export const gateViewTemplate = `
<section class="panel">
  <h2>闸口放行</h2>
  <p class="hint">岸桥禁放第12号：须票态已裁定、无开放超重、且岸桥计划有匹配泊位行；缺泊位行则由放行写口原子拒收，正式册零增。</p>
  <div class="form-row">
    <div><label>过磅票（仅泊位计划齐套）</label>
      <select v-model.number="gateForm.ticket_id">
        <option v-for="t in releasableTickets" :key="t.id" :value="t.id">{{ t.ticket_code }} · {{ t.crane_berth_slot }}</option>
      </select>
    </div>
    <div><label>值班员</label><input v-model="gateForm.officer"/></div>
  </div>
  <div class="actions">
    <button @click="releaseGate">确认放行</button>
    <button class="secondary" @click="refresh">刷新</button>
  </div>
  <p v-if="!releasableTickets.length" class="hint">无可抬杆票：岸桥计划泊位行未齐套的票一律禁放。</p>
  <p v-if="blockedReleases.length" class="hint">
    禁放/待补 {{ blockedReleases.length }} 票：
    <span v-for="b in blockedReleases" :key="b.id" class="badge fail" style="margin-right:6px">{{ b.ticket_code }} · {{ b.release_state }}</span>
  </p>
  <table class="data-table">
    <thead><tr><th>放行号</th><th>票号</th><th>车道</th><th>泊位</th><th>值班员</th><th>册别</th><th>时间</th></tr></thead>
    <tbody>
      <tr v-for="g in gateReleases" :key="g.id">
        <td>{{ g.release_ref }}</td>
        <td>{{ g.ticket_code }}</td>
        <td>{{ g.lane_code }}</td>
        <td>{{ g.crane_berth_slot || '—' }}</td>
        <td>{{ g.officer }}</td>
        <td>
          <span class="badge" :class="g.release_register === '正式' ? 'pass' : 'fail'">
            {{ g.release_register }} · {{ g.release_state }}
          </span>
        </td>
        <td>{{ g.released_at }}</td>
      </tr>
    </tbody>
  </table>
</section>
`;
