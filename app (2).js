const $ = (selector) => document.querySelector(selector);
const DAY = 86400000;
const today = new Date(); today.setHours(0,0,0,0);
let selectedDate = new Date(today);
const palettes = ['blue','green','orange'];
const demoCategories = [
  {name:'PRONOS 1',tag:'SÉLECTION 01',description:'Une première sélection de rencontres.',matches:[['Lions FC','United Stars','Ligue de démonstration','Victoire domicile','1.55','16:00'],['Riverside','Olympique Nord','Coupe de démonstration','Plus de 1,5 buts','1.42','19:30'],['Harbor City','Eastern Wolves','Ligue de démonstration','Victoire extérieur','1.90','20:00'],['North Rovers','Delta FC','Championnat de démonstration','Match nul ou victoire domicile','1.33','21:00']]},
  {name:'PRONOS 2',tag:'SÉLECTION 02',description:'Une deuxième sélection de rencontres.',matches:[['Atlantic SC','Mountain FC','Championnat de démonstration','Les deux équipes marquent','1.70','15:00'],['City Athletic','Royal Blue','Ligue de démonstration','Double chance 1X','1.38','18:00'],['Falcons FC','Union Sud','Coupe de démonstration','Plus de 2,5 buts','1.75','20:45']]},
  {name:'PRONOS 3',tag:'SÉLECTION 03',description:'Une troisième sélection de rencontres.',matches:[['Green Valley','Capital FC','Coupe de démonstration','Moins de 3,5 buts','1.48','14:30'],['Sporting East','West Rangers','Championnat de démonstration','Plus de 2,5 buts','1.85','17:00'],['Red Stars','Blue Harbor','Ligue de démonstration','Victoire domicile','1.60','19:00'],['Oakland FC','Pearl City','Ligue de démonstration','Les deux équipes marquent','1.72','21:00']]}
];

// ---- Fiche Google Sheets « Tickets » ----
// Lien de la fiche (CSV). Laissé vide = données de démonstration.
const SHEET_URL = 'https://docs.google.com/spreadsheets/d/1F5eWYYynORK2nOSKEPjAsnjekF3HbVQ0l6WsXRQRIwg/gviz/tq?tqx=out:csv&headers=1&sheet=Tickets';
let tickets = null, sheetState = SHEET_URL ? 'loading' : 'demo';
function parseCSV(text){
  const rows=[]; let row=[], cell='', quoted=false;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(quoted){ if(c==='"'){ if(text[i+1]==='"'){cell+='"';i++} else quoted=false } else cell+=c }
    else if(c==='"') quoted=true;
    else if(c===','){ row.push(cell); cell='' }
    else if(c==='\n'||c==='\r'){ if(c==='\r'&&text[i+1]==='\n') i++; row.push(cell); rows.push(row); row=[]; cell='' }
    else cell+=c;
  }
  if(cell!==''||row.length){ row.push(cell); rows.push(row) }
  return rows;
}
function toDateKey(v){
  v=String(v||'').trim();
  let m=v.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/); if(m) return `${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
  m=v.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})/); if(m) return `${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
  m=v.match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})/); if(m) return `${m[3]}-${m[2].padStart(2,'0')}-${m[1].padStart(2,'0')}`;
  m=v.match(/^Date\((\d{4}),(\d{1,2}),(\d{1,2})/); if(m) return `${m[1]}-${String(Number(m[2])+1).padStart(2,'0')}-${m[3].padStart(2,'0')}`;
  return '';
}
// Lecture par position de colonne : A Date, B Type de Case, C Statut global, puis Match / Prono / Cote 1 à 4 (D à O)
function rowsToTickets(rows){
  return rows.map(r=>{
    const cell=i=>String(r[i]==null?'':r[i]).trim();
    const date=toDateKey(cell(0)); if(!date) return null;
    const matches=[];
    for(let k=0;k<4;k++){
      const label=cell(3+k*3); if(!label) continue;
      const parts=label.split(/\s+-\s+/);
      matches.push({home:parts[0],away:parts.slice(1).join(' - '),pick:cell(4+k*3),odds:cell(5+k*3)});
    }
    return {date,type:Number((cell(1).match(/\d+/)||[''])[0]),status:cell(2),matches};
  }).filter(Boolean);
}
let debugInfo='';
async function loadSheet(){
  if(!SHEET_URL) return;
  try{
    const res=await fetch(SHEET_URL,{cache:'no-store'});
    if(!res.ok) throw new Error('HTTP '+res.status);
    const text=await res.text();
    if(/^\s*</.test(text)) throw new Error('La fiche renvoie une page web (accès non public ?)');
    const rows=parseCSV(text);
    tickets=rowsToTickets(rows); sheetState='ready';
    debugInfo=`Fiche lue : ${rows.length} lignes, ${tickets.length} pronostics reconnus.\nDates reconnues : ${[...new Set(tickets.map(t=>t.date))].join(', ')||'aucune'}\nJour affiché : ${dateKey(selectedDate)}\nPremière ligne reçue : ${(rows[0]||[]).slice(0,5).join(' | ')}\nDeuxième ligne reçue : ${(rows[1]||[]).slice(0,5).join(' | ')}`;
  }catch(err){ console.info('Fiche Google Sheets indisponible',err); sheetState='error'; debugInfo='Erreur : '+err.message }
  renderCards();
  if(/[?&]debug/.test(location.search)){ let box=$('#debugBox'); if(!box){box=document.createElement('pre');box.id='debugBox';box.style.cssText='white-space:pre-wrap;word-break:break-all;background:#fff;color:#14233c;font-size:12px;padding:12px;margin:12px;border:1px solid #ccc;border-radius:8px';document.body.appendChild(box)} box.textContent=debugInfo }
}
const ordinals=['première','deuxième','troisième'];
function categoriesForDay(){
  if(sheetState==='demo') return demoCategories.map(c=>({...c,matches:c.matches.map(m=>({home:m[0],away:m[1],league:m[2],pick:m[3],odds:m[4],time:m[5]}))}));
  const key=dateKey(selectedDate);
  return [1,2,3].map(n=>{
    const t=tickets&&tickets.find(x=>x.date===key&&x.type===n);
    const base={name:'PRONOS '+n,tag:'SÉLECTION 0'+n,status:t?t.status:'',matches:t?t.matches:[]};
    if(sheetState==='loading') return {...base,description:'Chargement des pronostics…'};
    if(sheetState==='error') return {...base,description:'Pronostics momentanément indisponibles.'};
    if(!t||!t.matches.length) return {...base,description:'Aucun pronostic publié pour ce jour.'};
    const c=t.matches.length;
    return {...base,description:`${c} match${c>1?'s':''} au programme${t.status?' · '+t.status:''}`};
  });
}
const dateFmt = new Intl.DateTimeFormat('fr-FR',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
const shortFmt = new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'});
function dateKey(date){return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`}
function dayOffset(){return Math.round((selectedDate-today)/DAY)}
function updateDate(){
  const offset=dayOffset();
  $('#dateLabel').textContent=dateFmt.format(selectedDate);
  $('#dateHint').textContent=offset===0?'Pronostics et résultats du jour':offset<0?`Archives — il y a ${Math.abs(offset)} jour${Math.abs(offset)>1?'s':''}`:`Prévisions — dans ${offset} jour${offset>1?'s':''}`;
  $('#prevBtn').disabled=offset<=-10; $('#nextBtn').disabled=offset>=2;
  $('#rangeProgress').style.width=`${((offset+10)/12)*100}%`;
  renderCards();
}
function renderCards(){
  $('#selectionGrid').innerHTML=categoriesForDay().map((item,i)=>`<button class="selection-card" data-category="${i}" aria-label="Ouvrir ${item.name}"><span class="card-banner ${palettes[i]}" data-number="0${i+1}"><strong>${item.name}</strong></span><span class="card-body"><span class="card-kicker">${item.tag}</span><p>${item.description}</p><span class="card-bottom">Consulter la sélection <span class="card-arrow">→</span></span></span></button>`).join('');
  document.querySelectorAll('[data-category]').forEach(card=>card.addEventListener('click',()=>openCategory(Number(card.dataset.category))));
}
function openCategory(index){
  const item=categoriesForDay()[index]; $('#dialogEyebrow').textContent=item.tag; $('#dialogTitle').textContent=item.name;
  $('#dialogDate').textContent=dateFmt.format(selectedDate)+(item.status?' · '+item.status:'');
  const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  $('#matchList').innerHTML=item.matches.length?item.matches.map(m=>`<article class="match-card">${m.league||m.time?`<div class="match-meta"><span>${esc(m.league)}</span><span>${esc(m.time)}</span></div>`:''}<div class="match-teams"><span>${esc(m.home)}</span><span>VS</span><span>${esc(m.away)}</span></div><div class="match-pick"><span>Pronostic : <strong>${esc(m.pick)}</strong></span>${m.odds?`<strong>Cote ${esc(m.odds)}</strong>`:''}</div></article>`).join(''):`<p class="empty-note">${esc(item.description)}</p>`;
  $('#contentDialog').showModal();
}
$('#prevBtn').addEventListener('click',()=>{if(dayOffset()>-10){selectedDate=new Date(selectedDate.getTime()-DAY);updateDate()}});
$('#nextBtn').addEventListener('click',()=>{if(dayOffset()<2){selectedDate=new Date(selectedDate.getTime()+DAY);updateDate()}});
$('#todayBtn').addEventListener('click',()=>{selectedDate=new Date(today);updateDate()});
$('#closeDialog').addEventListener('click',()=>$('#contentDialog').close());
$('#contentDialog').addEventListener('click',e=>{if(e.target===$('#contentDialog'))$('#contentDialog').close()});
const info={privacy:['Politique de confidentialité','Cette page sera complétée avant la mise en production pour expliquer quelles données sont collectées, pourquoi elles le sont et comment exercer vos droits.'],legal:['Mentions légales','Les coordonnées de l’éditeur et de l’hébergeur seront ajoutées avant la publication officielle.'],terms:['Conditions d’utilisation','Les conditions d’utilisation seront publiées avant l’ouverture publique de Goal4win.']};
[['privacyLink','privacy'],['legalLink','legal'],['termsLink','terms']].forEach(([id,key])=>{$('#'+id).addEventListener('click',e=>{e.preventDefault();$('#infoTitle').textContent=info[key][0];$('#infoText').textContent=info[key][1];$('#infoDialog').showModal()})});
$('#closeInfo').addEventListener('click',()=>$('#infoDialog').close());
$('#year').textContent=new Date().getFullYear();
updateDate();
loadSheet();
if('serviceWorker' in navigator && location.protocol.startsWith('http')) window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js').catch(err=>console.info('Service worker non enregistré',err)));
