"""Server-rendered, private recharge referral dashboard."""
import html
from fastapi import APIRouter,Request
from fastapi.responses import HTMLResponse
from . import accounts, referrals
from .wallet_page import _page
router=APIRouter(tags=['invite-page'])
def _esc(v):return html.escape(str(v),quote=True)
_STYLE='''<style>
.invite-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:24px 0}.invite-grid article,.invite-card{padding:20px;border:1px solid #d5e7dc;border-radius:18px;background:#ffffffb3;min-width:0}.invite-grid b{display:block;font-size:27px;color:#245c43;margin-top:8px}.invite-card{margin:18px 0}.invite-card p,.invite-card li{line-height:1.8;color:#526d5e}.invite-code{font:600 28px monospace;letter-spacing:.15em;color:#245c43}.invite-copy{min-height:44px;padding:10px 20px;border:1px solid #b9d8c6;border-radius:12px;background:#276f50;color:white;cursor:pointer;margin:12px 0}.invite-row{padding:14px 0;border-bottom:1px solid #e0ebe4;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.invite-row small{display:block;color:#637b6c;line-height:1.8}.invite-table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:12px;text-align:left;border-bottom:1px solid #dce9e1;white-space:nowrap}h1{font-size:clamp(26px,5vw,38px)}@media(max-width:600px){.invite-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.invite-card{padding:16px}}
</style>'''

def _invite_body(info,user):
    r=info['rules']; first=r['first_bps']/100; repeat=r['repeat_bps']/100; days=r['window_hours']//24
    rows=''.join(f'<div class="invite-row"><div><b>{_esc(i["display_name"])}</b><small>{_esc(i["created_at"][:10])} · {"已充值" if i["paid"] else "待充值"}</small></div><span>贡献 {_esc(i["earned_points"])} 积分</span></div>' for i in info['invitees'])
    records=''.join(f'<tr><td>{_esc(i["created_at"][:10])}</td><td>{"首充" if i["kind"]=="first" else "复充"}</td><td>{i["granted"]}</td><td>{i["reversed"]}</td><td>{i["debt"]}</td></tr>' for i in info['recent_rewards'])
    admin='<a href="/admin/referral-recharge">邀请返奖管理 →</a>' if user.get('role')=='admin' else ''
    return f'''<header class="wx-head"><a class="wx-back" href="/">← 返回工作台</a><a class="wx-back" href="/wallet">我的积分 →</a></header>
    <p class="wx-eyebrow">INVITE FRIENDS</p><h1>邀请好友充值，积分持续返</h1>
    <p class="wx-account">好友通过你的链接注册，首次充值返你 {first:g}% 积分，{days} 天内复充继续返 {repeat:g}%。</p>
    <p>{"活动已开启" if info['enabled'] else "活动暂未开启，邀请关系会正常保留"}</p>
    <div class="invite-grid"><article>累计邀请<b>{info['counts']['total']}</b></article><article>已充值好友<b>{info['counts']['paid']}</b></article><article>累计净奖励积分<b>{info['earned_points']}</b></article><article>待核查订单<b>{info['pending_count']}</b></article></div>
    <section class="invite-card"><h2>我的专属邀请码</h2><div class="invite-code" id="wx-invite-code">{_esc(info['code'])}</div><button class="invite-copy" id="wx-invite-copy" type="button">复制邀请链接</button><p id="copy-status" role="status" aria-live="polite"></p></section>
    <section class="invite-card"><h2>活动规则</h2><ul>
    <li>注册和首次任务只记录邀请关系，不额外赠送邀请积分；正常注册试用积分不受影响。</li>
    <li>以好友真实实付金额计算，按每元 {r['points_per_yuan']} 基础积分折算，首充返 {first:g}%，复充返 {repeat:g}%，积分向下取整。</li>
    <li>每位好友累计最多贡献 {r['cap']} 积分；复充奖励截止于首次真实充值后 {days} 天。</li>
    <li>活动生效前的充值不补奖，老用户不重置首充时间。支付或历史资料不足、异常邀请需核查。</li>
    <li>奖励进入赠送积分，不可提现、转账。充值退款会冲正对应奖励；赠送积分不足时，待冲正金额由后续奖励抵扣。</li>
    </ul><p>活动生效时间（UTC）：{_esc(info['effective_at'] or '待开启')}<br>当前待冲正：{info['debt_points']} 积分。没有需要手动领取的奖励，通过核验后自动到账。</p></section>
    <section class="invite-card"><h2>邀请的好友</h2>{rows or '<p>暂无邀请记录。</p>'}</section>
    <section class="invite-card"><h2>最近充值返奖记录</h2><div class="invite-table"><table><thead><tr><th>日期</th><th>类型</th><th>发放</th><th>已冲正</th><th>待冲正</th></tr></thead><tbody>{records or '<tr><td colspan="5">暂无充值返奖记录</td></tr>'}</tbody></table></div></section>{admin}
    <script>document.querySelector('#wx-invite-copy').onclick=async function(){{const link=location.origin+'/?ref='+encodeURIComponent(document.querySelector('#wx-invite-code').textContent);try{{await navigator.clipboard.writeText(link);document.querySelector('#copy-status').textContent='邀请链接已复制';}}catch(e){{document.querySelector('#copy-status').textContent='请手动复制：'+link;}}}};</script>'''

@router.get('/invite',response_class=HTMLResponse,include_in_schema=False)
def invite_page(request:Request):
    user=accounts.user_from_request(request)
    if not user:return HTMLResponse(_page('请先登录','<h1>请先登录</h1><a href="/">返回工作台登录</a>'),status_code=401,headers={'Cache-Control':'no-store'})
    return HTMLResponse(_page('邀请好友充值',_STYLE+_invite_body(referrals.summary(user['id']),user)),headers={'Cache-Control':'no-store'})
