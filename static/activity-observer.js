(() => {
let last=0;
function observe(event){
 if(document.visibilityState!=='visible' || (event && !event.isTrusted) || Date.now()-last<60000)return;
 last=Date.now(); fetch('/api/activity',{method:'POST',credentials:'same-origin'}).catch(()=>{});
}
['pointerdown','keydown'].forEach(name=>document.addEventListener(name,observe,{passive:true}));
})();