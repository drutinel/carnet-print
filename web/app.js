(() => {
"use strict";
// Modo kiosko: /c/<cliente> inyecta window.KIOSK (plantilla fija, campos que se pueden llenar).
const KIOSK=window.KIOSK||null;
const FIELD_INPUT={name:"d-name",ced:"d-ced",cat:"d-cat",extra:"d-extra",code:"d-code",issue:"d-issue",photo:"d-photo"};
const EDITABLE=new Set(KIOSK?KIOSK.editable:Object.keys(FIELD_INPUT));
const canEdit=bindId=>!KIOSK || [...EDITABLE].some(f=>FIELD_INPUT[f]===bindId);
if(KIOSK) document.body.classList.add("kiosk");
const $ = (s,r=document)=>r.querySelector(s);
const $$ = (s,r=document)=>[...r.querySelectorAll(s)];
const {esc,digits,fmtCed,validCed,todayISO,addValidity,fmtDate,slug,resolveLayout,getPath,setPath,fieldsWidth,fitField}=window.CarnetLib;   // funciones puras: web/lib.js

/* ---------- Almacén: API del middleware (templates.json y carnets.json junto al .exe) ---------- */
async function api(path,opt={}){
  const r=await fetch(apiBase()+path,{...opt,headers:{...apiHeaders(),...(opt.headers||{})}});
  if(r.status===401) throw new Error("API key inválida (abre “Conexión al middleware”)");
  if(!r.ok){
    const e=await r.json().catch(()=>({}));
    // 422 de pydantic: lista de {loc, msg}; se muestra «front.margins.top: Input should be…»
    const detail=Array.isArray(e.detail)?e.detail.map(d=>`${(d.loc||[]).slice(1).join(".")}: ${d.msg}`).join("; "):e.detail;
    throw new Error(typeof detail==="string"?detail:("error "+r.status));
  }
  return r.status===204?null:r.json();
}
const jsonPut=(path,obj)=>api(path,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(obj)});
const jsonPatch=(path,obj)=>api(path,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(obj)});
const jsonPost=(path,obj)=>api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(obj)});
const canSeeRegistry=!KIOSK||!!KIOSK.show_registry;   // un kiosko sin registro no puede leer /cards
const getAll=()=>api("/cards");                      // registro liviano: sin imágenes
const getCard=control=>api("/cards/"+encodeURIComponent(control));   // completo, con imágenes

/* ---------- Estado de imágenes (dataURL) ---------- */
const img={logo1:null,logo2:null,seal:null,sign:null,photo:null};
// Un solo componente "subir / miniatura / quitar" para logos, sello, firma y foto.
// Ids que usa el resto del código: t-<clave> (input) y th-<clave> (miniatura); la foto usa d-photo.
const inputId=k=>k==="photo"?"d-photo":"t-"+k;
$$(".asset").forEach(el=>{
  const k=el.dataset.key;
  el.innerHTML=`<span>${esc(el.dataset.label)}</span><div class="row">
    <span class="btn sm filebtn">Subir<input type="file" id="${inputId(k)}" accept="image/*" aria-label="${esc(el.dataset.label)}"></span>
    <img class="thumb" id="th-${k}" alt="" hidden>
    <button class="btn sm" data-clear="${k}" type="button">Quitar</button></div>`;
});
function setImg(k,value){
  img[k]=value||null;
  const t=$("#th-"+k); if(t){ t.hidden=!img[k]; t.src=img[k]||""; }
}
// La foto del titular se reduce a 800 px (JPEG) antes de guardarla: la tarjeta la imprime a ~330 px y una
// foto de celular de varios MB superaría el límite del servidor. Logos, sello y firma conservan su
// transparencia (PNG) y solo se reducen si son enormes.
const IMAGE_RULES={photo:{max:800,type:"image/jpeg",quality:0.9}};
const DEFAULT_IMAGE_RULE={max:1600,type:"image/png"};
const readAsDataURL=file=>new Promise((ok,fail)=>{
  const fr=new FileReader(); fr.onload=()=>ok(fr.result); fr.onerror=()=>fail(fr.error); fr.readAsDataURL(file);
});
async function prepareImage(file,rule){
  const original=await readAsDataURL(file);
  const bitmap=await createImageBitmap(file);   // SVG o formato raro: createImageBitmap falla y el servidor lo rechazará con su mensaje
  const scale=Math.min(1,rule.max/Math.max(bitmap.width,bitmap.height));
  if(scale===1 && rule.type!=="image/jpeg" && file.size<1_500_000){ bitmap.close(); return original; }   // ya es chica: tal cual
  const canvas=document.createElement("canvas");
  canvas.width=Math.round(bitmap.width*scale); canvas.height=Math.round(bitmap.height*scale);
  const g=canvas.getContext("2d");
  if(rule.type==="image/jpeg"){ g.fillStyle="#fff"; g.fillRect(0,0,canvas.width,canvas.height); }   // JPEG no tiene transparencia
  g.drawImage(bitmap,0,0,canvas.width,canvas.height); bitmap.close();
  return canvas.toDataURL(rule.type,rule.quality);
}
Object.keys(img).forEach(k=>{
  $("#"+inputId(k)).addEventListener("change",async e=>{
    const f=e.target.files[0]; if(!f) return;
    try{ setImg(k,await prepareImage(f,IMAGE_RULES[k]||DEFAULT_IMAGE_RULE)); render(); }
    catch(err){ setStatus("No se pudo leer la imagen: "+err.message,"bad"); }
    finally{ e.target.value=""; }
  });
});
$$("[data-clear]").forEach(b=>b.addEventListener("click",()=>{
  const k=b.dataset.clear; setImg(k,null);
  if(k==="photo") draftDirty=true;
  render();
}));

/* ---------- Borrador del titular ----------
   Lo que se está llenando (nombre, cédula, código, categoría, dato extra, fecha y foto) se guarda solo en el
   servidor (draft.json junto al .exe) y se recupera al abrir, aunque cambie el navegador, el puerto o se
   reinicie el programa. Se borra al imprimir bien o con «Limpiar». Cada kiosko tiene el suyo. */
const LEGACY_DRAFT_KEY="carnet-borrador-titular";   // versiones viejas lo guardaban en el navegador
const DRAFT_FIELDS=["d-name","d-ced","d-code","d-cat","d-extra","d-issue"];
const DRAFT_KEYS={"d-name":"name","d-ced":"ced","d-code":"code","d-cat":"cat","d-extra":"extra","d-issue":"issue"};
let draftDirty=false, draftTimer=0, draftErrorShown=false;
let EDITING=null;   // {control, templateId} mientras se corrige un carnet ya emitido
function saveDraft(){
  if(!draftDirty || EDITING) return;   // editar un carnet no toca el borrador del carnet que se estaba llenando
  clearTimeout(draftTimer);
  draftTimer=setTimeout(async()=>{
    if(EDITING) return;   // si mientras tanto se abrió un carnet para corregirlo, no se guarda sobre el borrador
    const body=Object.fromEntries(DRAFT_FIELDS.map(id=>[DRAFT_KEYS[id],$("#"+id).value]));
    body.photo=img.photo||null;
    try{ await jsonPut("/draft",body); draftErrorShown=false; }
    catch(e){
      console.warn("No se pudo guardar el borrador:",e);
      if(!draftErrorShown){ draftErrorShown=true; setStatus("No se pudo guardar el borrador: "+e.message,"warn"); }
    }
  },500);
}
function fillTitular(o){
  DRAFT_FIELDS.forEach(id=>{ const v=o[DRAFT_KEYS[id]]; if(v!=null && v!=="") $("#"+id).value=v; });
  if(o.photo) setImg("photo",o.photo);
  $("#d-ced").dispatchEvent(new Event("input"));   // formato y validación de la cédula
}
async function restoreDraft(){
  let o={};
  try{ o=await api("/draft"); }
  catch(e){ console.warn("No se pudo leer el borrador:",e); return false; }
  if(!Object.keys(o).length){   // borrador de una versión anterior (estaba en el navegador): se sube una vez
    try{
      const old=JSON.parse(localStorage.getItem(LEGACY_DRAFT_KEY)||"null");
      if(old){
        o={name:old["d-name"]||"",ced:old["d-ced"]||"",code:old["d-code"]||"",cat:old["d-cat"]||"",
           extra:old["d-extra"]||"",issue:old["d-issue"]||"",photo:old.photo||null};
        await jsonPut("/draft",o); localStorage.removeItem(LEGACY_DRAFT_KEY);
      }
    }catch(e){ console.warn("No se pudo migrar el borrador viejo:",e); }
  }
  if(!Object.values(o).some(v=>v)) return false;
  fillTitular(o);
  return true;
}
// Guarda ya lo pendiente (antes de cargar otro carnet en pantalla)
async function flushDraft(){
  if(!draftDirty || EDITING) return;
  clearTimeout(draftTimer);
  const body=Object.fromEntries(DRAFT_FIELDS.map(id=>[DRAFT_KEYS[id],$("#"+id).value]));
  body.photo=img.photo||null;
  await jsonPut("/draft",body);
}
function clearDraft(){
  clearTimeout(draftTimer); draftDirty=false;
  api("/draft",{method:"DELETE"}).catch(e=>console.warn("No se pudo borrar el borrador:",e));
}
function resetTitularFields(){
  ["d-name","d-ced","d-code","d-cat","d-extra"].forEach(id=>$("#"+id).value="");
  $("#d-issue").value=todayISO();
  setImg("photo",null);
  $("#ced-msg").textContent=""; $("#ced-msg").className="validmsg";
}
function clearTitular(){
  resetTitularFields();
  EDITING=null; updateEditUI();
  clearDraft(); render();
}
DRAFT_FIELDS.forEach(id=>$("#"+id).addEventListener("input",()=>{draftDirty=true;}));
$("#d-issue").addEventListener("change",()=>{draftDirty=true;});
$("#d-photo").addEventListener("change",()=>{draftDirty=true;});

/* ---------- Validación de cédula RD ---------- */
$("#d-ced").addEventListener("input",e=>{
  e.target.value=fmtCed(e.target.value);
  const m=$("#ced-msg"); const d=digits(e.target.value);
  if(d.length===0){m.textContent="";m.className="validmsg";}
  else if(d.length<11){m.textContent="Cédula incompleta";m.className="validmsg bad";}
  else if(validCed(e.target.value)){m.textContent="✓ Cédula válida";m.className="validmsg ok";}
  else {m.textContent="✗ Dígito verificador no coincide";m.className="validmsg bad";}
  render();
});

/* ---------- Fechas ---------- */
$("#d-issue").value=todayISO();
function calcExpiry(){
  return addValidity($("#d-issue").value||todayISO(), parseInt($("#t-valnum").value||"1",10), $("#t-valunit").value);
}

/* ---------- Render tarjeta ---------- */
// Campos del diseño: clave -> [id del control, valor por defecto]. Fuente única para
// leer (tpl), aplicar (applyTpl), repintar al editar y cargar un carnet viejo (lookup).
const TPL_FIELDS={
  org:["t-org",""], title:["t-title",""], band:["t-band","#1e40af"], accent:["t-accent","#1e40af"],
  cardbg:["t-cardbg","#ffffff"], signname:["t-signname",""], contact:["t-contact",""],
  legend:["t-legend",""], valnum:["t-valnum","1"], valunit:["t-valunit","years"], prefix:["t-prefix",""],
  sealsize:["t-sealsize","80"], sealop:["t-sealop","7"], sealsrc:["t-sealsrc","seal"],
  orgsize:["t-orgsize","12"], orgbold:["t-orgbold","700"], titlesize:["t-titlesize","9.5"], titlebold:["t-titlebold","400"]
};
const TPL_IMAGES=["logo1","logo2","seal","sign"];
// Layout editable (rótulos, tamaños, ajuste de texto, márgenes): se guarda dentro de cada plantilla
let layoutState=resolveLayout({});
function tpl(){return {...Object.fromEntries(Object.entries(TPL_FIELDS).map(([k,[id]])=>[k,$("#"+id).value])), layout:layoutState};}
// Ancho real del texto en el canvas (misma tipografía que la tarjeta) para ajustar los campos largos
const _measureCtx=document.createElement("canvas").getContext("2d");
const measureText=(text,size,bold)=>{ _measureCtx.font=`${bold?"bold":"normal"} ${size}px Arial, Helvetica, sans-serif`; return _measureCtx.measureText(text).width; };
function titleStyles(t){
  return{
    org:`font-size:${t.orgsize||12}px;font-weight:${t.orgbold||700}`,
    title:`font-size:${t.titlesize||9.5}px;font-weight:${t.titlebold||400}`
  };
}
function sealImg(t){return img[t.sealsrc||"seal"];}
function sealStyle(t){
  const src=sealImg(t);
  const size=parseInt(t.sealsize||80,10);
  const op=(parseFloat(t.sealop||7)||7)/100;
  return `background-image:url('${src}');background-size:${size}px;opacity:${op}`;
}
function data(){
  const issue=$("#d-issue").value||todayISO();
  const expiry=calcExpiry();
  $("#d-expiry").value=fmtDate(expiry);
  return{
    name:$("#d-name").value, ced:$("#d-ced").value, code:$("#d-code").value,
    cat:$("#d-cat").value, extra:$("#d-extra").value, issue, expiry
  };
}
// preview=true: la vista previa agrega huecos tocables (logos, dato extra); la imagen impresa no.
function cardFrontHTML(t,d,preview=false){
  const slots=preview&&!KIOSK;   // huecos tocables: no en modo kiosko
  const L=resolveLayout(t.layout), F=L.front, m=F.margins;
  const photoSize=`width:${F.photo.width}px;height:${F.photo.height}px`;
  const photo = img.photo
    ? `<img class="photo" style="${photoSize}" src="${img.photo}" alt="">`
    : `<div class="photo ph" style="${photoSize}">FOTO</div>`;
  const vstyle=f=>`font-size:${f.size}px;${f.bold?"":"font-weight:400;"}`;
  const avail=fieldsWidth(F);
  // Un campo: rótulo + valor. Si el valor no cabe se ajusta según su política (cortar, achicar o varias líneas)
  const field=(key,value,bindId)=>{
    const f=F.fields[key], fit=fitField(value||"—",f,avail,measureText);
    const style=`font-size:${fit.size}px;${f.bold?"":"font-weight:400;"}${fit.lines>1?`--lines:${fit.lines};`:""}`;
    return `<div class="fld"><div class="k kblack">${esc(f.label)}</div><div class="v${fit.lines>1?" multi":""} kblack" style="${style}" data-bind="${bindId}">${esc(value)||"—"}</div></div>`;
  };
  const seal = sealImg(t) ? `<div class="seal" style="${sealStyle(t)}"></div>` : "";
  const logo=(k,id,label)=>img[k]
    ? `<img src="${img[k]}" alt=""${slots?` data-upload="${id}" title="Toca para cambiar el ${label}"`:""}>`
    : slots?`<div class="ph-slot" data-upload="${id}" title="Toca para subir el ${label}">+ ${label}</div>`:"";
  const l1 = logo("logo1","t-logo1","logo 1");
  const l2 = logo("logo2","t-logo2","logo 2");
  const sealChip = slots && !sealImg(t) ? `<div class="ph-chip" data-upload="t-seal" title="Toca para subir el sello / marca de agua">+ sello</div>` : "";
  return `<div class="card" style="--card-bg:${t.cardbg};--card-band:${t.band};--card-accent:${t.accent}">
    ${seal}${sealChip}
    <div class="band">
      <div class="bandside left">${l1}</div>
      <div class="titles"><span class="org${(t.org||"").length>25?" long":""}" style="${titleStyles(t).org}" data-bind="t-org">${esc(t.org)||"ORGANIZACIÓN"}</span>
        <span class="ctitle" style="${titleStyles(t).title}" data-bind="t-title">${esc(t.title)||"Carnet"}</span></div>
      <div class="bandside right">${l2}</div>
    </div>
    <div class="front-body" style="padding:${m.top}px ${m.right}px ${m.bottom}px ${m.left}px;gap:${F.gap}px">${photo}
      <div class="fields">
        ${field("name",d.name,"d-name")}
        ${field("ced",d.ced,"d-ced")}
        ${field("cat",d.cat,"d-cat")}
        ${d.extra||(preview&&canEdit("d-extra"))?field("extra",d.extra,"d-extra"):""}
        <div class="footer">
          <div class="dates">
            <div class="fld"><div class="k kblack">${esc(F.footer.issue.label)}</div><div class="v kblack" style="${vstyle(F.footer.issue)}">${fmtDate(d.issue)}</div></div>
            <div class="fld"><div class="k kblack">${esc(F.footer.expiry.label)}</div><div class="v kblack" style="${vstyle(F.footer.expiry)}">${fmtDate(d.expiry)}</div></div>
          </div>
          <div class="code"><div class="k kblack">${esc(F.footer.code.label)}</div><div class="v" style="${vstyle(F.footer.code)}" data-bind="d-code">${esc(d.code)||"—"}</div></div>
        </div>
      </div>
    </div></div>`;
}
function cardBackHTML(t,d,preview=false){
  const seal = sealImg(t) ? `<div class="seal" style="${sealStyle(t)}"></div>` : "";
  const sign = img.sign
    ? `<img src="${img.sign}" alt=""${preview&&!KIOSK?` data-upload="t-sign" title="Toca para cambiar la firma"`:""}>`
    : preview&&!KIOSK?`<div class="ph-slot sign-slot" data-upload="t-sign" title="Toca para subir la firma">+ firma</div>`:"";
  const bm=resolveLayout(t.layout).back.margins;
  return `<div class="card back" style="--card-bg:${t.cardbg};--card-band:${t.band};--card-accent:${t.accent};padding:${bm.top}px ${bm.right}px ${bm.bottom}px ${bm.left}px">
    ${seal}
    <div class="backband" style="margin:-${bm.top}px -${bm.right}px 12px -${bm.left}px"><span class="org${(t.org||"").length>25?" long":""}" style="${titleStyles(t).org}" data-bind="t-org">${esc(t.org)||""}</span></div>
    <div class="legend kblack" data-bind="t-legend">${esc(t.legend)||"Este carnet es propiedad de la organización emisora. En caso de extravío, favor devolverlo."}</div>
    <div class="sign">
      <div class="box">${sign}<div class="line kblack" data-bind="t-signname">${esc(t.signname)||"Firma autorizada"}</div></div>
    </div>
    <div class="contact kblack" data-bind="t-contact">${esc(t.contact)||""}</div>
  </div>`;
}
function render(){
  const t=tpl(), d=data();
  $("#v-orgsize").textContent=t.orgsize+" px";
  $("#v-titlesize").textContent=t.titlesize+" px";
  $("#v-sealsize").textContent=t.sealsize+" px";
  $("#v-sealop").textContent=t.sealop+" %";
  $("#pv-front").innerHTML=cardFrontHTML(t,d,true);
  $("#pv-back").innerHTML=cardBackHTML(t,d,true);
  enableInlineEdit();
  scheduleAutosave();
  saveDraft();
}

/* ---------- Edición directa en la vista previa ----------
   Cada texto con data-bind="<id del campo>" se edita tocándolo; el valor va al
   campo del formulario y la tarjeta se vuelve a dibujar al salir (Enter o clic fuera). */
// Texto guía de los campos vacíos: solo en pantalla, la imagen impresa no lo lleva.
const INLINE_HINTS={"d-name":"Nombre y apellidos","d-ced":"000-0000000-0","d-cat":"Cargo o categoría",
  "d-code":"Auto","d-extra":"Dato extra","t-contact":"Tel. / correo / web (opcional)"};
function enableInlineEdit(){
  $$("#pv-front [data-bind], #pv-back [data-bind]").forEach(el=>{
    const field=$("#"+el.dataset.bind); if(!field) return;
    if(!canEdit(field.id)){ el.removeAttribute("data-bind"); return; }
    el.contentEditable="plaintext-only";
    el.spellcheck=false;
    el.title="Toca para editar";
    if(!field.value.trim()){
      el.classList.add("is-empty");
      if(INLINE_HINTS[field.id]) el.textContent=INLINE_HINTS[field.id];
    }
  });
  $$("#pv-front .photo").forEach(el=>el.title="Toca para cambiar la foto");
}
function inlineCommit(el){
  const field=$("#"+el.dataset.bind); if(!field) return;
  const multiline=field.tagName==="TEXTAREA";
  let v=el.innerText.replace(/ /g," ");
  v=multiline?v.trim():v.replace(/\s+/g," ").trim();
  if(field.value!==v){ field.value=v; field.dispatchEvent(new Event("input",{bubbles:true})); }
  else render();
}
["#pv-front","#pv-back"].forEach(sel=>{
  const host=$(sel);
  host.addEventListener("focusin",e=>{
    const el=e.target.closest("[data-bind]"); if(!el) return;
    if(el.classList.contains("is-empty")){ el.textContent=""; el.classList.remove("is-empty"); }
    // seleccionar todo el texto: escribir reemplaza, flechas permiten corregir
    const r=document.createRange(); r.selectNodeContents(el);
    const s=getSelection(); s.removeAllRanges(); s.addRange(r);
  });
  host.addEventListener("focusout",e=>{
    const el=e.target.closest("[data-bind]"); if(el) inlineCommit(el);
  });
  host.addEventListener("keydown",e=>{
    const el=e.target.closest("[data-bind]"); if(!el) return;
    const multiline=$("#"+el.dataset.bind)?.tagName==="TEXTAREA";
    if(e.key==="Enter" && !(multiline && e.shiftKey)){ e.preventDefault(); el.blur(); }
    if(e.key==="Tab"){
      // Al salir se redibuja la tarjeta; se enfoca el texto siguiente/anterior por posición.
      e.preventDefault();
      const sel="#pv-front [data-bind], #pv-back [data-bind]";
      const i=[...$$(sel)].indexOf(el)+(e.shiftKey?-1:1);
      el.blur();
      const next=[...$$(sel)][i]; if(next) next.focus();
    }
    if(e.key==="Escape"){ e.preventDefault(); el.removeAttribute("data-bind"); el.blur(); render(); }
  });
  host.addEventListener("click",e=>{
    const up=e.target.closest("[data-upload]");
    if(up && !KIOSK) $("#"+up.dataset.upload).click();
    else if(e.target.closest(".photo") && canEdit("d-photo")) $("#d-photo").click();
  });
});
[...Object.values(TPL_FIELDS).map(([id])=>id),"d-name","d-code","d-cat","d-extra","d-issue"]
  .forEach(id=>{ const el=$("#"+id); el.addEventListener("input",render); el.addEventListener("change",render); });

/* ---------- Plantillas (templates.json junto al .exe) ---------- */
let TPLS={}, ACTIVE_TPL=null, CUR_TPL=null;
function tplSnapshot(){return {...tpl(), img:{logo1:img.logo1,logo2:img.logo2,seal:img.seal,sign:img.sign}};}
function renderTplSelect(){
  const sel=$("#tpl-select");
  sel.innerHTML=Object.entries(TPLS).map(([id,t])=>
    `<option value="${esc(id)}">${esc(t.name||id)}${id===ACTIVE_TPL?" ★ API":""}</option>`).join("")
    ||'<option value="">(sin plantillas)</option>';
  // CUR_TPL nulo = diseño tomado de un carnet viejo: no se autoguarda sobre ninguna plantilla
  if(!CUR_TPL && Object.keys(TPLS).length) sel.insertAdjacentHTML("afterbegin",'<option value="">(diseño del carnet cargado)</option>');
  sel.value=CUR_TPL||"";
  $("#tpl-name").textContent=CUR_TPL?(TPLS[CUR_TPL]?.name||CUR_TPL)+(CUR_TPL===ACTIVE_TPL?" ★":""):"sin guardar";
  $("#tpl-note").textContent=CUR_TPL
    ? `Los cambios se guardan solos en «${TPLS[CUR_TPL]?.name||CUR_TPL}»${CUR_TPL===ACTIVE_TPL?" (la que usa el API)":""}.`
    : "Diseño tomado de un carnet viejo: no se autoguarda. Usa «Nueva…» para conservarlo.";
}
async function refreshTemplates(){
  const r=await api("/templates");
  TPLS=r.templates; ACTIVE_TPL=r.active;
  if(!CUR_TPL || !TPLS[CUR_TPL]) CUR_TPL=ACTIVE_TPL||Object.keys(TPLS)[0]||null;
  renderTplSelect();
}
async function putTpl(id,name){
  const body={name,...tplSnapshot()};
  await jsonPut("/templates/"+encodeURIComponent(id),body);
  TPLS[id]=body; if(!ACTIVE_TPL) ACTIVE_TPL=id;
}
async function doSaveTpl(){
  try{
    if(!CUR_TPL) return doNewTpl();
    await putTpl(CUR_TPL,TPLS[CUR_TPL]?.name||CUR_TPL); renderTplSelect();
    setStatus("Plantilla guardada.","ok");
  }catch(e){setStatus("No se pudo guardar la plantilla: "+e.message,"bad");}
}
async function doNewTpl(){
  const name=(prompt("Nombre de la plantilla nueva:")||"").trim(); if(!name) return;
  const id=slug(name); if(!id) return setStatus("Nombre no válido.","bad");
  if(TPLS[id] && !confirm(`Ya existe “${TPLS[id].name||id}”. ¿Reemplazarla con el diseño actual?`)) return;
  try{ await putTpl(id,name); CUR_TPL=id; renderTplSelect(); setStatus(`Plantilla “${name}” guardada.`,"ok"); }
  catch(e){setStatus("No se pudo guardar la plantilla: "+e.message,"bad");}
}
async function doDelTpl(){
  if(!CUR_TPL || !confirm(`¿Eliminar la plantilla “${TPLS[CUR_TPL]?.name||CUR_TPL}”?`)) return;
  try{
    await api("/templates/"+encodeURIComponent(CUR_TPL),{method:"DELETE"});
    CUR_TPL=null; await refreshTemplates();
    if(CUR_TPL) applyTpl(TPLS[CUR_TPL]);
    setStatus("Plantilla eliminada.","ok");
  }catch(e){setStatus("No se pudo eliminar: "+e.message,"bad");}
}
async function doActivateTpl(){
  if(!CUR_TPL) return setStatus("Guarda primero la plantilla.","warn");
  try{
    await doSaveTpl();
    const r=await api("/templates/"+encodeURIComponent(CUR_TPL)+"/activate",{method:"POST"});
    ACTIVE_TPL=r.active; renderTplSelect();
    setStatus(`El API usa ahora “${TPLS[CUR_TPL]?.name||CUR_TPL}”.`,"ok");
  }catch(e){setStatus("No se pudo activar: "+e.message,"bad");}
}
// El diseño se guarda solo (en la plantilla elegida) al cambiar, y se carga al abrir.
let tplReady=false, autosaveTimer=0;
function scheduleAutosave(){
  if(!tplReady || !CUR_TPL) return;
  clearTimeout(autosaveTimer);
  const id=CUR_TPL;
  autosaveTimer=setTimeout(()=>{ putTpl(id,TPLS[id]?.name||id).catch(e=>setStatus("No se pudo guardar la plantilla: "+e.message,"bad")); },800);
}
$("#tpl-select").addEventListener("change",e=>{
  const id=e.target.value; if(!id||!TPLS[id]) return;
  clearTimeout(autosaveTimer); CUR_TPL=id; applyTpl(TPLS[id]);
  setStatus(`Plantilla “${TPLS[id].name||id}” cargada.`,"ok");
});
function applyTpl(s){
  Object.entries(TPL_FIELDS).forEach(([k,[id,def]])=>{ $("#"+id).value=s[k]||def; });
  if(s.img) TPL_IMAGES.forEach(k=>setImg(k,s.img[k]));
  layoutState=resolveLayout(s.layout);
  refreshLayoutEditor();
  render();
}
$("#new-tpl").addEventListener("click",doNewTpl);
$("#del-tpl").addEventListener("click",doDelTpl);
$("#activate-tpl").addEventListener("click",doActivateTpl);

/* ---------- Estatus ---------- */
function setStatus(msg,cls=""){const s=$("#status");s.textContent=msg;s.className="status "+cls;}

/* ---------- Registro ---------- */
function statusOf(c){
  if(c.voided) return "anu";
  const now=todayISO();
  return (c.data.expiry && c.data.expiry < now) ? "ven" : "vig";
}
async function renderRegistry(){
  const all=(await getAll()).sort((a,b)=>b.control.localeCompare(a.control));
  const q=($("#reg-q").value||"").toLowerCase();
  const rows=all.filter(c=>{
    if(!q) return true;
    return [c.control,c.data.name,c.data.ced,c.data.code,c.tpl.org].join(" ").toLowerCase().includes(q);
  });
  $("#reg-body").innerHTML=rows.map(c=>{
    const st=statusOf(c);
    const lbl={vig:"Vigente",ven:"Vencido",anu:"Anulado"}[st];
    return `<tr class="${c.voided?"":"editable-row"}" ${c.voided?"":`data-edit="${esc(c.control)}" tabindex="0" title="Clic para cargarlo y corregirlo"`}>
      <td>${esc(c.control)}</td>
      <td>${esc(new Date(c.createdAt).toLocaleString('es-DO'))}</td>
      <td>${esc(c.data.name)}</td><td>${esc(c.data.ced)}</td><td>${esc(c.data.code)}</td>
      <td>${esc(c.data.cat)}</td><td>${esc(c.tpl.org)}</td>
      <td>${fmtDate(c.data.issue)}</td><td>${fmtDate(c.data.expiry)}</td>
      <td>${c.prints||1}</td>
      <td><span class="badge ${st}">${lbl}</span></td>
      <td>
        <button class="btn sm" data-reprint="${esc(c.control)}">Reimprimir</button>
        ${c.voided?"":`<button class="btn sm danger" data-void="${esc(c.control)}">Anular</button>`}
      </td></tr>`;
  }).join("") || `<tr><td colspan="12" style="color:var(--muted);text-align:center;padding:16px">Sin registros todavía.</td></tr>`;
  const vig=all.filter(c=>statusOf(c)==="vig").length;
  $("#stats").textContent=`${all.length} emitidos · ${vig} vigentes`;
}

/* ---------- Impresoras y ajustes (settings.json junto al .exe) ---------- */
// Todo se imprime por el API (PNG directo al SDK); no hay impresión por el navegador.
const CANVAS={w:1015,h:640};   // DS3: página física del driver a 300 ppp (incluye ~2 px de sangrado por lado)
const DEFAULT_CAL={rotate:false,split:false,ox:0,oy:0};
const DEFAULT_SETTINGS={printer:"",quality:"fine",hopper:"",cal:{}};
let SETTINGS={...DEFAULT_SETTINGS}, settingsTimer=0, PRINTER_LIST=[];
const curPrinter=()=>PRINTER_LIST.find(p=>p.id===$("#printer").value)||null;
async function loadSettings(){
  const saved=await api("/settings");
  SETTINGS={...DEFAULT_SETTINGS,...saved,cal:{...(saved.cal||{})}};
}
function saveSettings(){
  if(KIOSK) return;   // el kiosko nunca modifica la configuración
  clearTimeout(settingsTimer);
  settingsTimer=setTimeout(()=>{ settingsTimer=0; jsonPut("/settings",SETTINGS).catch(
    e=>setStatus("No se pudo guardar el ajuste: "+e.message,"bad")); },500);
}
async function flushSettings(){
  if(KIOSK || !settingsTimer) return;
  clearTimeout(settingsTimer); settingsTimer=0;
  await jsonPut("/settings",SETTINGS);
}
async function loadPrinters(){
  PRINTER_LIST=await api("/printers");
  const sel=$("#printer");
  sel.innerHTML=PRINTER_LIST.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("")
    ||'<option value="">(sin impresoras en printers.yaml)</option>';
  if(PRINTER_LIST.some(p=>p.id===SETTINGS.printer)) sel.value=SETTINGS.printer;
}
function applyPrinter(){
  const p=$("#printer").value, v={...DEFAULT_CAL,...SETTINGS.cal[p]};
  $("#opt-rotate").checked=!!v.rotate; $("#opt-split").checked=!!v.split;
  $("#off-x").value=v.ox||0; $("#off-y").value=v.oy||0;
  $("#printer-note").textContent="Imprime sin diálogo por el SDK de Entrust: frente y reverso a "+CANVAS.w+" × "+CANVAS.h+
    " px (300 ppp), a doble cara. Espera a que la tarjeta salga (30-60 s) y avisa si la impresora reporta un error."+
    (SETTINGS.cal[p]?" · Calibración guardada para esta impresora.":"");
  refreshPrinterChip();
}
function readCal(){
  return {rotate:$("#opt-rotate").checked,split:$("#opt-split").checked,
          ox:parseFloat($("#off-x").value||0),oy:parseFloat($("#off-y").value||0)};
}
$("#printer").addEventListener("change",()=>{ SETTINGS.printer=$("#printer").value; saveSettings(); applyPrinter(); });
$$("#opt-rotate,#opt-split,#off-x,#off-y").forEach(el=>el.addEventListener("change",()=>{
  SETTINGS.cal[$("#printer").value]=readCal(); saveSettings(); applyPrinter();
}));
$("#adv-quality").addEventListener("change",e=>{ SETTINGS.quality=e.target.value; saveSettings(); });
$("#adv-hopper").addEventListener("change",e=>{ SETTINGS.hopper=e.target.value; saveSettings(); });
$("#cal-reset").addEventListener("click",()=>{
  const p=$("#printer").value; delete SETTINGS.cal[p]; saveSettings(); applyPrinter();
  setStatus("Calibración restablecida.","ok");
});
// Tarjeta de calibración: va por el API como cualquier carnet (solo cinta de color, sin capa K).
// Coordenadas en px de tarjeta (4 px/mm: 342.4 × 216); rasterizeFace ya aplica X/Y y el giro.
function calCard(side,ox,oy){
  const tick=(x,y,w,h)=>`<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;background:#000"></div>`;
  let marks="";
  for(let mm=5;mm<86;mm+=5){ const len=mm%10?8:14; marks+=tick(mm*4,0,1,len)+tick(mm*4,216-len,1,len); }
  for(let mm=5;mm<54;mm+=5){ const len=mm%10?8:14; marks+=tick(0,mm*4,len,1)+tick(342.4-len,mm*4,len,1); }
  return `<div class="card" style="--card-bg:#fff;font:600 11px/1 Arial,sans-serif;color:#000">
    <div style="position:absolute;inset:0;border:1.2px solid #000;box-sizing:border-box"></div>${marks}
    ${tick(171,0,1,216)}${tick(0,108,342.4,1)}
    <div style="position:absolute;left:155px;top:92px;width:32px;height:32px;border:1.2px solid #000;border-radius:50%"></div>
    <div style="position:absolute;left:20px;top:20px">${side}</div>
    <div style="position:absolute;right:20px;top:20px">Calibración</div>
    <div style="position:absolute;left:20px;bottom:20px">X ${ox} mm · Y ${oy} mm</div>
    <div style="position:absolute;right:20px;bottom:20px">85.6 × 54 mm</div></div>`;
}
$("#cal-test").addEventListener("click",()=>withBusy(async()=>{
  const ox=parseFloat($("#off-x").value||0), oy=parseFloat($("#off-y").value||0);
  const ok=await runJob({frontHTML:calCard("FRENTE",ox,oy),backHTML:calCard("REVERSO",ox,oy),withK:false,templateId:null});
  if(ok) setStatus("Mide el borde impreso: si no cae en 85.6 × 54 mm, ajusta X e Y y repite.","ok");
}));

/* ---------- Estado de la impresora (encabezado) ---------- */
async function refreshPrinterChip(){
  const chip=$("#printer-chip");
  try{
    PRINTER_LIST=await api("/printers");
    const p=curPrinter();
    const txt={ready:"lista",busy:"imprimiendo",offline:"sin conexión",unknown:"estado desconocido"};
    chip.textContent=p?`${p.label}: ${txt[p.status]||p.status}`:"Sin impresora configurada (printers.yaml)";
    chip.dataset.state=p?p.status:"bad";
  }catch(e){
    chip.textContent=/API key/.test(e.message)?"API key inválida: pégala en Avanzado":"Sin conexión con el middleware";
    chip.dataset.state="bad";
  }
}
setInterval(()=>{ if(!busy && !document.hidden) refreshPrinterChip(); },30000);

/* ---------- Impresión vía middleware (API) ---------- */
const API_URL_KEY="carnet-api-url", API_KEY_KEY="carnet-api-key";
function apiBase(){
  return ($("#api-url").value.trim()||"").replace(/\/+$/,"");
}
function apiHeaders(){return {"X-API-Key":$("#api-key").value.trim()};}
function loadApiCfg(){
  let url="", key="";
  try{url=localStorage.getItem(API_URL_KEY)||""; key=localStorage.getItem(API_KEY_KEY)||"";}catch(e){ console.warn("localStorage no disponible:",e); }
  if(!url) url=location.protocol.startsWith("http")?location.origin:"http://localhost:8787";
  const BOOT=window.BOOT||{};
  if(BOOT.api_key) key=BOOT.api_key;      // abierta desde la PC del programa: ya viene la clave vigente
  if(KIOSK){ key=KIOSK.api_key||key; url=location.origin; }   // el kiosko no guarda la clave en el navegador
  $("#api-url").value=url; $("#api-key").value=key;
}
function saveApiCfg(){
  try{localStorage.setItem(API_URL_KEY,$("#api-url").value.trim());
      localStorage.setItem(API_KEY_KEY,$("#api-key").value.trim());}catch(e){ console.warn("No se pudo guardar la conexión:",e); }
}
$("#api-url").addEventListener("change",saveApiCfg);
$("#api-key").addEventListener("change",saveApiCfg);
$("#api-test").addEventListener("click",async()=>{
  saveApiCfg();
  try{
    const r=await fetch(apiBase()+"/printers",{headers:apiHeaders()});
    if(r.status===401) return setStatus("API key inválida.","bad");
    if(!r.ok) return setStatus("El middleware respondió "+r.status+".","bad");
    const list=await r.json();
    setStatus("Conectado: "+list.map(p=>`${p.label} (${p.status})`).join(" · "),"ok");
  }catch{setStatus("No se pudo conectar con "+apiBase()+" (¿está corriendo? ¿CORS?).","bad");}
});

// Cara → PNG 300 ppp al tamaño nativo de la impresora. SVG foreignObject: sin librerías,
// fiel al CSS de la vista previa. La tarjeta CSS (342.4 × 216) se escala para cubrir el
// lienzo (sangrado incluido) y se centra.
// layer "color": todo menos los textos .kblack; layer "k": solo los .kblack en negro puro
// sobre blanco, umbralizado a 1 bit (sin antialias) para que el driver los mande al panel K.
const LAYER_CSS={
  color:`.card .kblack{color:transparent!important}`,
  k:`.card,.card *{background:transparent!important;border-color:transparent!important;
       box-shadow:none!important;color:transparent!important;text-shadow:none!important}
     .card img,.card .seal{visibility:hidden!important}
     .card .kblack{color:#000!important}`
};
async function rasterizeFace(cardHTML,{rotate,ox,oy,w=CANVAS.w,h=CANVAS.h,layer="color"}){
  const css=[...document.styleSheets].flatMap(s=>[...s.cssRules]).map(r=>r.cssText).join("\n");
  const scale=Math.max(w/342.4,h/216);
  const dx=(w-342.4*scale)/2, dy=(h-216*scale)/2;
  const holder=document.createElement("div");
  holder.setAttribute("style",`width:342.4px;height:216px;transform:translate(${dx}px,${dy}px) scale(${scale});
    transform-origin:top left;--card-ink:#111418`);
  holder.innerHTML=`<style>${css}\n${LAYER_CSS[layer]||""}</style>${cardHTML}`;
  const xhtml=new XMLSerializer().serializeToString(holder);   // XHTML bien formado (<img/> etc.)
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">`+
    `<foreignObject width="100%" height="100%">${xhtml}</foreignObject></svg>`;
  const image=new Image();
  image.src="data:image/svg+xml;charset=utf-8,"+encodeURIComponent(svg);
  await image.decode();
  const c=document.createElement("canvas"); c.width=w; c.height=h;
  const g=c.getContext("2d");
  g.fillStyle="#fff"; g.fillRect(0,0,w,h);
  const pxmm=300/25.4;
  g.save();
  if(rotate){g.translate(w/2,h/2); g.rotate(Math.PI); g.translate(-w/2,-h/2);}
  g.translate(ox*pxmm,oy*pxmm);
  g.drawImage(image,0,0,w,h);
  g.restore();
  if(layer==="k"){
    const d=g.getImageData(0,0,w,h), px=d.data;
    for(let i=0;i<px.length;i+=4){
      const v=(0.299*px[i]+0.587*px[i+1]+0.114*px[i+2])<150?0:255;
      px[i]=px[i+1]=px[i+2]=v; px[i+3]=255;
    }
    g.putImageData(d,0,0);
  }
  return new Promise((res,rej)=>c.toBlob(b=>b?res(b):rej(new Error("No se pudo generar la imagen")),"image/png"));
}

// Genera los PNG de las caras, los manda a imprimir y espera a que la tarjeta salga.
// Devuelve true si se imprimió; si no, deja el motivo en la barra de estado.
async function runJob({frontHTML,backHTML,control=null,withK=true,templateId=CUR_TPL}){
  const printer=curPrinter();
  if(!printer){ setStatus("No hay impresora configurada en printers.yaml.","bad"); return false; }
  const rot=$("#opt-rotate").checked;
  const ox=parseFloat($("#off-x").value||0), oy=parseFloat($("#off-y").value||0);
  try{
    setStatus("Generando imágenes y enviando al middleware…","warn");
    const {w,h}=CANVAS;
    const face=(html,rotate,layer)=>rasterizeFace(html,{rotate,ox,oy,w,h,layer});
    const [front,back]=await Promise.all([face(frontHTML,false,"color"),face(backHTML,rot,"color")]);
    const fd=new FormData();
    fd.append("printer_id",printer.id);
    if(templateId) fd.append("template_id",templateId);   // si no, el API usa la plantilla activa
    if(control) fd.append("control",control);              // nombra la carpeta de PNG
    fd.append("front",front,"front.png"); fd.append("back",back,"back.png");
    if(withK){
      // Capa negra aparte (1 bit, mismo tamaño): el puente la imprime por el panel K
      const [frontK,backK]=await Promise.all([face(frontHTML,false,"k"),face(backHTML,rot,"k")]);
      fd.append("front_k",frontK,"front_k.png"); fd.append("back_k",backK,"back_k.png");
    }
    // Sin «options» el servidor usa las de «Avanzado» (calidad, tolva, split ribbon): las mismas que la línea de comandos
    await flushSettings();   // un ajuste cambiado hace un instante debe estar guardado antes de imprimir
    const r=await fetch(apiBase()+"/jobs",{method:"POST",headers:apiHeaders(),body:fd});
    if(r.status===401){ setStatus("API key inválida (abre «Avanzado» > Conexión).","bad"); return false; }
    if(!r.ok){const e=await r.json().catch(()=>({})); setStatus("Error del middleware: "+(e.detail||r.status),"bad"); return false;}
    let job=await r.json();
    const pngDir=job.png_dir;   // solo viene en la respuesta del POST
    const label=printer.label, t0=Date.now();
    // Con SDK (Entrust) el trabajo sigue en cola hasta que la tarjeta sale: 30-60 s por carnet.
    while(job.state==="queued" && Date.now()-t0<6*60*1000){
      setStatus(`Imprimiendo en ${label}… ${Math.round((Date.now()-t0)/1000)} s`,"warn");
      await new Promise(ok=>setTimeout(ok,1000));
      job=await (await fetch(apiBase()+"/jobs/"+job.id,{headers:apiHeaders()})).json();
    }
    if(job.state==="failed"){ setStatus("La impresión falló: "+(job.error||"error"),"bad"); return false; }
    if(job.state==="queued"){ setStatus(`Sigue en cola en ${label} tras 6 min: revisa la impresora.`,"bad"); return false; }
    setStatus((job.state==="printed"
      ? `Impreso en ${label} (trabajo ${job.backend_job_id||job.id}).`
      : `Enviado a ${label} (trabajo ${job.backend_job_id||job.id}).`)+
      (pngDir?` PNG guardados en png/${pngDir}.`:""),"ok");
    return true;
  }catch(err){
    setStatus("No se pudo imprimir: "+(err&&err.message||err),"bad");
    return false;
  }
}
async function printCard(card){
  const now={...img}; Object.assign(img, card.img||img);   // imágenes del carnet guardado
  const frontHTML=cardFrontHTML(card.tpl,card.data), backHTML=cardBackHTML(card.tpl,card.data);
  Object.assign(img, now);
  const ok=await runJob({frontHTML,backHTML,control:card.control!=="—"?card.control:null,templateId:card.templateId||CUR_TPL});
  if(ok){
    const wasEditing=!!EDITING;
    if(wasEditing){ EDITING=null; updateEditUI(); resetTitularFields(); render(); await restoreDraft(); }   // vuelve lo que se estaba llenando
    else{
      clearDraft();   // impreso: el borrador ya no hace falta
      if(KIOSK) clearTitular();   // listo para la siguiente persona
    }
  }
}

/* ---------- Generar ---------- */
let busy=false;
function setBusy(b){ busy=b; ["generate","preview-print"].forEach(id=>$("#"+id).disabled=b); }
// Una tarjeta física no se deshace: mientras hay un trabajo en curso no se acepta otro clic.
async function withBusy(fn){ if(busy) return; setBusy(true); try{ await fn(); } finally{ setBusy(false); refreshPrinterChip(); } }
// mode: "new" emite un carnet nuevo · "edit" corrige el que se está editando (mismo control) · "none" solo imprime
async function generate(mode){ return withBusy(()=>generateNow(mode)); }
async function generateNow(mode){
  const d=data(), t=tpl();
  if(!d.name.trim()){setStatus("Falta el nombre del titular.","bad");return;}
  if(digits(d.ced).length===11 && !validCed(d.ced)){
    if(!confirm("La cédula no pasa el dígito verificador. ¿Generar de todos modos?")) return;
  }
  const imgs={logo1:img.logo1,logo2:img.logo2,seal:img.seal,sign:img.sign,photo:img.photo};
  let card;
  if(mode==="edit"){
    const {control,templateId}=EDITING;
    // Corrige el MISMO carnet (control y código no cambian; lo anterior queda en su historial) y lo reimprime
    const updated=await jsonPatch("/cards/"+encodeURIComponent(control),{tpl:t,data:d,img:imgs,templateId});
    $("#d-code").value=updated.data.code; render();
    await jsonPost(`/cards/${encodeURIComponent(control)}/reprint`,{});
    card={...updated,img:imgs};
    setStatus(`Carnet ${control} corregido; imprimiendo con los datos nuevos.`,"ok");
    if(canSeeRegistry) await renderRegistry();
  }else if(mode==="new"){
    if(canSeeRegistry){   // aviso si ya hay carnet vigente con esa cédula
      const existing=(await getAll()).find(c=>digits(c.data.ced)===digits(d.ced) && statusOf(c)==="vig");
      if(existing && !confirm(`La cédula ${d.ced} ya tiene un carnet vigente (${existing.control}). ¿Emitir otro?`)) return;
    }
    // El servidor asigna control y código (no se pisan carnets si hay varios kioskos a la vez)
    const created=await jsonPost("/cards",{tpl:t,data:d,img:imgs,templateId:EDITING?EDITING.templateId:CUR_TPL});
    $("#d-code").value=created.data.code; render();
    card={...created,img:imgs};
    setStatus(`Carnet ${created.control} registrado.`,"ok");
    if(canSeeRegistry) await renderRegistry();
  }else{
    card={control:"—",tpl:t,data:d,img:imgs};
    setStatus("Impresión sin registrar.","warn");
  }
  await printCard(card);
}
$("#generate").addEventListener("click",()=>generate(EDITING?"edit":"new"));
$("#preview-print").addEventListener("click",()=>generate("none"));

/* ---------- Editar un carnet ya emitido ---------- */
function updateEditUI(){
  const banner=$("#edit-banner");
  banner.hidden=!EDITING;
  if(EDITING) $("#edit-text").textContent=`Estás corrigiendo el carnet ${EDITING.control}: los cambios se guardan en ese mismo carnet (control y código no cambian).`;
  $("#generate").textContent=EDITING?"Guardar cambios e imprimir":(KIOSK?"Generar e imprimir":"Generar, registrar e imprimir");
}
async function editCard(control){
  if(busy) return;
  try{
    const card=await getCard(control);
    if(card.voided){ setStatus(`El carnet ${control} está anulado y no se puede editar: emite uno nuevo.`,"warn"); return; }
    try{ await flushDraft(); }catch(e){ console.warn("No se pudo guardar el borrador antes de editar:",e); }   // lo que se estaba llenando no se pierde
    clearTimeout(autosaveTimer); clearTimeout(draftTimer);
    EDITING={control,templateId:card.templateId||null};   // desde aquí nada de lo que se cargue pisa el borrador
    if(!KIOSK){ CUR_TPL=null; renderTplSelect(); applyTpl({...card.tpl,img:card.img}); }   // el diseño con el que se emitió
    resetTitularFields();
    const d=card.data;
    $("#d-name").value=d.name||""; $("#d-ced").value=d.ced||""; $("#d-code").value=d.code||"";
    $("#d-cat").value=d.cat||""; $("#d-extra").value=d.extra||""; $("#d-issue").value=d.issue||todayISO();
    setImg("photo",card.img&&card.img.photo);
    $("#d-ced").dispatchEvent(new Event("input"));
    updateEditUI(); render();
    $("#pv-front").scrollIntoView({behavior:"smooth",block:"center"});
    setStatus(`Carnet ${control} cargado: corrige lo que haga falta y pulsa «Guardar cambios e imprimir».`,"ok");
  }catch(e){ EDITING=null; updateEditUI(); setStatus("No se pudo cargar el carnet: "+e.message,"bad"); }
}
$("#edit-cancel").addEventListener("click",async()=>{
  EDITING=null; updateEditUI(); resetTitularFields();
  if(!(await restoreDraft())) render();   // vuelve lo que se estaba llenando antes
  setStatus("Edición cancelada: no se cambió nada.","ok");
});
$("#edit-as-new").addEventListener("click",()=>generate("new").then(()=>{ EDITING=null; updateEditUI(); }));

/* reimprimir / anular / buscar */
$("#reg-body").addEventListener("click",async e=>{
  const rp=e.target.dataset.reprint, vd=e.target.dataset.void;
  if(!rp && !vd){   // clic en la fila: se carga el carnet para corregirlo
    const row=e.target.closest("tr[data-edit]");
    if(row) await editCard(row.dataset.edit);
    return;
  }
  try{
    if(rp) await withBusy(async()=>{
      const full=await getCard(rp);   // el registro liviano no trae las imágenes
      await jsonPost("/cards/"+encodeURIComponent(rp)+"/reprint",{});
      await renderRegistry();
      await printCard(full);
    });
    if(vd){
      if(!confirm(`¿Anular el carnet ${vd}? No se podrá revertir.`)) return;
      await jsonPost("/cards/"+encodeURIComponent(vd)+"/void",{});
      await renderRegistry();
    }
  }catch(err){ setStatus("No se pudo completar la acción: "+err.message,"bad"); }
});
$("#reg-q").addEventListener("input",renderRegistry);

/* ---------- Buscar por cédula y precargar ---------- */
async function lookup(ced){
  const matches=(await getAll()).filter(c=>digits(c.data.ced)===digits(ced)).sort((a,b)=>b.control.localeCompare(a.control));
  if(!matches.length){setStatus("No hay carnet registrado con esa cédula.","warn");return;}
  const c=await getCard(matches[0].control), d=c.data;
  clearTimeout(autosaveTimer); CUR_TPL=null; renderTplSelect();
  $("#d-name").value=d.name; $("#d-ced").value=d.ced; $("#d-code").value=d.code;
  $("#d-cat").value=d.cat; $("#d-extra").value=d.extra||""; $("#d-issue").value=d.issue;
  applyTpl({...c.tpl,img:c.img});          // diseño e imágenes del carnet
  setImg("photo",c.img&&c.img.photo);
  setStatus(`Datos de ${c.control} cargados.`,"ok");
}
// «Continuar desde el último»: los datos del último carnet emitido, listos para el siguiente.
// El código queda vacío (el servidor asigna uno nuevo) y la emisión es hoy.
$("#last-btn").addEventListener("click",async()=>{
  try{
    const c=await api("/cards/last"), d=c.data;
    ["d-name","d-ced","d-code","d-cat","d-extra"].forEach(id=>$("#"+id).value="");
    fillTitular({name:d.name,ced:d.ced,cat:d.cat,extra:d.extra,photo:c.img&&c.img.photo});
    $("#d-issue").value=todayISO();
    draftDirty=true; render();
    setStatus(`Datos de ${c.control} cargados; el código y la fecha son nuevos.`,"ok");
  }catch(e){ setStatus("No se pudo cargar el último carnet: "+e.message,"warn"); }
});
$("#lookup-btn").addEventListener("click",()=>lookup($("#lookup-ced").value));
$("#clear-titular").addEventListener("click",()=>{ clearTitular(); setStatus("Titular limpio.","ok"); });
$("#lookup-ced").addEventListener("input",e=>e.target.value=fmtCed(e.target.value));

/* ---------- Export / import ---------- */
$("#exp-csv").addEventListener("click",async()=>{
  const all=(await getAll()).sort((a,b)=>a.control.localeCompare(b.control));
  const head=["Control","Generado","Titular","Cedula","Codigo","Categoria","Organizacion","Emision","Expira","Impresiones","Estado"];
  const lines=all.map(c=>{
    const st={vig:"Vigente",ven:"Vencido",anu:"Anulado"}[statusOf(c)];
    return [c.control,new Date(c.createdAt).toISOString(),c.data.name,c.data.ced,c.data.code,
      c.data.cat,c.tpl.org,c.data.issue,c.data.expiry,c.prints||1,st]
      .map(v=>`"${String(v??"").replace(/"/g,'""')}"`).join(",");
  });
  download("registro-carnets.csv","text/csv",[head.join(","),...lines].join("\n"));
});
$("#exp-json").addEventListener("click",async()=>{
  const all=await api("/cards?full=true");
  download("respaldo-carnets.json","application/json",JSON.stringify({version:1,cards:all},null,2));
});
$("#imp-json").addEventListener("change",async e=>{
  const f=e.target.files[0]; if(!f) return;
  try{
    const obj=JSON.parse(await f.text()); const cards=obj.cards||obj;
    if(!Array.isArray(cards)) throw new Error("no es un respaldo de carnets");
    const failed=[];
    for(const c of cards){
      try{ await jsonPut("/cards/"+encodeURIComponent(c.control),c); }
      catch(err){ failed.push(`${c.control}: ${err.message}`); }
    }
    await renderRegistry();
    setStatus(failed.length
      ? `Restaurados ${cards.length-failed.length} de ${cards.length}. Falló ${failed[0]}`
      : `Restaurados ${cards.length} registros.`, failed.length?"warn":"ok");
  }catch(err){ setStatus("Archivo de respaldo no válido: "+err.message,"bad"); }
  finally{ e.target.value=""; }
});
function download(name,type,content){
  const blob=new Blob([content],{type}); const url=URL.createObjectURL(blob);
  const a=document.createElement("a"); a.href=url; a.download=name; a.click();
  URL.revokeObjectURL(url);
}

/* ---------- Versión del programa (GET /health) ---------- */
async function showVersion(){
  try{
    const r=await fetch(apiBase()+"/health");
    const {version}=await r.json();
    const el=$("#app-version"); el.textContent=version; el.hidden=false;
  }catch(e){ console.warn("No se pudo leer la versión:",e); }
}

/* ---------- Requisitos de la PC (/preflight): qué falta instalar y dónde bajarlo ---------- */
async function loadPreflight(){
  const box=$("#preflight");
  try{
    const r=await fetch(apiBase()+"/preflight");
    const problems=r.ok?await r.json():[];
    box.hidden=!problems.length;
    box.innerHTML=problems.length?`<h2>Falta algo para poder imprimir</h2><ul>`+problems.map(p=>
      `<li><b>${esc(p.title)}</b>: ${esc(p.detail)}${p.url?` <a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url_label||"Descargar")}</a>`:""}</li>`).join("")+
      `</ul><button class="btn sm" id="preflight-retry" type="button">Volver a comprobar</button>`:"";
    const b=$("#preflight-retry"); if(b) b.addEventListener("click",loadPreflight);
  }catch(e){ console.warn("No se pudo consultar /preflight:",e); }
}

/* ---------- Editor del layout: campos, márgenes y JSON ---------- */
const MARGIN_FIELDS=[["top","Superior"],["right","Derecho"],["bottom","Inferior"],["left","Izquierdo"]];
const FIELD_ROWS=[["name","Nombre"],["ced","Cédula"],["cat","Categoría"],["extra","Dato extra"]];
const FOOTER_ROWS=[["issue","Emisión"],["expiry","Expiración"],["code","Código"]];
const FIT_OPTIONS=[["clip","Cortar con …"],["shrink","Achicar la letra"],["wrap","Varias líneas"]];
const pid=path=>"lay-"+path.replace(/\./g,"-");
const numInput=(path,min,max,step=0.5)=>`<input type="number" id="${pid(path)}" data-path="${path}" min="${min}" max="${max}" step="${step}">`;
function buildLayoutEditor(){
  const box=$("#layout-form"); if(!box) return;
  const margins=(side,title)=>`<div class="field"><span>${title} (px)</span><div class="grid4">`+
    MARGIN_FIELDS.map(([k,l])=>`<label class="mini"><span>${l}</span>${numInput(`${side}.margins.${k}`,0,40)}</label>`).join("")+`</div></div>`;
  box.innerHTML=
    margins("front","Márgenes del frente")+
    `<div class="grid3"><label class="field"><span>Ancho de la foto</span>${numInput("front.photo.width",40,140,1)}</label>
       <label class="field"><span>Alto de la foto</span>${numInput("front.photo.height",50,170,1)}</label>
       <label class="field"><span>Espacio foto-texto</span>${numInput("front.gap",0,30)}</label></div>`+
    margins("back","Márgenes del reverso")+
    `<div class="table-wrap lay-table"><table><thead><tr><th>Campo</th><th>Rótulo</th><th>Tamaño</th><th>Negrita</th><th>Si no cabe</th><th>Líneas</th><th>Mínimo</th></tr></thead><tbody>`+
    FIELD_ROWS.map(([k,l])=>`<tr><td>${l}</td>
      <td><input type="text" id="${pid(`front.fields.${k}.label`)}" data-path="front.fields.${k}.label" maxlength="40"></td>
      <td>${numInput(`front.fields.${k}.size`,6,24)}</td>
      <td><input type="checkbox" id="${pid(`front.fields.${k}.bold`)}" data-path="front.fields.${k}.bold"></td>
      <td><select id="${pid(`front.fields.${k}.fit`)}" data-path="front.fields.${k}.fit">${FIT_OPTIONS.map(([v,t])=>`<option value="${v}">${t}</option>`).join("")}</select></td>
      <td>${numInput(`front.fields.${k}.maxLines`,1,4,1)}</td>
      <td>${numInput(`front.fields.${k}.minSize`,5,20)}</td></tr>`).join("")+
    FOOTER_ROWS.map(([k,l])=>`<tr><td>${l}</td>
      <td><input type="text" id="${pid(`front.footer.${k}.label`)}" data-path="front.footer.${k}.label" maxlength="40"></td>
      <td>${numInput(`front.footer.${k}.size`,6,24)}</td>
      <td><input type="checkbox" id="${pid(`front.footer.${k}.bold`)}" data-path="front.footer.${k}.bold"></td><td colspan="3"></td></tr>`).join("")+
    `</tbody></table></div>`;
  refreshLayoutEditor();
}
function refreshLayoutEditor(){
  $$("#layout-form [data-path]").forEach(el=>{
    const v=getPath(layoutState,el.dataset.path);
    if(el.type==="checkbox") el.checked=!!v; else el.value=v??"";
  });
  const t=$("#layout-json-text"); if(t) t.value=JSON.stringify(layoutState,null,2);
}
$("#layout-form").addEventListener("input",e=>{
  const el=e.target.closest("[data-path]"); if(!el) return;
  let v=el.type==="checkbox"?el.checked:el.value;
  if(el.type==="number"){ v=parseFloat(v); if(Number.isNaN(v)) return; }
  layoutState=setPath(layoutState,el.dataset.path,v);
  $("#layout-json-text").value=JSON.stringify(layoutState,null,2);
  render();
});
$("#layout-json-btn").addEventListener("click",()=>{ const box=$("#layout-json"); box.hidden=!box.hidden; });
$("#layout-reset").addEventListener("click",()=>{
  layoutState=resolveLayout({}); refreshLayoutEditor(); render();
  $("#layout-json-msg").textContent="Valores por defecto restaurados."; $("#layout-json-msg").className="validmsg ok";
});
$("#layout-json-apply").addEventListener("click",async()=>{
  const msg=$("#layout-json-msg"), previous=layoutState;
  try{
    const parsed=JSON.parse($("#layout-json-text").value);
    if(parsed===null||typeof parsed!=="object"||Array.isArray(parsed)) throw new Error("debe ser un objeto JSON");
    layoutState=resolveLayout(parsed); refreshLayoutEditor(); render();
    if(CUR_TPL) await putTpl(CUR_TPL,TPLS[CUR_TPL]?.name||CUR_TPL);   // el servidor valida rangos y claves
    msg.textContent="Layout aplicado y guardado."; msg.className="validmsg ok";
  }catch(err){
    layoutState=previous; refreshLayoutEditor(); render();
    msg.textContent="No se aplicó: "+err.message; msg.className="validmsg bad";
  }
});
buildLayoutEditor();

/* ---------- Clientes (modo kiosko): perfiles en clients.json ---------- */
let CLIENTS={};
function renderClients(){
  const sel=$("#cl-select");
  sel.innerHTML='<option value="">+ Nuevo perfil</option>'+Object.entries(CLIENTS).map(([id,c])=>
    `<option value="${esc(id)}">${esc(c.name)}</option>`).join("");
  $("#cl-tpl").innerHTML=Object.entries(TPLS).map(([id,t])=>`<option value="${esc(id)}">${esc(t.name||id)}</option>`).join("");
  fillClientForm(sel.value);
}
function fillClientForm(id){
  const c=CLIENTS[id]||{name:"",template_id:ACTIVE_TPL||CUR_TPL||"",editable:["name","ced","cat"],show_registry:false};
  $("#cl-select").value=id; $("#cl-name").value=c.name; $("#cl-tpl").value=c.template_id;
  $$("#cl-fields input").forEach(cb=>cb.checked=c.editable.includes(cb.value));
  $("#cl-registry").checked=!!c.show_registry;
  const url=id?`${location.origin}/c/${id}`:"";
  $("#cl-link").innerHTML=id
    ? `Abrir: <a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a><br>o con el programa: <code>CarnetPrint.exe --client ${esc(id)}</code>`
    : "Guarda el perfil para obtener su enlace.";
  $("#cl-del").hidden=!id;
}
$("#cl-select").addEventListener("change",e=>fillClientForm(e.target.value));
$("#cl-save").addEventListener("click",async()=>{
  const name=$("#cl-name").value.trim(); if(!name) return setStatus("Falta el nombre del cliente.","bad");
  const id=$("#cl-select").value||slug(name); if(!id) return setStatus("Nombre no válido.","bad");
  const body={name,template_id:$("#cl-tpl").value,show_registry:$("#cl-registry").checked,
    editable:$$("#cl-fields input:checked").map(cb=>cb.value)};
  try{
    CLIENTS[id]=await jsonPut("/clients/"+encodeURIComponent(id),body);
    renderClients(); $("#cl-select").value=id; fillClientForm(id);
    setStatus(`Perfil «${name}» guardado.`,"ok");
  }catch(e){ setStatus("No se pudo guardar el perfil: "+e.message,"bad"); }
});
$("#cl-del").addEventListener("click",async()=>{
  const id=$("#cl-select").value; if(!id||!confirm(`¿Eliminar el perfil «${CLIENTS[id]?.name||id}»?`)) return;
  try{ await api("/clients/"+encodeURIComponent(id),{method:"DELETE"}); delete CLIENTS[id]; renderClients(); setStatus("Perfil eliminado.","ok"); }
  catch(e){ setStatus("No se pudo eliminar: "+e.message,"bad"); }
});

/* ---------- Modo kiosko: plantilla fija y solo los campos permitidos ---------- */
function setupKiosk(){
  document.title=KIOSK.name;
  $("header.app h1").textContent=KIOSK.name;
  if(!KIOSK.show_registry) $("#registry").hidden=true;
  if(!EDITABLE.has("photo")) $("#photo-asset").hidden=true;
  if(!EDITABLE.has("ced")) $("#lookup-field").hidden=true;
  ["extra","issue"].forEach(f=>{ if(!EDITABLE.has(f)) $("#"+FIELD_INPUT[f]).disabled=true; });
  $("#generate").textContent="Generar e imprimir";
}

/* ---------- Init ---------- */
(async()=>{
  loadApiCfg();
  loadPreflight();
  showVersion();
  if(KIOSK){
    if(!$("#api-key").value){   // abierto desde otra PC: el servidor no entrega la clave
      const k=prompt("API key de CarnetPrint (está en el archivo .env junto al .exe):");
      if(k) $("#api-key").value=k.trim();
    }
    setupKiosk();
  }
  render();   // la tarjeta se dibuja aunque el middleware no responda
  try{
    await loadSettings();
    $("#adv-quality").value=SETTINGS.quality; $("#adv-hopper").value=SETTINGS.hopper;
    await loadPrinters();
  }catch(e){ setStatus("No se pudieron leer los ajustes o las impresoras: "+e.message,"warn"); }
  applyPrinter();
  if(await restoreDraft()) setStatus("Se recuperó el carnet que estabas llenando.","ok");
  try{
    await refreshTemplates();
    if(KIOSK){
      if(!TPLS[KIOSK.template_id]) throw new Error("la plantilla de este cliente ya no existe");
      CUR_TPL=KIOSK.template_id;          // fija; tplReady sigue en false: no se autoguarda nada
      applyTpl(TPLS[CUR_TPL]);
    }else{
        if(CUR_TPL) applyTpl(TPLS[CUR_TPL]);
      tplReady=true;
      CLIENTS=await api("/clients"); renderClients();
    }
    if(canSeeRegistry) await renderRegistry();
  }
  catch(e){
    setStatus("Sin conexión con el middleware ("+e.message+").","warn");
    if(!KIOSK){
      $("#advanced").open=true;   // ahí está la URL y la API key
      if(/API key/.test(e.message)) $("#api-key").focus();
    }
  }
})();
$("#open-adv").addEventListener("click",()=>{ $("#advanced").open=true; });
})();
$("#reg-body").addEventListener("keydown",e=>{
  const row=e.target.closest("tr[data-edit]");
  if(row && e.key==="Enter" && e.target===row){ e.preventDefault(); editCard(row.dataset.edit); }
});
