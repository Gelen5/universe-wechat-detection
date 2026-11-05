(async()=>{
  const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let page=1,total=0;
  async function loadOrders(){
    const r=await fetch('/api/agent/orders?page='+page,{cache:'no-store'});if(!r.ok)throw Error('无法加载充值记录');const d=await r.json();total=d.total;
    $('#summary').textContent=`付费客户 ${d.paid_customers} 人 · 订单金额 ¥${d.order_total} · 累计退款 ¥${d.refunded_total}`;
    $('#orders').innerHTML=d.orders.length?'<table><thead><tr><th>客户</th><th>订单号</th><th>订单金额</th><th>累计退款</th><th>状态</th><th>支付时间</th></tr></thead><tbody>'+d.orders.map(o=>`<tr><td>${esc(o.email)}</td><td>${esc(o.out_trade_no)}</td><td>¥${esc(o.total_amount)}</td><td>¥${esc(o.refunded_amount)}</td><td>${esc(o.status)}</td><td>${esc(o.paid_at||'未知')}</td></tr>`).join('')+'</tbody></table>':'暂无已入账充值';
    $('#page').textContent=`第 ${page} 页，共 ${total} 笔`;$('#prev').disabled=page<=1;$('#next').disabled=page*50>=total;
  }
  try{
    const r=await fetch('/api/agent/me',{cache:'no-store'});if(!r.ok)throw Error('无法加载代理信息');const d=await r.json();
    $('#link').value=location.origin+'/?agent='+encodeURIComponent(d.code);if(!d.active)$('#status').textContent='推广已停用，链接不能绑定新客户。';
    $('#copy').onclick=async()=>{try{await navigator.clipboard.writeText($('#link').value);$('#status').textContent='链接已复制'}catch{$('#link').select();$('#status').textContent='请手动复制链接'}};
    $('#prev').onclick=()=>{if(page>1){page--;loadOrders().catch(e=>$('#orders').textContent=e.message)}};
    $('#next').onclick=()=>{if(page*50<total){page++;loadOrders().catch(e=>$('#orders').textContent=e.message)}};
    const balanceResponse=await fetch('/api/agent/balance',{cache:'no-store'});if(!balanceResponse.ok)throw Error('无法加载结算信息');const b=await balanceResponse.json();
    const yuan=c=>(c/100).toFixed(2);$('#pending').textContent=b.pending_cents<0?'待抵扣 ¥'+yuan(-b.pending_cents):'¥'+yuan(b.pending_cents);$('#earnings-meta').textContent=`累计预估收益 ¥${yuan(b.earned_cents)} · 已记录结算 ¥${yuan(b.settled_cents)}`;
    await loadOrders();
  }catch(e){$('#status').textContent=e.message;$('#orders').textContent=e.message}
})();
