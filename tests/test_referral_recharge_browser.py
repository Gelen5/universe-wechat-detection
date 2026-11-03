import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser,ui

@pytest.mark.parametrize('width',[320,390,1440])
def test_invite_page_and_mobile_copy(ui,width):
    from server.invite_page import _invite_body,_STYLE
    from server.wallet_page import _page
    from server.referral_reward_rules import Rules
    from dataclasses import asdict
    info={'code':'ABC234','counts':{'total':2,'paid':1},'rules':asdict(Rules()),'enabled':True,
          'effective_at':'2026-11-03T00:00:00+00:00','earned_points':10,'pending_count':0,'debt_points':0,
          'invitees':[{'display_name':'好***','created_at':'2026-11-03','paid':True,'earned_points':10}],
          'recent_rewards':[{'created_at':'2026-11-03','kind':'first','granted':10,'reversed':0,'debt':0}]}
    page,_=ui
    page.set_viewport_size({'width':width,'height':900})
    page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text}}})")
    page.route('**/invite',lambda route:route.fulfill(content_type='text/html',body=_page('邀请',_STYLE+_invite_body(info,{'role':'user'}))))
    page.goto('http://ui.test/invite')
    expect(page.get_by_role('heading',name='邀请好友充值，积分持续返')).to_be_visible()
    page.locator('#wx-invite-copy').click()
    assert page.evaluate('window.copied')=='http://ui.test/?ref=ABC234'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert page.get_by_text('邀请返奖管理',exact=False).count()==0
    import os
    if os.getenv('REFERRAL_SCREENSHOTS'):
        page.screenshot(path=os.path.join(os.environ['REFERRAL_SCREENSHOTS'],f'invite-{width}.png'),full_page=True)
