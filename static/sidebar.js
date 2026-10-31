/* Shared navigation footer; reuse existing account handlers in the main shell. */
(() => {
 const queryMode=new URLSearchParams(location.search);
 if(queryMode.get('embed')==='1' || queryMode.get('embedded')==='1')document.body.classList.add('embedded');
 const nav = document.querySelector('.v3-topbar');
 if (!nav || document.body.classList.contains('embedded')) return;
 const communityScript=document.createElement('script');communityScript.src='/static/community.js?v=20261031-1';document.body.append(communityScript);
 const desktop = matchMedia('(min-width:1101px)');
 const mainShell = !!document.getElementById('settings-menu');
 if (!mainShell) {
   const right = nav.querySelector('.right');
   const oldAvatar = right?.querySelector('.avatar');
   if (right) {
     const wrapper = document.createElement('span'); wrapper.id='nav-menu-wrap';
     const trigger=oldAvatar || document.createElement('span'); trigger.id='nav-avatar'; trigger.className='avatar';
     const menu=document.createElement('div'); menu.id='settings-menu'; menu.className='settings-popover'; menu.setAttribute('role','menu'); menu.hidden=true;
     menu.innerHTML='<a role="menuitem" href="/workbench?sidebar=settings">设置</a><a role="menuitem" href="/wallet">我的积分</a>';
     trigger.addEventListener('click',()=>{menu.hidden=!menu.hidden;});
     wrapper.append(trigger,menu);right.append(wrapper);
     document.addEventListener('click',event=>{if(!wrapper.contains(event.target))menu.hidden=true;});
   }
 }
  const wrap = document.getElementById('nav-menu-wrap');
  const avatar = document.getElementById('nav-avatar');
  const menu = document.getElementById('settings-menu');
  // The phone layout hides the entire sidebar footer. Mirror its existing
  // actions into More, keeping the original controls as the permission source.
  const moreMenu = document.getElementById('shell-more-menu');
  if (menu && moreMenu) {
    const section = document.createElement('section');
    section.className = 'shell-account-actions';
    section.setAttribute('aria-label', '账号管理');
    const heading = document.createElement('h3'); heading.textContent = '账号与设置';
    const actions = document.createElement('div');
    section.append(heading, actions); moreMenu.append(section);
    const pairs = [...menu.querySelectorAll(':scope > button, :scope > a')].map(source => {
      const button = document.createElement('button'); button.type = 'button';
      button.addEventListener('click', () => {
        if (source.hidden || source.disabled) return;
        moreMenu.close(); source.click();
      });
      actions.append(button);
      return {source, button};
    });
    const syncActions = () => pairs.forEach(({source, button}) => {
      button.textContent = source.textContent.trim();
      button.hidden = source.hidden;
      button.disabled = !!source.disabled;
    });
    new MutationObserver(syncActions).observe(menu, {subtree:true, childList:true,
      characterData:true, attributes:true, attributeFilter:['hidden', 'disabled']});
    syncActions();
  }
  let settingsToggle;
  if (wrap && avatar && menu) {
    settingsToggle = document.createElement('button');
    settingsToggle.id = 'mint-settings-toggle'; settingsToggle.type = 'button';
    settingsToggle.title = '设置'; settingsToggle.setAttribute('aria-label', '打开设置菜单');
    settingsToggle.setAttribute('aria-haspopup', 'menu'); settingsToggle.setAttribute('aria-controls', menu.id);
    settingsToggle.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9.5 3-.7 2.3-2 .9-2.2-.6-2.5 4.2 1.6 1.7v2.3L2.1 15l2.5 4.3 2.2-.6 2 .9.7 2.4h5l.7-2.4 2-.9 2.2.6 2.5-4.3-1.6-1.2v-2.3l1.6-1.7-2.5-4.2-2.2.6-2-.9L14.5 3z"/><circle cx="12" cy="12.5" r="3"/></svg>';
    wrap.insertBefore(settingsToggle, menu);
    // Reuse the original trigger so the existing menu and actions stay intact.
    settingsToggle.addEventListener('click', () => avatar.click());
    const syncMenu = () => settingsToggle.setAttribute('aria-expanded', String(!menu.hidden));
    new MutationObserver(syncMenu).observe(menu, {attributes:true, attributeFilter:['hidden']});
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && desktop.matches && !menu.hidden) {
        avatar.click(); settingsToggle.focus();
      }
    });
    syncMenu();
  }

 const syncDesktop=()=>{
   if(settingsToggle)settingsToggle.hidden=!desktop.matches;
   if(!desktop.matches && menu)menu.hidden=true;
 };
 desktop.addEventListener('change',syncDesktop);syncDesktop();
 if(mainShell) {
   const query=new URLSearchParams(location.search);const action=query.get('sidebar');
   const target=action==='wallet'?'wallet-settings-button':action==='settings'?'settings-button':null;
   if(target) {
     query.delete('sidebar');history.replaceState(null,'',location.pathname+(query.size?'?'+query.toString():'')+location.hash);
     const openPanel=()=>document.getElementById(target)?.click();
     if(typeof currentAccount!=='undefined' && currentAccount)openPanel();
     else window.addEventListener('account-changed',openPanel,{once:true});
   }
 } else if(desktop.matches) {
   const stat=nav.querySelector('.stat');
   if(stat) {
     stat.replaceChildren();const label=document.createElement('span');label.className='pd-pl';label.textContent='本月积分';
     const value=document.createElement('b');value.textContent='—';stat.append(label,value);
     fetch('/api/wallet',{credentials:'same-origin'}).then(async response=>{
       if(!response.ok){value.textContent=response.status===401?'未登录':'暂不可用';return;}
       const data=await response.json();const balance=data.wallet?.balance;
       value.textContent=typeof balance==='number'?balance.toLocaleString('en-US'):'暂不可用';
     }).catch(()=>{value.textContent='暂不可用';});
   }
 }
})();
