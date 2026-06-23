const params = new URLSearchParams(location.search);
const requestId = params.get("request_id");
const accessToken = params.get("access_token");
const nodes = Object.fromEntries(["title", "status", "content", "meta", "note", "assets", "events"].map((id) => [id, document.querySelector(`#${id}`)]));
function esc(value){const el=document.createElement("div");el.textContent=value||"";return el.innerHTML}
async function load(){
  if(!requestId || !accessToken){nodes.status.textContent="缺少视频申请访问凭证。";nodes.status.className="status error";return}
  try{
    const res=await fetch(`./api/media/requests/${encodeURIComponent(requestId)}`,{headers:{"X-Media-Access-Token":accessToken}});
    const data=await res.json(); if(!res.ok) throw new Error(data.detail||"加载失败"); render(data);
  }catch(error){nodes.status.textContent=error.message;nodes.status.className="status error"}
}
function render(item){
  nodes.title.textContent=`${item.status === "DEMO_DELIVERED" ? "演示交付包已完成" : "视频生产申请"}`;
  nodes.status.textContent=item.status; nodes.note.textContent=item.status_note||"";
  nodes.meta.innerHTML=[`申请 ${item.request_id.slice(-8)}`,`${item.estimate.total_seconds} 秒口播`,`${item.estimate.estimated_clips} 个预估镜头`,item.output_profile].map((x)=>`<span>${esc(x)}</span>`).join("");
  nodes.assets.innerHTML=(item.assets||[]).map((asset)=>`<a href="./api/media/requests/${encodeURIComponent(item.request_id)}/assets/${encodeURIComponent(asset.asset_id)}" data-asset="${asset.asset_id}">${esc(asset.asset_type)} 下载</a>`).join("")||"暂未产生可下载交付物。";
  nodes.assets.querySelectorAll("a[data-asset]").forEach((link)=>link.addEventListener("click",(event)=>{event.preventDefault();fetch(link.href,{headers:{"X-Media-Access-Token":accessToken}}).then((r)=>r.blob()).then((blob)=>{const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=link.textContent.trim();a.click();URL.revokeObjectURL(a.href)})}));
  nodes.events.innerHTML=(item.events||[]).map((event)=>`<div><strong>${esc(event.action)}</strong> · ${esc(event.note)}<br><small>${esc(event.created_at)}</small></div>`).join("");
  nodes.content.classList.remove("hidden");
  if(!["DEMO_DELIVERED","DELIVERED","REJECTED","FAILED"].includes(item.status)) setTimeout(load,2500);
}
load();
